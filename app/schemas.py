"""Pydantic v2 request/response models and enums for QueueStorm Investigator.

All enum values match the problem statement EXACTLY (case-sensitive). The request
model is deliberately liberal on optional fields: unknown / garbage enum values are
coerced to ``None`` rather than raising 422. Only ``ticket_id`` and ``complaint`` are
strictly required.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------- #
# Enums (exact spelling / casing — any variant is a schema violation)
# --------------------------------------------------------------------------- #
class Language(str, Enum):
    en = "en"
    bn = "bn"
    mixed = "mixed"


class Channel(str, Enum):
    in_app_chat = "in_app_chat"
    call_center = "call_center"
    email = "email"
    merchant_portal = "merchant_portal"
    field_agent = "field_agent"


class UserType(str, Enum):
    customer = "customer"
    merchant = "merchant"
    agent = "agent"
    unknown = "unknown"


class TransactionType(str, Enum):
    transfer = "transfer"
    payment = "payment"
    cash_in = "cash_in"
    cash_out = "cash_out"
    settlement = "settlement"
    refund = "refund"


class TransactionStatus(str, Enum):
    completed = "completed"
    failed = "failed"
    pending = "pending"
    reversed = "reversed"


class EvidenceVerdict(str, Enum):
    consistent = "consistent"
    inconsistent = "inconsistent"
    insufficient_data = "insufficient_data"


class CaseType(str, Enum):
    wrong_transfer = "wrong_transfer"
    payment_failed = "payment_failed"
    refund_request = "refund_request"
    duplicate_payment = "duplicate_payment"
    merchant_settlement_delay = "merchant_settlement_delay"
    agent_cash_in_issue = "agent_cash_in_issue"
    phishing_or_social_engineering = "phishing_or_social_engineering"
    other = "other"


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Department(str, Enum):
    customer_support = "customer_support"
    dispute_resolution = "dispute_resolution"
    payments_ops = "payments_ops"
    merchant_operations = "merchant_operations"
    agent_operations = "agent_operations"
    fraud_risk = "fraud_risk"


def _coerce_enum(value: Any, enum_cls: type[Enum]) -> Optional[Enum]:
    """Coerce a raw value to an enum member, or ``None`` if it does not match.

    Liberal-in-what-you-accept: unknown / garbage values become ``None`` instead of
    raising a validation error.
    """
    if value is None:
        return None
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value).strip())
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Transaction entry (tolerant of missing / mistyped sub-fields)
# --------------------------------------------------------------------------- #
class TxnEntry(BaseModel):
    model_config = {"extra": "ignore"}

    transaction_id: str = ""
    timestamp: str = ""
    type: str = ""
    amount: float = 0.0
    counterparty: str = ""
    status: str = ""

    @field_validator("transaction_id", "timestamp", "type", "counterparty", "status", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: Any) -> float:
        if v is None or v == "":
            return 0.0
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0


# --------------------------------------------------------------------------- #
# Request model
# --------------------------------------------------------------------------- #
class AnalyzeRequest(BaseModel):
    model_config = {"extra": "ignore"}

    ticket_id: str
    complaint: str

    language: Optional[Language] = None
    channel: Optional[Channel] = None
    user_type: Optional[UserType] = None
    campaign_context: Optional[str] = None
    transaction_history: list[TxnEntry] = Field(default_factory=list)
    metadata: Optional[dict] = None

    @field_validator("language", mode="before")
    @classmethod
    def _v_language(cls, v: Any) -> Optional[Language]:
        return _coerce_enum(v, Language)

    @field_validator("channel", mode="before")
    @classmethod
    def _v_channel(cls, v: Any) -> Optional[Channel]:
        return _coerce_enum(v, Channel)

    @field_validator("user_type", mode="before")
    @classmethod
    def _v_user_type(cls, v: Any) -> Optional[UserType]:
        return _coerce_enum(v, UserType)

    @field_validator("campaign_context", mode="before")
    @classmethod
    def _v_campaign(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v)

    @field_validator("transaction_history", mode="before")
    @classmethod
    def _v_history(cls, v: Any) -> list:
        # Tolerate a non-list (e.g. null, dict, garbage) by falling back to empty.
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return []

    @field_validator("metadata", mode="before")
    @classmethod
    def _v_metadata(cls, v: Any) -> Optional[dict]:
        if isinstance(v, dict):
            return v
        return None


# --------------------------------------------------------------------------- #
# Response model
# --------------------------------------------------------------------------- #
class AnalyzeResponse(BaseModel):
    ticket_id: str
    relevant_transaction_id: Optional[str] = None
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: Optional[float] = None
    reason_codes: Optional[list[str]] = None
