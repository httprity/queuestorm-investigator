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


@app.post("/analyze-ticket")
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
