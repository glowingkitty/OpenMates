"""Pure prompt-selection tests; no provider calls or product E2E execution."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.apps.ai.assistant_speech.voice_context import (
    VOICE_MAIN_INSTRUCTION_KEY,
    build_voice_main_instruction,
)
from backend.apps.ai.utils.instruction_loader import load_base_instructions
from backend.apps.ai.utils.mate_utils import (
    MateConfig,
    load_mates_config,
    select_mate_system_prompt,
)

ROOT = Path(__file__).resolve().parents[2]
MATES = load_mates_config(str(ROOT / "backend/apps/ai/mates"))


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics,video-call.audio.spoken-rich-response
@pytest.mark.parametrize("mate", MATES, ids=lambda mate: mate.id)
@pytest.mark.parametrize("learning_mode", [False, True])
def test_voice_mate_composes_domain_policy_and_explicit_delivery(mate, learning_mode):
    prompt = select_mate_system_prompt(mate, voice_mode=True, learning_mode=learning_mode)
    # Keep the full domain source, including medical/legal limitations and
    # documentation/security requirements, rather than a generic replacement.
    assert mate.default_system_prompt in prompt
    delivery = mate.voice_learning_mode_system_prompt if learning_mode else mate.voice_system_prompt
    assert prompt.endswith(delivery)
    assert "language" in delivery and "prose" in delivery and "embeds" in delivery
    if learning_mode:
        assert mate.learning_mode_system_prompt in prompt
        assert prompt.index(mate.learning_mode_system_prompt) < prompt.index(delivery)


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response
@pytest.mark.parametrize("mate", MATES, ids=lambda mate: mate.id)
@pytest.mark.parametrize("learning_mode", [False, True])
def test_regular_chat_keeps_exact_existing_mate_selection(mate, learning_mode):
    expected = mate.learning_mode_system_prompt if learning_mode else mate.default_system_prompt
    assert select_mate_system_prompt(mate, voice_mode=False, learning_mode=learning_mode) == expected


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics,video-call.audio.spoken-rich-response
def test_voice_main_source_handles_old_instruction_cache_and_preserves_rich_delivery():
    instructions = load_base_instructions()
    source = instructions[VOICE_MAIN_INSTRUCTION_KEY]
    assert build_voice_main_instruction(instructions, voice_mode=True) == source
    assert build_voice_main_instruction({}, voice_mode=True) == source
    assert build_voice_main_instruction(instructions, voice_mode=False) == ""
    for required in (
        "user's language", "conversational prose", "Markdown headings", "bullet lists",
        "numbered lists", "Explicit requests", "inline embeds", "large embeds", "image groups",
        "nearby prose", "exact normal embed syntax", "ethics", "privacy", "tool permissions",
        "model routing", "thinking rules", "Do not claim work has completed",
        "Stay silent", "thinking pause", "unsolicited listening cues", "Are you still listening?",
    ):
        assert required in source
    # Shared source remains authoritative; the voice file does not copy ethics.
    assert instructions["base_ethics_instruction"] not in source
    assert instructions["base_privacy_instruction"] not in source


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics,video-call.audio.spoken-rich-response
def test_old_cached_mates_require_reload_instead_of_silently_losing_voice_policy():
    assert len(MATES) == 16
    mate = MATES[0]
    assert MateConfig.model_validate_json(mate.model_dump_json()) == mate
    old_cached = mate.model_dump(exclude={"voice_system_prompt", "voice_learning_mode_system_prompt"})
    with pytest.raises(ValidationError):
        MateConfig.model_validate(old_cached)


# contract-test: supporting surface=rest_api assertions=video-call.chat.ethics,video-call.chat.skill-integration,video-call.audio.spoken-rich-response
@pytest.mark.parametrize("voice_mode", [False, True])
@pytest.mark.parametrize("learning_mode", [False, True])
def test_actual_main_prompt_blocks_select_voice_without_removing_canonical_safeguards(voice_mode, learning_mode):
    """Execute actual assembly blocks without importing provider/runtime services.

    This is bounded source-wiring coverage, not full main processing or E2E.
    Other format/focus guidance is represented by a sentinel before delivery.
    """
    tree = ast.parse((ROOT / "backend/apps/ai/processing/main_processor.py").read_text())
    main = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "handle_main_processing")
    body = main.body

    def assignment_index(name):
        return next(index for index, node in enumerate(body)
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))

    prefix_index = assignment_index("stable_prefix_parts")
    mate_index = next(index for index, node in enumerate(body)
                      if isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                      and node.test.id == "selected_mate_config")
    voice_index = assignment_index("voice_main_instruction")
    join_index = assignment_index("full_system_prompt")
    assert voice_index < join_index
    # The delivery is appended after all ordinary format/focus instructions and
    # remains in prompt_parts for recovery/reassembly paths.
    assert isinstance(body[voice_index + 1], ast.If)
    selected_nodes = [
        *body[prefix_index:prefix_index + 3],
        *ast.parse('prompt_parts.append("ordinary format and focus guidance")').body,
        body[mate_index],
        *body[voice_index:join_index + 1],
    ]
    instructions = load_base_instructions()
    mate = next(mate for mate in MATES if mate.id == "sophia")
    namespace = {
        "base_instructions": instructions,
        "composer_suggestion_enabled": True,
        "selected_mate_config": mate,
        "learning_mode_active": learning_mode,
        "request_data": SimpleNamespace(voice_mode=voice_mode),
        "select_mate_system_prompt": select_mate_system_prompt,
        "build_voice_main_instruction": build_voice_main_instruction,
    }
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), "main_prompt_blocks", "exec"), namespace)
    prompt = namespace["full_system_prompt"]
    assert instructions["base_ethics_instruction"] in prompt
    assert instructions["base_privacy_instruction"] in prompt
    assert select_mate_system_prompt(mate, voice_mode=voice_mode, learning_mode=learning_mode) in prompt
    voice_source = instructions[VOICE_MAIN_INSTRUCTION_KEY]
    assert (voice_source in prompt) is voice_mode
    if voice_mode:
        assert prompt.endswith(voice_source)
