"""Transaction matching -> ``relevant_transaction_id``.

Scores each transaction against extracted signals and applies the decision rules,
including the ambiguity rule (Sample-08) and the duplicate-cluster rule (Sample-10).
Returns the chosen id plus a small :class:`MatchContext` for the reasoning layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .extract import Signals
from .schemas import TxnEntry

# Scoring weights
W_AMOUNT = 5
W_COUNTERPARTY = 5
W_TYPE = 2
W_STATUS = 2
W_TIME = 1

MIN_FLOOR = 5  # nothing even matches amount or counterparty below this
NEAR_TIE = 1  # points within which two tops are "near-tied"
DUP_WINDOW_SECONDS = 300  # "a few minutes" for a duplicate cluster


@dataclass
class MatchContext:
    chosen_id: Optional[str] = None
    matched_txn: Optional[TxnEntry] = None
    ambiguous: bool = False
    duplicate_cluster: bool = False
    established_recipient: bool = False
    top_score: int = 0
    scores: dict = field(default_factory=dict)


def normalize_phone(value: str) -> Optional[str]:
    """Reduce a BD phone-ish string to its 10-digit subscriber form for comparison."""
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("880") and len(digits) >= 13:
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        return digits
    return digits or None


def _expected_types(signals: Signals) -> set[str]:
    """Rough mechanism inference (independent of any chosen txn) for type alignment."""
    types: set[str] = set()
    if signals.wrong_transfer:
        types.add("transfer")
    if signals.payment_failed or signals.duplicate or signals.refund:
        types.add("payment")
    if signals.settlement:
        types.add("settlement")
    if signals.cash_in:
        types.add("cash_in")
    # "sent X to someone" with a non-receipt complaint is transfer-shaped.
    if signals.not_received and not types:
        types.add("transfer")
    return types


def _parse_ts(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _counterparty_matches(signals: Signals, txn: TxnEntry) -> bool:
    cp = (txn.counterparty or "").upper()
    # token match (AGENT-/MERCHANT-/BILLER-)
    for tok in signals.tokens:
        if tok.upper() == cp or tok.upper() in cp:
            return True
    # phone match
    txn_phone = normalize_phone(txn.counterparty)
    if txn_phone:
        for ph in signals.phones:
            if normalize_phone(ph) == txn_phone:
                return True
    return False


def _score_txn(signals: Signals, txn: TxnEntry, expected_types: set[str],
               latest_date) -> int:
    score = 0
    if signals.amounts and any(abs(txn.amount - a) < 1e-6 for a in signals.amounts):
        score += W_AMOUNT
    if _counterparty_matches(signals, txn):
        score += W_COUNTERPARTY
    if txn.type in expected_types:
        score += W_TYPE
    # status alignment with the claim
    status = (txn.status or "").lower()
    if signals.payment_failed and status == "failed":
        score += W_STATUS
    elif (signals.not_received or signals.settlement or signals.cash_in) and status == "pending":
        score += W_STATUS
    elif signals.refund and status == "completed":
        score += W_STATUS
    # weak time hint
    ts = _parse_ts(txn.timestamp)
    if ts is not None:
        if signals.clock_hour is not None and abs(ts.hour - signals.clock_hour) <= 1:
            score += W_TIME
        elif (signals.mentions_today or signals.mentions_yesterday) and latest_date \
                and ts.date() == latest_date:
            score += W_TIME
    return score


def _find_duplicate_cluster(history: list[TxnEntry]) -> Optional[list[TxnEntry]]:
    """Return a list of >=2 txns sharing amount+counterparty within a short window."""
    for i, a in enumerate(history):
        cluster = [a]
        ts_a = _parse_ts(a.timestamp)
        for b in history[i + 1:]:
            if (abs(b.amount - a.amount) < 1e-6
                    and (b.counterparty or "").upper() == (a.counterparty or "").upper()
                    and (b.type or "").lower() == (a.type or "").lower()):
                ts_b = _parse_ts(b.timestamp)
                if ts_a is not None and ts_b is not None:
                    if abs((ts_b - ts_a).total_seconds()) <= DUP_WINDOW_SECONDS:
                        cluster.append(b)
                else:
                    cluster.append(b)
        if len(cluster) >= 2:
            return cluster
    return None


def _established_recipient(chosen: TxnEntry, history: list[TxnEntry]) -> bool:
    if (chosen.type or "").lower() != "transfer":
        return False
    cp = (chosen.counterparty or "").upper()
    if not cp:
        return False
    prior = [
        t for t in history
        if t.transaction_id != chosen.transaction_id
        and (t.type or "").lower() == "transfer"
        and (t.counterparty or "").upper() == cp
    ]
    return len(prior) >= 2


def match(signals: Signals, history: list[TxnEntry]) -> MatchContext:
    ctx = MatchContext()
    if not history:
        return ctx

    # Duplicate cluster takes precedence when the customer alleges a duplicate.
    if signals.duplicate:
        cluster = _find_duplicate_cluster(history)
        if cluster:
            # choose the later (second) transaction
            later = max(
                cluster,
                key=lambda t: (_parse_ts(t.timestamp) or datetime.min, t.transaction_id),
            )
            ctx.chosen_id = later.transaction_id
            ctx.matched_txn = later
            ctx.duplicate_cluster = True
            ctx.top_score = W_AMOUNT + W_COUNTERPARTY
            return ctx

    expected = _expected_types(signals)
    dates = [d.date() for d in (_parse_ts(t.timestamp) for t in history) if d is not None]
    latest_date = max(dates) if dates else None

    scores = {t.transaction_id: _score_txn(signals, t, expected, latest_date) for t in history}
    ctx.scores = scores

    ranked = sorted(history, key=lambda t: scores[t.transaction_id], reverse=True)
    top = ranked[0]
    top_score = scores[top.transaction_id]
    ctx.top_score = top_score

    # Rule 3: nothing even matches the salient features.
    if top_score < MIN_FLOOR:
        return ctx

    # Rule 4: ambiguity — multiple near-tied tops that share the salient matched
    # feature (amount) but differ on identity (counterparty) -> do not guess.
    near_top = [t for t in history if top_score - scores[t.transaction_id] <= NEAR_TIE
                and scores[t.transaction_id] >= MIN_FLOOR]
    if len(near_top) >= 2:
        amounts = {round(t.amount, 2) for t in near_top}
        counterparties = {(t.counterparty or "").upper() for t in near_top}
        if len(amounts) == 1 and len(counterparties) >= 2:
            ctx.ambiguous = True
            return ctx

    # Rule 6: single best match.
    ctx.chosen_id = top.transaction_id
    ctx.matched_txn = top
    ctx.established_recipient = _established_recipient(top, history)
    return ctx
