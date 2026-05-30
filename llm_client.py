import json
import logging
from typing import Dict, Optional, List
from anthropic import Anthropic
import config

logger = logging.getLogger(__name__)

class LLMClient:
    """Wrapper around Claude API for transaction extraction."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.ANTHROPIC_API_KEY
        self.client = Anthropic(api_key=self.api_key) if self.api_key else None
        self.model = config.ANTHROPIC_MODEL

    def build_system_prompt(self, accounts: List[Dict], categories: List[Dict]) -> str:
        """Build the system prompt with account and category lists."""
        account_list = "\n".join([f"- {acc['name']}" for acc in accounts])
        category_list = "\n".join([f"- {cat['name']}" for cat in categories])

        return f"""You are a financial data extraction assistant. Extract transaction details from the email below.

AVAILABLE ACCOUNTS (use exact names only):
{account_list}

AVAILABLE CATEGORIES (use exact names only):
{category_list}

PAYMENT TYPE OPTIONS: cash | debit_card | credit_card | transfer | voucher | mobile_payment | web_payment

CATEGORIZATION HEURISTICS:
- Grocery stores, supermarkets → "Food & Drinks"
- Netflix, Spotify, Adobe, SaaS subscriptions → "Entertainment" or "Subscriptions"
- Uber, Lyft, taxi, fuel, parking → "Transport"
- Doctor, pharmacy, hospital → "Health"
- Amazon, Shein, online retail → "Shopping"
- Salary, freelance payment, client transfer → positive amount + income category
- ATM withdrawal → cash paymentType; do NOT create record if it is just a balance notification
- Two-factor authentication, newsletters, promotional emails → skipReason = "not a transaction"

Respond ONLY with a JSON object. No explanation. No markdown.
"""

    def build_user_prompt(self, email_content: str) -> str:
        """Build the user prompt with email content."""
        return f"""Extract transaction details from the following email:

{email_content}

Respond with this exact JSON schema:
{{
  "amount": <number, negative=expense, positive=income>,
  "recordDate": "<ISO 8601, e.g. 2025-05-28T10:30:00Z>",
  "paymentType": "<from list above>",
  "counterParty": "<merchant or sender, max 255 chars>",
  "note": "<brief user-facing description, max 255 chars>",
  "accountName": "<exact name from AVAILABLE ACCOUNTS>",
  "categoryName": "<exact name from AVAILABLE CATEGORIES>",
  "skipReason": "<non-empty string if NOT a transaction, else null>"
}}
"""

    def extract(self, email_content: str, accounts: List[Dict], categories: List[Dict]) -> Optional[Dict]:
        """
        Send email to Claude and get structured JSON response.
        Returns parsed JSON or None if extraction fails.
        """
        if not self.api_key:
            logger.warning("LLM client not configured, returning mock response")
            return self._mock_response()

        if not self.client:
            logger.warning("LLM client initialization failed, returning mock response")
            return self._mock_response()

        system_prompt = self.build_system_prompt(accounts, categories)
        user_prompt = self.build_user_prompt(email_content)

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            response_text = message.content[0].text
            parsed = json.loads(response_text)
            logger.info(f"LLM extraction successful, skipReason={parsed.get('skipReason')}")
            return parsed

        except json.JSONDecodeError as e:
            logger.error(f"LLM returned invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            return None

    @staticmethod
    def _mock_response() -> Dict:
        """Return a mock LLM response for testing without API key."""
        return {
            "amount": -45.99,
            "recordDate": "2025-05-28T14:30:00Z",
            "paymentType": "debit_card",
            "counterParty": "STARBUCKS COFFEE #1234",
            "note": "Morning coffee",
            "accountName": "Checking",
            "categoryName": "Food & Drinks",
            "skipReason": None,
        }
