"""Vector author: validation, requirement review, correction, script engine, fallbacks and billing."""
from types import SimpleNamespace

import pytest

from backend.apps.images import vector_author
from backend.apps.images.tasks import generate_task
from backend.apps.images.vector_script import ScriptRun, script_run_credits
from backend.apps.images.vector_author import (
    InvalidSvgError,
    MAX_CORRECTION_ROUNDS,
    VectorAuthorError,
    VectorReview,
    VectorUsage,
    author_svg,
    build_request_message,
    extract_script,
    extract_svg,
    normalize_requirements,
    partial_svg,
    validate_svg,
)

GOOD = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">\n<rect width="10" height="10" fill="red"/>\n</svg>'
BETTER = GOOD.replace("red", "green")


def _stream(*answers, usage=(100, 400), fail_models=()):
    """Fake provider stream: one scripted answer per call, sent line by line, then usage."""
    calls = []

    async def stream_fn(**kwargs):
        calls.append(kwargs)
        if kwargs["model_id"] in fail_models:
            raise RuntimeError("provider down")
        answer = answers[min(len(calls) - 1 - stream_fn.failed, len(answers) - 1)]
        for line in answer.splitlines(keepends=True):
            yield line
        yield SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1])

    stream_fn.failed = 0
    stream_fn.calls = calls
    return stream_fn


def _review(*outcomes):
    seen = []

    async def review_fn(**kwargs):
        seen.append(kwargs)
        return outcomes[min(len(seen) - 1, len(outcomes) - 1)]

    review_fn.seen = seen
    return review_fn


REQUIREMENTS = ["nothing is cut off", "the square is green"]
ACCEPT = VectorReview(accepted=True, status="accepted", input_tokens=900)
REJECT = VectorReview(
    accepted=False, status="rejected", feedback="these requirements are not met: (1) nothing is cut off",
    input_tokens=900, unmet=("nothing is cut off",),
)
SCRIPT = "import math\n\ndef build_svg():\n    return SVG\n"


def _sandbox(*runs):
    seen = []

    async def script_fn(code, **kwargs):
        seen.append(code)
        return runs[min(len(seen) - 1, len(runs) - 1)]

    script_fn.seen = seen
    return script_fn


# contract-test: supporting surface=rest_api assertions=images-generate.vector.validated-reviewed-corrected
@pytest.mark.parametrize("svg,reason", [
    ('<svg viewBox="0 0 1 1"><script>alert(1)</script><rect/></svg>', "script"),
    ('<svg viewBox="0 0 1 1"><rect onclick="x()"/></svg>', "event attribute"),
    ('<svg viewBox="0 0 1 1"><image href="https://example.org/a.png"/></svg>', "image"),
    ('<svg viewBox="0 0 1 1"><use href="https://example.org/a.svg#x"/></svg>', "internal"),
    ('<svg viewBox="0 0 1 1"><rect fill="url(https://example.org/p)"/></svg>', "external"),
    ('<svg viewBox="0 0 1 1"><style>@import "x.css";</style><rect/></svg>', "style"),
    ('<svg viewBox="0 0 1 1"><foreignObject/><rect/></svg>', "foreignobject"),
    ('<svg><rect/></svg>', "viewBox"),
    ('<svg viewBox="0 0 1 1"><g/></svg>', "draws nothing"),
    ('<svg viewBox="0 0 1 1"><rect></svg>', "well-formed"),
    ('<html viewBox="0 0 1 1"><rect/></html>', "root"),
])
# contract-test: supporting surface=rest_api assertions=images-generate.vector.validated-reviewed-corrected
def test_unsafe_or_unusable_svg_is_rejected(svg, reason):
    with pytest.raises(InvalidSvgError, match=reason):
        validate_svg(svg)


# contract-test: supporting surface=rest_api assertions=images-generate.vector.validated-reviewed-corrected
def test_safe_svg_with_internal_references_is_accepted():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><defs><linearGradient id="g"/></defs>'
        '<rect id="r" fill="url(#g)"/><use href="#r"/></svg>'
    )
    assert validate_svg(svg) == svg


# contract-test: supporting surface=rest_api assertions=images-generate.vector.progressive-drafts
def test_partial_svg_keeps_only_complete_lines_and_strips_prose():
    assert partial_svg("Here it is:\n<svg viewBox='0 0 1 1'>\n<rect/>\n<circle r=") == "<svg viewBox='0 0 1 1'>\n<rect/>\n"
    assert partial_svg("thinking about it") == ""
    assert partial_svg(f"```svg\n{GOOD}\n```") == GOOD
    assert extract_svg(f"text {GOOD} more") == GOOD


# contract-test: supporting surface=rest_api assertions=images-generate.vector.references-vector-and-pixel
def test_request_message_carries_svg_source_as_text_and_pixels_as_image_blocks():
    plain = build_request_message(prompt=" make it blue ", aspect_ratio="16:9", source_svgs=[GOOD], reference_images=[])
    assert isinstance(plain["content"], str)
    assert "Request: make it blue" in plain["content"]
    assert 'viewBox="0 0 1600 900"' in plain["content"]
    assert GOOD in plain["content"]

    mixed = build_request_message(
        prompt="redraw", aspect_ratio="1:1", source_svgs=[], reference_images=[(b"\x89PNG", "image/png")],
    )
    assert [block["type"] for block in mixed["content"]] == ["text", "image_url"]
    assert mixed["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


# contract-test: direct surface=rest_api assertions=images-generate.vector.skill-authors-svg,images-generate.vector.progressive-drafts
async def test_first_model_draws_reports_drafts_and_records_usage(monkeypatch):
    monkeypatch.setattr(vector_author, "DRAFT_INTERVAL_SECONDS", 0)
    stream_fn, review_fn, drafts = _stream(GOOD), _review(ACCEPT), []

    async def on_draft(svg, stage, attempt):
        drafts.append((svg, stage, attempt))

    result = await author_svg(
        task_id="t", prompt="a red square", requirements=REQUIREMENTS, on_draft=on_draft,
        stream_fn=stream_fn, review_fn=review_fn,
    )
    assert review_fn.seen[0]["requirements"] == REQUIREMENTS

    assert (result.svg, result.model_id, result.attempts, result.review_status) == (GOOD, "google/gemini-3.8-flash", 1, "accepted")
    assert result.usage == [
        VectorUsage("drawing", "google/gemini-3.8-flash", 100, 400),
        VectorUsage("review", "typesafe/jev-1.14", 900, 0),
    ]
    call = stream_fn.calls[0]
    assert call["system_prompt"] == vector_author.SYSTEM_PROMPT
    assert call["message_history"] == [{"role": "user", "content": call["message_history"][0]["content"]}]
    assert call["requested_reasoning_level"] == "LOW"
    drawing = [draft for draft in drafts if draft[1] == "drawing"]
    assert len(drawing) >= 2 and all(len(a[0]) < len(b[0]) for a, b in zip(drawing, drawing[1:]))
    assert drafts[-1] == (GOOD, "checking", 1)


# contract-test: direct surface=rest_api assertions=images-generate.vector.validated-reviewed-corrected
async def test_rejected_draft_is_corrected_with_the_reviewer_feedback():
    stream_fn, review_fn = _stream(GOOD, BETTER), _review(REJECT, ACCEPT)

    result = await author_svg(
        task_id="t", prompt="a square", quality="max", requirements=REQUIREMENTS, stream_fn=stream_fn, review_fn=review_fn,
    )

    assert (result.svg, result.attempts, result.review_status) == (BETTER, 2, "accepted")
    correction = stream_fn.calls[1]["message_history"]
    assert [message["role"] for message in correction] == ["user", "assistant", "user"]
    assert correction[1]["content"] == GOOD
    assert "nothing is cut off" in correction[2]["content"]
    assert stream_fn.calls[1]["requested_reasoning_level"] == "HIGH"
    assert [entry.step for entry in result.usage] == ["drawing", "review", "correcting", "review"]


# contract-test: direct surface=rest_api assertions=images-generate.vector.validated-reviewed-corrected
async def test_correction_stops_at_the_round_limit_and_delivers_the_last_valid_drawing():
    stream_fn, review_fn = _stream(GOOD, BETTER), _review(REJECT)

    result = await author_svg(
        task_id="t", prompt="a square", requirements=REQUIREMENTS, stream_fn=stream_fn, review_fn=review_fn,
    )

    assert len(stream_fn.calls) == MAX_CORRECTION_ROUNDS + 1 == 3
    assert (result.svg, result.attempts, result.review_status) == (BETTER, 3, "rejected")
    assert result.unmet_requirements == ("nothing is cut off",)
    assert len(result.usage) == 6


# contract-test: direct surface=rest_api assertions=images-generate.vector.validated-reviewed-corrected
async def test_unsafe_draft_is_never_reviewed_or_delivered():
    unsafe = GOOD.replace("<rect", "<script>x</script><rect")
    stream_fn, review_fn = _stream(unsafe, GOOD), _review(ACCEPT)

    result = await author_svg(
        task_id="t", prompt="a square", requirements=REQUIREMENTS, stream_fn=stream_fn, review_fn=review_fn,
    )

    assert (result.svg, result.attempts) == (GOOD, 2)
    assert len(review_fn.seen) == 1
    assert "<script> is not allowed" in stream_fn.calls[1]["message_history"][2]["content"]


# contract-test: direct surface=rest_api assertions=images-generate.vector.validated-reviewed-corrected
async def test_unavailable_review_delivers_the_valid_drawing_without_review_cost():
    stream_fn = _stream(GOOD)
    review_fn = _review(VectorReview(accepted=True, status="unavailable"))

    result = await author_svg(
        task_id="t", prompt="a square", requirements=REQUIREMENTS, stream_fn=stream_fn, review_fn=review_fn,
    )

    assert (result.review_status, result.attempts) == ("unavailable", 1)
    assert [entry.step for entry in result.usage] == ["drawing"]


# contract-test: direct surface=rest_api assertions=images-generate.vector.skill-authors-svg
async def test_next_model_takes_over_when_the_first_fails_and_all_failing_raises():
    stream_fn, review_fn = _stream(GOOD, fail_models=("google/gemini-3.8-flash",)), _review(ACCEPT)
    stream_fn.failed = 1

    result = await author_svg(task_id="t", prompt="a square", stream_fn=stream_fn, review_fn=review_fn)

    assert result.model_id == "openai/gpt-6.1-sol"
    assert [call["model_id"] for call in stream_fn.calls] == ["google/gemini-3.8-flash", "openai/gpt-6.1-sol"]

    with pytest.raises(VectorAuthorError, match="no valid SVG after 3 attempts"):
        await author_svg(
            task_id="t", prompt="a square", stream_fn=_stream("no drawing here"), review_fn=review_fn, models=("m/one",),
        )


# contract-test: direct surface=rest_api assertions=images-generate.vector.references-vector-and-pixel
async def test_modification_is_reviewed_as_a_modification():
    stream_fn, review_fn = _stream(BETTER), _review(ACCEPT)

    await author_svg(
        task_id="t", prompt="make it green", requirements=REQUIREMENTS, source_svgs=[GOOD],
        stream_fn=stream_fn, review_fn=review_fn,
    )

    assert review_fn.seen[0]["is_modification"] is True
    assert GOOD in stream_fn.calls[0]["message_history"][0]["content"]


PRICES = {
    "openai/gpt-6.1-sol": {"tokens": {"input": {"per_credit_unit": 100}, "output": {"per_credit_unit": 20}}},
    "typesafe/jev-1.14": {"tokens": {"input": {"per_credit_unit": 300}, "output": {"per_credit_unit": 300}}},
}


# contract-test: direct surface=rest_api assertions=images-generate.vector.token-metered-billing
async def test_credits_are_the_sum_of_every_call_priced_at_its_own_model(monkeypatch):
    async def pricing(model_id, _log_prefix):
        return PRICES.get(model_id)

    monkeypatch.setattr(generate_task, "_fetch_model_pricing_config", pricing)
    usage = [
        VectorUsage("drawing", "openai/gpt-6.1-sol", 600, 3000),
        VectorUsage("review", "typesafe/jev-1.14", 900, 0),
        VectorUsage("correcting", "openai/gpt-6.1-sol", 4000, 3200),
        VectorUsage("review", "typesafe/jev-1.14", 900, 0),
    ]

    credits, details = await generate_task._vector_author_credits(usage, "[t]")

    # 6 + 150 + 3 + 40 + 160 + 3 exact credits, rounded down once (not once per call).
    assert credits == 362
    assert [call["credits"] for call in details["provider_calls"]] == [156.0, 3.0, 200.0, 3.0]
    assert (details["input_tokens"], details["output_tokens"]) == (6400, 6200)


# contract-test: direct surface=rest_api assertions=images-generate.vector.token-metered-billing
@pytest.mark.parametrize("usage", [
    [VectorUsage("drawing", "openai/gpt-6.1-sol", 0, 0)],
    [VectorUsage("drawing", "unknown/model", 10, 10)],
])
# contract-test: direct surface=rest_api assertions=images-generate.vector.token-metered-billing
async def test_unpriced_or_unmetered_call_fails_instead_of_being_free(monkeypatch, usage):
    async def pricing(model_id, _log_prefix):
        return PRICES.get(model_id)

    monkeypatch.setattr(generate_task, "_fetch_model_pricing_config", pricing)
    with pytest.raises(RuntimeError):
        await generate_task._vector_author_credits(usage, "[t]")


# contract-test: direct surface=rest_api assertions=images-generate.vector.skill-authors-svg
def test_svg_is_drawn_by_the_author_unless_recraft_is_requested():
    assert generate_task._resolve_vector_engine(None) == "llm"
    assert generate_task._resolve_vector_engine("anything") == "llm"
    assert generate_task._resolve_vector_engine("Recraft") == "recraft"
    assert generate_task._resolve_vector_engine("script") == "script"
    assert generate_task._resolve_image_billing_model_ref(None, "svg", "default", False, "script") == "google/gemini-3.8-flash"
    assert generate_task._resolve_image_billing_model_ref(None, "svg", "default", False, "llm") == "google/gemini-3.8-flash"
    assert generate_task._resolve_image_billing_model_ref(None, "svg", "max", False, "recraft").startswith("recraft/")


# contract-test: direct surface=rest_api assertions=images-generate.vector.requirements-review
async def test_without_requirements_no_review_call_is_made():
    stream_fn, review_fn = _stream(GOOD), _review(REJECT)

    result = await author_svg(task_id="t", prompt="a square", stream_fn=stream_fn, review_fn=review_fn)

    assert review_fn.seen == []
    assert (result.svg, result.attempts, result.review_status) == (GOOD, 1, "skipped")
    assert [entry.step for entry in result.usage] == ["drawing"]


# contract-test: supporting surface=rest_api assertions=images-generate.vector.requirements-review
def test_requirements_are_trimmed_deduplicated_and_bounded():
    assert normalize_requirements(None) == []
    assert normalize_requirements("  two   variations ") == ["two variations"]
    assert normalize_requirements(["a", "a", "", "b"]) == ["a", "b"]
    assert len(normalize_requirements([f"r{index}" for index in range(20)])) == 8
    message = build_request_message(
        prompt="x", aspect_ratio="1:1", source_svgs=[], reference_images=[], requirements=["no gradients"],
    )
    assert "- no gradients" in message["content"]


# contract-test: direct surface=rest_api assertions=images-generate.vector.script-engine
async def test_script_engine_runs_the_generator_and_keeps_script_and_sandbox_time():
    stream_fn, review_fn = _stream(f"```python\n{SCRIPT}```"), _review(ACCEPT)
    script_fn, stages = _sandbox(ScriptRun(GOOD, 4.2)), []

    async def on_draft(svg, stage, attempt):
        stages.append((bool(svg), stage))

    result = await author_svg(
        task_id="t", prompt="a spiral", engine="script", requirements=REQUIREMENTS, on_draft=on_draft,
        stream_fn=stream_fn, review_fn=review_fn, script_fn=script_fn,
    )

    assert stream_fn.calls[0]["system_prompt"] == vector_author.SCRIPT_SYSTEM_PROMPT
    assert script_fn.seen == [SCRIPT.strip()]
    assert (result.svg, result.script, result.engine, result.sandbox_seconds) == (GOOD, SCRIPT.strip(), "script", [4.2])
    assert stages == [(False, "scripting"), (True, "checking")]
    assert [entry.step for entry in result.usage] == ["scripting", "review"]


# contract-test: direct surface=rest_api assertions=images-generate.vector.script-engine
async def test_failing_script_is_corrected_from_its_error_and_every_run_is_counted():
    stream_fn = _stream(SCRIPT, SCRIPT.replace("SVG", "DRAWING"))
    script_fn = _sandbox(ScriptRun(None, 1.5, "NameError: name 'SVG' is not defined"), ScriptRun(GOOD, 2.0))

    result = await author_svg(
        task_id="t", prompt="a spiral", engine="script", stream_fn=stream_fn, review_fn=_review(ACCEPT),
        script_fn=script_fn,
    )

    correction = stream_fn.calls[1]["message_history"]
    assert correction[1]["content"] == SCRIPT.strip()
    assert "NameError" in correction[2]["content"] and "Python module" in correction[2]["content"]
    assert (result.svg, result.attempts, result.sandbox_seconds) == (GOOD, 2, [1.5, 2.0])
    assert "DRAWING" in result.script


# contract-test: direct surface=rest_api assertions=images-generate.vector.script-engine
async def test_script_modification_starts_from_the_existing_generator():
    stream_fn = _stream(SCRIPT)

    await author_svg(
        task_id="t", prompt="more turns", engine="script", source_script="def build_svg():\n    return OLD\n",
        stream_fn=stream_fn, review_fn=_review(ACCEPT), script_fn=_sandbox(ScriptRun(GOOD, 1.0)),
    )

    assert "Existing generator script to modify:" in stream_fn.calls[0]["message_history"][0]["content"]
    assert "return OLD" in stream_fn.calls[0]["message_history"][0]["content"]
    assert extract_script("print('no entry point')") is None


# contract-test: direct surface=rest_api assertions=images-generate.vector.token-metered-billing
async def test_sandbox_time_and_a_flat_provider_fee_are_added_to_the_token_credits(monkeypatch):
    async def pricing(model_id, _log_prefix):
        return PRICES.get(model_id)

    monkeypatch.setattr(generate_task, "_fetch_model_pricing_config", pricing)
    usage = [VectorUsage("scripting", "openai/gpt-6.1-sol", 600, 3000)]

    credits, details = await generate_task._vector_author_credits(usage, "[t]", [1.5, 61.0])
    assert credits == 156 + 4 + 8
    assert [call["credits"] for call in details["provider_calls"]] == [156.0, 4, 8]

    review_only = [VectorUsage("review", "typesafe/jev-1.14", 900, 0)]
    credits, details = await generate_task._vector_author_credits(review_only, "[t]", flat_credits=100)
    assert credits == 103
    assert details["provider_calls"][-1] == {"step": "provider_flat_fee", "credits": 100}
    assert (script_run_credits(0), script_run_credits(0.1), script_run_credits(60), script_run_credits(60.1)) == (0, 4, 4, 8)


# contract-test: direct surface=rest_api assertions=images-generate.draft.flash-text-only
def test_text_only_draft_uses_flash_and_reference_drafts_use_klein_edit():
    flash = "recraft/recraftv4_1_flash"
    # Text-only draft keeps the Flash model whatever the quality setting says.
    assert generate_task._resolve_image_billing_model_ref(flash, "png", "max", False) == flash
    # Reference images switch the draft to the FLUX klein edit model.
    assert generate_task._resolve_image_billing_model_ref(flash, "png", "default", True) == "bfl/flux-2-klein-edit"
    # images.generate keeps choosing its raster tier by quality.
    assert generate_task._resolve_image_billing_model_ref("recraft/recraftv4_1_pro", "png", "default", False) == "recraft/recraftv4_1"
