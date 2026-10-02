# contract-test-file: infrastructure
"""Engineering checks for benchmark scoring and unavailable providers.

These checks prove that evaluation preserves continuous System One scores,
keeps native encoder labels separate from application compatibility, and
does not count rejected requests as successful or as correct decisions.
All HTTP responses and inputs are synthetic; no provider keys are required.
"""
import asyncio
import json

import httpx

from backend.scripts.benchmark_decision_models import evaluate, summarize, systemone_payload


def test_glide_instruction_encoding_preserves_all_structured_information():
    instruction = {"question": "Is this exact skill useful?", "candidate_id": "web-search", "candidate_description": "Public web search"}
    case = {"state": {"messages": []}, "questions": {"skill_0": {"type": "noul", "instructions": instruction}}}
    payload = systemone_payload(case, "fastino/GLiDE", encode_instructions=True)
    assert json.loads(payload["questions"]["skill_0"]["instructions"]) == instruction
    assert case["questions"]["skill_0"]["instructions"] is instruction


def run_response(case, model, payload, status=200):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload))) as client:
            return await evaluate(client, case, model, "synthetic-test-key")
    return asyncio.run(run())


def test_glide_uses_weighted_level_instead_of_argmax():
    case = {"id": "weighted", "area": "postprocessing", "state": "synthetic", "questions": {"safety": {"type": "score", "instructions": "Rate safety", "criteria": ["low", "medium", "high"]}}, "expected": {"safety": [1.6, 1.8]}}
    row = run_response(case, "glide", {"model": "glide", "answers": {"safety": {"type": "score", "score": 2, "expected_level": 1.7, "legend": {"0": "low", "1": "medium", "2": "high"}, "probabilities": {"0": .1, "1": .1, "2": .8}, "confidence": .7}}, "usage": {"input_tokens": 100, "output_tokens": 3}})
    assert row["status"] == "ok"
    assert row["case_correct"] is True
    assert row["estimated_cost_usd"] == 100 * .30 / 1_000_000


def test_encoder_label_success_does_not_claim_caller_compatibility():
    question = "route"
    case = {"id": "encoder", "area": "preprocessing", "state": "synthetic", "questions": {"route": {"type": "choice", "instructions": "Select the route", "criteria": {"code": "Programming", "general": "Conversation"}}}, "expected": {"route": "code"}}
    row = run_response(case, "gliner_decide", {"model": "fastino/GLiNER-2.5-Decide", "choices": [{"message": {"content": json.dumps({question: {"label": "Programming", "confidence": .9}})}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    assert row["status"] == "ok"
    assert row["case_correct"] is True
    assert row["caller_eligible"] is False


def test_missing_answer_is_not_counted_as_valid():
    case = {"id": "missing", "area": "workflow_check", "state": "synthetic", "questions": {"gate": {"type": "noul", "instructions": "Is it ready?"}}, "expected": {"gate": True}}
    row = run_response(case, "jev", {"model": "jev", "answers": {}, "usage": {"input_tokens": 10}})
    assert row["status"] == "error"
    assert summarize([row])["jev"]["all"]["valid"] == 0


def test_provider_rejection_is_not_counted_as_a_correct_decision():
    case = {"id": "rejected", "area": "workflow_check", "state": "synthetic", "questions": {"gate": {"type": "noul", "instructions": "Is it ready?"}}, "expected": {"gate": True}}
    row = run_response(case, "glide", {"error": "unavailable"}, status=503)
    assert row["status"] == "provider_error"
    summary = summarize([row])["glide"]["all"]
    assert summary["requests"] == 1
    assert summary["correct_cases"] == summary["valid"] == 0
