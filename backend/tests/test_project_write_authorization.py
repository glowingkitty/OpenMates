"""Focused Project focus, policy, and immutable approval authority tests."""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from backend.tests.runtime_import_stubs import install_code_route_import_stubs
from backend.tests.test_async_skill_continuation import async_skill_continuation  # noqa: F401

install_code_route_import_stubs()

from backend.core.api.app.routes.projects import (  # noqa: E402
    ProjectCreateRequest,
    ProjectFocusActivateRequest,
    ProjectSettingsUpdateRequest,
    ProjectItemMoveRequest,
    activate_project_focus,
    create_project,
    get_project_settings,
    serialize_project_settings,
    update_project_settings,
    move_item_to_folder,
)
from backend.core.api.app.services.directus.project_methods import ProjectMethods, hash_id  # noqa: E402
from backend.core.api.app.services.directus.team_methods import TeamPermissionError  # noqa: E402
from backend.core.api.app.services.project_write_authorization_service import (  # noqa: E402
    ProjectWriteAuthorizationError,
    ProjectWriteAuthorizationService,
    focus_id_hash,
)


FOCUS_ID = "9f56b770-3903-46bb-b9ea-5d01d6bc995b"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-setup
def test_deferred_project_policy_stays_unselected_in_response():
    for settings in (None, {"write_mode": None}, {"write_mode": "invalid"}):
        result = serialize_project_settings(settings)
        assert result["write_mode"] is None
        assert result["selection_required"] is True
    assert serialize_project_settings({"write_mode": "auto_approve_safe_writes"})["write_mode"] == "apply_and_show"


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def set(self, key: str, value, ttl=None) -> bool:
        self.data[key] = value
        return True

    async def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None

    async def get_and_delete(self, key: str):
        return self.data.pop(key, None)


class AtomicFocusCache(MemoryCache):
    """In-memory Redis boundary: each eval completes without yielding to races."""
    @property
    def client(self):
        async def ready():
            return self
        return ready()

    async def eval(self, script, key_count, *values):
        keys, args = values[:key_count], values[key_count:]
        if "PROJECT_FOCUS_ACTIVATE" in script:
            pending, current = self.data.get(keys[0]), self.data.get(keys[1])
            if not pending or not current or pending["request_id"] != args[0] or current["request_id"] != args[0]:
                return 0
            if self.data.get(keys[2]) != args[4] or pending["activate_at"] > args[5] or pending["expires_at"] <= args[5]:
                return 0
            old = self.data.get(keys[3])
            if (old.get("activation_id", "") if old else "") != pending.get("expected_base_activation_id", ""):
                return 0
            self.data[keys[3]] = json.loads(args[6])
            return 1
        if "PROJECT_FOCUS_CURRENT" in script:
            binding = self.data.get(keys[0])
            if not binding or binding["activation_id"] != args[0] or binding.get("activation_request_id") != args[1]:
                return 0
            receipt = self.data.get(keys[1])
            if receipt:
                return int(receipt["accepted"] and receipt["activation_id"] == args[0])
            pending, current = self.data.get(keys[2]), self.data.get(keys[3])
            return int(bool(pending and current and pending["request_id"] == args[1]
                and current["request_id"] == args[1] and pending["message_id"] == self.data.get(keys[4])
                and pending["expires_at"] > args[4]))
        if "PROJECT_FOCUS_DECISION" in script:
            pending, current = self.data.get(keys[0]), self.data.get(keys[1])
            if not pending or not current or pending["request_id"] != args[0] or current["request_id"] != args[0]:
                return None
            if pending["message_id"] != self.data.get(keys[2]) or pending["expires_at"] <= args[3]:
                return None
            binding, accepted = self.data.get(keys[3]), args[4] == "true"
            matches = bool(binding and binding.get("activation_request_id") == args[0])
            if accepted and (not matches or pending["activate_at"] > args[3]):
                return None
            activation = binding["activation_id"] if matches else ""
            if matches and not accepted:
                self.data.pop(keys[3], None)
                specialist = self.data.get(keys[5])
                if specialist and specialist.get("base_activation_id") == activation:
                    self.data.pop(keys[5], None)
            self.data[keys[4]] = {"accepted": accepted, "activation_id": activation}
            self.data.pop(keys[0])
            return json.dumps(pending)
        raise AssertionError("Unknown atomic boundary")


def project_settings(write_mode: str | None = "apply_and_show", **overrides):
    return {
        "write_mode": write_mode,
        "default_focus_id_hash": focus_id_hash(FOCUS_ID),
        "encrypted_settings": "cipher-settings-v1",
        "updated_at": 1,
        **overrides,
    }


def personal_directus(settings_ref: dict[str, object]):
    return SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(
                return_value={"id": "chat-a", "hashed_user_id": hash_id("user-1"), "hashed_team_id": None}
            )
        ),
        project=SimpleNamespace(
            get_project=AsyncMock(return_value={"id": "project-row", "project_id": "project-a"}),
            get_project_settings=AsyncMock(side_effect=lambda *_args, **_kwargs: settings_ref.get("value")),
        ),
    )


def make_request(cache: MemoryCache, method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/v1/projects/test",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "app": SimpleNamespace(state=SimpleNamespace(cache_service=cache)),
        }
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.project-specialist-composition
@pytest.mark.asyncio
async def test_private_specialist_requires_live_project_and_current_item_revision():
    from backend.core.api.app.services.project_recommendation_service import project_item_revision
    project_id = "11111111-1111-4111-8111-111111111111"
    item_id = "22222222-2222-4222-8222-222222222222"
    item = {"item_type": "embed", "updated_at": 1, "encrypted_metadata": "cipher-v1"}
    directus = SimpleNamespace(project=SimpleNamespace(get_item=AsyncMock(return_value=item)))
    service = ProjectWriteAuthorizationService(directus, MemoryCache())
    service.get_active_focus = AsyncMock(return_value={"project_id": project_id, "team_id": None, "activation_id": "base-activation"})
    arguments = dict(user_id="user", chat_id="chat", focus_id=f"project-focus:{project_id}:{item_id}",
                     instruction="---\nname: Debugging\ndescription: Diagnose code failures\npreprocessor_hint: Debugging software\n---\nCurrent specialist instructions", item_revision=project_item_revision(item))
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_SPECIALIST_FOCUS_NOT_ACCEPTED"):
        await service.validate_specialist_context(**arguments)
    await service.accept_specialist_focus(user_id="user", chat_id="chat", focus_id=arguments["focus_id"])
    assert (await service.validate_specialist_context(**arguments))["instruction"] == arguments["instruction"]
    legacy_phased = ("---\nname: Debugging\ndescription: Diagnose code failures\n"
                     "preprocessor_hint: Debugging software\nphases:\n"
                     "  - id: inspect\n    name: Inspect\n    instructions: Read the source.\n"
                     "---\nCurrent specialist instructions")
    assert (await service.validate_specialist_context(**{
        **arguments, "instruction": legacy_phased,
    }))["instruction"] == legacy_phased
    versioned_phased = ("---\nname: Debugging\ndescription: Diagnose code failures\n"
                        "preprocessor_hint: Debugging software\nphases_version: 1\nphases:\n"
                        "  - id: inspect\n    title: Inspect\n    instructions: Read the source.\n"
                        "    requirements:\n      - id: inspected\n        text: The source was read.\n"
                        "---\nCurrent specialist instructions")
    assert (await service.validate_specialist_context(**{
        **arguments, "instruction": versioned_phased,
    }))["instruction"] == versioned_phased
    from backend.apps.ai.processing.focus_phases import parse_project_phase_focus, phase_prompt, restore_state
    from backend.core.api.app.services.project_authoring_service import ProjectFocusDocument
    authored = ProjectFocusDocument.model_validate({
        "name": "Debugging", "description": "Diagnose code failures", "when_to_use": "Debugging software",
        "instructions": "Global guidance.", "phases_version": 1,
        "phases": [
            {"id": "inspect", "title": "Inspect", "instructions": "Check the current source.",
             "requirements": [{"id": "inspected", "text": "Current source was checked."}]},
            {"id": "report", "title": "Report", "instructions": "PRIVATE-FUTURE-INSTRUCTION",
             "requirements": [{"id": "reported", "text": "Findings were reported."}]},
        ],
    })
    markdown = authored.markdown()
    authorized = await service.validate_specialist_context(**{**arguments, "instruction": markdown})
    parsed = parse_project_phase_focus(authorized["instruction"], arguments["focus_id"])
    active = phase_prompt(parsed, restore_state(parsed, focus_id=arguments["focus_id"], chat_id="chat"))
    assert "Global guidance." in active and "Check the current source." in active
    assert "Report" in active and "PRIVATE-FUTURE-INSTRUCTION" not in active
    unphased_markdown = ProjectFocusDocument.model_validate({
        "name": "Debugging", "description": "Diagnose code failures", "when_to_use": "Debugging software",
        "instructions": "Plain global guidance.",
    }).markdown()
    unphased = await service.validate_specialist_context(**{**arguments, "instruction": unphased_markdown})
    assert parse_project_phase_focus(unphased["instruction"], arguments["focus_id"]) is None
    malformed_versioned = versioned_phased.replace("    title: Inspect\n", "    name: PRIVATE-SENTINEL\n")
    with pytest.raises(ProjectWriteAuthorizationError, match="INVALID_PROJECT_FOCUS_INSTRUCTION") as error:
        await service.validate_specialist_context(**{**arguments, "instruction": malformed_versioned})
    assert "PRIVATE-SENTINEL" not in "".join(traceback.format_exception(error.value))
    with pytest.raises(ProjectWriteAuthorizationError, match="INVALID_PROJECT_FOCUS_INSTRUCTION"):
        await service.validate_specialist_context(**{
            **arguments, "instruction": versioned_phased.replace("phases_version: 1", "phases_version: true"),
        })
    for malformed in ("An ordinary note", "---\nname: Missing metadata\n---\nBody",
                      "---\nname: One\nname: Two\ndescription: Diagnose\nwhen_to_use: Debug\n---\nBody"):
        with pytest.raises(ProjectWriteAuthorizationError, match="INVALID_PROJECT_FOCUS_INSTRUCTION"):
            await service.validate_specialist_context(**{**arguments, "instruction": malformed})
    item["encrypted_metadata"] = "cipher-v2"
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REVISION_STALE"):
        await service.validate_specialist_context(**arguments)
    await service.accept_specialist_focus(user_id="user", chat_id="chat", focus_id="code-debugging")
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_SPECIALIST_FOCUS_NOT_ACCEPTED"):
        await service.validate_specialist_context(**arguments)
    service.get_active_focus.return_value = None
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUIRED"):
        await service.validate_specialist_context(**arguments)


# contract-test: supporting surface=rest_api assertions=projects.focus.existing-instructions,focus-modes.off-instruction
@pytest.mark.asyncio
async def test_private_base_instruction_revision_change_cannot_reuse_cached_content():
    settings_ref = {"value": project_settings()}
    service = ProjectWriteAuthorizationService(personal_directus(settings_ref), MemoryCache())
    await activate(service)
    assert await service.get_active_focus(user_id="user-1", chat_id="chat-a")
    settings_ref["value"] = project_settings(encrypted_settings="cipher-new-instructions")
    assert await service.get_active_focus(user_id="user-1", chat_id="chat-a") is None


# contract-test: supporting surface=rest_api assertions=projects.focus.existing-instructions,focus-modes.project-specialist-composition
@pytest.mark.asyncio
@pytest.mark.parametrize("change", (
    "chat_revoked", "project_revoked", "settings_changed", "activation_replaced",
    "chat_revoked_settings_failed",
))
async def test_focus_reads_start_together_but_revalidate_latest_authority(change):
    cache = MemoryCache()
    directus = personal_directus({"value": project_settings()})
    service = ProjectWriteAuthorizationService(directus, cache)
    binding = await activate(service)
    started = {name: asyncio.Event() for name in ("chat", "project", "settings")}
    release = asyncio.Event()

    async def live_chat(*_args, **_kwargs):
        started["chat"].set()
        await release.wait()
        return {"hashed_user_id": hash_id("other-user") if change.startswith("chat_revoked")
                else hash_id("user-1"), "hashed_team_id": None}

    async def live_project(*_args, **_kwargs):
        started["project"].set()
        await release.wait()
        return None if change == "project_revoked" else {"id": "project-row"}

    async def live_settings(*_args, **_kwargs):
        started["settings"].set()
        await release.wait()
        if change == "chat_revoked_settings_failed":
            raise RuntimeError("settings unavailable")
        if change == "settings_changed":
            return project_settings(encrypted_settings="cipher-new-instructions")
        return project_settings()

    directus.chat.get_chat_metadata.side_effect = live_chat
    directus.project.get_project.side_effect = live_project
    directus.project.get_project_settings.side_effect = live_settings
    lookup = asyncio.create_task(service.get_active_focus(user_id="user-1", chat_id="chat-a"))
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), timeout=2)
        if change == "activation_replaced":
            await cache.set(service._focus_key("user-1", "chat-a"), {**binding, "activation_id": "new-activation"})
    finally:
        release.set()
    assert await lookup is None


# contract-test: supporting surface=rest_api assertions=projects.focus.existing-instructions
@pytest.mark.asyncio
async def test_focus_read_preserves_unexpected_settings_failure():
    directus = personal_directus({"value": project_settings()})
    service = ProjectWriteAuthorizationService(directus, MemoryCache())
    await activate(service)
    directus.project.get_project_settings.side_effect = RuntimeError("settings unavailable")
    with pytest.raises(RuntimeError, match="settings unavailable"):
        await service.get_active_focus(user_id="user-1", chat_id="chat-a")


async def automatic_focus_authorization():
    from backend.core.api.app.services.project_focus_request_service import ProjectFocusRequestService
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    cache = AtomicFocusCache()
    directus = personal_directus({"value": project_settings()})
    service = ProjectWriteAuthorizationService(directus, cache)
    requests = ProjectFocusRequestService(cache, directus)
    request_id = "22222222-2222-4222-8222-222222222222"
    pending = {"request_id": request_id, "user_id": "user-1", "chat_id": "chat-a",
        "project_id": "project-a", "team_id": None, "message_id": "turn", "activate_at": time.time()-1,
        "expires_at": time.time()+1200}
    pointer = requests.key("user-1", "chat-a")
    await cache.set(pointer, pending)
    await cache.set(pointer + ":" + request_id, pending)
    await cache.set(async_skill_latest_user_turn_key("user-1", "chat-a"), "turn")
    return service, requests, request_id


@pytest.fixture
def focus_continuation_import(async_skill_continuation, monkeypatch):  # noqa: F811 - imported pytest fixture
    import sys
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.async_skill_continuation", async_skill_continuation)


# contract-test: supporting surface=rest_api assertions=projects.focus.inferred-consent,focus-modes.countdown
@pytest.mark.asyncio
async def test_cancel_while_permissions_awaited_cannot_write_project_authority(focus_continuation_import):
    service, requests, request_id = await automatic_focus_authorization()
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed_settings(*args, **kwargs):
        entered.set()
        await release.wait()
        return project_settings()
    service.directus_service.project.get_project_settings.side_effect = delayed_settings
    activation = asyncio.create_task(service.activate_focus(user_id="user-1", chat_id="chat-a",
        project_id="project-a", focus_id=FOCUS_ID, instruction="Private base",
        activation_request_id=request_id))
    await entered.wait()
    assert await requests.consume_decision(user_id="user-1", chat_id="chat-a", request_id=request_id, accepted=False)
    release.set()
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUEST_EXPIRED"):
        await activation
    assert await service.cache_service.get(service._focus_key("user-1", "chat-a")) is None
    assert await service.get_active_focus(user_id="user-1", chat_id="chat-a") is None


# contract-test: supporting surface=rest_api assertions=projects.focus.inferred-consent,focus-modes.off-instruction
@pytest.mark.asyncio
async def test_cancel_after_automatic_write_revokes_only_its_activation(focus_continuation_import):
    service, requests, request_id = await automatic_focus_authorization()
    await service.activate_focus(user_id="user-1", chat_id="chat-a", project_id="project-a",
        focus_id=FOCUS_ID, instruction="Automatic base", activation_request_id=request_id)
    assert await service.get_active_focus(user_id="user-1", chat_id="chat-a")
    assert await requests.consume_decision(user_id="user-1", chat_id="chat-a", request_id=request_id, accepted=False)
    assert await service.get_active_focus(user_id="user-1", chat_id="chat-a") is None
    # A later manually accepted binding cannot be cleared by an old decision.
    service, requests, request_id = await automatic_focus_authorization()
    await service.activate_focus(user_id="user-1", chat_id="chat-a", project_id="project-a",
        focus_id=FOCUS_ID, instruction="Automatic base", activation_request_id=request_id)
    newer = await service.activate_focus(user_id="user-1", chat_id="chat-a", project_id="project-a",
        focus_id=FOCUS_ID, instruction="New explicit base")
    assert await requests.consume_decision(user_id="user-1", chat_id="chat-a", request_id=request_id, accepted=False)
    assert (await service.get_active_focus(user_id="user-1", chat_id="chat-a"))["activation_id"] == newer["activation_id"]


# contract-test: supporting surface=rest_api assertions=projects.focus.inferred-consent,focus-modes.project-specialist-composition
@pytest.mark.asyncio
async def test_accepted_automatic_project_remains_authoritative_for_later_turns(focus_continuation_import):
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    service, requests, request_id = await automatic_focus_authorization()
    binding = await service.activate_focus(user_id="user-1", chat_id="chat-a", project_id="project-a",
        focus_id=FOCUS_ID, instruction="Accepted base", activation_request_id=request_id)
    assert await requests.consume_decision(user_id="user-1", chat_id="chat-a", request_id=request_id, accepted=True)
    await service.cache_service.set(async_skill_latest_user_turn_key("user-1", "chat-a"), "next-turn")
    assert (await service.get_active_focus(user_id="user-1", chat_id="chat-a"))["activation_id"] == binding["activation_id"]


# contract-test: supporting surface=rest_api assertions=projects.focus.inferred-consent,focus-modes.countdown
@pytest.mark.asyncio
async def test_old_countdown_cannot_overwrite_new_explicit_project_binding(focus_continuation_import):
    service, requests, request_id = await automatic_focus_authorization()
    newer = await service.activate_focus(user_id="user-1", chat_id="chat-a", project_id="project-a",
        focus_id=FOCUS_ID, instruction="Explicit new binding")
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUEST_STALE"):
        await service.activate_focus(user_id="user-1", chat_id="chat-a", project_id="project-a",
            focus_id=FOCUS_ID, instruction="Old automatic binding", activation_request_id=request_id)
    assert (await service.get_active_focus(user_id="user-1", chat_id="chat-a"))["activation_id"] == newer["activation_id"]


# contract-test: supporting surface=rest_api assertions=focus-modes.off-instruction,projects.focus.inferred-consent
@pytest.mark.asyncio
async def test_off_consumes_pending_countdown_without_recreating_authority(async_skill_continuation, monkeypatch):  # noqa: F811 - imported pytest fixture
    import sys
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.async_skill_continuation", async_skill_continuation)
    async_skill_continuation.dispatch_async_skill_continuation = AsyncMock()
    from backend.core.api.app.services.project_focus_request_service import ProjectFocusRequestService
    cache = MemoryCache()
    service = ProjectWriteAuthorizationService(personal_directus({"value": project_settings()}), cache)
    pending_service = ProjectFocusRequestService(cache, service.directus_service)
    pending = await pending_service.create_pending(user_id="user-1", chat_id="chat-a", request_id="request-1",
                                                   project_id="project-a", message_id="turn")
    await service.deactivate_focus(user_id="user-1", chat_id="chat-a")
    assert await cache.get(pending_service.key("user-1", "chat-a") + ":" + pending["request_id"]) is None
    assert await service.get_active_focus(user_id="user-1", chat_id="chat-a") is None
    async_skill_continuation.dispatch_async_skill_continuation.assert_awaited_once()
    assert async_skill_continuation.dispatch_async_skill_continuation.call_args.kwargs["completed_results"][0]["access_granted"] is False


# contract-test: supporting surface=rest_api assertions=projects.lifecycle.encrypted-crud,projects.association.safe-metadata-encrypted-authority
@pytest.mark.asyncio
async def test_encrypted_item_metadata_patch_preserves_folder_and_rejects_changed_revision():
    from backend.core.api.app.services.project_recommendation_service import project_item_revision
    item = {"id": "row", "updated_at": 1, "encrypted_metadata": "cipher-old", "hashed_folder_id": "folder-hash"}
    directus = SimpleNamespace(project=SimpleNamespace(
        get_project=AsyncMock(return_value={"project_id": "project"}), get_item=AsyncMock(return_value=item),
        update_item_metadata=AsyncMock(return_value={**item, "encrypted_metadata": "cipher-new"}),
    ))
    revision = project_item_revision(item)
    arguments = dict(request=make_request(MemoryCache(), "PATCH"), project_id="project", project_item_id="item",
                     current_user=SimpleNamespace(id="user"), directus_service=directus)
    result = await move_item_to_folder(**arguments,
        body=ProjectItemMoveRequest(encrypted_metadata="cipher-new", expected_item_revision=revision, updated_at=2))
    assert result["item"]["hashed_folder_id"] == "folder-hash"
    directus.project.update_item_metadata.assert_awaited_once_with(
        item, {"encrypted_metadata": "cipher-new", "updated_at": 2}, conditional=True)
    directus.project.update_item_metadata.reset_mock()
    item["encrypted_metadata"] = "cipher-other"
    with pytest.raises(HTTPException) as exc:
        await move_item_to_folder(**arguments,
            body=ProjectItemMoveRequest(encrypted_metadata="cipher-new", expected_item_revision=revision, updated_at=2))
    assert exc.value.status_code == 409
    directus.project.update_item_metadata.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=projects.files.write-policy-setup,projects.focus.default-owned
def test_project_create_requires_explicit_policy_and_encrypted_default_focus() -> None:
    with pytest.raises(ValidationError):
        ProjectCreateRequest(
            project_id="project-a",
            encrypted_project_key="cipher-key",
            encrypted_name="cipher-name",
            created_at=10,
            updated_at=10,
            last_opened_at=10,
        )


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-setup,projects.focus.default-owned
def test_chat_organization_defers_policy_without_enabling_file_work() -> None:
    values = dict(project_id="project-a", encrypted_project_key="cipher-key", encrypted_name="cipher-name",
                  created_at=10, updated_at=10, last_opened_at=10, write_mode=None,
                  default_focus_id=FOCUS_ID, encrypted_settings="cipher-settings")
    with pytest.raises(ValidationError):
        ProjectCreateRequest(**values)
    project = ProjectCreateRequest(**values, chat_organization_only=True)
    assert project.write_mode is None


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-setup
@pytest.mark.asyncio
async def test_only_new_chat_organization_settings_allow_deferred_policy() -> None:
    directus = SimpleNamespace(create_item=AsyncMock(return_value=(True, {"id": "settings"})), update_item=AsyncMock())
    methods = ProjectMethods(directus)
    methods.get_project_settings = AsyncMock(return_value=None)
    payload = {"write_mode": None, "default_focus_id": FOCUS_ID, "encrypted_settings": "cipher", "updated_at": 1}
    assert await methods.upsert_project_settings("project-a", "user-1", payload) is None
    assert await methods.upsert_project_settings("project-a", "user-1", payload, allow_deferred_write_mode=True)
    saved = directus.create_item.call_args.args[1]
    assert saved["write_mode"] is None
    methods.get_project_settings.return_value = {"id": "existing", "write_mode": "always_ask"}
    assert await methods.upsert_project_settings("project-a", "user-1", payload, allow_deferred_write_mode=True) is None
    directus.update_item.assert_not_called()


async def activate(service: ProjectWriteAuthorizationService, *, chat_id: str = "chat-a", project_id: str = "project-a"):
    return await service.activate_focus(
        user_id="user-1",
        chat_id=chat_id,
        project_id=project_id,
        focus_id=FOCUS_ID,
        instruction="Stay inside the Project and follow its checked-in instructions.",
    )


# contract-test: supporting surface=rest_api assertions=projects.files.chat-focus-required,focus-modes.project-write-gate
@pytest.mark.anyio
async def test_write_gate_requires_same_chat_and_project_active_focus() -> None:
    settings_ref = {"value": project_settings()}
    service = ProjectWriteAuthorizationService(personal_directus(settings_ref), MemoryCache())

    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
        )

    await activate(service)
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-b",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
        )
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_MISMATCH"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-b",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
        )

    await service.deactivate_focus(user_id="user-1", chat_id="chat-a")
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
        )


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement,projects.files.recovery-authorization
@pytest.mark.anyio
async def test_current_policy_and_exact_approval_are_rechecked_at_commit() -> None:
    settings_ref = {"value": project_settings()}
    cache = MemoryCache()
    service = ProjectWriteAuthorizationService(personal_directus(settings_ref), cache)
    await activate(service)

    automatic = await service.require_write_authorization(
        requester_user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
    )
    assert automatic["approval"] == "not_required"

    settings_ref["value"] = project_settings("always_ask", updated_at=2)
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_WRITE_APPROVAL_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
        )

    await service.approve_write(
        user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
    )
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_WRITE_APPROVAL_MISMATCH"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_B,
        )

    preflight = await service.require_write_authorization(
        requester_user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
    )
    assert preflight["approval"] == "approved"

    settings_ref["value"] = project_settings(
        "always_ask",
        encrypted_settings="cipher-settings-v2",
        updated_at=3,
    )
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_WRITE_APPROVAL_MISMATCH"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
            consume_approval=True,
        )


# contract-test: supporting surface=rest_api assertions=projects.files.recovery-authorization,focus-modes.project-write-gate
@pytest.mark.anyio
async def test_consumed_approval_is_idempotent_only_for_same_operation_and_digest() -> None:
    settings_ref = {"value": project_settings("always_ask")}
    service = ProjectWriteAuthorizationService(personal_directus(settings_ref), MemoryCache())
    await activate(service)
    await service.approve_write(
        user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
    )

    first = await service.require_write_authorization(
        requester_user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
        consume_approval=True,
    )
    retry = await service.require_write_authorization(
        requester_user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
        consume_approval=True,
    )
    assert first["idempotent_replay"] is False
    assert retry["idempotent_replay"] is True

    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_WRITE_APPROVAL_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-2",
            proposal_digest=DIGEST_A,
            consume_approval=True,
        )


# contract-test: supporting surface=rest_api assertions=projects.files.chat-focus-required,projects.files.write-policy-enforcement
@pytest.mark.anyio
async def test_team_role_and_missing_policy_changes_fail_closed() -> None:
    settings_ref = {"value": project_settings()}
    membership = AsyncMock(return_value={"role": "member"})
    directus = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(
                return_value={"id": "chat-a", "hashed_user_id": hash_id("owner"), "hashed_team_id": hash_id("team-1")}
            )
        ),
        team=SimpleNamespace(require_team_role=membership),
        project=SimpleNamespace(
            get_project=AsyncMock(return_value={"id": "project-row", "project_id": "project-a"}),
            get_project_settings=AsyncMock(side_effect=lambda *_args, **_kwargs: settings_ref.get("value")),
        ),
    )
    service = ProjectWriteAuthorizationService(directus, MemoryCache())
    await service.activate_focus(
        user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        focus_id=FOCUS_ID,
        instruction="Team Project instructions",
        team_id="team-1",
    )

    membership.side_effect = TeamPermissionError("removed")
    with pytest.raises(ProjectWriteAuthorizationError, match="TEAM_PERMISSION_DENIED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
            team_id="team-1",
        )

    membership.side_effect = None
    membership.return_value = {"role": "member"}
    settings_ref["value"] = project_settings(None)
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_WRITE_MODE_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
            team_id="team-1",
        )


# contract-test: direct surface=rest_api assertions=projects.files.write-policy-setup,projects.files.write-policy-settings
@pytest.mark.anyio
async def test_settings_missing_state_and_explicit_setup_contract() -> None:
    cache = MemoryCache()
    project_api = SimpleNamespace(
        get_project=AsyncMock(return_value={"id": "project-row"}),
        get_project_settings=AsyncMock(return_value=None),
        upsert_project_settings=AsyncMock(),
    )
    directus = SimpleNamespace(project=project_api)

    missing = await get_project_settings(
        request=make_request(cache, "GET"),
        project_id="project-a",
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )
    assert missing["settings"] == {
        "write_mode": None,
        "auto_selection": True,
        "selection_required": True,
        "default_focus_id_hash": None,
        "encrypted_settings": None,
        "updated_at": None,
    }

    with pytest.raises(HTTPException) as exc_info:
        await update_project_settings(
            request=make_request(cache, "PATCH"),
            project_id="project-a",
            body=ProjectSettingsUpdateRequest(write_mode="apply_and_show"),
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
        )
    assert exc_info.value.detail == "PROJECT_SETTINGS_SETUP_REQUIRED"
    project_api.upsert_project_settings.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=projects.files.chat-focus-required,focus-modes.project-write-gate
@pytest.mark.anyio
async def test_focus_activation_route_returns_no_plaintext_instruction() -> None:
    settings_ref = {"value": project_settings()}
    directus = personal_directus(settings_ref)
    response = await activate_project_focus(
        request=make_request(MemoryCache()),
        project_id="project-a",
        body=ProjectFocusActivateRequest(
            chat_id="chat-a",
            focus_id=FOCUS_ID,
            instruction="private transient instructions",
        ),
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )
    assert response["focus"]["active"] is True
    assert response["focus"]["project_id"] == "project-a"
    assert "instruction" not in response["focus"]


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-setup,projects.files.write-policy-settings
@pytest.mark.anyio
async def test_directus_settings_hashes_focus_and_preserves_omitted_ciphertext() -> None:
    existing = {
        "id": "settings-row",
        **project_settings("always_ask"),
    }
    directus = SimpleNamespace(
        get_items=AsyncMock(return_value=[existing]),
        update_item=AsyncMock(return_value={**existing, "write_mode": "apply_and_show", "updated_at": 2}),
    )
    methods = ProjectMethods(directus)
    await methods.upsert_project_settings(
        "project-a",
        "user-1",
        {"write_mode": "apply_and_show", "updated_at": 2},
    )
    update = directus.update_item.await_args.args[2]
    assert update["encrypted_settings"] == "cipher-settings-v1"
    assert update["default_focus_id_hash"] == focus_id_hash(FOCUS_ID)

    directus.get_items.return_value = []
    directus.create_item = AsyncMock(return_value=(True, {"id": "new-settings"}))
    await methods.upsert_project_settings(
        "project-b",
        "user-1",
        {
            "write_mode": "always_ask",
            "default_focus_id": FOCUS_ID,
            "encrypted_settings": "cipher-new",
            "updated_at": 3,
        },
    )
    create = directus.create_item.await_args.args[1]
    assert create["default_focus_id_hash"] == focus_id_hash(FOCUS_ID)
    assert "default_focus_id" not in create


# contract-test: direct surface=rest_api assertions=projects.files.write-policy-setup,projects.files.write-policy-settings,projects.focus.default-owned
@pytest.mark.anyio
async def test_project_create_persists_required_settings_before_success(monkeypatch) -> None:
    created = {"id": "project-row", "project_id": "project-a", "encrypted_name": "cipher-name"}
    saved_settings = {
        "write_mode": "apply_and_show",
        "default_focus_id_hash": focus_id_hash(FOCUS_ID),
        "encrypted_settings": "cipher-settings",
        "updated_at": 10,
    }
    project_api = SimpleNamespace(
        create_project=AsyncMock(return_value=created),
        upsert_project_settings=AsyncMock(return_value=saved_settings),
        delete_project=AsyncMock(),
    )
    history = {"change_set": {"change_set_id": "change-1"}, "entries": []}
    monkeypatch.setattr(
        "backend.core.api.app.routes.projects._record_project_history",
        AsyncMock(return_value=history),
    )

    response = await create_project(
        request=make_request(MemoryCache()),
        body=ProjectCreateRequest(
            project_id="project-a",
            encrypted_project_key="cipher-key",
            encrypted_name="cipher-name",
            created_at=10,
            updated_at=10,
            last_opened_at=10,
            write_mode="apply_and_show",
            default_focus_id=FOCUS_ID,
            encrypted_settings="cipher-settings",
        ),
        current_user=SimpleNamespace(id="user-1"),
        directus_service=SimpleNamespace(project=project_api),
        history_service=AsyncMock(),
    )

    create_payload = project_api.create_project.await_args.args[1]
    assert "write_mode" not in create_payload
    assert "default_focus_id" not in create_payload
    assert "encrypted_settings" not in create_payload
    project_api.upsert_project_settings.assert_awaited_once_with(
        "project-a",
        "user-1",
        {
            "write_mode": "apply_and_show",
            "default_focus_id": FOCUS_ID,
            "encrypted_settings": "cipher-settings",
            "updated_at": 10,
        },
        team_id=None,
    )
    project_api.delete_project.assert_not_awaited()
    assert response["settings"]["selection_required"] is False


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-setup,projects.focus.default-owned
@pytest.mark.anyio
async def test_project_create_rolls_back_when_settings_cannot_be_persisted() -> None:
    project_api = SimpleNamespace(
        create_project=AsyncMock(return_value={"id": "project-row", "project_id": "project-a"}),
        upsert_project_settings=AsyncMock(return_value=None),
        delete_project=AsyncMock(return_value=True),
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_project(
            request=make_request(MemoryCache()),
            body=ProjectCreateRequest(
                project_id="project-a",
                encrypted_project_key="cipher-key",
                encrypted_name="cipher-name",
                created_at=10,
                updated_at=10,
                last_opened_at=10,
                write_mode="always_ask",
                default_focus_id=FOCUS_ID,
                encrypted_settings="cipher-settings",
            ),
            current_user=SimpleNamespace(id="user-1"),
            directus_service=SimpleNamespace(project=project_api),
            history_service=AsyncMock(),
        )

    assert exc_info.value.detail == "Failed to create Project settings"
    project_api.delete_project.assert_awaited_once_with("project-a", "user-1", team_id=None)
