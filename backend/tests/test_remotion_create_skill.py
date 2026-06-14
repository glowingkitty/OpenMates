# backend/tests/test_remotion_create_skill.py
#
# Regression coverage for videos.create tool execution. These tests keep the
# deterministic Remotion path callable by the app-skill router without creating
# real E2B sandboxes or touching encrypted media storage.

import asyncio

import pytest

pytest.importorskip("celery")

from backend.apps.videos.skills.create_skill import CreateSkill


class FakeTaskSignature:
    id = "task-123"


class FakeCeleryProducer:
    def __init__(self) -> None:
        self.calls = []

    def send_task(self, name, args, queue):
        self.calls.append({"name": name, "args": args, "queue": queue})
        return FakeTaskSignature()


def test_videos_create_dispatches_remotion_render_task_with_placeholder_id() -> None:
    celery = FakeCeleryProducer()
    skill = CreateSkill(
        app=None,
        app_id="videos",
        skill_id="create",
        skill_name="Create video",
        skill_description="Create deterministic Remotion video",
        stage="production",
        celery_producer=celery,
    )

    result = asyncio.run(
        skill.execute(
            source="export const ProductAnnouncement = () => <div>OpenMates</div>;",
            filename="ProductAnnouncement.tsx",
            user_id="user-123",
            chat_id="chat-123",
            message_id="message-123",
            placeholder_embed_ids=["embed-123"],
            user_vault_key_id="vault-123",
        )
    )

    assert result["status"] == "rendering"
    assert result["task_id"] == "task-123"
    assert result["embed_id"] == "embed-123"
    assert celery.calls == [
        {
            "name": "apps.videos.tasks.render_remotion",
            "queue": "app_videos",
            "args": [
                {
                    "embed_id": "embed-123",
                    "chat_id": "chat-123",
                    "message_id": "message-123",
                    "user_id": "user-123",
                    "user_id_hash": "fcdec6df4d44dbc637c7c5b58efface52a7f8a88535423430255be0bb89bedd8",
                    "vault_key_id": "vault-123",
                    "remotion_source": "export const ProductAnnouncement = () => <div>OpenMates</div>;",
                    "filename": "ProductAnnouncement.tsx",
                    "source_version": 1,
                    "auto_started": True,
                    "render_id": result["render_id"],
                    "external_request": False,
                }
            ],
        }
    ]
