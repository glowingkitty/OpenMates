# backend/tests/test_remotion_render_task.py
#
# Mock-only coverage for Remotion E2B render planning and billing. The real E2B
# sandbox is never created from tests; this suite validates the deterministic
# payload and credit rules used by the worker.

import pytest

from backend.apps.videos.remotion_billing import calculate_remotion_render_credits
from backend.shared.providers.e2b_remotion_renderer import (
    RemotionRenderPlanningError,
    plan_remotion_render,
)


def test_remotion_render_plan_writes_safe_project_files() -> None:
    plan = plan_remotion_render(
        source="export const ProductAnnouncement = () => <div>Launch Week</div>;",
        filename="ProductAnnouncement.tsx",
    )

    paths = [file.path for file in plan.files]
    assert "package.json" in paths
    assert "src/ProductAnnouncement.tsx" in paths
    assert plan.render_command.startswith("npm exec remotion render")
    assert plan.enable_internet is True


def test_remotion_render_plan_rejects_unsafe_filename() -> None:
    with pytest.raises(RemotionRenderPlanningError, match="unsafe"):
        plan_remotion_render(source="export default null;", filename="../secret.tsx")


@pytest.mark.parametrize(
    ("runtime_seconds", "auto_started", "expected"),
    [
        (59, True, 0),
        (60, True, 0),
        (61, True, 5),
        (120, True, 5),
        (121, True, 10),
        (1, False, 5),
        (60, False, 5),
    ],
)
def test_auto_started_renders_get_first_minute_free(runtime_seconds: int, auto_started: bool, expected: int) -> None:
    assert calculate_remotion_render_credits(runtime_seconds=runtime_seconds, auto_started=auto_started) == expected
