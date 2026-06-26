"""Orchestration: request -> signals -> match -> reasoning -> replies -> safety."""

from __future__ import annotations

from . import extract, matcher, reasoning as reasoning_mod, replies, safety
from .schemas import AnalyzeRequest, AnalyzeResponse


def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    signals = extract.extract(req.complaint)

    ctx = matcher.match(signals, req.transaction_history)

    user_type = req.user_type.value if req.user_type else None
    channel = req.channel.value if req.channel else None
    r = reasoning_mod.reason(signals, ctx, user_type, channel)

    lang = replies.detect_language(req.language.value if req.language else None, req.complaint)
    cred_line = replies.BN_CRED if lang == "bn" else replies.EN_CRED

    agent_summary = replies.build_agent_summary(r, ctx, signals)
    next_action = replies.build_next_action(r, ctx)
    customer_reply = replies.build_customer_reply(r, ctx, lang, user_type)

    # FINAL safety pass over outgoing text (unconditional).
    customer_reply, _v1 = safety.filter_customer_reply(customer_reply, cred_line)
    next_action, _v2 = safety.filter_next_action(next_action)

    return AnalyzeResponse(
        ticket_id=req.ticket_id,
        relevant_transaction_id=ctx.chosen_id,
        evidence_verdict=r.evidence_verdict,
        case_type=r.case_type,
        severity=r.severity,
        department=r.department,
        agent_summary=agent_summary,
        recommended_next_action=next_action,
        customer_reply=customer_reply,
        human_review_required=r.human_review_required,
        confidence=round(r.confidence, 2),
        reason_codes=r.reason_codes,
    )
