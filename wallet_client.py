import logging
import time
from typing import Dict, List, Tuple, Optional
import requests
import config

logger = logging.getLogger(__name__)

class WalletAPIClient:
    """Wallet REST API client with error handling and rate limit management."""

    def __init__(self, api_token: str = None, base_url: str = None):
        self.api_token = api_token or config.WALLET_API_TOKEN
        self.base_url = base_url or config.WALLET_API_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def get_accounts(self) -> List[Dict]:
        """Fetch all accounts with pagination."""
        accounts = []
        offset = 0
        limit = 200

        while True:
            try:
                response = self.session.get(
                    f"{self.base_url}/v1/api/accounts",
                    params={"limit": limit, "offset": offset},
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                accounts.extend(data.get("accounts", []))

                next_offset = data.get("nextOffset")
                if not next_offset or next_offset <= offset:
                    break
                offset = next_offset

            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to fetch accounts: {e}")
                raise

        logger.info(f"Fetched {len(accounts)} accounts")
        return accounts

    def get_categories(self) -> List[Dict]:
        """Fetch all categories with pagination."""
        categories = []
        offset = 0
        limit = 200

        while True:
            try:
                response = self.session.get(
                    f"{self.base_url}/v1/api/categories",
                    params={"limit": limit, "offset": offset},
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                categories.extend(data.get("categories", []))

                next_offset = data.get("nextOffset")
                if not next_offset or next_offset <= offset:
                    break
                offset = next_offset

            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to fetch categories: {e}")
                raise

        logger.info(f"Fetched {len(categories)} categories")
        return categories

    def post_records(self, records: List[Dict], dry_run: bool = False) -> Tuple[int, List[Dict]]:
        """
        POST up to 20 records. Returns (status_code, results_list).
        Results list contains detailed per-record success/error info.
        """
        if len(records) > config.MAX_BATCH_SIZE:
            logger.warning(f"Batch size {len(records)} exceeds max {config.MAX_BATCH_SIZE}, truncating")
            records = records[:config.MAX_BATCH_SIZE]

        if dry_run:
            logger.info(f"[DRY RUN] Would post {len(records)} records")
            for i, record in enumerate(records):
                logger.info(f"  {i+1}. {record['counterParty']} {record['amount']} {record['paymentType']}")
            return 200, [{"status": "success"} for _ in records]

        try:
            # API expects a bare JSON array, not {"records": [...]}
            response = self.session.post(
                f"{self.base_url}/v1/api/records",
                json=records,
                timeout=15,
            )

            # Handle 207 Partial Success
            if response.status_code == 207:
                logger.warning("Partial success (207) from Wallet API")
                data = response.json()
                # Response may be a bare array or wrapped
                results = data if isinstance(data, list) else data.get("results", data.get("records", []))
                return 207, results

            # Handle 200/201 full success
            if response.status_code in (200, 201):
                logger.info(f"Successfully posted {len(records)} records")
                try:
                    data = response.json()
                    results = data if isinstance(data, list) else data.get("results", data.get("records", []))
                except Exception:
                    results = []
                return response.status_code, results

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "60")
                logger.error(f"Rate limited (429), retry after {retry_after}s")
                return 429, []

            if response.status_code >= 500:
                logger.error(f"Server error ({response.status_code}): {response.text}")
                return response.status_code, []

            if response.status_code >= 400:
                logger.error(f"Client error ({response.status_code}): {response.text}")
                return response.status_code, []

            return response.status_code, []

        except requests.exceptions.Timeout:
            logger.error("Request timeout")
            return 504, []
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            return 500, []

    def get_labels(self) -> List[Dict]:
        """Fetch all labels."""
        try:
            response = self.session.get(
                f"{self.base_url}/v1/api/labels",
                params={"limit": 200},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            labels = data.get("labels", [])
            logger.info(f"Fetched {len(labels)} labels")
            return labels
        except Exception as e:
            logger.error(f"Failed to fetch labels: {e}")
            return []

    def check_api_health(self) -> bool:
        """Quick check if API is reachable and token is valid."""
        try:
            response = self.session.get(
                f"{self.base_url}/v1/api/accounts",
                params={"limit": 1},
                timeout=5,
            )
            if response.status_code == 409:
                logger.warning("Initial sync in progress (409), wait 5 minutes")
                return False
            if response.status_code == 200:
                return True
            logger.error(f"API health check failed: {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"API health check failed: {e}")
            return False
