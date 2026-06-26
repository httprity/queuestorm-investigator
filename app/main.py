"""FastAPI application: routes, manual JSON handling, and crash-safe error handlers.

HTTP contract:
  * 400 — malformed JSON or missing required field (ticket_id / complaint).
  * 422 — schema-valid but semantically invalid (empty / whitespace complaint).
  * 500 — internal error, body {"error": "internal error"} (never leaks internals).

The process must never crash on bad input; every path returns JSON.
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .pipeline import analyze
from .schemas import AnalyzeRequest

logger = logging.getLogger("queuestorm")

app = FastAPI(
    title="QueueStorm Investigator API",
    description="Evidence-grounded support copilot for digital-wallet complaints.",
    version="1.0.0",
)


# --- OpenAPI examples (documentation only; do not affect runtime logic) ---
_EXAMPLE_REQUEST = {
    "ticket_id": "TKT-001",
    "complaint": "I sent 5000 taka to a wrong number around 2pm today. Please help me get my money back.",
    "language": "en",
    "channel": "in_app_chat",
    "user_type": "customer",
    "transaction_history": [
        {
            "transaction_id": "TXN-9101",
            "timestamp": "2026-04-14T14:08:22Z",
            "type": "transfer",
            "amount": 5000,
            "counterparty": "+8801719876543",
            "status": "completed",
        }
    ],
}

_EXAMPLE_RESPONSE = {
    "ticket_id": "TKT-001",
    "relevant_transaction_id": "TXN-9101",
    "evidence_verdict": "consistent",
    "case_type": "wrong_transfer",
    "severity": "high",
    "department": "dispute_resolution",
    "agent_summary": "Customer reports sending 5000 BDT via TXN-9101 to +8801719876543, now believed to be the wrong recipient.",
    "recommended_next_action": "Verify TXN-9101 details with the customer and initiate the wrong-transfer dispute workflow per policy.",
    "customer_reply": "We have noted your concern about transaction TXN-9101. Please do not share your PIN or OTP with anyone. Our dispute team will review the case and contact you through official support channels.",
    "human_review_required": True,
    "confidence": 0.9,
    "reason_codes": ["wrong_transfer", "transaction_match", "dispute_initiated"],
}


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Last line of defense: never leak stack traces / secrets.
    logger.exception("Unhandled error on %s", request.url.path)
    return _error(500, "internal error")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    return {"service": "queuestorm-investigator", "status": "ok", "endpoint": "POST /analyze-ticket"}


@app.post(
    "/analyze-ticket",
    summary="Analyze a support ticket and return an evidence-grounded verdict.",
    responses={
        200: {
            "description": "Successful analysis",
            "content": {"application/json": {"example": _EXAMPLE_RESPONSE}},
        },
        400: {"description": "Malformed JSON or missing required field",
              "content": {"application/json": {"example": {"error": "malformed JSON"}}}},
        422: {"description": "Empty / whitespace complaint",
              "content": {"application/json": {"example": {"error": "complaint must not be empty"}}}},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": AnalyzeRequest.model_json_schema(),
                    "example": _EXAMPLE_REQUEST,
                }
            },
        }
    },
)
async def analyze_ticket(request: Request) -> JSONResponse:
    # --- read & parse body manually for full control over 400 vs 422 ---
    try:
        raw = await request.body()
    except Exception:
        return _error(400, "could not read request body")

    if not raw or not raw.strip():
        return _error(400, "request body is empty")

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return _error(400, "malformed JSON")

    if not isinstance(data, dict):
        return _error(400, "request body must be a JSON object")

    # Required fields must be present (400 if absent).
    if data.get("ticket_id") is None or data.get("complaint") is None:
        return _error(400, "missing required field: ticket_id and complaint are required")

    # Semantic validation: empty / whitespace complaint -> 422.
    if not str(data.get("complaint")).strip():
        return _error(422, "complaint must not be empty")
    if not str(data.get("ticket_id")).strip():
        return _error(422, "ticket_id must not be empty")

    # Build the (liberal) request model. Optional garbage is coerced, not rejected.
    try:
        req = AnalyzeRequest.model_validate(data)
    except Exception:
        # ticket_id / complaint already validated; any remaining error is treated as 400.
        return _error(400, "invalid request payload")

    # Run the analysis pipeline; never let an internal error crash the worker.
    try:
        response = analyze(req)
    except Exception:
        logger.exception("pipeline failure")
        return _error(500, "internal error")

    return JSONResponse(status_code=200, content=response.model_dump())
