"""
shopify_client.py

Synchronous Shopify Admin GraphQL client for sr-ops-suite.

Extracted from lop_unfulfilled_report.py so all scripts in the repo
can share a single client implementation.

Usage:
    from shopify_client import ShopifyClient

    client = ShopifyClient()
    data = client.graphql(QUERY, variables={...})
"""

import os
import logging
from typing import Any, Dict, Optional

import requests


class ShopifyClient:
    def __init__(self) -> None:
        shop_url    = os.getenv("SHOP_URL")
        access_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
        api_version  = os.getenv("SHOPIFY_API_VERSION", "2025-01")

        if not shop_url or not access_token:
            raise RuntimeError(
                "SHOP_URL and SHOPIFY_ACCESS_TOKEN must be set in environment variables."
            )

        # Accept bare domain or full https:// URL
        if shop_url.startswith("http://") or shop_url.startswith("https://"):
            base_domain = shop_url.split("://", 1)[1].rstrip("/")
        else:
            base_domain = shop_url.rstrip("/")

        self.base_url = f"https://{base_domain}/admin/api/{api_version}/graphql.json"
        self.session  = requests.Session()
        self.session.headers.update({
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        })

    def graphql(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {"query": query, "variables": variables or {}}
        resp    = self.session.post(self.base_url, json=payload, timeout=(10, 120))

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