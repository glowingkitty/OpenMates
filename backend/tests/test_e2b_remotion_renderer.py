# backend/tests/test_e2b_remotion_renderer.py
#
# Mock-only coverage for Remotion E2B render planning. The real E2B sandbox is
# never created from tests; this suite validates the deterministic project files
# and safety checks passed to the worker boundary.

import pytest

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
