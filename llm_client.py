import json
import logging
from typing import Dict, Optional, List
from abc import ABC, abstractmethod
import config

logger = logging.getLogger(__name__)


def _parse_json_response(text: str) -> dict:
    """Parse JSON from LLM response, stripping markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    return json.loads(text.strip())


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def classify(self, email_content: str) -> Optional[Dict]:
        """Classify whether an email is a financial transaction.

        Returns:
            Dict with keys: output ({is_transaction, reason}), system_prompt, user_prompt,
            raw_response, parsing_error, success.
            Returns None on network/API errors.
        """
        pass

    @abstractmethod
    def extract(self, email_content: str, accounts: List[Dict], categories: List[Dict],
                resolved_account: Dict = None) -> Optional[Dict]:
        """Extract transaction details from an email confirmed to be a transaction.

        Returns:
            Dict with keys: output (extraction JSON), system_prompt, user_prompt,
            raw_response, parsing_error, success.
            Returns None on network/API errors.
        """
        pass

    def build_classify_system_prompt(self) -> str:
        return """You are a financial email classifier. Determine if this email is a financial transaction notification.
Respond with JSON only — no markdown, no explanation outside the JSON.

A financial transaction notification involves:
- A payment made or received
- A charge or debit to an account
- A purchase confirmation or receipt
- A bank or wire transfer
- An invoice with an actual charge (not a quote or reminder)

NOT a financial transaction:
- Balance inquiries or account summaries (no actual movement)
- OTP, 2FA, or verification codes
- Marketing, promotional, or newsletter emails
- Email or account verification requests
- Subscription renewal reminders without a confirmed charge

Respond ONLY with a JSON object. No explanation. No markdown.
"""

    def build_classify_user_prompt(self, email_content: str) -> str:
        return f"""Is this email a financial transaction notification?

{email_content}

Respond with this exact JSON:
{{
  "is_transaction": <true or false>,
  "reason": "<one sentence explanation, max 120 chars>",
  "confidence": "<high | medium | low>"
}}
"""

    def build_system_prompt(self, accounts: List[Dict], categories: List[Dict],
                            resolved_account: Dict = None) -> str:
        category_list = "\n".join([
            f"- {cat['name']}" for cat in categories
            if cat.get("id") not in {
                "5c5c4e20-00c8-8000-8000-000000000000",
                "5c5c4e21-00c8-8000-8000-000000000000",
                "5c5c4e22-00c8-8000-8000-000000000000",
                "5c5c4e23-00c8-8000-8000-000000000000",
            }
        ])

        # Build account section based on resolver confidence
        if resolved_account and resolved_account.get("confidence") == "high":
            acc = resolved_account
            account_section = (
                f"ACCOUNT (pre-resolved from email — use this exact name, do not change it):\n"
                f"- {acc['account_name']} ({acc.get('account_type', '')}, {acc.get('currency', 'DOP')})"
            )
        elif resolved_account and resolved_account.get("confidence") == "medium":
            acc = resolved_account
            account_section = (
                f"MOST LIKELY ACCOUNT (strongly recommended — override only if email clearly indicates otherwise):\n"
                f"- {acc['account_name']} ({acc.get('account_type', '')}, {acc.get('currency', 'DOP')})\n\n"
                f"OTHER ACCOUNTS (use exact name only if the above is wrong):\n"
                + "\n".join(
                    f"- {a['name']} ({a.get('accountType', '')}, "
                    f"{(a.get('initialBalance') or {}).get('currencyCode', 'DOP')})"
                    for a in accounts
                    if a.get("name") != acc["account_name"]
                )
            )
        elif resolved_account and resolved_account.get("confidence") == "low":
            candidates = resolved_account.get("candidates", [])
            candidate_list = "\n".join(
                f"- {c['name']} ({c.get('type', '')}, {c.get('currency', 'DOP')})"
                for c in candidates
            )
            account_section = (
                f"LIKELY ACCOUNTS for this transaction (choose one based on card digits or type in email):\n"
                f"{candidate_list}"
            )
        else:
            # No resolution — show all active accounts
            account_section = "AVAILABLE ACCOUNTS (use exact name only):\n" + "\n".join(
                f"- {a['name']} ({a.get('accountType', '')}, "
                f"{(a.get('initialBalance') or {}).get('currencyCode', 'DOP')})"
                for a in accounts
            )

        return f"""You are a financial data extraction assistant. Extract transaction details from the email below.

{account_section}

AVAILABLE CATEGORIES (use exact name only):
{category_list}

PAYMENT TYPE OPTIONS: cash | debit_card | credit_card | transfer | voucher | mobile_payment | web_payment

CATEGORIZATION HEURISTICS:
- Grocery stores, supermarkets → "Groceries"
- Bars, cafes, coffee shops → "Bar cafe"
- Restaurants, fast food → "Restaurants & fast food"
- Netflix, Spotify, SaaS, streaming → "Tv, streaming" or "Books, audio, subscription"
- Taxi, Uber, Lyft → "Taxi"
- Fuel, gas station → "Fuel"
- Parking → "Parking"
- Doctor, pharmacy, hospital → "Health care & doctor"
- Salary, freelance, client transfer → positive amount + "Wage, invoices"
- Loan payment → "Loan, interests"
- ATM withdrawal → paymentType=cash; skip if it is just a balance notification

If for any reason this email is NOT a financial transaction, set skipReason to a brief explanation and leave other fields null.

Respond ONLY with a JSON object. No explanation. No markdown.
"""

    def build_user_prompt(self, email_content: str) -> str:
        return f"""Extract transaction details from the following email:

{email_content}

Respond with this exact JSON schema:
{{
  "amount": <number, negative=expense, positive=income>,
  "recordDate": "<ISO 8601, e.g. 2025-05-28T10:30:00Z>",
  "paymentType": "<from list above>",
  "payee": "<merchant, establishment, or counterparty name as it appears in the email, max 255 chars>",
  "note": "<brief description of what was purchased or purpose of transfer, max 255 chars>",
  "accountName": "<exact name from ACCOUNT section above>",
  "categoryName": "<exact name from AVAILABLE CATEGORIES>",
  "skipReason": "<non-empty string if NOT a transaction, else null>"
}}

For payee: extract the merchant or counterparty name exactly as it appears — store name, person name, company name.
For note: describe what the transaction was for, distinct from the payee (e.g. "Monthly grocery run", "Electricity bill", "Lunch").
If payee and note would be identical, note can be null.
"""

    def _mock_classify_response(self) -> Dict:
        data = {"is_transaction": True, "reason": "Mock: assumed transaction for testing"}
        return {
            "output": data,
            "system_prompt": "MOCK",
            "user_prompt": "MOCK",
            "raw_response": json.dumps(data),
            "parsing_error": None,
            "success": True,
        }

    def _mock_extract_response(self) -> Dict:
        data = {
            "amount": -45.99,
            "recordDate": "2025-05-28T14:30:00Z",
            "paymentType": "debit_card",
            "payee": "STARBUCKS COFFEE #1234",
            "note": "Morning coffee",
            "accountName": "Checking",
            "categoryName": "Food & Drinks",
            "skipReason": None,
        }
        return {
            "output": data,
            "system_prompt": "MOCK",
            "user_prompt": "MOCK",
            "raw_response": json.dumps(data),
            "parsing_error": None,
            "success": True,
        }


class AnthropicProvider(LLMProvider):
    """Claude (Anthropic) LLM provider."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.ANTHROPIC_API_KEY
        self.model = config.ANTHROPIC_MODEL
        self.client = None
        if self.api_key:
            try:
                from anthropic import Anthropic
                self.client = Anthropic(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize Anthropic client: {e}")

    def classify(self, email_content: str) -> Optional[Dict]:
        if not self.client:
            return self._mock_classify_response()

        system_prompt = self.build_classify_system_prompt()
        user_prompt = self.build_classify_user_prompt(email_content)

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            response_text = message.content[0].text
            try:
                parsed = _parse_json_response(response_text)
                return {
                    "output": parsed,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "raw_response": response_text,
                    "parsing_error": None,
                    "success": True,
                }
            except (json.JSONDecodeError, ValueError) as e:
                return {
                    "output": None,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "raw_response": response_text,
                    "parsing_error": str(e),
                    "success": False,
                }
        except Exception as e:
            logger.error(f"Anthropic classify failed: {e}")
            return None

    def extract(self, email_content: str, accounts: List[Dict], categories: List[Dict], resolved_account: Dict = None) -> Optional[Dict]:
        if not self.client:
            return self._mock_extract_response()

        system_prompt = self.build_system_prompt(accounts, categories)
        user_prompt = self.build_user_prompt(email_content)

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            response_text = message.content[0].text
            try:
                parsed = _parse_json_response(response_text)
                return {
                    "output": parsed,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "raw_response": response_text,
                    "parsing_error": None,
                    "success": True,
                }
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Anthropic returned invalid JSON: {e}")
                return {
                    "output": None,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "raw_response": response_text,
                    "parsing_error": str(e),
                    "success": False,
                }
        except Exception as e:
            logger.error(f"Anthropic extraction failed: {e}")
            return None


class OpenAIProvider(LLMProvider):
    """OpenAI (GPT) LLM provider."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.OPENAI_API_KEY
        self.model = config.OPENAI_MODEL
        self.client = None
        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")

    def classify(self, email_content: str) -> Optional[Dict]:
        if not self.client:
            return self._mock_classify_response()

        system_prompt = self.build_classify_system_prompt()
        user_prompt = self.build_classify_user_prompt(email_content)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=1024,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            response_text = response.choices[0].message.content
            try:
                parsed = _parse_json_response(response_text)
                return {
                    "output": parsed,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "raw_response": response_text,
                    "parsing_error": None,
                    "success": True,
                }
            except (json.JSONDecodeError, ValueError) as e:
                return {
                    "output": None,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "raw_response": response_text,
                    "parsing_error": str(e),
                    "success": False,
                }
        except Exception as e:
            logger.error(f"OpenAI classify failed: {e}")
            return None

    def extract(self, email_content: str, accounts: List[Dict], categories: List[Dict], resolved_account: Dict = None) -> Optional[Dict]:
        if not self.client:
            return self._mock_extract_response()

        system_prompt = self.build_system_prompt(accounts, categories)
        user_prompt = self.build_user_prompt(email_content)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=2048,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            response_text = response.choices[0].message.content
            try:
                parsed = _parse_json_response(response_text)
                return {
                    "output": parsed,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "raw_response": response_text,
                    "parsing_error": None,
                    "success": True,
                }
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"OpenAI returned invalid JSON: {e}")
                return {
                    "output": None,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "raw_response": response_text,
                    "parsing_error": str(e),
                    "success": False,
                }
        except Exception as e:
            logger.error(f"OpenAI extraction failed: {e}")
            return None


class GeminiProvider(LLMProvider):
    """Google Gemini LLM provider."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model = config.GEMINI_MODEL
        self._genai = None
        self.client = None
        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._genai = genai
                self.client = True  # SDK ready; models are created per-call
                logger.info(f"Gemini SDK initialized (model: {self.model})")
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini client: {e}")

    def _make_model(self, system_instruction: str, max_output_tokens: int):
        """Create a Gemini model instance with JSON output mode and correct token budget.

        Gemini 2.x thinking models share the max_output_tokens budget between
        internal reasoning and the visible response.  Keeping this value too low
        (e.g. 256) causes the JSON output to be truncated mid-stream.
        """
        genai = self._genai
        return genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system_instruction,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                max_output_tokens=max_output_tokens,
            ),
        )

    def _gemini_call(self, model, user_prompt: str, system_prompt: str,
                     max_retries: int = 3) -> Optional[Dict]:
        """Shared Gemini call + response handling with rate-limit retry."""
        import time
        import re

        for attempt in range(max_retries + 1):
            try:
                response = model.generate_content(user_prompt)

                if response.candidates:
                    finish_reason = response.candidates[0].finish_reason
                    if finish_reason and hasattr(finish_reason, "name") and finish_reason.name != "STOP":
                        logger.warning(f"Gemini finish_reason={finish_reason.name} — response may be incomplete")

                response_text = response.text
                try:
                    parsed = _parse_json_response(response_text)
                    return {
                        "output": parsed,
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                        "raw_response": response_text,
                        "parsing_error": None,
                        "success": True,
                    }
                except (json.JSONDecodeError, ValueError) as e:
                    return {
                        "output": None,
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                        "raw_response": response_text,
                        "parsing_error": str(e),
                        "success": False,
                    }

            except Exception as e:
                err_str = str(e)
                is_rate_limit = "429" in err_str or "ResourceExhausted" in type(e).__name__

                if is_rate_limit and attempt < max_retries:
                    # Parse the server-suggested retry delay from the error body
                    m = re.search(r"retry in ([\d.]+)s", err_str)
                    delay = float(m.group(1)) + 1.0 if m else (2 ** attempt) * 5.0
                    logger.warning(
                        f"Gemini rate-limited (attempt {attempt + 1}/{max_retries}), "
                        f"waiting {delay:.1f}s before retry"
                    )
                    time.sleep(delay)
                    continue

                logger.error(f"Gemini call failed (attempt {attempt + 1}): {type(e).__name__}: {err_str[:200]}")
                return None

        return None

    def classify(self, email_content: str) -> Optional[Dict]:
        if not self.client:
            return self._mock_classify_response()

        system_prompt = self.build_classify_system_prompt()
        user_prompt = self.build_classify_user_prompt(email_content)
        model = self._make_model(system_prompt, max_output_tokens=1024)
        return self._gemini_call(model, user_prompt, system_prompt)

    def extract(self, email_content: str, accounts: List[Dict], categories: List[Dict], resolved_account: Dict = None) -> Optional[Dict]:
        if not self.client:
            return self._mock_extract_response()

        system_prompt = self.build_system_prompt(accounts, categories)
        user_prompt = self.build_user_prompt(email_content)
        model = self._make_model(system_prompt, max_output_tokens=2048)
        return self._gemini_call(model, user_prompt, system_prompt)


class OllamaProvider(LLMProvider):
    """Ollama (local/self-hosted) LLM provider."""

    def __init__(self, base_url: str = None, model: str = None):
        self.base_url = base_url or config.OLLAMA_BASE_URL
        self.model = model or config.OLLAMA_MODEL
        self.client = None
        try:
            import requests
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                self.client = True
                logger.info(f"Connected to Ollama at {self.base_url}")
            else:
                logger.warning(f"Ollama connection failed: {response.status_code}")
        except Exception as e:
            logger.warning(f"Failed to connect to Ollama: {e}")

    def _call_ollama(self, prompt: str) -> Optional[str]:
        if not self.client:
            return None
        import requests
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=60,
            )
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            return None

    def classify(self, email_content: str) -> Optional[Dict]:
        if not self.client:
            return self._mock_classify_response()

        system_prompt = self.build_classify_system_prompt()
        user_prompt = self.build_classify_user_prompt(email_content)
        response_text = self._call_ollama(f"{system_prompt}\n\n{user_prompt}")

        if response_text is None:
            return None

        try:
            parsed = _parse_json_response(response_text)
            return {
                "output": parsed,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "raw_response": response_text,
                "parsing_error": None,
                "success": True,
            }
        except (json.JSONDecodeError, ValueError) as e:
            return {
                "output": None,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "raw_response": response_text,
                "parsing_error": str(e),
                "success": False,
            }

    def extract(self, email_content: str, accounts: List[Dict], categories: List[Dict], resolved_account: Dict = None) -> Optional[Dict]:
        if not self.client:
            return self._mock_extract_response()

        system_prompt = self.build_system_prompt(accounts, categories)
        user_prompt = self.build_user_prompt(email_content)
        response_text = self._call_ollama(f"{system_prompt}\n\n{user_prompt}")

        if response_text is None:
            return None

        try:
            parsed = _parse_json_response(response_text)
            return {
                "output": parsed,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "raw_response": response_text,
                "parsing_error": None,
                "success": True,
            }
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Ollama returned invalid JSON: {e}")
            return {
                "output": None,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "raw_response": response_text,
                "parsing_error": str(e),
                "success": False,
            }


def create_llm_client(provider: str = None) -> LLMProvider:
    """Factory function to create the appropriate LLM provider."""
    provider = provider or config.LLM_PROVIDER

    if provider == "anthropic":
        logger.info("Using Anthropic (Claude) as LLM provider")
        return AnthropicProvider()
    elif provider == "openai":
        logger.info("Using OpenAI (GPT) as LLM provider")
        return OpenAIProvider()
    elif provider == "gemini":
        logger.info("Using Google Gemini as LLM provider")
        return GeminiProvider()
    elif provider == "ollama":
        logger.info("Using Ollama (local) as LLM provider")
        return OllamaProvider()
    else:
        logger.warning(f"Unknown LLM provider: {provider}, defaulting to OpenAI")
        return OpenAIProvider()
