"""Signed LIVE_MOCK replay for one end-to-end HTML diagram creation turn.

The fixture enters through Jev and the ordinary cached model wrapper. It never
publishes an embed itself: stream_consumer must parse the returned fence.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.testing.mock_context import get_mock_group, mock_mode_var


GROUP = "diagram_html_web"
PROMPT = (
    "Create a dark high-level architecture diagram of the OpenMates stack. "
    "DIAGRAM_HTML_E2E:architecture_dark"
)
DISCUSSION_PROMPT = (
    "We are comparing the OpenMates stack's ingestion, query and storage layers "
    "for a dark presentation. What are the architectural relationships and tradeoffs? "
    "DIAGRAM_HTML_E2E:architecture_discussion"
)
ON_DEMAND_PROMPT = (
    "Create a dark editable architecture diagram of the ingestion, query and storage layers. "
    "DIAGRAM_HTML_E2E:on_demand"
)
PROSE_PROMPT = (
    "Discuss the architecture of a planner, researcher and implementation worker. "
    "Answer in prose only, without a visual. DIAGRAM_HTML_E2E:architecture_prose"
)
PROSE_RESPONSE = "The planner defines scope, the researcher reports findings, and the implementation worker owns a bounded task."
SOURCE_PROMPT = (
    "Give me Mermaid source code for a planner-to-worker architecture flow. "
    "DIAGRAM_HTML_E2E:explicit_mermaid_source"
)
SOURCE_RESPONSE = "```mermaid\nflowchart TD\n    Planner --> Worker\n```"
MINDMAP_PROMPT = (
    "Create a native mind map of the planner and implementation worker architecture. "
    "DIAGRAM_HTML_E2E:native_mindmap"
)
MINDMAP_SOURCE = json.dumps({
    "openmatesType": "mindmap", "schemaVersion": 1, "title": "Planner and Worker",
    "rootId": "planner", "nodes": [
        {"id": "planner", "label": "Planner", "children": ["worker"]},
        {"id": "worker", "label": "Implementation Worker"},
    ], "edges": [], "view": {"layout": "radial-tree", "collapsedNodeIds": []},
})
MINDMAP_RESPONSE = f"```openmates_mindmap\n{MINDMAP_SOURCE}\n```"
_PROMPTS = (PROMPT, DISCUSSION_PROMPT, ON_DEMAND_PROMPT, PROSE_PROMPT, SOURCE_PROMPT, MINDMAP_PROMPT)
_HTML_PATH = Path(__file__).parent / "fixtures" / "diagram_html_web.html"


def _fixture_text(value: Any) -> str:
    """Recognize the one known anonymized sentence without bypassing PII."""
    return re.sub(
        r"Give me \[PERSON_NAME_\d+\] source code for a planner-to-worker architecture flow\. "
        r"DIAGRAM_HTML_E2E:explicit_mermaid_source",
        SOURCE_PROMPT, str(value or ""),
    )


def active() -> bool:
    """Require the already authenticated request-scoped replay context."""
    return (
        mock_mode_var.get() == "mock"
        and get_mock_group() == GROUP
        and os.getenv("MOCK_EXTERNAL_APIS") == "true"
        and os.getenv("SERVER_ENVIRONMENT", "production").strip().lower()
        not in {"production", "prod"}
    )


def _latest_user_contains_prompt(messages: Any) -> bool:
    if not isinstance(messages, list):
        return False
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return any(prompt in _fixture_text(message.get("content"))
                       for prompt in _PROMPTS)
    return False


def _state_matches(state: Any) -> bool:
    if not isinstance(state, Mapping):
        return False
    if _latest_user_contains_prompt(state.get("messages")):
        return True
    return any(prompt in _fixture_text(state.get("user_message"))
               for prompt in _PROMPTS)


def _choice(question_id: str, criteria: Any) -> str | None:
    if not isinstance(criteria, Mapping) or not criteria:
        return None
    preferred = {
        "complexity": "simple", "task_area": "creative",
        "topic_shift": "noticeable_shift", "temperature": "creative",
        "preview": "none", "language": "en", "icon": "cpu",
        "project_target": "none", "diagram_primary_type": "type-architecture",
        "diagram_secondary_type": "none", "diagram_tertiary_type": "none",
        "diagram_variant": "minimal_dark",
    }.get(question_id)
    if question_id == "diagram_primary_type" and preferred not in criteria:
        return None
    return preferred if preferred in criteria else next(iter(criteria))


def jev_response(state: Any, questions: Mapping[str, Mapping[str, Any]], model: str) -> DecisionResponse | None:
    """Answer the real bounded Jev question batch for this exact fixture turn."""
    if not active() or not _state_matches(state) or not questions:
        return None
    answers: dict[str, dict[str, Any]] = {}
    on_demand = ON_DEMAND_PROMPT in json.dumps(state)
    for question_id, question in questions.items():
        question_type = question.get("type")
        instructions = question.get("instructions")
        if question_type == "noul":
            candidate = instructions if isinstance(instructions, Mapping) else {}
            selected = question_id in {"diagram_guidance_relevant", "needs_detailed_context"} or (
                question_id.startswith("app_")
                and (candidate.get("candidate_id") or candidate.get("app_id")) in {"diagrams", "mindmaps"}
            )
            if on_demand:
                selected = False  # Deliberately miss all optional guide/app preselection.
            answers[question_id] = {"type": "noul", "noul": 1.0 if selected else 0.0}
        elif question_type == "choice":
            criteria = question.get("criteria")
            chosen = _choice(question_id, criteria)
            if chosen is None:
                return None
            answers[question_id] = {
                "type": "choice", "choice": chosen,
                "probabilities": {str(key): float(key == chosen) for key in criteria},
                "confidence": 1.0,
            }
        elif question_type == "score" and question_id == "harmful_response":
            criteria = question.get("criteria")
            if not isinstance(criteria, list) or not criteria:
                return None
            legend = {str(index): str(label) for index, label in enumerate(criteria)}
            answers[question_id] = {
                "type": "score", "score": 0.0, "legend": legend,
                "probabilities": {key: float(key == "0") for key in legend},
                "confidence": 1.0,
            }
        else:
            return None
    return DecisionResponse.model_validate({
        "provider": "diagram_fixture", "model": model, "answers": answers,
        "usage": {"input_tokens": 100, "output_tokens": len(answers)},
    })


def _tool_names(tools: Any) -> set[str]:
    if not isinstance(tools, list):
        return set()
    return {function["name"] for tool in tools if isinstance(tool, dict)
            if isinstance(function := tool.get("function"), dict)
            and isinstance(function.get("name"), str)}


def _postprocessing_fixture(model: str, task_id: Any) -> dict[str, Any]:
    arguments = {
        "follow_up_app_skill_suggestions": ["Create another architecture diagram with more detail"],
        "follow_up_general_suggestions": ["Explain the main architecture layers in order"],
        "new_chat_app_skill_suggestions": ["Create a data flow diagram for OpenMates"],
        "new_chat_general_suggestions": ["Describe common architecture diagram design choices"],
        "chat_summary": "Created an editable dark architecture diagram.",
        "chat_tags": ["architecture", "diagram"],
        "share_cta_text": "Explore the OpenMates architecture",
        "updated_chat_title": "OpenMates Architecture Diagram",
        "daily_inspiration_topic_suggestions": ["software architecture", "diagram design"],
        "quick_tip_slug": "",
    }
    call = {
        "tool_call_id": "diagram-postprocess-fixture",
        "function_name": "generate_suggestions_and_metadata",
        "function_arguments_raw": json.dumps(arguments, sort_keys=True),
        "function_arguments_parsed": arguments,
        "parsing_error": None,
    }
    return {"response": {"type": "non_stream", "value": {
        "kind": "pydantic", "module": "backend.apps.ai.llm_providers.google_client",
        "class": "UnifiedGoogleResponse", "value": {
            "task_id": str(task_id or "diagram-postprocess-fixture"), "model_id": model,
            "success": True, "tool_calls_made": [call],
            "usage": {"prompt_token_count": 100, "candidates_token_count": 40,
                      "total_token_count": 140},
        },
    }}}


def llm_fixture(category: str, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """Return provider-shaped chunks only for the exact signed diagram turn."""
    if not active() or not _latest_user_contains_prompt(kwargs.get("messages")):
        return None
    model = str(kwargs.get("model") or kwargs.get("model_id") or "")
    if not model:
        return None
    names = _tool_names(kwargs.get("tools"))
    if category == "llm_non_stream/gemini-3.5-flash-lite" \
            and names == {"generate_suggestions_and_metadata"} \
            and kwargs.get("tool_choice") == "required":
        return _postprocessing_fixture(model, kwargs.get("task_id"))
    if category != f"llm/{model}" or kwargs.get("stream") is False:
        return None
    if "generate_suggestions_and_metadata" in names:
        return None
    latest_user_text = next((_fixture_text(message.get("content"))
                             for message in reversed(kwargs.get("messages", []))
                             if isinstance(message, Mapping) and message.get("role") == "user"), "")
    if ON_DEMAND_PROMPT in latest_user_text:
        from backend.apps.diagrams.diagram_guidance import diagram_guidance_prompt
        system = "\n".join(str(message.get("content") or "")
                           for message in kwargs.get("messages", [])
                           if isinstance(message, Mapping) and message.get("role") == "system")
        guide = diagram_guidance_prompt(["type-architecture"], variant="minimal_dark")
        if guide not in system:
            tools_seen = [message for message in kwargs.get("messages", [])
                          if isinstance(message, Mapping) and message.get("role") == "tool"]
            found = any('app:diagrams:type-architecture' in str(message.get("content")) for message in tools_seen)
            name = "load_memories" if found else "find_memories"
            if name not in names:
                raise AssertionError("Missed preselection did not expose internal Memory tools")
            arguments = ({"memory_ids": ["app:diagrams:type-architecture"], "diagram_variant": "minimal_dark"}
                         if found else {"query": "architecture"})
            return {"response": {"type": "mixed_stream", "body": "", "chunk_format_version": 1, "chunks": [{
                "kind": "pydantic", "module": "backend.apps.ai.llm_providers.openai_shared",
                "class": "ParsedOpenAIToolCall", "value": {
                    "tool_call_id": f"diagram-{name}-fixture", "function_name": name,
                    "function_arguments_raw": json.dumps(arguments), "function_arguments_parsed": arguments,
                    "parsing_error": None,
                },
            }]}}
    discussion = any(prompt in latest_user_text
                     for prompt in (DISCUSSION_PROMPT, PROSE_PROMPT, SOURCE_PROMPT, MINDMAP_PROMPT))
    if discussion:
        # Fail closed if the real prompt assembler omitted either native protocol
        # or the complete selected guide. A canned response alone is no proof
        # that discussion-only requests receive their drawing context.
        from backend.apps.diagrams.diagram_guidance import diagram_guidance_prompt

        system = "\n".join(str(message.get("content") or "")
                           for message in kwargs.get("messages", [])
                           if isinstance(message, Mapping) and message.get("role") == "system")
        complete_guide = diagram_guidance_prompt(["type-architecture"], variant="minimal_dark")
        if (complete_guide not in system or "**Mind Map Generation (Mind Maps App)**" not in system
                or "Loading guidance does not require creating" not in system):
            raise AssertionError("Discussion replay did not receive complete native visualization guidance")
        if PROSE_PROMPT in latest_user_text:
            return {"response": {"type": "mixed_stream", "body": "", "chunk_format_version": 1,
                                  "chunks": [{"kind": "text", "value": PROSE_RESPONSE}]}}
        if SOURCE_PROMPT in latest_user_text:
            return {"response": {"type": "mixed_stream", "body": "", "chunk_format_version": 1,
                                  "chunks": [{"kind": "text", "value": SOURCE_RESPONSE}]}}
        if MINDMAP_PROMPT in latest_user_text:
            return {"response": {"type": "mixed_stream", "body": "", "chunk_format_version": 1,
                                  "chunks": [{"kind": "text", "value": MINDMAP_RESPONSE}]}}
    source = _HTML_PATH.read_text(encoding="utf-8")
    fenced = f"```openmates_diagram\n{source.rstrip()}\n```"
    return {"response": {
        "type": "mixed_stream", "body": "", "chunk_format_version": 1,
        "chunks": [{"kind": "text", "value": fenced[index:index + 1024]}
                   for index in range(0, len(fenced), 1024)],
    }}
