"""Reasoning layer: verdict, case_type, severity, department, human review.

Rules are reverse-engineered from the worked sample cases and are written to
GENERALISE. Nothing here branches on ``ticket_id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .extract import Signals
from .matcher import MatchContext
from .schemas import (
    CaseType,
    Department,
    EvidenceVerdict,
    Severity,
)


@dataclass
class Reasoning:
    case_type: CaseType
    evidence_verdict: EvidenceVerdict
    severity: Severity
    department: Department
    human_review_required: bool
    confidence: float
    reason_codes: list[str] = field(default_factory=list)


_DEPARTMENT_BY_CASE = {
    CaseType.wrong_transfer: Department.dispute_resolution,
    CaseType.payment_failed: Department.payments_ops,
    CaseType.duplicate_payment: Department.payments_ops,
    CaseType.refund_request: Department.customer_support,
    CaseType.merchant_settlement_delay: Department.merchant_operations,
    CaseType.agent_cash_in_issue: Department.agent_operations,
    CaseType.phishing_or_social_engineering: Department.fraud_risk,
    CaseType.other: Department.customer_support,
}

_BASE_SEVERITY = {
    CaseType.wrong_transfer: Severity.high,
    CaseType.payment_failed: Severity.high,
    CaseType.duplicate_payment: Severity.high,
    CaseType.agent_cash_in_issue: Severity.high,
    CaseType.merchant_settlement_delay: Severity.medium,
    CaseType.refund_request: Severity.low,
    CaseType.other: Severity.low,
}

_SEVERITY_ORDER = [Severity.low, Severity.medium, Severity.high, Severity.critical]


def _drop_one_notch(sev: Severity) -> Severity:
    idx = _SEVERITY_ORDER.index(sev)
    return _SEVERITY_ORDER[max(0, idx - 1)]


def _classify_case_type(signals: Signals, ctx: MatchContext,
                        user_type: Optional[str], channel: Optional[str]) -> CaseType:
    """First-match-wins priority resolution driven by mechanism, not surface keywords."""
    matched = ctx.matched_txn
    matched_type = (matched.type or "").lower() if matched else ""

    # 1. phishing / social engineering wins over everything.
    if signals.phishing:
        return CaseType.phishing_or_social_engineering

    # 2. duplicate payment.
    if ctx.duplicate_cluster or signals.duplicate:
        return CaseType.duplicate_payment

    # 3. payment failed (failure claim, often with deduction).
    if signals.payment_failed:
        return CaseType.payment_failed

    # 4. wrong transfer: explicit wrong/mistake/reverse, or a "sent to someone who
    #    didn't receive" transfer dispute.
    transfer_dispute = signals.wrong_transfer or (
        signals.not_received
        and not signals.cash_in
        and not signals.settlement
        and not signals.payment_failed
    )
    if transfer_dispute and matched_type in ("transfer", ""):
        # When there is a matched txn it should look like a transfer; with no match
        # (ambiguous/none) we still classify from the complaint shape.
        if matched is None or matched_type == "transfer":
            return CaseType.wrong_transfer

    # 5. merchant settlement delay.
    is_merchant = user_type == "merchant" or channel == "merchant_portal"
    if signals.settlement or (is_merchant and signals.not_received):
        return CaseType.merchant_settlement_delay

    # 6. agent cash-in issue.
    if signals.cash_in and (signals.not_received or matched_type == "cash_in"):
        return CaseType.agent_cash_in_issue

    # 7. refund request (change of mind on a completed payment).
    if signals.refund:
        return CaseType.refund_request

    # 8. fallback.
    return CaseType.other


def _verdict(case_type: CaseType, signals: Signals, ctx: MatchContext) -> EvidenceVerdict:
    if ctx.chosen_id is None:
        return EvidenceVerdict.insufficient_data

    matched = ctx.matched_txn
    status = (matched.status or "").lower() if matched else ""

    # Contradiction detectors -> inconsistent.
    if case_type == CaseType.wrong_transfer and ctx.established_recipient:
        return EvidenceVerdict.inconsistent
    if signals.payment_failed and status == "completed":
        return EvidenceVerdict.inconsistent

    return EvidenceVerdict.consistent


def _severity(case_type: CaseType, verdict: EvidenceVerdict) -> Severity:
    if case_type == CaseType.phishing_or_social_engineering:
        return Severity.critical
    base = _BASE_SEVERITY[case_type]
    if verdict in (EvidenceVerdict.inconsistent, EvidenceVerdict.insufficient_data) \
            and base == Severity.high:
        return _drop_one_notch(base)
    return base


def _human_review(case_type: CaseType, ctx: MatchContext) -> bool:
    if case_type == CaseType.phishing_or_social_engineering:
        return True
    if case_type == CaseType.wrong_transfer:
        return ctx.chosen_id is not None
    if case_type == CaseType.duplicate_payment:
        return ctx.chosen_id is not None
    if case_type == CaseType.agent_cash_in_issue:
        return True
    return False


def _confidence(case_type: CaseType, verdict: EvidenceVerdict, ctx: MatchContext) -> float:
    if case_type == CaseType.phishing_or_social_engineering:
        return 0.95
    if verdict == EvidenceVerdict.insufficient_data:
        return 0.65 if ctx.ambiguous else 0.6
    if verdict == EvidenceVerdict.inconsistent:
        return 0.75
    # consistent
    by_case = {
        CaseType.duplicate_payment: 0.93,
        CaseType.merchant_settlement_delay: 0.92,
        CaseType.wrong_transfer: 0.9,
        CaseType.payment_failed: 0.9,
        CaseType.agent_cash_in_issue: 0.88,
        CaseType.refund_request: 0.85,
        CaseType.other: 0.7,
    }
    return by_case.get(case_type, 0.85)


def _reason_codes(case_type: CaseType, verdict: EvidenceVerdict, ctx: MatchContext) -> list[str]:
    codes: list[str] = [case_type.value]
    if case_type == CaseType.phishing_or_social_engineering:
        return ["phishing", "credential_protection", "critical_escalation"]
    if ctx.ambiguous:
        return ["ambiguous_match", "needs_clarification"]
    if verdict == EvidenceVerdict.insufficient_data:
        codes.append("needs_clarification" if ctx.chosen_id is None else "insufficient_evidence")
        if case_type == CaseType.other:
            return ["vague_complaint", "needs_clarification"]
        return codes
    if verdict == EvidenceVerdict.inconsistent:
        if ctx.established_recipient:
            return ["wrong_transfer_claim", "established_recipient_pattern", "evidence_inconsistent"]
        return [case_type.value, "evidence_inconsistent"]
    # consistent
    if ctx.chosen_id is not None:
        codes.append("transaction_match")
    if case_type == CaseType.duplicate_payment:
        codes.append("biller_verification_required")
    elif case_type == CaseType.wrong_transfer:
        codes.append("dispute_initiated")
    elif case_type == CaseType.merchant_settlement_delay:
        codes.append("pending")
    elif case_type == CaseType.agent_cash_in_issue:
        codes.append("pending_transaction")
    elif case_type == CaseType.refund_request:
        codes.append("merchant_policy_dependent")
    elif case_type == CaseType.payment_failed:
        codes.append("potential_balance_deduction")
    return codes


def reason(signals: Signals, ctx: MatchContext,
           user_type: Optional[str], channel: Optional[str]) -> Reasoning:
    case_type = _classify_case_type(signals, ctx, user_type, channel)
    verdict = _verdict(case_type, signals, ctx)
    severity = _severity(case_type, verdict)
    department = _DEPARTMENT_BY_CASE[case_type]
    human = _human_review(case_type, ctx)
    confidence = _confidence(case_type, verdict, ctx)
    codes = _reason_codes(case_type, verdict, ctx)
    return Reasoning(
        case_type=case_type,
        evidence_verdict=verdict,
        severity=severity,
        department=department,
        human_review_required=human,
        confidence=confidence,
        reason_codes=codes,
    )
