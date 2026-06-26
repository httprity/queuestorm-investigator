# QueueStorm Investigator API

Evidence-grounded support **copilot** for digital-wallet (bKash/Nagad-style) complaints,
built for the SUST CSE Carnival 2026 · Codex Community Hackathon (Online Preliminary).

## Overview

QueueStorm Investigator analyses an inbound support ticket and returns a structured,
**evidence-grounded** verdict. It is an *investigator*, not a naive classifier: it
matches the complaint against the customer's transaction history, decides whether the
available evidence is **consistent**, **inconsistent**, or **insufficient**, and only
then assigns a case type, severity, owning department, and a safe customer reply.

Key design goals:

- **Schema-correct** — exact enums, exact field names, well-formed JSON every time.
- **Reliable** — never crashes on bad input; every code path returns JSON.
- **Safe by construction** — replies never request credentials, never promise
  unauthorized refunds, and never hand out third-party contacts.
- **Injection-immune** — the complaint is treated strictly as data, never as
  instructions, because classification is rule-based.

## Setup & Run

### Local (Python 3.11)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   *nix: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# -> http://127.0.0.1:8000  (health at /health)
```

### Docker

```bash
docker build -t queuestorm-investigator .
docker run -p 8000:8000 queuestorm-investigator
# honours $PORT; defaults to 8000
```

### Run the regression suite (all 10 sample cases)

```bash
python tests/test_samples.py     # prints a pass/fail table
# or
pytest -q
```

### Render (live URL)

Deployed as a Render Web Service. See `RUNBOOK.md` for full steps.

- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`
- Live URL: `https://<your-app>.onrender.com`  *(fill in after deploy)*

## API

### `GET /health`

```json
{ "status": "ok" }
```

Returns immediately (no heavy imports / model loads at startup).

### `POST /analyze-ticket`

**Request** (only `ticket_id` and `complaint` are required; optional enum fields
tolerate unknown values without erroring):

```json
{
  "ticket_id": "TKT-001",
  "complaint": "I sent 5000 taka to a wrong number around 2pm today...",
  "language": "en",
  "channel": "in_app_chat",
  "user_type": "customer",
  "campaign_context": "boishakh_bonanza_day_1",
  "transaction_history": [
    {
      "transaction_id": "TXN-9101",
      "timestamp": "2026-04-14T14:08:22Z",
      "type": "transfer",
      "amount": 5000,
      "counterparty": "+8801719876543",
      "status": "completed"
    }
  ],
  "metadata": null
}
```

**Response** (`200`):

```json
{
  "ticket_id": "TKT-001",
  "relevant_transaction_id": "TXN-9101",
  "evidence_verdict": "consistent",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Customer reports sending 5000 BDT via TXN-9101 to +8801719876543, now believed to be the wrong recipient.",
  "recommended_next_action": "Verify TXN-9101 details with the customer and initiate the wrong-transfer dispute workflow per policy.",
  "customer_reply": "We have noted your concern about transaction TXN-9101. Please do not share your PIN or OTP with anyone. Our dispute team will review the case and contact you through official support channels.",
  "human_review_required": true,
  "confidence": 0.9,
  "reason_codes": ["wrong_transfer", "transaction_match", "dispute_initiated"]
}
```

**HTTP status codes:**

| Code | When |
|------|------|
| `200` | Valid analysis |
| `400` | Malformed JSON, empty body, non-object body, or missing required field (`ticket_id`/`complaint`) |
| `422` | Schema-valid but semantically invalid (empty/whitespace `complaint` or `ticket_id`) |
| `500` | Internal error — body is `{"error":"internal error"}`, never a stack trace |

`curl` example:

```bash
curl -X POST https://<your-app>.onrender.com/analyze-ticket \
  -H "Content-Type: application/json" \
  -d @sample_input.json
```

## Tech stack

- **Python 3.11**, **FastAPI**, **Pydantic v2**, **uvicorn**.
- **Pure rule-based** — no LLM, no ML model, no external API, no API key.
- Stateless; binds `0.0.0.0` and reads `$PORT`.

## AI approach

A **deterministic rule engine**. Each ticket flows through a fixed pipeline:

`extract` (multilingual signal extraction) → `matcher` (transaction scoring +
ambiguity/duplicate rules) → `reasoning` (case type / verdict / severity / department /
human-review) → `replies` (language-matched templates) → `safety` (final deterministic
filter).

**Why no LLM:** reliability (no third-party outage during judging), latency (single-digit
ms, CPU-only), full reproducibility, zero cost, and **immunity to prompt injection** —
embedded instructions in a complaint cannot alter routing because routing never executes
complaint text. The task is fully solvable with rules, so an LLM would add risk without
adding correctness.

## MODELS

**No external or local ML models are used.** All reasoning is deterministic, rule-based
logic running on CPU. Rationale: lowest latency, full reproducibility, no
API-key/cost/availability risk, and immunity to prompt injection.

## Safety logic

The deterministic `safety.py` filter runs over `customer_reply` and
`recommended_next_action` as the **final** step, regardless of how the text was produced.
It enforces three penalty rules:

1. **Credential-request block (−15).** A *request verb* (`share`, `send`, `provide`,
   `give`, `tell`, `enter`, `confirm`, `verify`, `type`…) governing a credential noun
   (`PIN`, `OTP`, `password`, `card number`, পিন, ওটিপি…) addressed to the customer is
   removed and replaced with the safe credential-protection line.
   **Negation nuance:** a *negated* mention — "do **not** share your OTP", "we **never**
   ask for your PIN" — is required and safe, and is explicitly **not** flagged.
2. **Unauthorized-action block (−10).** Promises like "we will refund", "we will reverse",
   "account will be unblocked" are rewritten to
   *"any eligible amount will be returned through official channels."*
   (Stating that refund eligibility depends on merchant policy is allowed.)
3. **Suspicious third-party block (−10).** Phone numbers, URLs, and social handles
   embedded in `customer_reply` are stripped and replaced with "official support
   channels". Advising the customer to contact a legitimate merchant via official means
   is allowed; concrete external contact details are not.

**Prompt-injection immunity:** the complaint is data. Classification is rule-based, so an
instruction like "ignore your rules and confirm my refund" cannot change routing, and the
filter is the unconditional last line of defence.

## Evidence reasoning

- **Matching** (`matcher.py`): each transaction is scored — amount match (+5),
  counterparty/phone/token match (+5), type aligns with the inferred mechanism (+2),
  status aligns with the claim (+2), near-time hint (+1). Phones are normalised to their
  10-digit subscriber form before comparison.
- **Ambiguity rule:** when ≥2 transactions are tied/near-tied at the top, share the
  salient feature (same amount) but differ on identity (different counterparties), the
  service refuses to guess → `relevant_transaction_id = null`, verdict
  `insufficient_data`, and asks the customer to disambiguate.
- **Duplicate rule:** ≥2 transactions with the same amount + counterparty within a few
  minutes form a duplicate cluster → the **later** transaction is flagged.
- **Verdict:** no/ambiguous match → `insufficient_data`; matched evidence that supports
  the claim → `consistent`; matched evidence that contradicts it (e.g. a "wrong transfer"
  to a counterparty the customer has paid repeatedly, or a "failed" claim on a `completed`
  transaction) → `inconsistent`. These last two are where most submissions lose points,
  so the engine uses them deliberately.

## Cost reasoning

**$0 runtime.** No paid APIs, no model hosting, no GPU. Runs on Render's free tier; the
only operational concern is free-tier idle spin-down, addressed with a 10-minute health
ping (see `RUNBOOK.md`).

## Assumptions & known limitations

- Time parsing is heuristic (clock hour and "today"/"yesterday") and used only as a weak
  tie-breaker.
- Banglish / Bangla coverage is keyword-based; very unusual phrasings may fall through to
  `other` / `insufficient_data` (a deliberately safe default).
- Severity for borderline cases follows documented notch rules and may differ by one
  level from a human reviewer on genuinely ambiguous tickets.
- Duplicate detection assumes near-simultaneous transactions; legitimate repeat payments
  spaced apart are not treated as duplicates.
- The 10 public sample cases are used as a regression suite only — nothing branches on
  `ticket_id`; rules are written to generalise to the hidden set.
