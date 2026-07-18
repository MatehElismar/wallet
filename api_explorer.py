#!/usr/bin/env python3
"""
Wallet API Explorer
Discovers the full API schema by calling every relevant endpoint and logging
complete request/response payloads. Run this before Phase 3 to understand
exactly what data is available and what the POST format looks like.

Usage:
    python api_explorer.py              # Full discovery, saves api_discovery.json
    python api_explorer.py --test-post  # Also make one real test record (labeled)
    python api_explorer.py --dry-post   # Simulate the POST payload without sending
"""

import json
import logging
import sys
import argparse
from datetime import datetime, timezone
import requests
import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

DISCOVERY_FILE = "api_discovery.json"

# Label appended to every auto-imported record so they're easy to find/delete
AUTO_IMPORT_TAG = "wallet-sync"
TEST_TAG = "wallet-sync-test"


class APIExplorer:
    def __init__(self):
        self.base_url = config.WALLET_API_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {config.WALLET_API_TOKEN}",
            "Content-Type": "application/json",
        })
        self.discovery = {
            "explored_at": datetime.now(timezone.utc).isoformat(),
            "base_url": self.base_url,
        }

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        logger.info(f"GET {path} {params or ''}")
        resp = self.session.get(url, params=params, timeout=15)
        logger.info(f"  → {resp.status_code}")
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict) -> tuple:
        url = f"{self.base_url}{path}"
        logger.info(f"POST {path}")
        logger.info(f"  payload: {json.dumps(payload, indent=2)}")
        resp = self.session.post(url, json=payload, timeout=15)
        logger.info(f"  → {resp.status_code}")
        body = {}
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        logger.info(f"  response: {json.dumps(body, indent=2)}")
        return resp.status_code, body

    # ── Accounts ─────────────────────────────────────────────────────────────

    def _paginate(self, path: str, key: str, limit: int = 200) -> list:
        """Fetch all pages from a paginated endpoint."""
        results, offset = [], 0
        while True:
            data = self._get(path, {"limit": limit, "offset": offset})
            page = data.get(key, [])
            results.extend(page)
            next_offset = data.get("nextOffset")
            if not next_offset or next_offset <= offset:
                break
            offset = next_offset
        return results

    def explore_accounts(self) -> list:
        logger.info("\n=== ACCOUNTS ===")
        accounts = self._paginate("/v1/api/accounts", "accounts")
        active = [a for a in accounts if not a.get("archived")]
        logger.info(f"  Total: {len(accounts)} ({len(active)} active)")

        if accounts:
            logger.info(f"  Fields: {list(accounts[0].keys())}")
        for acc in accounts:
            status = "" if not acc.get("archived") else " [archived]"
            logger.info(
                f"  {acc.get('name')!r:30s} {acc.get('accountType'):15s} "
                f"id={acc.get('id')}{status}"
            )

        self.discovery["accounts"] = {
            "count": len(accounts),
            "active_count": len(active),
            "fields": list(accounts[0].keys()) if accounts else [],
            "active": active,
            "full": accounts,
        }
        return accounts

    # ── Categories ───────────────────────────────────────────────────────────

    def explore_categories(self) -> list:
        logger.info("\n=== CATEGORIES ===")
        categories = self._paginate("/v1/api/categories", "categories", limit=500)
        active = [c for c in categories if not c.get("archived") and c.get("enabled", True)]
        logger.info(f"  Total: {len(categories)} ({len(active)} active/enabled)")

        if categories:
            logger.info(f"  Fields: {list(categories[0].keys())}")
        for cat in active:
            envelope = cat.get("envelope", {})
            env_name = envelope.get("name", "") if isinstance(envelope, dict) else ""
            logger.info(f"  {cat.get('name')!r:35s} [{env_name}]  id={cat.get('id')}")

        self.discovery["categories"] = {
            "count": len(categories),
            "active_count": len(active),
            "fields": list(categories[0].keys()) if categories else [],
            "active": active,
            "full": categories,
        }
        return categories

    # ── Existing records ─────────────────────────────────────────────────────

    def explore_existing_records(self) -> dict:
        logger.info("\n=== EXISTING RECORDS (sample) ===")
        data = self._get("/v1/api/records", {"limit": 3})
        records = data.get("records", [])
        next_offset = data.get("nextOffset", 0)

        logger.info(f"  nextOffset (≈ total): {next_offset}")
        if records:
            logger.info(f"  Fields: {list(records[0].keys())}")
            for rec in records:
                amount = rec.get("amount", {})
                val = amount.get("value") if isinstance(amount, dict) else amount
                cur = amount.get("currencyCode", "") if isinstance(amount, dict) else ""
                logger.info(
                    f"  {val} {cur} | note={rec.get('note')!r} | "
                    f"labels={rec.get('labels')} | source={rec.get('source')}"
                )

        self.discovery["existing_records"] = {
            "approx_total": next_offset,
            "fields": list(records[0].keys()) if records else [],
            "amount_format": records[0].get("amount") if records else None,
            "sample": records,
        }
        return data

    # ── POST schema discovery ─────────────────────────────────────────────────

    def dry_post(self, accounts: list, categories: list):
        """Log what a real POST payload would look like without sending it."""
        logger.info("\n=== DRY POST PAYLOAD (not sent) ===")

        if not accounts:
            logger.warning("No accounts found, cannot construct test payload")
            return

        acc = accounts[0]
        cat = next((c for c in categories if c.get("id") not in {
            "5c5c4e20-00c8-8000-8000-000000000000",
            "5c5c4e21-00c8-8000-8000-000000000000",
            "5c5c4e22-00c8-8000-8000-000000000000",
            "5c5c4e23-00c8-8000-8000-000000000000",
        }), None)

        payload = {
            "records": [
                {
                    "amount": -1.00,
                    "recordDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "paymentType": "debit_card",
                    "counterParty": "API Explorer Test",
                    "note": f"Test record — safe to delete [{TEST_TAG}]",
                    "accountId": acc.get("id"),
                    "categoryId": cat.get("id") if cat else None,
                }
            ]
        }
        logger.info(f"  Would POST:\n{json.dumps(payload, indent=2)}")
        self.discovery["post_payload_example"] = payload

    def real_test_post(self, accounts: list, categories: list, labels: list) -> dict:
        """POST one clearly-labeled test record and log the full request/response."""
        logger.info("\n=== REAL TEST POST ===")

        active_accounts = [a for a in accounts if not a.get("archived")]
        if not active_accounts:
            logger.error("No active accounts — cannot post")
            return {}

        RESTRICTED = {
            "5c5c4e20-00c8-8000-8000-000000000000",
            "5c5c4e21-00c8-8000-8000-000000000000",
            "5c5c4e22-00c8-8000-8000-000000000000",
            "5c5c4e23-00c8-8000-8000-000000000000",
        }
        active_cats = [c for c in categories if not c.get("archived") and c.get("id") not in RESTRICTED]

        acc = active_accounts[0]
        cat = active_cats[0] if active_cats else None

        # Use the "Imported" sync label
        auto_label = next(
            (l for l in labels if l.get("name", "").strip().lower() == "imported"),
            None
        )

        record = {
            "amount": -1.00,
            "recordDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "paymentType": "debit_card",
            "note": f"API explorer test — safe to delete [{TEST_TAG}]",
            "accountId": acc.get("id"),
        }
        if cat:
            record["categoryId"] = cat.get("id")
        if auto_label:
            record["labelIds"] = [auto_label.get("id")]

        payload = [record]  # API expects bare array

        status_code, response_body = self._post("/v1/api/records", payload)

        self.discovery["post_test"] = {
            "request_payload": payload,
            "response_status": status_code,
            "response_body": response_body,
            "label_used": auto_label,
        }

        if status_code in (200, 201, 207):
            logger.info("  ✓ POST accepted — delete this test record from the Wallet app")
        else:
            logger.error(f"  ✗ POST failed: {status_code}")

        return response_body

    # ── Labels / tags discovery ───────────────────────────────────────────────

    def explore_labels(self) -> list:
        """Fetch labels and identify the auto-import label."""
        logger.info("\n=== LABELS ===")
        try:
            data = self._get("/v1/api/labels", {"limit": 200})
            labels = data.get("labels", [])
            active = [l for l in labels if not l.get("archived")]
            logger.info(f"  Total: {len(labels)} ({len(active)} active)")
            for label in active:
                logger.info(f"  {label.get('name')!r:25s} id={label.get('id')}  color={label.get('color')}")

            # Find the "Imported" sync label
            api_label = next(
                (l for l in active if l.get("name", "").strip().lower() == "imported"),
                None
            )
            if api_label:
                logger.info(f"\n  ✓ 'Imported' sync label found: id={api_label.get('id')}")
            else:
                logger.warning("\n  ✗ Label 'Imported' not found in Wallet.")

            self.discovery["labels"] = {
                "count": len(labels),
                "active": active,
                "auto_import_label": auto_label,
            }
            return active
        except requests.HTTPError as e:
            logger.warning(f"  Labels endpoint failed: {e.response.status_code}")
            return []

    # ── Save results ──────────────────────────────────────────────────────────

    def save(self):
        with open(DISCOVERY_FILE, "w") as f:
            json.dump(self.discovery, f, indent=2, default=str)
        logger.info(f"\nFull discovery saved → {DISCOVERY_FILE}")

    # ── Summary ───────────────────────────────────────────────────────────────

    def print_summary(self, accounts, categories):
        logger.info("\n" + "=" * 60)
        logger.info("SUMMARY — what to feed the LLM")
        logger.info("=" * 60)

        logger.info("\nACCOUNTS available to LLM:")
        for acc in accounts:
            logger.info(
                f"  name={acc.get('name')!r:30s} "
                f"currency={acc.get('currencyCode') or acc.get('currency')!r:5s} "
                f"type={acc.get('type')!r}"
            )

        logger.info(f"\nCATEGORIES ({len(categories)} total):")
        for cat in categories:
            if cat.get("id") not in {
                "5c5c4e20-00c8-8000-8000-000000000000",
                "5c5c4e21-00c8-8000-8000-000000000000",
                "5c5c4e22-00c8-8000-8000-000000000000",
                "5c5c4e23-00c8-8000-8000-000000000000",
            }:
                logger.info(f"  {cat.get('name')!r}")

        logger.info(f"\nRecord fields the API accepts — see {DISCOVERY_FILE} for full schema")
        logger.info(f"Auto-import tag for all synced records: [{AUTO_IMPORT_TAG}]")
        logger.info(f"Test record tag:                        [{TEST_TAG}]")


def main():
    parser = argparse.ArgumentParser(description="Wallet API schema explorer")
    parser.add_argument("--test-post", action="store_true",
                        help="POST one real test record (labeled, safe to delete)")
    parser.add_argument("--dry-post", action="store_true",
                        help="Show what a POST payload looks like without sending")
    args = parser.parse_args()

    if not config.WALLET_API_TOKEN:
        logger.error("WALLET_API_TOKEN not set")
        sys.exit(1)

    explorer = APIExplorer()

    try:
        accounts = explorer.explore_accounts()
        categories = explorer.explore_categories()
        explorer.explore_existing_records()
        explorer.explore_labels()

        labels = explorer.explore_labels()

        if args.test_post:
            explorer.real_test_post(accounts, categories, labels)
        elif args.dry_post or not args.test_post:
            explorer.dry_post(accounts, categories)

        explorer.print_summary(accounts, categories)
        explorer.save()

    except requests.HTTPError as e:
        logger.error(f"API error: {e.response.status_code} — {e.response.text[:300]}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Explorer failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
