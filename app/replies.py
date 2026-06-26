"""Templated, language-matched, safe-by-construction text outputs.

``agent_summary`` is internal-facing and always English. ``customer_reply`` is
returned in the customer's language (Bangla for Bangla complaints). Every reply is
assembled from safe ingredients and still passes through the §6 safety filter.
"""

from __future__ import annotations

from typing import Optional

from .extract import Signals
from .matcher import MatchContext
from .reasoning import Reasoning
from .schemas import CaseType, EvidenceVerdict

EN_CRED = "Please do not share your PIN or OTP with anyone."
BN_CRED = "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"

BANGLA_BLOCK = tuple(range(0x0980, 0x0A00))


def detect_language(language: Optional[str], complaint: str) -> str:
    """Return 'bn' or 'en' for reply generation."""
    if language == "bn":
        return "bn"
    if language == "en":
        return "en"
    # mixed / absent: detect Bangla Unicode in the complaint.
    for ch in complaint or "":
        if 0x0980 <= ord(ch) <= 0x09FF:
            return "bn"
    return "en"


def _fmt_amount(amount: Optional[float]) -> str:
    if amount is None:
        return ""
    if abs(amount - round(amount)) < 1e-9:
        return str(int(round(amount)))
    return f"{amount:.2f}"


# --------------------------------------------------------------------------- #
# agent_summary (always English, internal-facing)
# --------------------------------------------------------------------------- #
def build_agent_summary(r: Reasoning, ctx: MatchContext, signals: Signals) -> str:
    txn = ctx.matched_txn
    tid = ctx.chosen_id
    amt = _fmt_amount(txn.amount) if txn else (
        _fmt_amount(signals.amounts[0]) if signals.amounts else None)
    ct = r.case_type

    if ct == CaseType.phishing_or_social_engineering:
        return ("Customer reports an unsolicited contact requesting credentials (OTP/PIN). "
                "Likely social engineering. Customer indicates no credentials shared yet.")

    if ct == CaseType.wrong_transfer:
        if tid is None:
            return ("Customer reports a transfer that the recipient did not receive, but multiple "
                    "transactions of the same amount exist to different recipients. Cannot identify "
                    "the correct transaction without further input.")
        if r.evidence_verdict == EvidenceVerdict.inconsistent:
            return (f"Customer claims {tid} ({amt} BDT to {txn.counterparty}) was a wrong transfer, "
                    f"but history shows prior transfers to the same counterparty, suggesting an "
                    f"established recipient.")
        return (f"Customer reports sending {amt} BDT via {tid} to {txn.counterparty}, now believed "
                f"to be the wrong recipient.")

    if ct == CaseType.payment_failed:
        return (f"Customer attempted a {amt} BDT payment ({tid}) which failed, but reports the balance "
                f"was deducted. Requires payments operations investigation.")

    if ct == CaseType.duplicate_payment:
        return (f"Customer reports a duplicate payment. Two identical {amt} BDT payments to "
                f"{txn.counterparty} were completed close together; {tid} is the suspected duplicate.")

    if ct == CaseType.refund_request:
        return (f"Customer requests a refund of {amt} BDT for {tid} (merchant payment) due to change "
                f"of mind. Not a service failure.")

    if ct == CaseType.merchant_settlement_delay:
        return (f"Merchant reports settlement {tid} ({amt} BDT) is delayed beyond the standard window. "
                f"Settlement status is pending.")

    if ct == CaseType.agent_cash_in_issue:
        return (f"Customer reports {amt} BDT cash-in via {txn.counterparty} ({tid}) not reflected in "
                f"balance. Transaction status is {txn.status}.")

    # other / vague
    return ("Customer reports a vague concern without specifying transaction, amount, or issue. "
            "Insufficient detail to identify any relevant transaction.")


# --------------------------------------------------------------------------- #
# recommended_next_action (internal-facing, English)
# --------------------------------------------------------------------------- #
def build_next_action(r: Reasoning, ctx: MatchContext) -> str:
    tid = ctx.chosen_id
    ct = r.case_type

    if ct == CaseType.phishing_or_social_engineering:
        return ("Escalate to the fraud_risk team immediately. Confirm to the customer that the company "
                "never asks for OTP or PIN. Log any reported number for fraud pattern analysis.")
    if ct == CaseType.wrong_transfer:
        if tid is None:
            return ("Reply to the customer asking for the recipient's number to identify the correct "
                    "transaction. Do not initiate a dispute until the transaction is confirmed.")
        if r.evidence_verdict == EvidenceVerdict.inconsistent:
            return ("Flag for human review. Verify with the customer whether this was genuinely a wrong "
                    "transfer given the established transaction pattern with this recipient.")
        return (f"Verify {tid} details with the customer and initiate the wrong-transfer dispute "
                f"workflow per policy.")
    if ct == CaseType.payment_failed:
        return (f"Investigate {tid} ledger status. If the balance was deducted on a failed payment, "
                f"initiate the automatic reversal flow within standard SLA.")
    if ct == CaseType.duplicate_payment:
        return (f"Verify the duplicate with payments_ops. If the biller confirms a single payment, "
                f"initiate reversal of {tid}.")
    if ct == CaseType.refund_request:
        return ("Inform the customer that refund eligibility depends on the merchant's own policy and "
                "provide guidance on contacting the merchant through official means.")
    if ct == CaseType.merchant_settlement_delay:
        return (f"Route to merchant_operations to verify the settlement batch status for {tid}. If the "
                f"batch is delayed, communicate a revised ETA to the merchant.")
    if ct == CaseType.agent_cash_in_issue:
        return (f"Investigate {tid} pending status with agent operations. Confirm the settlement state "
                f"and resolve within the standard cash-in SLA.")
    return ("Reply to the customer asking for specific details: which transaction, what amount, what "
            "went wrong, and the approximate time.")


# --------------------------------------------------------------------------- #
# customer_reply (customer's language, safe by construction)
# --------------------------------------------------------------------------- #
def build_customer_reply(r: Reasoning, ctx: MatchContext, lang: str,
                         user_type: Optional[str]) -> str:
    tid = ctx.chosen_id
    ct = r.case_type
    bn = lang == "bn"
    cred = BN_CRED if bn else EN_CRED

    # Phishing — never verify the caller; reinforce credential safety.
    if ct == CaseType.phishing_or_social_engineering:
        if bn:
            return ("কোনো তথ্য শেয়ার করার আগে যোগাযোগ করার জন্য ধন্যবাদ। আমরা কখনোই আপনার পিন, ওটিপি বা "
                    "পাসওয়ার্ড চাই না। কেউ আমাদের পরিচয় দিলেও এগুলো শেয়ার করবেন না। আমাদের ফ্রড টিমকে এই "
                    "বিষয়ে অবগত করা হয়েছে।")
        return ("Thank you for reaching out before sharing any information. We never ask for your PIN, "
                "OTP, or password under any circumstances. Please do not share these with anyone, even "
                "if they claim to be from us. Our fraud team has been notified of this incident.")

    # Ambiguous / vague — ask for the disambiguating detail.
    if r.evidence_verdict == EvidenceVerdict.insufficient_data and ct == CaseType.wrong_transfer:
        if bn:
            return ("যোগাযোগ করার জন্য ধন্যবাদ। ওই দিনের একই পরিমাণের একাধিক লেনদেন আমরা দেখতে পাচ্ছি। সঠিক "
                    "লেনদেনটি শনাক্ত করতে অনুগ্রহ করে প্রাপকের নম্বরটি জানান। " + cred)
        return ("Thank you for reaching out. We see multiple transactions of the same amount on that "
                "date. Could you share the recipient's number so we can identify the right transaction? "
                + cred)
    if ct == CaseType.other:
        if bn:
            return ("যোগাযোগ করার জন্য ধন্যবাদ। দ্রুত সাহায্য করতে অনুগ্রহ করে লেনদেন আইডি, সংশ্লিষ্ট পরিমাণ "
                    "এবং কী সমস্যা হয়েছে তা জানান। " + cred)
        return ("Thank you for reaching out. To help you faster, please share the transaction ID, the "
                "amount involved, and a short description of what went wrong. " + cred)

    txn_ref_en = f"transaction {tid}" if tid else "your reported transaction"
    txn_ref_bn = f"লেনদেন {tid}" if tid else "আপনার উল্লেখ করা লেনদেন"

    if ct == CaseType.refund_request:
        if bn:
            return ("যোগাযোগ করার জন্য ধন্যবাদ। সম্পন্ন হওয়া মার্চেন্ট পেমেন্টের রিফান্ড মার্চেন্টের নিজস্ব "
                    "নীতির উপর নির্ভর করে। আমরা সরাসরি মার্চেন্টের সাথে যোগাযোগের পরামর্শ দিচ্ছি। প্রয়োজনে "
                    "আমরা আপনাকে অফিসিয়াল চ্যানেলে সহায়তা করব। " + cred)
        return ("Thank you for reaching out. Refunds for completed merchant payments depend on the "
                "merchant's own policy. We recommend contacting the merchant directly. If you need help "
                "reaching them, please reply and we will guide you through official channels. " + cred)

    if ct == CaseType.merchant_settlement_delay:
        # business-formal, merchant tone
        if bn:
            return (f"আপনার {txn_ref_bn} সংক্রান্ত উদ্বেগটি আমরা নথিভুক্ত করেছি। আমাদের মার্চেন্ট অপারেশন্স দল "
                    f"ব্যাচের অবস্থা যাচাই করে অফিসিয়াল চ্যানেলে প্রত্যাশিত সেটেলমেন্টের সময় জানাবে।")
        return (f"We have noted your concern regarding settlement {tid}. Our merchant operations team "
                f"will check the batch status and update you on the expected settlement time through "
                f"official channels.")

    money_return_en = "any eligible amount will be returned through official channels"
    money_return_bn = "যেকোনো প্রযোজ্য পরিমাণ অফিসিয়াল চ্যানেলের মাধ্যমে ফেরত দেওয়া হবে"

    if ct in (CaseType.payment_failed, CaseType.duplicate_payment):
        if bn:
            return (f"আমরা {txn_ref_bn} সংক্রান্ত বিষয়টি অবগত হয়েছি। আমাদের পেমেন্টস দল বিষয়টি যাচাই করবে "
                    f"এবং {money_return_bn}। {cred}")
        return (f"We have noted {txn_ref_en}, which may have caused an unexpected deduction. Our payments "
                f"team will review the case and {money_return_en}. {cred}")

    if ct == CaseType.agent_cash_in_issue:
        if bn:
            return (f"আপনার {txn_ref_bn} এর বিষয়ে আমরা অবগত হয়েছি। আমাদের এজেন্ট অপারেশন্স দল এটি দ্রুত "
                    f"যাচাই করবে এবং অফিসিয়াল চ্যানেলে আপনাকে জানাবে। {cred}")
        return (f"We have noted your concern about {txn_ref_en}. Our agent operations team will verify it "
                f"promptly and update you through official support channels. {cred}")

    # wrong_transfer with an identified transaction (consistent or inconsistent)
    if bn:
        return (f"আপনার {txn_ref_bn} সংক্রান্ত অনুরোধটি আমরা গ্রহণ করেছি। আমাদের ডিসপিউট দল বিষয়টি যত্নসহকারে "
                f"পর্যালোচনা করবে এবং অফিসিয়াল চ্যানেলে আপনার সাথে যোগাযোগ করবে। {cred}")
    return (f"We have noted your concern about {txn_ref_en}. {cred} Our dispute team will review the case "
            f"and contact you through official support channels.")
