# backend/tests/test_remotion_render_task.py
#
# Mock-only coverage for Remotion E2B render planning and billing. The real E2B
# sandbox is never created from tests; this suite validates the deterministic
# payload and credit rules used by the worker.

import asyncio

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


def test_remotion_render_task_uses_existing_e2b_vault_secret_path() -> None:
    pytest.importorskip("celery")
    from backend.apps.videos.tasks.render_remotion_task import _e2b_api_key

    class FakeSecretsManager:
        async def get_secret(self, *, secret_path: str, secret_key: str) -> str:
            assert secret_path == "kv/data/providers/e2b"
            assert secret_key == "api_key"
            return "e2b-key-from-vault"

    class FakeTask:
        _secrets_manager = FakeSecretsManager()

    assert asyncio.run(_e2b_api_key(FakeTask())) == "e2b-key-from-vault"


def test_remotion_render_task_resolves_user_vault_key_after_cache_miss() -> None:
    pytest.importorskip("celery")
    from backend.apps.videos.tasks.render_remotion_task import _resolve_user_vault_key_id

    class FakeCacheService:
        async def get_user_vault_key_id(self, user_id: str) -> None:
            assert user_id == "user-123"
            return None

    class FakeDirectusService:
        async def get_user_fields_direct(self, user_id: str, fields: list[str]) -> dict[str, str]:
            assert user_id == "user-123"
            assert fields == ["vault_key_id"]
            return {"vault_key_id": "vault-from-directus"}

    class FakeTask:
        _cache_service = FakeCacheService()
        _directus_service = FakeDirectusService()

    resolved = asyncio.run(
        _resolve_user_vault_key_id(
            FakeTask(),
            user_id="user-123",
            vault_key_id="",
        )
    )

    assert resolved == "vault-from-directus"


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
