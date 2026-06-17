#!/usr/bin/env python3
"""
verify_shopify_auth.py

Standalone preflight check that the Shopify client credentials grant is wired
up correctly BEFORE you run a full report. Exercises the three things that
actually break:

  1. Token acquisition via the client credentials grant
  2. A live `{ shop { name } }` query using that token
  3. The forced-refresh path (invalidate -> refetch)

Run from the repo root:
    python scripts/verify_shopify_auth.py

Exit code 0 = safe to run reports. Non-zero = auth is not ready; the printed
error names the most likely cause.
"""

import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

# Match the repo's import convention: scripts/ on sys.path, .env at repo root.
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

from shopify_client import ShopifyClient, get_token_manager  # noqa: E402


def main() -> None:
    tm = get_token_manager()
    print(f"Auth mode: {tm.mode}")
    print(f"Store:     {tm.domain}")
    if tm.mode != "client_credentials":
        print(
            "\n⚠️  Not running in client_credentials mode. To test the Dev "
            "Dashboard rollout, set SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET "
            "and remove SHOPIFY_ACCESS_TOKEN."
        )

    token = tm.get_token()
    print(f"Token acquired: {token[:10]}… (len={len(token)})")

    client = ShopifyClient()
    data = client.graphql("{ shop { name myshopifyDomain } }")
    shop = data["shop"]
    print(f"Live query OK:  {shop['name']} ({shop['myshopifyDomain']})")

    # Prove the refresh path works (this is what keeps reports alive past 24h).
    tm.invalidate()
    token2 = tm.get_token(force_refresh=True)
    print(f"Refresh OK:     {token2[:10]}…")

    print("\n✅ Auth verified. Safe to run reports.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 - this is a CLI preflight tool
        print(f"\n❌ Auth verification failed: {e}")
        sys.exit(1)
      
