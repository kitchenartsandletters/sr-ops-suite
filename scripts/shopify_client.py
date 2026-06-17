"""
shopify_client.py

Synchronous Shopify Admin GraphQL client for sr-ops-suite.

WHAT CHANGED (Jan 2026 Dev Dashboard migration)
------------------------------------------------
Custom apps created in the Shopify Dev Dashboard no longer expose a static
Admin API access token. The app holds a Client ID + Client secret, which are
exchanged for a short-lived Admin API access token via the OAuth client
credentials grant. Those tokens expire after ~24h and must be refreshed.

This module centralizes that token lifecycle in a process-wide TokenManager.
Every report script that constructs a ShopifyClient transparently gets a
valid, auto-refreshing token. No caller code changes:
    client = ShopifyClient()
    data   = client.graphql(QUERY, variables={...})

AUTH MODES (auto-detected from env)
-----------------------------------
  1. client_credentials (preferred):  SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET
  2. static (legacy / local fallback): SHOPIFY_ACCESS_TOKEN
If client-credentials vars are present they win, so you can leave a static
token in place during cutover without it masking a CCG misconfig... except
that to *honestly test* CCG you should remove SHOPIFY_ACCESS_TOKEN (see PoC
notes in the rollout message).

REQUIRED (all modes):   SHOP_URL              e.g. castironbooks.myshopify.com
OPTIONAL:               SHOPIFY_API_VERSION   default below

PREREQUISITE for CCG: the app must be INSTALLED on SHOP_URL's store and have
its Admin API access scopes configured in the Dev Dashboard, or the token
request returns 400/401.
"""

import os
import time
import logging
import threading
from typing import Any, Dict, Optional

import requests

VALIDATE_QUERY = """{ shop { name } }"""

DEFAULT_API_VERSION = "2025-10"

# Refresh this many seconds before the token's stated expiry, to absorb clock
# skew and requests already in flight when the token would otherwise lapse.
TOKEN_EXPIRY_SAFETY_MARGIN = 300


def _normalize_domain(shop_url: str) -> str:
    if shop_url.startswith(("http://", "https://")):
        return shop_url.split("://", 1)[1].rstrip("/")
    return shop_url.rstrip("/")


class TokenManager:
    """
    Process-wide holder of a Shopify Admin API access token.

    Obtains the token via the OAuth client credentials grant and caches it
    until shortly before expiry. Thread-safe: concurrent callers share a single
    in-flight refresh rather than each hammering the token endpoint. (The CCG
    has no refresh token to rotate, so there is none of the cross-process
    clobbering hazard that the authorization-code flow has.)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._expires_at: float = 0.0  # time.monotonic() deadline

        shop_url = os.getenv("SHOP_URL")
        if not shop_url:
            raise RuntimeError("SHOP_URL must be set in environment variables.")
        self._domain = _normalize_domain(shop_url)

        self._client_id = os.getenv("SHOPIFY_CLIENT_ID")
        self._client_secret = os.getenv("SHOPIFY_CLIENT_SECRET")
        self._static_token = os.getenv("SHOPIFY_ACCESS_TOKEN")

        if self._client_id and self._client_secret:
            self._mode = "client_credentials"
        elif self._static_token:
            self._mode = "static"
        else:
            raise RuntimeError(
                "No Shopify credentials found. Set SHOPIFY_CLIENT_ID + "
                "SHOPIFY_CLIENT_SECRET (preferred), or SHOPIFY_ACCESS_TOKEN."
            )
        logging.info("[shopify] TokenManager initialized in '%s' mode", self._mode)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def token_endpoint(self) -> str:
        return f"https://{self._domain}/admin/oauth/access_token"

    def get_token(self, force_refresh: bool = False) -> str:
        if self._mode == "static":
            return self._static_token  # type: ignore[return-value]

        now = time.monotonic()
        if not force_refresh and self._token and now < self._expires_at:
            return self._token

        with self._lock:
            # Re-check inside the lock: another thread may have just refreshed.
            now = time.monotonic()
            if not force_refresh and self._token and now < self._expires_at:
                return self._token
            self._refresh_locked()
            return self._token  # type: ignore[return-value]

    def invalidate(self) -> None:
        """Drop the cached token so the next get_token() refetches."""
        if self._mode == "static":
            return
        with self._lock:
            self._token = None
            self._expires_at = 0.0

    def _refresh_locked(self) -> None:
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "client_credentials",
        }
        try:
            resp = requests.post(
                self.token_endpoint,
                json=payload,
                headers={"Content-Type": "application/json",
                         "Accept": "application/json"},
                timeout=(10, 30),
            )
        except requests.RequestException as e:
            raise RuntimeError(f"Shopify token request failed (network): {e}") from e

        if resp.status_code != 200:
            hint = ""
            if resp.status_code in (400, 401):
                hint = (
                    " Likely causes: the app is not installed on this store, "
                    "SHOPIFY_CLIENT_ID/SHOPIFY_CLIENT_SECRET are wrong, or the "
                    "app's Admin API access scopes are not configured."
                )
            raise RuntimeError(
                f"Shopify token request failed: status={resp.status_code} "
                f"body={resp.text[:300]}.{hint}"
            )

        data = resp.json()
        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 86400))
        if not token:
            raise RuntimeError(f"Shopify token response missing access_token: {data}")

        self._token = token
        self._expires_at = time.monotonic() + max(
            expires_in - TOKEN_EXPIRY_SAFETY_MARGIN, 30
        )
        # Never log the full token or the client secret.
        logging.info(
            "[shopify] Access token refreshed (prefix=%s…, expires_in=%ss)",
            token[:8], expires_in,
        )


# Process-wide singleton, created lazily so importing this module never
# requires env vars to be present (e.g. during test collection).
_token_manager: Optional[TokenManager] = None
_token_manager_lock = threading.Lock()


def get_token_manager() -> TokenManager:
    global _token_manager
    if _token_manager is None:
        with _token_manager_lock:
            if _token_manager is None:
                _token_manager = TokenManager()
    return _token_manager


class ShopifyClient:
    def __init__(self) -> None:
        api_version = os.getenv("SHOPIFY_API_VERSION", DEFAULT_API_VERSION)
        self._tokens = get_token_manager()
        self.base_url = (
            f"https://{self._tokens.domain}/admin/api/{api_version}/graphql.json"
        )
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def validate_connection(self):
        try:
            self.graphql(VALIDATE_QUERY)
            logging.info(f"[shopify] API connection validated: {self.base_url}")
        except RuntimeError as e:
            if "Not Found" in str(e) or "404" in str(e):
                raise RuntimeError(
                    f"Shopify API version may be sunset. "
                    f"Check SHOPIFY_API_VERSION env var. URL: {self.base_url}"
                )
            raise

    def graphql(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._graphql_once(query, variables, allow_retry=True)

    def _graphql_once(
        self,
        query: str,
        variables: Optional[Dict[str, Any]],
        allow_retry: bool,
    ) -> Dict[str, Any]:
        self.session.headers["X-Shopify-Access-Token"] = self._tokens.get_token()
        payload = {"query": query, "variables": variables or {}}
        resp = self.session.post(self.base_url, json=payload, timeout=(10, 120))

        # 401 == invalid/expired token. Refresh once and retry. We deliberately
        # do NOT retry on 403: that is a scope/permission problem a refresh
        # can't fix, and it should surface clearly.
        if resp.status_code == 401 and allow_retry:
            logging.warning(
                "[shopify] 401 on GraphQL call; refreshing token and retrying once."
            )
            self._tokens.invalidate()
            self.session.headers["X-Shopify-Access-Token"] = self._tokens.get_token(
                force_refresh=True
            )
            return self._graphql_once(query, variables, allow_retry=False)

        try:
            data = resp.json()
        except ValueError:
            logging.error("Non-JSON response from Shopify: %s", resp.text[:500])
            resp.raise_for_status()
            raise

        if resp.status_code != 200 or "errors" in data:
            logging.error(
                "GraphQL error: status=%s errors=%s",
                resp.status_code,
                data.get("errors"),
            )
            raise RuntimeError(f"Shopify GraphQL error: {data.get('errors')}")

        return data["data"]
