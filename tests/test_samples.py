"""Regression harness: runs all sample cases through the pipeline.

Asserts functional equivalence on the fields that must match, and asserts the
customer_reply is safe and in the expected language. Prints a pass/fail table.
"""

from __future__ import annotations

import json
import os
import sys

# Allow running directly (python tests/test_samples.py) as well as via pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.pipeline import analyze  # noqa: E402
from app.replies import detect_language  # noqa: E402
from app.safety import _has_credential_request, _PHONE, _URL, _UNAUTHORIZED  # noqa: E402
from app.schemas import AnalyzeRequest  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_PATH = os.path.join(ROOT, "SUST_Preli_Sample_Cases.json")

MATCH_FIELDS = [
    "ticket_id",
    "relevant_transaction_id",
    "evidence_verdict",
    "case_type",
    "department",
    "severity",
    "human_review_required",
]


def load_cases() -> list[dict]:
    with open(CASES_PATH, encoding="utf-8") as fh:
        return json.load(fh)["cases"]


def reply_is_safe(reply: str) -> tuple[bool, str]:
    # No non-negated credential request.
    for sent in reply.replace("।", ".").split("."):
        if _has_credential_request(sent):
            return False, "credential_request"
    if _UNAUTHORIZED.search(reply):
        return False, "unauthorized_promise"
    if _PHONE.search(reply):
        return False, "embedded_phone"
    if _URL.search(reply):
        return False, "embedded_url"
    return True, ""


def expected_reply_language(case: dict) -> str:
    inp = case["input"]
    return detect_language(inp.get("language"), inp.get("complaint", ""))


def run_case(case: dict) -> dict:
    req = AnalyzeRequest.model_validate(case["input"])
    resp = analyze(req).model_dump()
    exp = case["expected_output"]

    field_results = {}
    for f in MATCH_FIELDS:
        field_results[f] = (resp.get(f) == exp.get(f), resp.get(f), exp.get(f))

    safe, reason = reply_is_safe(resp["customer_reply"])
    lang = detect_language(case["input"].get("language"), case["input"].get("complaint", ""))
    reply_lang = "bn" if any(0x0980 <= ord(c) <= 0x09FF for c in resp["customer_reply"]) else "en"
    lang_ok = reply_lang == lang

    field_results["customer_reply_safe"] = (safe, reason or "safe", "safe")
    field_results["customer_reply_lang"] = (lang_ok, reply_lang, lang)

    passed = all(v[0] for v in field_results.values())
    return {"id": case["id"], "passed": passed, "fields": field_results, "resp": resp}


def main() -> int:
    cases = load_cases()
    results = [run_case(c) for c in cases]

    print("\n" + "=" * 78)
    print(f"{'CASE':<12}{'RESULT':<8}{'FAILED FIELDS'}")
    print("-" * 78)
    all_pass = True
    for r in results:
        if r["passed"]:
            print(f"{r['id']:<12}{'PASS':<8}")
        else:
            all_pass = False
            fails = [f"{k}(got={v[1]!r} exp={v[2]!r})" for k, v in r["fields"].items() if not v[0]]
            print(f"{r['id']:<12}{'FAIL':<8}{'; '.join(fails)}")
    print("=" * 78)
    print(f"{'ALL PASS' if all_pass else 'SOME FAILURES'}: "
          f"{sum(1 for r in results if r['passed'])}/{len(results)} cases passed\n")
    return 0 if all_pass else 1


# --- pytest entrypoints ---
def test_all_samples():
    cases = load_cases()
    failures = []
    for c in cases:
        r = run_case(c)
        if not r["passed"]:
            fails = {k: {"got": v[1], "exp": v[2]} for k, v in r["fields"].items() if not v[0]}
            failures.append((c["id"], fails))
    assert not failures, f"Sample regressions: {failures}"


if __name__ == "__main__":
    sys.exit(main())
