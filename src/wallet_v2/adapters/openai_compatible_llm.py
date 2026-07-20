"""Strict JSON extraction through OpenAI-compatible chat-completions APIs."""

from __future__ import annotations

import json
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from wallet_v2.application.contracts import (
    ExtractedStatement,
    ExtractedTransaction,
    ExtractionResult,
    MailboxMessage,
)
from wallet_v2.domain.enums import (
    DocumentKind,
    FinancialEventStatus,
    TransactionDirection,
)


_DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# These aliases are deliberately narrow. A symbol such as ``$`` is ambiguous
# and must be rejected; ``RD$`` is the unambiguous Dominican-peso notation.
_CURRENCY_ALIASES = {"RD$": "DOP"}


class OpenAICompatibleExtractor:
    """Call a configured OpenAI-compatible model with one extraction contract.

    ``openai``, ``gemini``, ``deepseek``, and ``openrouter`` have safe
    built-in endpoint aliases. Any other compatible gateway can be selected
    with its own ``base_url``. Provider selection changes only endpoint,
    credentials, and model name; it never changes extraction semantics.
    """

    def __init__(
        self, *, provider: str, model: str, api_key: str, timeout_seconds: float,
        base_url: str | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = (base_url or _DEFAULT_BASE_URLS.get(provider, "")).rstrip("/")
        if not self.base_url:
            raise ValueError("an explicit base_url is required for this LLM provider")

    def extract(self, message: MailboxMessage) -> ExtractionResult:
        request_payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classify and extract financial evidence from an email. Return JSON only: "
                        "{is_transaction:boolean, document_kind:'notification'|'statement'|null, "
                        "statement:{issuer:string,account_reference:string,period_start:'YYYY-MM-DD'|null, "
                        "period_end:'YYYY-MM-DD'|null,statement_date:'YYYY-MM-DD'|null,currency:string|null, "
                        "opening_balance_minor:integer|null,closing_balance_minor:integer|null}|null, "
                        "transactions:[{direction:'debit'|'credit', "
                        "amount_minor:integer, currency:string, merchant:string|null, "
                        "reference:string|null, transaction_date:'YYYY-MM-DD'|null, "
                        "posting_date:'YYYY-MM-DD'|null,running_balance_minor:integer|null, "
                        "issuer:string|null,account_reference:string|null, "
                        "event_status:'posted'|'reversed'|'cancelled',related_reference:string|null}]}. "
                        "Currency must be a three-letter ISO-4217 code such as USD or DOP, "
                        "never a currency symbol. "
                        "For a periodic statement, return document_kind:'statement', its account "
                        "metadata, and every completed line item; do not select an arbitrary row. "
                        "For a notification return document_kind:'notification' and statement:null. "
                        "Return {is_transaction:false,document_kind:null,statement:null,transactions:[]} "
                        "when no completed transaction exists."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"subject": message.subject, "sender": message.sender, "body": message.body_text},
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(request_payload).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310 -- configured endpoint
                raw = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"LLM extraction request failed: {exc}") from exc
        envelope = json.loads(raw)
        try:
            content = envelope["choices"][0]["message"]["content"]
            structured = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("LLM response was not valid structured extraction JSON") from exc
        return self._parse(structured, envelope)

    def _parse(self, structured: object, raw: dict[str, object]) -> ExtractionResult:
        if not isinstance(structured, dict) or not isinstance(structured.get("is_transaction"), bool):
            raise ValueError("LLM extraction must contain boolean is_transaction")
        raw_transactions = structured.get("transactions", [])
        if not isinstance(raw_transactions, list):
            raise ValueError("LLM extraction transactions must be a list")
        if not structured["is_transaction"]:
            if raw_transactions:
                raise ValueError("non-transaction extraction must not include transactions")
            return ExtractionResult(
                is_transaction=False,
                transaction=None,
                raw_response=raw,
                structured_output=structured,
                model_id=self.model,
                token_usage=raw.get("usage") if isinstance(raw.get("usage"), dict) else None,
            )
        if not raw_transactions:
            raise ValueError("transaction extraction must include one or more transactions")
        if len(raw_transactions) > 100:
            raise ValueError("LLM extraction may include at most 100 transactions")
        transactions = tuple(self._parse_transaction(item) for item in raw_transactions)
        raw_kind = structured.get("document_kind")
        if raw_kind is None:
            document_kind = DocumentKind.STATEMENT if structured.get("statement") else DocumentKind.NOTIFICATION
        else:
            try:
                document_kind = DocumentKind(raw_kind)
            except (TypeError, ValueError) as exc:
                raise ValueError("LLM document_kind must be notification or statement") from exc
        statement = self._parse_statement(structured.get("statement")) if document_kind == DocumentKind.STATEMENT else None
        return ExtractionResult(
            is_transaction=True,
            transaction=transactions[0],
            transactions=transactions,
            document_kind=document_kind,
            statement=statement,
            raw_response=raw,
            structured_output=structured,
            model_id=self.model,
            token_usage=raw.get("usage") if isinstance(raw.get("usage"), dict) else None,
        )

    @staticmethod
    def _parse_transaction(item: object) -> ExtractedTransaction:
        if not isinstance(item, dict):
            raise ValueError("each LLM transaction must be an object")
        amount = item.get("amount_minor")
        raw_currency = item.get("currency")
        currency = _CURRENCY_ALIASES.get(raw_currency, raw_currency) if isinstance(raw_currency, str) else raw_currency
        if type(amount) is not int or amount <= 0:
            raise ValueError("LLM transaction amount_minor must be a positive integer")
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isupper():
            raise ValueError("LLM transaction currency must be a three-letter uppercase code")
        try:
            direction = TransactionDirection(item.get("direction"))
        except (TypeError, ValueError) as exc:
            raise ValueError("LLM transaction direction must be debit or credit") from exc
        raw_date = item.get("transaction_date")
        raw_posting_date = item.get("posting_date")
        running_balance_minor = item.get("running_balance_minor")
        if running_balance_minor is not None and type(running_balance_minor) is not int:
            raise ValueError("LLM transaction running_balance_minor must be an integer or null")
        raw_event_status = item.get("event_status", FinancialEventStatus.POSTED.value)
        try:
            event_status = FinancialEventStatus(raw_event_status)
        except (TypeError, ValueError) as exc:
            raise ValueError("LLM transaction event_status must be posted, reversed, or cancelled") from exc
        return ExtractedTransaction(
            direction=direction,
            amount_minor=amount,
            currency=currency,
            merchant=item.get("merchant") if isinstance(item.get("merchant"), str) else None,
            reference=item.get("reference") if isinstance(item.get("reference"), str) else None,
            transaction_date=date.fromisoformat(raw_date) if isinstance(raw_date, str) else None,
            posting_date=date.fromisoformat(raw_posting_date) if isinstance(raw_posting_date, str) else None,
            running_balance_minor=running_balance_minor,
            issuer=item.get("issuer").strip() if isinstance(item.get("issuer"), str) and item.get("issuer").strip() else None,
            account_reference=item.get("account_reference").strip() if isinstance(item.get("account_reference"), str) and item.get("account_reference").strip() else None,
            event_status=event_status,
            related_reference=item.get("related_reference").strip() if isinstance(item.get("related_reference"), str) and item.get("related_reference").strip() else None,
        )

    @staticmethod
    def _parse_statement(raw_statement: object) -> ExtractedStatement:
        if not isinstance(raw_statement, dict):
            raise ValueError("statement extraction must include a statement object")
        issuer = raw_statement.get("issuer")
        account_reference = raw_statement.get("account_reference")
        if not isinstance(issuer, str) or not issuer.strip():
            raise ValueError("statement issuer must be a non-blank string")
        if not isinstance(account_reference, str) or not account_reference.strip():
            raise ValueError("statement account_reference must be a non-blank string")
        currency = raw_statement.get("currency")
        if currency is not None:
            currency = _CURRENCY_ALIASES.get(currency, currency)
            if not isinstance(currency, str) or len(currency) != 3 or not currency.isupper():
                raise ValueError("statement currency must be a three-letter uppercase code or null")
        balance_values = ("opening_balance_minor", "closing_balance_minor")
        for field in balance_values:
            value = raw_statement.get(field)
            if value is not None and type(value) is not int:
                raise ValueError(f"statement {field} must be an integer or null")
        return ExtractedStatement(
            issuer=issuer.strip(),
            account_reference=account_reference.strip(),
            period_start=OpenAICompatibleExtractor._parse_optional_date(raw_statement.get("period_start")),
            period_end=OpenAICompatibleExtractor._parse_optional_date(raw_statement.get("period_end")),
            statement_date=OpenAICompatibleExtractor._parse_optional_date(raw_statement.get("statement_date")),
            currency=currency,
            opening_balance_minor=raw_statement.get("opening_balance_minor"),
            closing_balance_minor=raw_statement.get("closing_balance_minor"),
        )

    @staticmethod
    def _parse_optional_date(value: object) -> date | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("statement dates must be YYYY-MM-DD strings or null")
        return date.fromisoformat(value)
