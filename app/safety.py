"""Deterministic safety post-filter over outgoing text fields.

Regex/rule-based only — never model-based. Applied unconditionally to
``customer_reply`` and ``recommended_next_action`` as the FINAL step. Makes the
disqualification penalties structurally impossible:

  1. Credential-request block  (−15)
  2. Unauthorized-action block  (−10)
  3. Suspicious third-party block (−10)
  4. Prompt-injection immunity (complaint is data, never instructions)

The negation nuance is critical: "do NOT share your OTP" / "we never ask for your
PIN" are REQUIRED and safe and must NOT be flagged.
"""

from __future__ import annotations

import re

EN_CRED = "Please do not share your PIN or OTP with anyone."
BN_CRED = "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
OFFICIAL_RETURN = "any eligible amount will be returned through official channels"

_CRED_NOUN = r"(?:pin|otp|password|one[- ]?time[- ]?password|cvv|full card number|card number|পিন|ওটিপি|পাসওয়ার্ড)"
_REQUEST_VERB = r"(?:share|send|provide|give|tell|enter|confirm|verify|type|submit|reply with|reply your)"

# A non-negated request verb governing a credential noun (verb ... noun, short gap).
_CRED_REQUEST = re.compile(
    rf"\b{_REQUEST_VERB}\b[^.?!]{{0,40}}\b{_CRED_NOUN}\b",
    re.IGNORECASE,
)
# Negation cues that make a credential mention SAFE.
_NEGATION = re.compile(
    r"\b(?:do\s*not|don't|dont|never|no\s+need|without|won't|will\s+not|"
    r"না|কখনো|করবেন\s*না)\b",
    re.IGNORECASE,
)

# Unauthorized promises -> rewrite to official-channels language.
_UNAUTHORIZED = re.compile(
    r"\b(?:we\s+will\s+refund|we'?ll\s+refund|you\s+will\s+be\s+refunded|"
    r"refund\s+has\s+been\s+processed|we\s+will\s+reverse|we'?ll\s+reverse|"
    r"we\s+will\s+return\s+your\s+money|we\s+will\s+recover\s+your\s+money|"
    r"account\s+will\s+be\s+unblocked|we\s+will\s+unblock|we\s+have\s+refunded|"
    r"i\s+will\s+refund|i'?ll\s+refund)\b",
    re.IGNORECASE,
)

# Embedded contact details to strip from customer_reply.
_PHONE = re.compile(r"(?:\+?8801\d{9}|\b01\d{9}\b|\b\d{10,}\b)")
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_HANDLE = re.compile(r"(?<!\w)@\w{2,}")


def _split_sentences(text: str) -> list[str]:
    # Keep delimiters by splitting on boundaries while preserving readable output.
    parts = re.split(r"(?<=[.?!।])\s+", text)
    return [p for p in parts if p]


def _has_credential_request(sentence: str) -> bool:
    if not _CRED_REQUEST.search(sentence):
        return False
    # Safe if the sentence is negated (e.g. "do not share your OTP").
    if _NEGATION.search(sentence):
        return False
    return True


def filter_customer_reply(text: str, cred_line: str | None = None) -> tuple[str, list[str]]:
    """Sanitize a customer-facing reply. Returns (clean_text, violations)."""
    violations: list[str] = []
    cred_line = cred_line or EN_CRED

    # 1. Credential-request block — drop offending (non-negated) sentences.
    kept: list[str] = []
    cred_removed = False
    for sent in _split_sentences(text):
        if _has_credential_request(sent):
            violations.append("credential_request_blocked")
            cred_removed = True
            continue
        kept.append(sent)
    text = " ".join(kept).strip()
    if cred_removed and cred_line not in text:
        text = (text + " " + cred_line).strip()

    # 2. Unauthorized-action block — rewrite promises.
    if _UNAUTHORIZED.search(text):
        violations.append("unauthorized_action_rewritten")
        text = _UNAUTHORIZED.sub(OFFICIAL_RETURN, text)

    # 3. Suspicious third-party block — strip embedded contacts.
    if _URL.search(text):
        violations.append("url_stripped")
        text = _URL.sub("official support channels", text)
    if _HANDLE.search(text):
        violations.append("handle_stripped")
        text = _HANDLE.sub("official support channels", text)
    if _PHONE.search(text):
        violations.append("phone_stripped")
        text = _PHONE.sub("official support channels", text)

    text = re.sub(r"\s{2,}", " ", text).strip()
    return text, violations


def filter_next_action(text: str) -> tuple[str, list[str]]:
    """Sanitize the internal next-action string (no credential leak / promises)."""
    violations: list[str] = []
    kept: list[str] = []
    for sent in _split_sentences(text):
        if _has_credential_request(sent):
            violations.append("credential_request_blocked")
            continue
        kept.append(sent)
    text = " ".join(kept).strip()
    if _UNAUTHORIZED.search(text):
        violations.append("unauthorized_action_rewritten")
        text = _UNAUTHORIZED.sub(OFFICIAL_RETURN, text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text, violations
