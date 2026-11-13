"""images.modify author loop: program validation, input preparation, sandbox runs, review, correction and billing.

Specification: feature.app-skill.images-modify. Model, sandbox and review are fakes; the real
template, models and Jev are proven by the dev runs recorded in docs/plans/images-modify-skill/results.md.
"""
from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest
from PIL import Image as PIL_Image

from backend.apps.images import modify_review
from backend.apps.images.modify_author import (
    MAX_CORRECTION_ROUNDS,
    ModifyAuthorError,
    author_modification,
)
from backend.apps.images.modify_program import (
    DRAFT_MAX_BYTES,
    MAX_IMAGES,
    InvalidProgramError,
    ModifyInputError,
    build_author_message,
    extract_program,
    prepare_input,
    prepare_inputs,
    reduced_jpeg,
    validate_program,
)
from backend.apps.images.vector_author import VectorReview
from backend.shared.providers.e2b_image_edit import ImageEditRun

GOOD = "from PIL import Image\n\ndef edit(inputs):\n    return inputs[0]['image'].copy()\n"
BETTER = GOOD.replace(".copy()", ".copy().rotate(0)")
CRASHING = "def edit(inputs):\n    return inputs[3]['image']\n"
ESCAPING = "import os\n\ndef edit(inputs):\n    os.system('id')\n"
REQUIREMENTS = ["the ornament lies completely on the black back panel", "the rest of the photo is unchanged"]
ACCEPT = VectorReview(accepted=True, status="accepted", input_tokens=900)
REJECT = VectorReview(accepted=False, status="rejected", feedback="these requirements are not met: (1) on the panel",
                      input_tokens=900, unmet=(REQUIREMENTS[0],))
REJECT_BOTH = VectorReview(accepted=False, status="rejected", feedback="both unmet", input_tokens=900,
                           unmet=tuple(REQUIREMENTS))
UNAVAILABLE = VectorReview(accepted=True, status="unavailable")


def _png(size=(64, 48), mode="RGB", colour="black") -> bytes:
    buffer = io.BytesIO()
    PIL_Image.new(mode, size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _inputs():
    return prepare_inputs([("back.png", _png((300, 400)), "pixel"), ("flame.png", _png((50, 80), "RGBA"), "pixel")])


def _stream(*answers, usage=(100, 400), fail_models=()):
    """Fake provider stream: one scripted answer per call, then usage."""
    calls = []

    async def stream_fn(**kwargs):
        calls.append(kwargs)
        if kwargs["model_id"] in fail_models:
            raise RuntimeError("provider down")
        answer = answers[min(len([c for c in calls if c["model_id"] not in fail_models]) - 1, len(answers) - 1)]
        yield answer
        yield SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1])

    stream_fn.calls = calls
    return stream_fn


def _sandbox(*runs):
    seen = []

    async def run_fn(program, inputs):
        seen.append((program, inputs))
        return runs[min(len(seen) - 1, len(runs) - 1)]

    run_fn.seen = seen
    return run_fn


def _review(*outcomes):
    seen = []

    async def review_fn(**kwargs):
        seen.append(kwargs)
        return outcomes[min(len(seen) - 1, len(outcomes) - 1)]

    review_fn.seen = seen
    return review_fn


OK_RUN = ImageEditRun(image=_png((300, 400)), mime_type="image/png", width=300, height=400, seconds=1.5)
OK_RUN_2 = ImageEditRun(image=_png((300, 400), colour="white"), mime_type="image/png", width=300, height=400,
                        seconds=2.5)
CRASH_RUN = ImageEditRun(image=None, mime_type=None, width=0, height=0, seconds=0.8,
                         error='File "program.py", line 2, in edit\nIndexError: list index out of range')


def _author(stream, run, review=None, requirements=(), **kwargs):
    stages = []

    async def progress(stage, attempt, draft):
        stages.append((stage, attempt, draft))

    result = asyncio.run(author_modification(
        task_id="t", instructions="put the flame on the back", inputs=_inputs(), requirements=requirements,
        stream_fn=stream, run_fn=run, review_fn=review or _review(ACCEPT), progress=progress, **kwargs,
    ))
    return result, stages


# contract-test: supporting surface=rest_api assertions=images-modify.author.program-not-pixels
def test_program_is_extracted_from_fences_or_plain_text_and_must_define_edit():
    assert extract_program(f"Here:\n```python\n{GOOD}```\nDone") == GOOD.strip()
    assert extract_program(GOOD) == GOOD.strip()
    assert extract_program("def build_svg():\n    return ''\n") is None


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
@pytest.mark.parametrize("code,reason", [
    (ESCAPING, "import of 'os'"),
    ("import subprocess\ndef edit(inputs):\n    pass\n", "import of 'subprocess'"),
    ("from socket import socket\ndef edit(inputs):\n    pass\n", "import of 'socket'"),
    ("def edit(inputs):\n    eval('1')\n", "eval is not allowed"),
    ("def edit(inputs):\n    exec('1')\n", "exec is not allowed"),
    ("def edit(inputs):\n    __import__('os')\n", "__import__ is not allowed"),
    ("def edit(inputs):\n    open('/tmp/x', 'w')\n", "writing files"),
    ("def edit(inputs):\n    inputs[0]['image'].save('/tmp/x.png')\n", "saving to a file path"),
    ("import cv2\ndef edit(inputs):\n    cv2.imwrite('x.png', 0)\n", ".imwrite"),
    ("def edit(inputs):\n    ().__class__.__bases__\n", ".__bases__"),
    ("def edit(inputs)\n    pass\n", "not valid Python"),
    ("def other(inputs):\n    pass\n", "must define a top-level function edit"),
])
# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_static_check_rejects_escapes_and_unusable_programs(code, reason):
    with pytest.raises(InvalidProgramError, match=reason):
        validate_program(code)


# contract-test: supporting surface=rest_api assertions=images-modify.author.program-not-pixels
def test_static_check_accepts_the_allowed_libraries_and_reading():
    code = ("import io, math, random\nimport numpy as np\nimport cv2\nimport cairosvg\n"
            "from PIL import Image, ImageOps, ImageFilter\n\n"
            "def edit(inputs):\n    rng = random.Random(1)\n    buf = io.BytesIO()\n"
            "    inputs[0]['image'].save(buf, format='PNG')\n    open(inputs[0]['path'], 'rb').read()\n"
            "    return inputs[0]['image']\n")
    assert validate_program(code) == code


# contract-test: supporting surface=rest_api assertions=images-modify.request.pictures-from-the-chat
def test_more_than_six_pictures_or_unreadable_ones_fail_before_any_model_call():
    with pytest.raises(ModifyInputError, match=f"at most {MAX_IMAGES} pictures"):
        prepare_inputs([("p.png", _png(), "pixel")] * (MAX_IMAGES + 1))
    with pytest.raises(ModifyInputError, match="could not be read"):
        prepare_input("broken.png", b"not a picture", "pixel")
    with pytest.raises(ModifyInputError, match="empty"):
        prepare_input("empty.png", b"", "pixel")
    with pytest.raises(ModifyInputError, match="larger than 20 MB"):
        prepare_input("huge.png", b"x" * (20 * 1024 * 1024 + 1), "pixel")


# contract-test: supporting surface=rest_api assertions=images-modify.request.pictures-from-the-chat
def test_inputs_carry_their_oriented_exact_size_and_a_reduced_viewing_copy():
    exif = PIL_Image.Exif()
    exif[0x0112] = 6  # stored sideways, shown upright
    buffer = io.BytesIO()
    PIL_Image.new("RGB", (2400, 1200), "red").save(buffer, format="JPEG", exif=exif)
    item = prepare_input("photo.jpg", buffer.getvalue(), "pixel")
    assert (item.upload.width, item.upload.height) == (1200, 2400)
    assert item.upload.extension == "jpg" and item.upload.data == buffer.getvalue()  # the original goes to the sandbox
    with PIL_Image.open(io.BytesIO(item.preview)) as preview:
        assert preview.size == (512, 1024)
    transparent = prepare_input("motif.png", _png((80, 40), "RGBA", (0, 0, 0, 0)), "pixel")
    assert transparent.has_alpha and transparent.preview_mime == "image/png"


# contract-test: supporting surface=rest_api assertions=images-modify.author.program-not-pixels
def test_author_message_names_order_kind_exact_sizes_and_attaches_reduced_copies():
    message = build_author_message(instructions="put the flame on the back", requirements=REQUIREMENTS,
                                   inputs=_inputs(), output_type="jpg", source_program=GOOD)
    text = message["content"][0]["text"]
    assert "inputs[0] (index 1, 'back'): picture (RGB), 300 x 400 px" in text
    assert "inputs[1] (index 2, 'flame'): picture with transparency (RGBA), 50 x 80 px" in text
    assert "Result file type: jpg." in text
    assert all(f"- {item}" in text for item in REQUIREMENTS)
    assert "Existing program to change" in text and GOOD in text
    images = [block for block in message["content"] if block["type"] == "image_url"]
    assert len(images) == 2 and images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


# contract-test: supporting surface=rest_api assertions=images-modify.review.requirements-checked
def test_without_requirements_the_first_valid_picture_is_delivered_without_review():
    review = _review(ACCEPT)
    result, _stages = _author(_stream(GOOD), _sandbox(OK_RUN), review)
    assert result.review_status == "skipped" and result.attempts == 1
    assert result.image == OK_RUN.image and result.program == GOOD.strip()
    assert (result.width, result.height, result.mime_type) == (300, 400, "image/png")
    assert review.seen == []


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_crashing_program_is_corrected_with_the_error_text():
    stream = _stream(CRASHING, GOOD)
    run = _sandbox(CRASH_RUN, OK_RUN)
    result, stages = _author(stream, run)
    assert result.attempts == 2 and result.delivered_attempt == 2 and result.review_status == "skipped"
    correction = stream.calls[1]["message_history"]
    assert correction[1] == {"role": "assistant", "content": CRASHING.strip()}
    assert "IndexError: list index out of range" in correction[2]["content"]
    assert [stage for stage, _attempt, _draft in stages] == ["writing", "running", "correcting", "running"]


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_escaping_program_is_corrected_without_reaching_the_sandbox():
    stream = _stream(ESCAPING, GOOD)
    run = _sandbox(OK_RUN)
    result, _ = _author(stream, run)
    assert result.attempts == 2
    assert [program for program, _inputs in run.seen] == [GOOD.strip()]
    assert "import of 'os' is not allowed" in stream.calls[1]["message_history"][2]["content"]


# contract-test: supporting surface=rest_api assertions=images-modify.review.requirements-checked
def test_unmet_requirement_sends_picture_and_reason_back_and_is_marked_corrected():
    stream = _stream(GOOD, BETTER)
    review = _review(REJECT, ACCEPT)
    result, stages = _author(stream, _sandbox(OK_RUN, OK_RUN_2), review, requirements=REQUIREMENTS)
    assert result.review_status == "corrected" and result.attempts == 2
    assert result.image == OK_RUN_2.image and result.program == BETTER.strip()
    correction = stream.calls[1]["message_history"][2]["content"]
    assert "on the panel" in correction[0]["text"] and correction[1]["type"] == "image_url"
    assert review.seen[0]["requirements"] == REQUIREMENTS and len(review.seen[0]["input_images"]) == 2
    checking = [draft for stage, _attempt, draft in stages if stage == "checking"]
    assert len(checking) == 2 and all(draft and len(draft) <= DRAFT_MAX_BYTES for draft in checking)


# contract-test: supporting surface=rest_api assertions=images-modify.review.requirements-checked
def test_first_picture_accepted_is_marked_accepted():
    result, _ = _author(_stream(GOOD), _sandbox(OK_RUN), _review(ACCEPT), requirements=REQUIREMENTS)
    assert result.review_status == "accepted" and result.attempts == 1 and result.unmet_requirements == ()


# contract-test: supporting surface=rest_api assertions=images-modify.review.requirements-checked
def test_still_unmet_after_the_last_round_delivers_the_best_picture_with_the_unmet_list():
    review = _review(REJECT, REJECT_BOTH, REJECT)
    run = _sandbox(OK_RUN, OK_RUN_2, OK_RUN_2)
    result, _ = _author(_stream(GOOD, BETTER), run, review, requirements=REQUIREMENTS)
    assert result.review_status == "unmet_delivered"
    assert result.attempts == MAX_CORRECTION_ROUNDS + 1 == 3
    # Rounds 1 and 3 each miss one requirement; the earlier one is delivered.
    assert result.delivered_attempt == 1 and result.image == OK_RUN.image
    assert result.unmet_requirements == (REQUIREMENTS[0],)


# contract-test: supporting surface=rest_api assertions=images-modify.review.requirements-checked
def test_unreachable_review_delivers_the_picture_as_unreviewed():
    result, _ = _author(_stream(GOOD), _sandbox(OK_RUN), _review(UNAVAILABLE), requirements=REQUIREMENTS)
    assert result.review_status == "unavailable" and result.attempts == 1
    assert [entry.step for entry in result.usage] == ["writing"]


# contract-test: supporting surface=rest_api assertions=images-modify.review.requirements-checked
def test_no_valid_picture_after_all_rounds_and_models_raises():
    stream = _stream(CRASHING)
    with pytest.raises(ModifyAuthorError, match="no valid picture after 3 attempts"):
        _author(stream, _sandbox(CRASH_RUN), models=("model/a", "model/b"))
    assert len(stream.calls) == 6


# contract-test: supporting surface=rest_api assertions=images-modify.author.program-not-pixels
def test_provider_failure_moves_on_to_the_next_model():
    stream = _stream(GOOD, fail_models=("model/a",))
    result, _ = _author(stream, _sandbox(OK_RUN), models=("model/a", "model/b"))
    assert result.model_id == "model/b"
    assert [call["model_id"] for call in stream.calls] == ["model/a", "model/b"]


# contract-test: supporting surface=rest_api assertions=images-modify.billing.metered
def test_every_author_call_review_and_sandbox_run_is_recorded_for_billing():
    review = _review(REJECT, ACCEPT)
    result, _ = _author(_stream(GOOD, BETTER, usage=(1000, 2000)), _sandbox(CRASH_RUN, OK_RUN, OK_RUN_2), review,
                        requirements=REQUIREMENTS)
    assert [(u.step, u.input_tokens, u.output_tokens) for u in result.usage] == [
        ("writing", 1000, 2000), ("correcting", 1000, 2000), ("review", 900, 0),
        ("correcting", 1000, 2000), ("review", 900, 0),
    ]
    assert result.sandbox_seconds == [0.8, 1.5, 2.5]
    assert result.review_status == "corrected" and result.attempts == 3


# contract-test: supporting surface=rest_api assertions=images-modify.result.normal-image
def test_follow_up_change_sends_the_stored_program_to_the_author():
    stream = _stream(BETTER)
    _author(stream, _sandbox(OK_RUN), source_program=GOOD)
    text = stream.calls[0]["message_history"][0]["content"][0]["text"]
    assert "Existing program to change" in text and GOOD in text


# contract-test: supporting surface=rest_api assertions=images-modify.request.pictures-from-the-chat
def test_instructions_over_the_limit_or_unknown_output_type_fail_before_any_call():
    stream = _stream(GOOD)
    with pytest.raises(ModifyInputError, match="longer than 2000"):
        asyncio.run(author_modification(task_id="t", instructions="x" * 2001, inputs=_inputs(),
                                        stream_fn=stream, run_fn=_sandbox(OK_RUN)))
    with pytest.raises(ModifyInputError, match="output type"):
        asyncio.run(author_modification(task_id="t", instructions="crop", inputs=_inputs(), output_type="gif",
                                        stream_fn=stream, run_fn=_sandbox(OK_RUN)))
    assert stream.calls == []


# contract-test: supporting surface=rest_api assertions=images-modify.progress.shown-while-running
def test_drafts_are_small_jpegs():
    draft = reduced_jpeg(_png((3000, 2000), "RGBA", (255, 0, 0, 128)))
    with PIL_Image.open(io.BytesIO(draft)) as image:
        assert image.format == "JPEG" and max(image.size) <= 512
    assert len(draft) <= DRAFT_MAX_BYTES


# contract-test: supporting surface=rest_api assertions=images-modify.review.requirements-checked
def test_jev_review_sends_square_jpegs_and_only_a_clear_no_rejects(monkeypatch):
    from backend.shared.providers.typesafe.models import NoulAnswer

    sent = {}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def evaluate_with_images(self, *, state, questions, images):
            sent.update(state=state, questions=questions, images=images)
            answers = {"requirement_1": NoulAnswer(type="noul", noul=0.1), "requirement_2": NoulAnswer(type="noul", noul=0.5)}
            return SimpleNamespace(answers=answers, usage=SimpleNamespace(input_tokens=1234, output_tokens=56))

    monkeypatch.setattr("backend.apps.ai.utils.internal_decisions.JevDecisionClient", FakeClient)
    outcome = asyncio.run(modify_review.review_image_with_jev(
        image=_png((400, 300)), instructions="put it on the back", requirements=REQUIREMENTS,
        input_images=[_png((300, 400)), _png((50, 80), "RGBA")], secrets_manager=None, task_id="t"))
    assert not outcome.accepted and outcome.unmet == (REQUIREMENTS[0],) and outcome.input_tokens == 1234
    assert outcome.output_tokens == 56 and outcome.model_id == "typesafe/jev-1.14"
    assert len(sent["images"]) == 3
    for reference, content in sent["images"].items():
        with PIL_Image.open(io.BytesIO(content)) as image:
            assert image.format == "JPEG" and image.size == (336, 336)
        assert len(content) <= 256 * 1024
    assert sent["state"]["edited_result"] in sent["images"]


# contract-test: supporting surface=rest_api assertions=images-modify.review.requirements-checked
def test_jev_review_unreachable_is_unavailable(monkeypatch):
    from backend.shared.providers.typesafe import client as client_module

    class DownClient:
        def __init__(self, **_kwargs):
            pass

        async def evaluate_with_images(self, **_kwargs):
            raise client_module.DecisionProviderUnavailable("down")

    monkeypatch.setattr("backend.apps.ai.utils.internal_decisions.JevDecisionClient", DownClient)
    outcome = asyncio.run(modify_review.review_image_with_jev(
        image=_png(), instructions="x", requirements=REQUIREMENTS, input_images=[], secrets_manager=None,
        task_id="t"))
    assert outcome.accepted and outcome.status == "unavailable"
