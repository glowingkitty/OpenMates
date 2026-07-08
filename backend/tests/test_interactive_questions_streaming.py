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


def test_valid_custom_choice_question_is_preserved() -> None:
    valid_custom_choice = """```interactive_question
{
  "type": "choice",
  "id": "project_direction",
  "multiple": false,
  "question": "What should we work on next?",
  "custom_option_id": "own_answer",
  "custom_placeholder": "Type your own answer",
  "options": [
    { "id": "ship_fix", "text": "Ship the bug fix" },
    { "id": "own_answer", "text": "I give you my own answer" }
  ]
}
```
"""

    finalized = _finalize_interactive_question_protocol(valid_custom_choice)

    assert finalized == valid_custom_choice


def test_valid_choice_question_with_embed_ids_is_preserved() -> None:
    valid_embed_choice = """```interactive_question
{
  "type": "choice",
  "id": "choose_snippet",
  "multiple": false,
  "question": "Which implementation should we use?",
  "options": [
    { "id": "minimal", "text": "Minimal implementation", "embed_ids": ["11111111-1111-4111-8111-111111111111"] },
    { "id": "robust", "text": "More robust implementation", "embed_ids": ["22222222-2222-4222-8222-222222222222"] }
  ]
}
```
"""

    finalized = _finalize_interactive_question_protocol(valid_embed_choice)

    assert finalized == valid_embed_choice


def test_choice_question_attaches_preceding_embed_ids_to_non_custom_options() -> None:
    text = """Here are the snippets.

```json
{"type": "code", "embed_id": "embed-code-a"}
```

```json
{"type": "code", "embed_id": "embed-code-b"}
```

```interactive_question
{
  "type": "choice",
  "id": "choose_snippet",
  "multiple": false,
  "question": "Which implementation should we use?",
  "custom_option_id": "custom",
  "custom_placeholder": "Describe what you need",
  "options": [
    { "id": "minimal", "text": "Minimal implementation" },
    { "id": "robust", "text": "More robust implementation" },
    { "id": "custom", "text": "Something else" }
  ]
}
```
"""

    finalized = _finalize_interactive_question_protocol(text)

    assert finalized == text


def test_choice_question_attaches_preceding_uuid_embed_ids_to_non_custom_options() -> None:
    text = """Here are the snippets.

```json
{"type": "code", "embed_id": "11111111-1111-4111-8111-111111111111"}
```

```json
{"type": "code", "embed_id": "22222222-2222-4222-8222-222222222222"}
```

```interactive_question
{
  "type": "choice",
  "id": "choose_snippet",
  "multiple": false,
  "question": "Which implementation should we use?",
  "custom_option_id": "custom",
  "custom_placeholder": "Describe what you need",
  "options": [
    { "id": "minimal", "text": "Minimal implementation" },
    { "id": "robust", "text": "More robust implementation" },
    { "id": "custom", "text": "Something else" }
  ]
}
```
"""

    finalized = _finalize_interactive_question_protocol(text)

    assert '"embed_ids": [\n        "11111111-1111-4111-8111-111111111111"\n      ]' in finalized
    assert '"embed_ids": [\n        "22222222-2222-4222-8222-222222222222"\n      ]' in finalized
    assert '"id": "custom",\n      "text": "Something else"' in finalized
    assert '"id": "custom",\n      "text": "Something else",\n      "embed_ids"' not in finalized


def test_choice_question_replaces_filename_embed_ids_with_preceding_uuid_refs() -> None:
    text = """```json
{"type": "code", "embed_id": "11111111-1111-4111-8111-111111111111"}
```

```json
{"type": "code", "embed_id": "22222222-2222-4222-8222-222222222222"}
```

```interactive_question
{
  "type": "choice",
  "id": "choose_snippet",
  "multiple": false,
  "question": "Which implementation should we use?",
  "options": [
    { "id": "minimal", "text": "Minimal implementation", "embed_ids": ["debounce_minimal.js"] },
    { "id": "robust", "text": "More robust implementation", "embed_ids": ["debounce_robust.js"] }
  ]
}
```
"""

    finalized = _finalize_interactive_question_protocol(text)

    assert "debounce_minimal.js" not in finalized
    assert "debounce_robust.js" not in finalized
    assert '"embed_ids": [\n        "11111111-1111-4111-8111-111111111111"\n      ]' in finalized
    assert '"embed_ids": [\n        "22222222-2222-4222-8222-222222222222"\n      ]' in finalized


def test_choice_question_does_not_guess_when_embed_count_mismatches_options() -> None:
    text = """```json
{"type": "code", "embed_id": "embed-code-a"}
```

```interactive_question
{
  "type": "choice",
  "id": "choose_snippet",
  "multiple": false,
  "question": "Which implementation should we use?",
  "options": [
    { "id": "minimal", "text": "Minimal implementation" },
    { "id": "robust", "text": "More robust implementation" }
  ]
}
```
"""

    finalized = _finalize_interactive_question_protocol(text)

    assert finalized == text


def test_swipe_question_attaches_preceding_embed_ids_to_cards() -> None:
    text = """```json
{"type": "code", "embed_id": "embed-code-a"}
```

```json
{"type": "code", "embed_id": "embed-code-b"}
```

```interactive_question
{
  "type": "swipe",
  "id": "choose_snippet",
  "cards": [
    { "id": "minimal", "text": "Minimal implementation" },
    { "id": "robust", "text": "More robust implementation" }
  ]
}
```
"""

    finalized = _finalize_interactive_question_protocol(text)

    assert finalized == text


def test_swipe_question_attaches_preceding_uuid_embed_ids_to_cards() -> None:
    text = """```json
{"type": "code", "embed_id": "11111111-1111-4111-8111-111111111111"}
```

```json
{"type": "code", "embed_id": "22222222-2222-4222-8222-222222222222"}
```

```interactive_question
{
  "type": "swipe",
  "id": "choose_snippet",
  "cards": [
    { "id": "minimal", "text": "Minimal implementation" },
    { "id": "robust", "text": "More robust implementation" }
  ]
}
```
"""

    finalized = _finalize_interactive_question_protocol(text)

    assert '"embed_ids": [\n        "11111111-1111-4111-8111-111111111111"\n      ]' in finalized
    assert '"embed_ids": [\n        "22222222-2222-4222-8222-222222222222"\n      ]' in finalized


def test_invalid_choice_question_embed_ids_are_rejected() -> None:
    invalid_embed_choice = """```interactive_question
{
  "type": "choice",
  "id": "choose_snippet",
  "multiple": false,
  "question": "Which implementation should we use?",
  "options": [
    { "id": "minimal", "text": "Minimal implementation", "embed_ids": [""] }
  ]
}
```
"""

    finalized = _finalize_interactive_question_protocol(invalid_embed_choice)

    assert "```interactive_question" not in finalized
    assert "Failed to display question." in finalized


def test_custom_choice_requires_matching_option() -> None:
    invalid_custom_choice = """```interactive_question
{
  "type": "choice",
  "id": "project_direction",
  "multiple": false,
  "question": "What should we work on next?",
  "custom_option_id": "missing_option",
  "options": [
    { "id": "ship_fix", "text": "Ship the bug fix" }
  ]
}
```
"""

    finalized = _finalize_interactive_question_protocol(invalid_custom_choice)

    assert "```interactive_question" not in finalized
    assert "Failed to display question." in finalized


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
