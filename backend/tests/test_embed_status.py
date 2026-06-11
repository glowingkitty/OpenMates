# backend/tests/test_embed_status.py
#
# Regression coverage for the canonical embed status state machine. Remotion
# video creation uses non-terminal render lifecycle states, so the backend must
# accept those transitions before WebSocket/cache updates can finalize embeds.

from backend.shared.python_schemas.embed_status import validate_embed_transition


def test_rendering_lifecycle_transitions_are_valid() -> None:
    assert validate_embed_transition("processing", "rendering", "embed-123")
    assert validate_embed_transition("rendering", "finished", "embed-123")
    assert validate_embed_transition("rendering", "error", "embed-123")
    assert validate_embed_transition("rendering", "cancelled", "embed-123")


def test_rerender_lifecycle_transitions_are_valid() -> None:
    assert validate_embed_transition("finished", "needs_rerender", "embed-123")
    assert validate_embed_transition("needs_rerender", "rendering", "embed-123")
    assert validate_embed_transition("needs_rerender", "error", "embed-123")
