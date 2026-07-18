"""
AccountResolver — pre-resolve Wallet account from email signals before LLM extraction.

Resolution priority:
  1. Card last-4 digits extracted from email body  (high confidence)
  2. Bank name + account type heuristic            (medium confidence)
  3. Bank name only → list of candidates           (low confidence, LLM picks)
  4. No resolution → LLM sees all active accounts  (no confidence)
"""

import re
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Bank alias map ────────────────────────────────────────────────────────────
# Maps a canonical bank key to strings that identify it in email sender/subject/body.
# Order within each list matters — more specific phrases first.
BANK_ALIASES: Dict[str, List[str]] = {
    "bhd":        ["banco bhd", "bhd león", "bhd leon", "bhd movil", "bhd"],
    "popular":    ["banco popular", "bancopopular", "popular"],
    "banreservas":["banco de reservas", "banreservas", "reservas"],
    "santa_cruz": ["banco santa cruz", "santa cruz"],
    "vimenca":    ["banco vimenca", "vimenca"],
    "qik":        ["qikmobile", "qik"],
    "gpay":       ["google pay", "g pay", "gpay"],
    "fundapec":   ["fundapec"],
}

# ── Card-digit extraction patterns (most-specific first) ─────────────────────
_DIGIT_PATTERNS = [
    # **** **** **** 1234  or  ****-****-****-1234
    re.compile(r'\*{4}[\s\-]*\*{4}[\s\-]*\*{4}[\s\-]*(\d{4})'),
    # ****1234  or  **** 1234
    re.compile(r'\*{4}[\s\-]?(\d{4})\b'),
    # "terminada en 1234" / "termina en 1234"
    re.compile(r'termina(?:da)?\s+en\s+(\d{4})', re.I),
    # "ending in 1234"
    re.compile(r'ending\s+in\s+(\d{4})', re.I),
    # "tarjeta Qik 2197" / "tarjeta BHD 1281" (card name then digits)
    re.compile(r'tarjeta\s+\w+\s+(\d{4})\b', re.I),
    # "tarjeta 1234" (card then digits, no intervening word)
    re.compile(r'tarjeta[^0-9\n]{0,20}(\d{4})\b', re.I),
    # "tu cuenta ...1234" / "cuenta terminada 1234"
    re.compile(r'cuenta[^0-9\n]{0,20}(\d{4})\b', re.I),
]

# Account types that correspond to "debit/credit card" email notifications
_CARD_ACCOUNT_TYPES = {"CreditCard", "General", "CurrentAccount"}


def _extract_card_digits(text: str) -> Optional[str]:
    """Return the first 4-digit card/account identifier found in the text."""
    for pattern in _DIGIT_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1)
    return None


def _detect_bank(sender: str, subject: str, body: str) -> Optional[str]:
    """Return a canonical bank key from the email sender / subject / body."""
    # Sender domain is the strongest signal
    combined = f"{sender} {subject} {body[:500]}".lower()
    for bank_key, aliases in BANK_ALIASES.items():
        if any(alias in combined for alias in aliases):
            return bank_key
    return None


def _detect_currency(body: str) -> Optional[str]:
    """Guess transaction currency from email body ('USD' or 'DOP')."""
    lower = body.lower()
    if "usd" in lower or "us$" in lower or "dollar" in lower:
        return "USD"
    if "dop" in lower or "rd$" in lower or "peso" in lower:
        return "DOP"
    return None


class AccountResolver:
    """
    Built once at bootstrap from the real account list; called per email to
    pre-resolve which Wallet account the transaction belongs to.
    """

    def __init__(self, accounts: List[Dict]):
        # id → full account object (active only)
        self._accounts: Dict[str, Dict] = {
            a["id"]: a for a in accounts if not a.get("archived")
        }
        # last-4 digits → {dop_id, usd_id}
        self._digits_index: Dict[str, Dict[str, str]] = {}
        # bank_key → list of account ids
        self._bank_index: Dict[str, List[str]] = {}

        self._build_indexes()

    def _build_indexes(self):
        for acc_id, acc in self._accounts.items():
            name = acc["name"]
            currency = (acc.get("initialBalance") or {}).get("currencyCode", "DOP")

            # ── digits index ─────────────────────────────────────────────────
            m = re.search(r'\b(\d{4})\b', name)
            if m:
                digits = m.group(1)
                entry = self._digits_index.setdefault(digits, {})
                # DOP is the primary slot; USD only fills the usd slot
                if currency == "USD":
                    entry["usd"] = acc_id
                else:
                    entry.setdefault("dop", acc_id)
                    entry["dop"] = acc_id  # always overwrite with DOP

            # ── bank index ───────────────────────────────────────────────────
            name_lower = name.lower()
            for bank_key, aliases in BANK_ALIASES.items():
                if any(alias in name_lower for alias in aliases):
                    self._bank_index.setdefault(bank_key, []).append(acc_id)
                    break

        logger.debug(
            f"AccountResolver indexed {len(self._accounts)} accounts, "
            f"{len(self._digits_index)} digit entries, "
            f"{len(self._bank_index)} bank groups"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def resolve(
        self,
        subject: str,
        sender: str,
        body: str,
        bank_hint: Optional[str] = None,
        amount_str: Optional[str] = None,
    ) -> Dict:
        """
        Returns a resolution dict:
          confidence='high'   → {confidence, account_id, account_name, method}
          confidence='medium' → same (bank + type gave single candidate)
          confidence='low'    → {confidence, candidates: [{id, name, type, currency}], method}
          confidence='none'   → {confidence}  (LLM sees full account list)
        """
        currency_hint = _detect_currency(body) or _detect_currency(subject)

        # ── 0. Explicit account name in email text ───────────────────────────
        combined_lower = f"{subject} {body}".lower()
        for acc_id, acc in self._accounts.items():
            name_lower = acc["name"].lower()
            # Only match specific names (avoid single-word bank names matching broadly)
            if len(name_lower) >= 6 and name_lower in combined_lower:
                logger.debug(f"Resolved by name match {acc['name']!r}")
                return {
                    "confidence": "high",
                    "account_id": acc_id,
                    "account_name": acc["name"],
                    "account_type": acc.get("accountType"),
                    "currency": (acc.get("initialBalance") or {}).get("currencyCode"),
                    "method": f"name:{acc['name']}",
                }

        # ── 1. Card last-4 digits ────────────────────────────────────────────
        digits = _extract_card_digits(body) or _extract_card_digits(subject)
        if digits and digits in self._digits_index:
            entry = self._digits_index[digits]
            # Prefer USD variant when amount currency suggests it
            acc_id = (
                entry.get("usd") if currency_hint == "USD" else None
            ) or entry.get("dop") or next(iter(entry.values()))
            acc = self._accounts[acc_id]
            logger.debug(f"Resolved by card digits {digits} → {acc['name']!r}")
            return {
                "confidence": "high",
                "account_id": acc_id,
                "account_name": acc["name"],
                "account_type": acc.get("accountType"),
                "currency": (acc.get("initialBalance") or {}).get("currencyCode"),
                "method": f"digits:{digits}",
            }

        # ── 2. Bank detection ────────────────────────────────────────────────
        bank_key = bank_hint or _detect_bank(sender, subject, body)
        if bank_key and bank_key in self._bank_index:
            candidates = self._bank_index[bank_key]

            # Narrow by currency if we have a hint
            if currency_hint:
                narrowed = [
                    c for c in candidates
                    if (self._accounts[c].get("initialBalance") or {}).get("currencyCode") == currency_hint
                ]
                candidates = narrowed or candidates  # fall back if narrowing leaves nothing

            # Narrow by account type based on email signals
            body_lower = (subject + " " + body).lower()
            if "crédito" in body_lower or "credito" in body_lower or "credit" in body_lower:
                narrowed = [c for c in candidates if self._accounts[c].get("accountType") == "CreditCard"]
                candidates = narrowed or candidates
            elif "débito" in body_lower or "debito" in body_lower or "movil" in body_lower:
                narrowed = [c for c in candidates if self._accounts[c].get("accountType") != "CreditCard"]
                candidates = narrowed or candidates

            if len(candidates) == 1:
                acc = self._accounts[candidates[0]]
                logger.debug(f"Resolved by bank {bank_key!r} (single) → {acc['name']!r}")
                return {
                    "confidence": "medium",
                    "account_id": candidates[0],
                    "account_name": acc["name"],
                    "account_type": acc.get("accountType"),
                    "currency": (acc.get("initialBalance") or {}).get("currencyCode"),
                    "method": f"bank:{bank_key}",
                }
            elif candidates:
                logger.debug(f"Resolved by bank {bank_key!r} → {len(candidates)} candidates")
                return {
                    "confidence": "low",
                    "method": f"bank:{bank_key}",
                    "candidates": [self._account_summary(c) for c in candidates],
                }

        # ── 3. No resolution ─────────────────────────────────────────────────
        return {"confidence": "none"}

    def _account_summary(self, acc_id: str) -> Dict:
        acc = self._accounts[acc_id]
        return {
            "id": acc_id,
            "name": acc["name"],
            "type": acc.get("accountType"),
            "currency": (acc.get("initialBalance") or {}).get("currencyCode", "DOP"),
        }

    def all_active_accounts(self) -> List[Dict]:
        """Return all active accounts as summaries for the LLM fallback."""
        return [self._account_summary(acc_id) for acc_id in self._accounts]
