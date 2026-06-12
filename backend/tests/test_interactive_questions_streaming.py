# backend/tests/test_interactive_questions_streaming.py
#
# Regression tests for the backend interactive-question protocol guard.
# Interactive questions are streamed as markdown fences, but they are durable
# encrypted message data once persisted. These tests keep malformed or open
# question fences from reaching clients as broken protocol content.

import importlib

import pytest

try:
    stream_consumer = importlib.import_module("backend.apps.ai.tasks.stream_consumer")
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


def _finalize_interactive_question_protocol(text: str) -> str:
    return stream_consumer._finalize_interactive_question_protocol(text)


def _is_inside_open_interactive_question(text: str) -> bool:
    return stream_consumer._is_inside_open_interactive_question(text)


VALID_QUESTION = """Please answer this.

```interactive_question
{
  "type": "choice",
  "id": "python_slicing",
  "multiple": false,
  "question": "Which expression returns every second item?",
  "options": [
    { "id": "step_2", "text": "items[::2]" },
    { "id": "from_2", "text": "items[2:]" }
  ]
}
```
"""


def test_valid_interactive_question_is_preserved() -> None:
    finalized = _finalize_interactive_question_protocol(VALID_QUESTION)

    assert finalized == VALID_QUESTION


def test_valid_input_question_without_title_is_preserved() -> None:
    valid_input = """```interactive_question
{
  "type": "input",
  "id": "experience",
  "fields": [
    { "id": "topic", "label": "Topic", "required": true }
  ]
}
```
"""

    finalized = _finalize_interactive_question_protocol(valid_input)

    assert finalized == valid_input


def test_unclosed_interactive_question_is_downgraded_before_persistence() -> None:
    malformed = """Please answer this.

```interactive_question
{
  "type": "choice",
  "id": "broken",
  "question": "Pick one",
  "options": [{ "id": "a", "text": "A" }]
"""

    finalized = _finalize_interactive_question_protocol(malformed)

    assert "```interactive_question" not in finalized
    assert "Failed to display question." in finalized


def test_code_fence_inside_open_interactive_question_is_not_treated_as_code_block() -> None:
    aggregated = """Intro

```interactive_question
{
  "type": "choice",
  "id": "broken",
  "question": "Pick one"
"""

    assert _is_inside_open_interactive_question(aggregated) is True


def test_embed_reference_after_invalid_interactive_question_is_removed() -> None:
    malformed_with_embed = """Please answer.

```interactive_question
{
  "type": "choice",
  "id": "broken"
}
```json
{"type": "code", "embed_id": "241cfa4d-6d60-4b7d-80c3-d3112291eb0a"}
```
"""

    finalized = _finalize_interactive_question_protocol(malformed_with_embed)

    assert "```interactive_question" not in finalized
    assert '"embed_id"' not in finalized
    assert "Failed to display question." in finalized
