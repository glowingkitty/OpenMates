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
    root = next(file.content for file in plan.files if file.path == "src/Root.tsx")
    assert "package.json" in paths
    assert "src/ProductAnnouncement.tsx" in paths
    assert "registerRoot(RemotionRoot);" in root
    assert "UserModule.RemotionVideo" in root
    assert "UserModule.ProductAnnouncement" in root
    assert plan.install_commands[0].startswith("sudo apt-get update")
    assert "libnspr4" in plan.install_commands[0]
    assert "@remotion/player" not in next(file.content for file in plan.files if file.path == "package.json")
    assert "--max-old-space-size=256" in plan.install_commands[1]
    assert "--omit=optional" in plan.install_commands[1]
    assert "--concurrency=1" in plan.render_command
    assert "--disable-dev-shm-usage" in plan.render_command
    assert "width={640}" in root
    assert "height={360}" in root
    assert plan.render_command.startswith("npm exec remotion render")
    assert plan.enable_internet is True


def test_remotion_render_plan_accepts_remotion_video_named_export() -> None:
    plan = plan_remotion_render(
        source="export const RemotionVideo = () => <div>OpenMates</div>;",
        filename="OpenMatesPromo.tsx",
    )

    root = next(file.content for file in plan.files if file.path == "src/Root.tsx")
    assert "UserModule.RemotionVideo" in root
    assert "registerRoot(RemotionRoot);" in root


def test_remotion_render_plan_rejects_unsafe_filename() -> None:
    with pytest.raises(RemotionRenderPlanningError, match="unsafe"):
        plan_remotion_render(source="export default null;", filename="../secret.tsx")
