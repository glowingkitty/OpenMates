"""Offline tests for the source-bound semantic-review boundary.

Exercise opaque model identities, strict complete verdicts, input validation,
bounded provider recovery, cancellation and partial completion. Provider calls
are replaced at the helper's dedicated model seam; no paid work is performed.
"""

# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from backend.apps.ai.daily_inspiration import semantic_review as review


def candidate(identity="private-source", marker="source"):
    return {
        "_review_identity": identity,
        "title": marker,
        "description": "Water evaporates and condenses.",
        "language": "de",
        "card_title": "Der Kreislauf des Wassers",
        "phrase": "Wasser verdunstet. Wie entstehen Wolken?",
        "assistant_response": "Wasser verdunstet. Dampf kondensiert. Was passiert danach?",
        "follow_up_suggestions": [
            "Was ist Wasserdampf?",
            "Wie kondensiert Wasser?",
            "Was verdunstet?",
        ],
    }


def arguments(verdict="allow", field="phrase", code=None):
    data = {
        "accepted": [review.OPAQUE_ID] if verdict == "allow" else [],
        "rejected": [review.OPAQUE_ID] if verdict == "reject" else [],
        "uncertain": [review.OPAQUE_ID] if verdict == "uncertain" else [],
        "field_reviews": [
            {
                "source_id": review.OPAQUE_ID,
                "field": name,
                "verdict": "allow",
                "codes": ["none"],
            }
            for name in review.FIELDS
        ],
    }
    if verdict != "allow":
        row = next(row for row in data["field_reviews"] if row["field"] == field)
        row.update(
            verdict=verdict,
            codes=[
                code or ("uncertain" if verdict == "uncertain" else "unsupported_fact")
            ],
        )
    return data


def response(data=None, error=None):
    return SimpleNamespace(
        arguments=arguments() if data is None else data, error_message=error
    )


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(review, "RETRY_DELAY_SECONDS", 0)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_opaque_singleton_projection_drops_all_labels_ids_records_and_returns_original(
    monkeypatch,
):
    original = candidate("known-reject-control", "Public source title")
    original.update(
        expected="reject",
        source_id="label_leak",
        record=object(),
        youtube_id="private-id",
        case_id="reject-fixture",
        internal={"secret": "private-value"},
    )
    source_before = original.copy()
    calls = []
    monkeypatch.setattr(review, "utc_assessment_date", lambda: "2026-10-21")

    async def call(**kwargs):
        calls.append(kwargs)
        wire = json.dumps([kwargs["message_history"], kwargs["tool_definition"]])
        assert all(
            value not in wire
            for value in (
                "known-reject-control",
                "label_leak",
                "private-id",
                "reject-fixture",
                "private-value",
            )
        )
        body = json.loads(kwargs["message_history"][1]["content"])
        assert set(body) == {"assessment_date", "sources"}
        assert body["assessment_date"] == "2026-10-21"
        assert len(body["sources"]) == 1
        source = body["sources"][0]
        assert set(source) == {"source_id", "language", "source", "copy_fields"}
        assert source["source_id"] == "source_000"
        assert set(source["source"]) == {"title", "description", "extract"}
        assert set(source["copy_fields"]) == set(review.FIELDS)
        schema = kwargs["tool_definition"]["function"]["parameters"]
        assert schema["properties"]["accepted"]["items"]["enum"] == ["source_000"]
        assert "reasoning_effort" not in kwargs and kwargs["temperature"] == 1.0
        assert kwargs["model_id"] == "google/gemini-3.8-flash"
        assert kwargs["fallback_models"] == [] and kwargs["allow_retries"] is False
        assert kwargs["single_attempt_timeout_seconds"] == 30
        # Exercise the real dispatch boundary: a locally invented purpose raises
        # before any provider call, even when all tool/request shape checks pass.
        from backend.shared.python_utils.tracing.ai_observability import ai_provider_span

        with ai_provider_span(kwargs["observability_purpose"]) as span:
            assert span is not None
        assert kwargs["observability_purpose"] == "inspiration"
        return response()

    monkeypatch.setattr(review, "call_semantic_model", call)
    cards = await review.review_copy_candidates(
        [original], None, task_id="offline-review"
    )
    assert cards[0] is original
    assert original == source_before
    assert len(calls) == 1
    assert "Date:2026-10-21" not in review.PROMPT
    assert "Assessment date: use the supplied assessment_date." in review.PROMPT


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_partition",
        "duplicate_source",
        "unknown_id",
        "missing_field",
        "duplicate_field",
        "foreign_field_id",
        "unknown_code",
        "duplicate_code",
        "allow_code",
        "reject_none",
        "uncertain_code",
        "partition_disagreement",
        "extra_field_key",
        "extra_top_key",
    ],
)
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
def test_complete_partition_and_codes_are_strict(mutation):
    data = arguments()
    if mutation == "missing_partition":
        del data["uncertain"]
    elif mutation == "duplicate_source":
        data["rejected"] = [review.OPAQUE_ID]
    elif mutation == "unknown_id":
        data["accepted"] = ["case-known-allow"]
    elif mutation == "missing_field":
        data["field_reviews"].pop()
    elif mutation == "duplicate_field":
        data["field_reviews"][1] = deepcopy(data["field_reviews"][0])
    elif mutation == "foreign_field_id":
        data["field_reviews"][0]["source_id"] = "another-source"
    elif mutation == "unknown_code":
        data = arguments("reject", code="provider-invented-code")
    elif mutation == "duplicate_code":
        data = arguments("reject")
        data["field_reviews"][1]["codes"] = ["unsupported_fact"] * 2
    elif mutation == "allow_code":
        data["field_reviews"][0]["codes"] = ["wrong_language"]
    elif mutation == "reject_none":
        data = arguments("reject", code="none")
    elif mutation == "uncertain_code":
        data = arguments("uncertain", code="unsupported_fact")
    elif mutation == "partition_disagreement":
        data["accepted"], data["rejected"] = [], [review.OPAQUE_ID]
    elif mutation == "extra_field_key":
        data["field_reviews"][0]["explanation"] = "untrusted prose"
    else:
        data["rewritten_copy"] = "must never be accepted"
    with pytest.raises(ValueError):
        review.validate(data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verdict,code,expected_code",
    [
        ("reject", "wrong_language", "phrase.language:wrong"),
        ("reject", "causal_role", "phrase.grounding:causal_role"),
        ("uncertain", "uncertain", "phrase.grounding:uncertain"),
    ],
)
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_complete_negative_or_uncertain_is_final_with_trusted_server_feedback(
    monkeypatch,
    verdict,
    code,
    expected_code,
):
    calls, feedback = [], {}

    async def call(**kwargs):
        calls.append(kwargs)
        return response(arguments(verdict, code=code))

    monkeypatch.setattr(review, "call_semantic_model", call)
    assert (
        await review.review_copy_candidates(
            [candidate("server-only")],
            None,
            task_id="test",
            rejection_feedback=feedback,
        )
        == []
    )
    assert len(calls) == 1
    assert feedback == {"server-only": [expected_code]}


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_provider_and_schema_failures_use_only_bounded_chain_and_original_messages(
    monkeypatch,
):
    calls = []

    async def call(**kwargs):
        calls.append(deepcopy(kwargs))
        kwargs["message_history"][-1]["content"] = "mutated adapter-local state"
        if len(calls) == 1:
            data = arguments()
            data["accepted"] = ["unapproved-source"]
            return response(data)
        return response()

    monkeypatch.setattr(review, "call_semantic_model", call)
    original = candidate()
    assert (await review.review_copy_candidates([original], None, task_id="test"))[
        0
    ] is original
    assert [call["model_id"] for call in calls] == [
        review.REVIEW_MODEL,
        review.REVIEW_MODEL,
    ]
    assert (
        calls[0]["message_history"] == calls[1]["message_history"]
    )


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_repeated_provider_errors_exhaust_at_two_without_logging_arbitrary_prose(
    monkeypatch, caplog
):
    calls, feedback = [], {}

    async def call(**kwargs):
        calls.append(kwargs)
        return response(error="sensitive raw source and provider error")

    monkeypatch.setattr(review, "call_semantic_model", call)
    assert (
        await review.review_copy_candidates(
            [candidate()], None, task_id="test", rejection_feedback=feedback
        )
        == []
    )
    assert len(calls) == 2
    assert feedback == {"private-source": ["review:unavailable"]}
    assert "sensitive raw source" not in caplog.text


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_attempt_timeout_preserves_real_fallback_opportunity(monkeypatch):
    monkeypatch.setattr(review, "ATTEMPT_TIMEOUT_SECONDS", 0.01)
    calls = []

    async def call(**kwargs):
        calls.append(kwargs["model_id"])
        if len(calls) < 2:
            await asyncio.sleep(10)
        return response()

    monkeypatch.setattr(review, "call_semantic_model", call)
    original = candidate()
    assert await review.review_copy_candidates([original], None, task_id="test") == [
        original
    ]
    assert calls == [review.REVIEW_MODEL, review.REVIEW_MODEL]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_external_cancellation_propagates_and_starts_no_recovery_call(
    monkeypatch,
):
    calls, started, cancelled = [], asyncio.Event(), []

    async def call(**kwargs):
        calls.append(kwargs)
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(review, "call_semantic_model", call)
    task = asyncio.create_task(
        review.review_copy_candidates([candidate()], None, task_id="test")
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) == len(cancelled) == 1


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_global_deadline_retains_finished_originals_and_withholds_unresolved(
    monkeypatch,
):
    monkeypatch.setattr(review, "GLOBAL_TIMEOUT_SECONDS", 0.025)
    calls, cancelled, feedback = [], [], {}
    originals = [candidate(str(i), f"source {i}") for i in range(6)]

    async def call(**kwargs):
        title = json.loads(kwargs["message_history"][-1]["content"])["sources"][0][
            "source"
        ]["title"]
        calls.append(title)
        if title == "source 0":
            return response()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(title)

    monkeypatch.setattr(review, "call_semantic_model", call)
    result = await review.review_copy_candidates(
        originals, None, task_id="test", rejection_feedback=feedback
    )
    assert len(result) == 1 and result[0] is originals[0]
    assert len(calls) == 4 and len(cancelled) == 3
    assert set(feedback) == {"1", "2", "3", "4", "5"}
    assert all(codes == ["review:unavailable"] for codes in feedback.values())


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_malformed_review_neighbor_does_not_discard_complete_approved_cards(
    monkeypatch,
):
    originals = [
        candidate("a", "valid first"),
        candidate("b", "malformed review"),
        candidate("c", "valid last"),
    ]
    calls = []

    async def call(**kwargs):
        title = json.loads(kwargs["message_history"][-1]["content"])["sources"][0][
            "source"
        ]["title"]
        calls.append(title)
        if title == "malformed review":
            return response({"not": "a partition"})
        if title == "valid first":
            await asyncio.sleep(0.005)
        return response()

    monkeypatch.setattr(review, "call_semantic_model", call)
    result = await review.review_copy_candidates(originals, None, task_id="test")
    assert len(result) == 2 and result[0] is originals[0] and result[1] is originals[2]
    assert calls.count("malformed review") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "missing_copy",
        "empty_copy",
        "missing_language",
        "empty_source",
        "oversize_copy",
        "oversize_source",
        "followups_two",
        "followups_four",
        "followup_wrong_type",
        "too_many_candidates",
    ],
)
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_whole_partition_validation_precedes_all_provider_io(
    monkeypatch, mutation
):
    rows = [candidate("valid"), candidate("invalid")]
    if mutation == "missing_copy":
        del rows[1]["card_title"]
    elif mutation == "empty_copy":
        rows[1]["assistant_response"] = " "
    elif mutation == "missing_language":
        del rows[1]["language"]
    elif mutation == "empty_source":
        rows[1]["title"] = rows[1]["description"] = rows[1]["extract"] = ""
    elif mutation == "oversize_copy":
        rows[1]["phrase"] = "x" * 6001
    elif mutation == "oversize_source":
        rows[1]["extract"] = "x" * 6001
    elif mutation == "followups_two":
        rows[1]["follow_up_suggestions"].pop()
    elif mutation == "followups_four":
        rows[1]["follow_up_suggestions"].append("Fourth")
    elif mutation == "followup_wrong_type":
        rows[1]["follow_up_suggestions"][1] = None
    else:
        rows = [candidate(str(i)) for i in range(51)]

    async def forbidden(**_kwargs):
        raise AssertionError("invalid whole partition reached paid boundary")

    monkeypatch.setattr(review, "call_semantic_model", forbidden)
    assert await review.review_copy_candidates(rows, None, task_id="test") == []


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_three_concurrent_singletons_maximum(monkeypatch):
    active, maximum = 0, 0

    async def call(**_kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.005)
        active -= 1
        return response()

    monkeypatch.setattr(review, "call_semantic_model", call)
    originals = [candidate(str(i)) for i in range(8)]
    result = await review.review_copy_candidates(originals, None, task_id="test")
    assert maximum == 3
    assert all(left is right for left, right in zip(result, originals))


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults,language-preferences.content-language
async def test_single_transport_failure_retries_only_same_gemini_model(monkeypatch):
    calls = []

    async def call(**kwargs):
        calls.append(kwargs['model_id'])
        if len(calls) == 1:
            raise ConnectionError('transport details')
        return response()

    monkeypatch.setattr(review, 'call_semantic_model', call)
    original = candidate()
    assert await review.review_copy_candidates([original], None, task_id='test') == [original]
    assert calls == ['google/gemini-3.8-flash', 'google/gemini-3.8-flash']
