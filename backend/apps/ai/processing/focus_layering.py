# backend/apps/ai/processing/focus_layering.py
# Dependency-free policy for a focus layered over an always-active Project base
# (feature.focus-modes@3: project-layering, layer-end, layer-precedence,
# conflict-detection, override-note). Main processing calls these helpers; the
# Project binding itself stays owned by ProjectWriteAuthorizationService.
# Tests live in backend/tests/test_focus_layering.py.

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FocusLayers:
    """Which focus layers are active for one request.

    ``base_focus_id`` is the Project's own focus from the verified binding.
    ``layered_focus_id`` is a more specific focus on top of it (a built-in
    focus such as Write specification, or a Focus stored in the Project).
    """

    base_focus_id: str | None
    layered_focus_id: str | None

    @property
    def base_only(self) -> bool:
        return bool(self.base_focus_id) and not self.layered_focus_id

    @property
    def layered(self) -> bool:
        return bool(self.base_focus_id and self.layered_focus_id)


def resolve_focus_layers(active_focus_id: str | None, active_project_focus: dict[str, Any] | None) -> FocusLayers:
    """Split the chat's active focus into the Project base and a layered focus."""
    base = (active_project_focus or {}).get("focus_id") or None
    layered = active_focus_id if active_focus_id and active_focus_id != base else None
    return FocusLayers(base_focus_id=base, layered_focus_id=layered)


def deactivate_focus_tool(layers: FocusLayers, active_focus_id: str | None) -> dict[str, Any] | None:
    """The deactivate tool the answering model may call, or None.

    A layered focus ends on its own (user off, or its task is done) and the
    Project base stays. The base itself goes off only when the user explicitly
    moves the conversation away from the Project; the assistant never switches
    it off because a task finished.
    """
    if layers.layered:
        description = (
            f"End the focus mode '{layers.layered_focus_id}' that runs on top of the Project focus. "
            "The Project focus stays active with its instructions and file access. Use this when the user "
            "asks to stop this focus or when its task is clearly done (for example the Specification and "
            "its Plan were approved)."
        )
    elif layers.base_only:
        description = (
            "Switch the Project focus off. Use this ONLY when the user explicitly moves the conversation "
            "away from this Project (for example 'forget the project, let's talk about something else'). "
            "Never call it because a task finished or the user asked an unrelated side question; the "
            "Project focus stays on for the whole Project chat otherwise."
        )
    elif active_focus_id:
        description = (
            f"Deactivate the current focus mode ({active_focus_id}) and return to normal assistant behavior. "
            "Use this when the user no longer needs the specialized focus mode or asks to exit it."
        )
    else:
        return None
    return {
        "type": "function",
        "function": {
            # Snake_case for Gemini compatibility (see activate_focus_mode).
            "name": "deactivate_focus_mode",
            "description": description,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def deactivation_result(layers: FocusLayers) -> dict[str, str]:
    """Tool result after deactivation, telling the model what stays active."""
    if layers.layered:
        return {
            "status": "deactivated",
            "previous_focus_id": layers.layered_focus_id or "",
            "message": (
                f"Focus mode '{layers.layered_focus_id}' ended. The Project focus '{layers.base_focus_id}' "
                "remains active with its instructions and file access."
            ),
        }
    if layers.base_only:
        return {
            "status": "deactivated",
            "previous_focus_id": layers.base_focus_id or "",
            "message": (
                "The Project focus was switched off because the user moved away from the Project. "
                "Its instructions and file write access no longer apply."
            ),
        }
    return {}


def layer_end_client_event(layers: FocusLayers, chat_id: str) -> dict[str, Any] | None:
    """Client event after the assistant ends a layered focus (focus-modes.layer-end).

    Clients show the chat's focus from the last activation frame. When only the
    layer ends, the Project base is active again, so they receive the base as a
    fresh activation and persist it with their chat key; without it the focus
    pill kept showing the ended layer. Returns None when no layer ended.
    """
    if not layers.layered or not chat_id:
        return None
    return {"event_type": "focus_mode_activated",
            "payload": {"chat_id": chat_id, "focus_id": layers.base_focus_id}}


LAYER_PRECEDENCE_HEADER = "--- Focus layering ---"
LAYER_PRECEDENCE_FOOTER = "--- End Focus layering ---"


def build_layer_precedence_section(
    layers: FocusLayers, *, first_answer_after_layering: bool,
    layered_name: str | None = None, base_name: str | None = None,
) -> str | None:
    """Precedence between the Project base and the layered focus.

    The layered focus wins inside its own task scope; Project safety rules,
    constraints, permissions, data boundaries and write gates always hold, and
    platform safety beats both. On the first answer after layering the model
    checks the two instruction sets and notes each override once.
    """
    if not layers.layered:
        return None
    base_label = f"{base_name} ({layers.base_focus_id})" if base_name else layers.base_focus_id
    layered_label = f"{layered_name} ({layers.layered_focus_id})" if layered_name else layers.layered_focus_id
    lines = [
        LAYER_PRECEDENCE_HEADER,
        f"Two focus layers are active: the Project focus '{base_label}' (base) and the focus mode "
        f"'{layered_label}' (layered on top). Follow both.",
        "When their instructions collide:",
        "- Within its own task scope (its process, phases, questions and output format) the layered focus wins.",
        "- The Project focus's safety rules, constraints, permissions, data boundaries and file-write rules are "
        "never overridden by the layered focus. If the layered focus asks for something they forbid, follow the "
        "Project focus.",
        "- Platform safety policy overrides both layers.",
    ]
    if first_answer_after_layering:
        lines += [
            "This is the first answer since the layered focus started. Compare the two instruction sets now. "
            "If the layered focus overrides a Project focus instruction, or a Project constraint keeps a layered "
            "instruction from applying, begin this answer with one short line in the user's language, formatted "
            "as a blockquote starting with the layered focus's display name, that names each overridden or "
            "refused instruction. If nothing collides, write no such line. Do not repeat this note in later answers.",
        ]
    lines.append(LAYER_PRECEDENCE_FOOTER)
    return "\n".join(lines)
