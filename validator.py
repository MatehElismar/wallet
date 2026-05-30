import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

VALID_PAYMENT_TYPES = {
    "cash",
    "debit_card",
    "credit_card",
    "transfer",
    "voucher",
    "mobile_payment",
    "web_payment",
}

RESTRICTED_CATEGORY_IDS = {
    "5c5c4e20-00c8-8000-8000-000000000000",  # Debt
    "5c5c4e21-00c8-8000-8000-000000000000",  # Transfer
    "5c5c4e22-00c8-8000-8000-000000000000",  # Shopping List
    "5c5c4e23-00c8-8000-8000-000000000000",  # Uncategorized
}

class ValidationError(Exception):
    pass

class RecordValidator:
    """Validate LLM output before posting to Wallet API."""

    def __init__(self, account_map: Dict[str, str], category_map: Dict[str, str]):
        self.account_map = account_map
        self.category_map = category_map

    def validate_record(self, record: Dict) -> Tuple[bool, str]:
        """
        Validate a single record from LLM output.
        Returns: (is_valid, error_message)
        """
        try:
            # Check skipReason
            if record.get("skipReason"):
                return False, f"Skipped by LLM: {record['skipReason']}"

            # Validate amount
            try:
                amount = float(record.get("amount", 0))
                if amount == 0:
                    return False, "Amount cannot be zero"
                if not self._is_valid_decimal(amount):
                    return False, f"Amount has too many decimal places: {amount}"
            except (ValueError, TypeError):
                return False, f"Invalid amount: {record.get('amount')}"

            # Validate recordDate
            try:
                record_date_str = record.get("recordDate", "").replace("Z", "+00:00")
                record_date = datetime.fromisoformat(record_date_str)
                # Make it naive for comparison
                if record_date.tzinfo:
                    record_date = record_date.replace(tzinfo=None)
                now = datetime.utcnow()
                if record_date > now + timedelta(hours=24):
                    return False, f"recordDate is more than 24 hours in the future"
                if record_date < now - timedelta(days=365*10):
                    return False, f"recordDate is more than 10 years in the past"
            except (ValueError, AttributeError):
                return False, f"Invalid recordDate format: {record.get('recordDate')}"

            # Validate paymentType
            if record.get("paymentType") not in VALID_PAYMENT_TYPES:
                return False, f"Invalid paymentType: {record.get('paymentType')}"

            # Validate accountName → accountId
            account_name = record.get("accountName", "")
            if account_name not in self.account_map:
                return False, f"Account not found: {account_name}"

            # Validate categoryName → categoryId (optional, but if present, must be valid)
            if record.get("categoryName"):
                category_name = record.get("categoryName")
                if category_name not in self.category_map:
                    return False, f"Category not found: {category_name}"
                category_id = self.category_map[category_name]
                if category_id in RESTRICTED_CATEGORY_IDS:
                    return False, f"Category is restricted and cannot be assigned: {category_name}"

            # Validate field lengths
            if len(str(record.get("note", ""))) > 255:
                return False, "Note field exceeds 255 characters"
            if len(str(record.get("counterParty", ""))) > 255:
                return False, "counterParty field exceeds 255 characters"

            return True, ""

        except Exception as e:
            return False, f"Validation error: {str(e)}"

    def normalize_record(self, record: Dict) -> Dict:
        """Normalize and sanitize a record after validation."""
        amount = float(record.get("amount", 0))
        account_name = record.get("accountName", "")
        category_name = record.get("categoryName")

        normalized = {
            "amount": self._round_decimal(amount),
            "recordDate": record.get("recordDate"),
            "paymentType": record.get("paymentType"),
            "counterParty": str(record.get("counterParty", ""))[:255],
            "note": str(record.get("note", ""))[:255],
            "accountId": self.account_map.get(account_name),
            "categoryId": self.category_map.get(category_name) if category_name else None,
        }
        return normalized

    @staticmethod
    def _is_valid_decimal(value: float) -> bool:
        """Check if value has at most 2 decimal places."""
        str_val = str(value)
        if "." in str_val:
            decimal_places = len(str_val.split(".")[1])
            return decimal_places <= 2
        return True

    @staticmethod
    def _round_decimal(value: float) -> float:
        """Round to 2 decimal places."""
        return round(value, 2)
