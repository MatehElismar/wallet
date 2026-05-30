import json
import logging
from typing import Dict, Optional, List
from abc import ABC, abstractmethod
import config

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def extract(self, email_content: str, accounts: List[Dict], categories: List[Dict]) -> Optional[Dict]:
        """Extract transaction from email and return JSON."""
        pass

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


class AnthropicProvider(LLMProvider):
    """Claude (Anthropic) LLM provider."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.ANTHROPIC_API_KEY
        self.model = config.ANTHROPIC_MODEL
        if self.api_key:
            try:
                from anthropic import Anthropic
                self.client = Anthropic(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize Anthropic client: {e}")
                self.client = None
        else:
            self.client = None

    def extract(self, email_content: str, accounts: List[Dict], categories: List[Dict]) -> Optional[Dict]:
        if not self.api_key:
            logger.warning("Anthropic API key not configured, returning mock response")
            return self._mock_response()

        if not self.client:
            logger.warning("Anthropic client initialization failed, returning mock response")
            return self._mock_response()

        system_prompt = self.build_system_prompt(accounts, categories)
        user_prompt = self.build_user_prompt(email_content)

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )
            response_text = message.content[0].text
            parsed = json.loads(response_text)
            logger.info(f"Anthropic extraction successful, skipReason={parsed.get('skipReason')}")
            return parsed
        except json.JSONDecodeError as e:
            logger.error(f"Anthropic returned invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Anthropic extraction failed: {e}")
            return None


class OpenAIProvider(LLMProvider):
    """OpenAI (GPT) LLM provider."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.OPENAI_API_KEY
        self.model = config.OPENAI_MODEL
        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")
                self.client = None
        else:
            self.client = None

    def extract(self, email_content: str, accounts: List[Dict], categories: List[Dict]) -> Optional[Dict]:
        if not self.api_key:
            logger.warning("OpenAI API key not configured, returning mock response")
            return self._mock_response()

        if not self.client:
            logger.warning("OpenAI client initialization failed, returning mock response")
            return self._mock_response()

        system_prompt = self.build_system_prompt(accounts, categories)
        user_prompt = self.build_user_prompt(email_content)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            response_text = response.choices[0].message.content
            parsed = json.loads(response_text)
            logger.info(f"OpenAI extraction successful, skipReason={parsed.get('skipReason')}")
            return parsed
        except json.JSONDecodeError as e:
            logger.error(f"OpenAI returned invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"OpenAI extraction failed: {e}")
            return None


class GeminiProvider(LLMProvider):
    """Google Gemini LLM provider."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model = config.GEMINI_MODEL
        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self.client = genai.GenerativeModel(self.model)
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini client: {e}")
                self.client = None
        else:
            self.client = None

    def extract(self, email_content: str, accounts: List[Dict], categories: List[Dict]) -> Optional[Dict]:
        if not self.api_key:
            logger.warning("Gemini API key not configured, returning mock response")
            return self._mock_response()

        if not self.client:
            logger.warning("Gemini client initialization failed, returning mock response")
            return self._mock_response()

        system_prompt = self.build_system_prompt(accounts, categories)
        user_prompt = self.build_user_prompt(email_content)

        try:
            response = self.client.generate_content(
                f"{system_prompt}\n\n{user_prompt}",
                generation_config={"max_output_tokens": 1024}
            )
            response_text = response.text
            parsed = json.loads(response_text)
            logger.info(f"Gemini extraction successful, skipReason={parsed.get('skipReason')}")
            return parsed
        except json.JSONDecodeError as e:
            logger.error(f"Gemini returned invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Gemini extraction failed: {e}")
            return None


class OllamaProvider(LLMProvider):
    """Ollama (local/self-hosted) LLM provider."""

    def __init__(self, base_url: str = None, model: str = None):
        self.base_url = base_url or config.OLLAMA_BASE_URL
        self.model = model or config.OLLAMA_MODEL
        self.client = None
        try:
            import requests
            # Test connection
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                self.client = True  # Just a flag; we use requests directly
                logger.info(f"Connected to Ollama at {self.base_url}")
            else:
                logger.warning(f"Ollama connection failed: {response.status_code}")
        except Exception as e:
            logger.warning(f"Failed to connect to Ollama: {e}")

    def extract(self, email_content: str, accounts: List[Dict], categories: List[Dict]) -> Optional[Dict]:
        if not self.client:
            logger.warning("Ollama not available, returning mock response")
            return self._mock_response()

        import requests

        system_prompt = self.build_system_prompt(accounts, categories)
        user_prompt = self.build_user_prompt(email_content)

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": f"{system_prompt}\n\n{user_prompt}",
                    "stream": False,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            response_text = data.get("response", "")
            # Try to extract JSON from response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                parsed = json.loads(json_str)
                logger.info(f"Ollama extraction successful, skipReason={parsed.get('skipReason')}")
                return parsed
            else:
                logger.error("Ollama response doesn't contain valid JSON")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"Ollama returned invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Ollama extraction failed: {e}")
            return None


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
