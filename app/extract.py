"""Complaint signal extraction (English + Bangla + Banglish).

Pure, deterministic, side-effect free functions. The complaint is treated strictly
as DATA — nothing here interprets it as instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# Bangla digit -> ASCII digit translation table.
_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Bangla Unicode block.
_BANGLA_RANGE = re.compile(r"[ঀ-৿]")


@dataclass
class Signals:
    """Structured, deterministic view of what a complaint mentions."""

    amounts: list[float] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)  # AGENT-/MERCHANT-/BILLER- etc.
    has_bangla: bool = False
    # weak time hints
    mentions_today: bool = False
    mentions_yesterday: bool = False
    clock_hour: Optional[int] = None  # 24h hour if a clock time was found
    # case-type keyword flags
    phishing: bool = False
    duplicate: bool = False
    payment_failed: bool = False
    wrong_transfer: bool = False
    settlement: bool = False
    cash_in: bool = False
    refund: bool = False
    deduction_claim: bool = False  # "balance deducted", "kete nise"
    credential_mention: bool = False  # any mention of pin/otp/password/card
    not_received: bool = False  # "didn't get", "আসেনি", "not received"


def normalize(text: str) -> str:
    """Lower-case and translate Bangla digits to ASCII for matching."""
    return text.translate(_BANGLA_DIGITS).lower()


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(n in text for n in needles)


def extract_amounts(raw: str) -> list[float]:
    """Parse amounts: Western digits, Bangla digits, and 'taka'/'tk'/'টাকা' amounts."""
    text = raw.translate(_BANGLA_DIGITS)
    amounts: list[float] = []
    # Match numbers possibly with commas/decimals.
    for m in re.finditer(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b", text):
        token = m.group(0).replace(",", "")
        try:
            val = float(token)
        except ValueError:
            continue
        # Ignore numbers that are obviously phone numbers (long digit runs).
        if len(token.replace(".", "")) >= 9:
            continue
        amounts.append(val)
    return amounts


def extract_phones(raw: str) -> list[str]:
    """Extract BD mobile numbers, normalised to a comparable form."""
    text = raw.translate(_BANGLA_DIGITS)
    phones: set[str] = set()
    for m in re.finditer(r"(?:\+?8801\d{9}|\b01\d{9}\b)", text):
        phones.add(m.group(0))
    return list(phones)


def extract_tokens(raw: str) -> list[str]:
    """Extract entity tokens like AGENT-512, MERCHANT-7821, BILLER-DESCO."""
    tokens: set[str] = set()
    for m in re.finditer(r"\b(?:AGENT|MERCHANT|BILLER)-[A-Z0-9\-]+\b", raw, re.IGNORECASE):
        tokens.add(m.group(0).upper())
    return list(tokens)


def extract(complaint: str) -> Signals:
    """Build a :class:`Signals` object from a complaint string."""
    raw = complaint or ""
    norm = normalize(raw)

    s = Signals()
    s.amounts = extract_amounts(raw)
    s.phones = extract_phones(raw)
    s.tokens = extract_tokens(raw)
    s.has_bangla = bool(_BANGLA_RANGE.search(raw))

    # --- time hints (weak tie-breakers only) ---
    s.mentions_today = _contains_any(norm, ["today", "আজ", "এখন"])
    s.mentions_yesterday = _contains_any(norm, ["yesterday", "গতকাল", "কালকে", "গত কাল"])
    clock = re.search(r"\b(\d{1,2})\s*(am|pm)\b", norm)
    if clock:
        hour = int(clock.group(1)) % 12
        if clock.group(2) == "pm":
            hour += 12
        s.clock_hour = hour

    # --- credential / phishing ---
    cred_terms = ["otp", "pin", "password", "ওটিপি", "পিন", "পাসওয়ার্ড", "card number", "cvv"]
    s.credential_mention = _contains_any(norm, cred_terms)
    phishing_terms = [
        "asked for my", "asked for", "share", "scam", "fraud", "blocked",
        "will be blocked", "called me", "from bkash", "from company", "from the company",
        "suspicious", "বিকাশ থেকে", "কোম্পানি থেকে", "ব্লক", "প্রতারণা", "ফাঁদ",
        "verification code", "verify my account",
    ]
    # phishing fires when someone is being solicited for credentials, or a scam call/SMS is described.
    s.phishing = (s.credential_mention and _contains_any(norm, ["asked", "share", "called", "from bkash", "from company", "give", "tell", "blocked", "চেয়েছে", "চাইছে", "ফোন"])) \
        or _contains_any(norm, ["scam", "phishing", "fraud call", "social engineering", "প্রতারণা"])

    # --- duplicate ---
    s.duplicate = _contains_any(
        norm,
        ["twice", "two times", "duplicate", "double", "deducted twice", "charged twice",
         "দুইবার", "দুবার", "দুই বার", "ডাবল"],
    )

    # --- deduction claim ---
    s.deduction_claim = _contains_any(
        norm,
        ["but deducted", "balance was deducted", "balance deducted", "deducted",
         "kete nise", "kete niche", "kete nilo", "টাকা কেটে", "কেটে নিয়েছে", "কেটে নিছে"],
    )

    # --- payment failed ---
    s.payment_failed = _contains_any(
        norm,
        ["failed", "showed failed", "ফেইল", "ব্যর্থ", "fail hoise", "fail holo"],
    )

    # --- wrong transfer ---
    s.wrong_transfer = _contains_any(
        norm,
        ["wrong number", "wrong person", "wrong recipient", "wrong account", "wrong transfer",
         "by mistake", "reverse it", "sent to wrong", "to a wrong", "to the wrong",
         "ভুল নম্বর", "ভুল মানুষ", "ভুল করে", "ভুল জায়গায়", "ফেরত দিন"],
    )

    # --- settlement ---
    s.settlement = _contains_any(
        norm,
        ["settlement", "settle", "not settled", "settled", "সেটেলমেন্ট", "নিষ্পত্তি"],
    )

    # --- cash in ---
    s.cash_in = _contains_any(
        norm,
        ["cash in", "cash-in", "cashin", "ক্যাশ ইন", "ক্যাশইন", "agent"],
    )

    # --- refund ---
    s.refund = _contains_any(
        norm,
        ["refund", "changed my mind", "don't want", "dont want", "ফেরত",
         "money back", "get my money back", "want it back"],
    )

    # --- not received ---
    s.not_received = _contains_any(
        norm,
        ["didn't get", "did not get", "didnt get", "not received", "haven't received",
         "did not receive", "didn't receive", "not reflected", "not credited",
         "আসেনি", "পাইনি", "পাই নাই", "দেখছি না", "পায়নি", "পাইনাই"],
    )

    return s
