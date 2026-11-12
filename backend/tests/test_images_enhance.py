# backend/tests/test_images_enhance.py
#
# Contract tests for the image Enhance action (feature.embed-user-edits,
# embed-user-edits.enhance.*; plan docs/plans/embed-user-edit-versions, A2):
# POST/GET /v1/images/enhance, the apps.images.tasks.enhance worker and the
# expiry sweep. Directus, S3, the ledger, the provider and the safety
# classifiers are replaced at their boundary; the route, job store, source
# decryption, variant encryption and billing identities run for real.
# Run: python -m pytest backend/tests/test_images_enhance.py -q

from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import httpx
import pytest
import yaml
from fastapi import HTTPException, Response
from PIL import Image
from pydantic import ValidationError

from backend.apps.images import enhance_jobs as jobs
from backend.apps.images.tasks import enhance_task
from backend.apps.images.tasks.image_revision import billing_event_id
from backend.core.api.app.routes import images_enhance as route
from backend.shared.providers.google import gemini_image_enhance as provider
from backend.shared.python_utils.media_encryption import encrypt_media_variants

ROOT = Path(__file__).resolve().parents[2]
USER_ID = "user-1"
OTHER_USER = "user-2"
VAULT_KEY = "vault-key-1"
CHAT_ID = "chat-1"
PROJECT_ID = "project-1"
EMBED_ID = "3e1733df-1aea-5245-a3d0-b9a7179d9b48"
SOURCE_KEY = f"{USER_ID}/20261111_source_original.png"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _png(width: int, height: int, colour: str = "teal") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _webp(content: bytes) -> bytes:
    buffer = io.BytesIO()
    with Image.open(io.BytesIO(content)) as image:
        image.save(buffer, format="WEBP")
    return buffer.getvalue()


def _matches(row: Dict[str, Any], params: Dict[str, Any]) -> bool:
    for key, value in params.items():
        if not key.startswith("filter["):
            continue
        field, op = key[len("filter["):-1].split("][")
        current = row.get(field)
        if op == "_eq" and current != value:
            return False
        if op == "_null" and (current is None) != bool(value):
            return False
        if op == "_lt" and not (current is not None and current < value):
            return False
        if op == "_in" and current not in str(value).split(","):
            return False
    return True


def _matches_dict(row: Dict[str, Any], filters: Dict[str, Dict[str, Any]]) -> bool:
    for field, condition in filters.items():
        ((op, value),) = condition.items()
        current = row.get(field)
        if (op == "_eq" and current != value) or (op == "_neq" and current == value) or (
                op == "_lt" and not (current is not None and current < value)):
            return False
    return True


class Directus:
    """Collections as lists of rows with the Directus calls the Enhance code uses."""

    def __init__(self, collections: Dict[str, List[Dict[str, Any]]]) -> None:
        self.collections = collections
        self.chat = SimpleNamespace(check_chat_ownership=self._owns_chat)

    async def _owns_chat(self, chat_id: str, user_id: str) -> bool:
        return chat_id == CHAT_ID and user_id == USER_ID

    async def get_items(self, collection: str, params: Optional[Dict[str, Any]] = None, **_: Any) -> List[Dict[str, Any]]:
        rows = [dict(row) for row in self.collections.get(collection, []) if _matches(row, params or {})]
        return rows[: int((params or {}).get("limit") or len(rows) or 1)]

    async def create_item(self, collection: str, payload: Dict[str, Any], admin_required: bool = False,
                          *, expected_unique_conflict_field: Optional[str] = None):
        rows = self.collections.setdefault(collection, [])
        if expected_unique_conflict_field and any(
                row.get(expected_unique_conflict_field) == payload.get(expected_unique_conflict_field) for row in rows):
            return False, {"status_code": 400}
        row = {**payload, "id": str(uuid.uuid4())}
        rows.append(row)
        return True, dict(row)

    async def update_item_if_version(self, collection: str, item_id: str, data: Dict[str, Any], expected_version: int,
                                     *, extra_filters: Optional[Dict[str, Any]] = None, **_: Any):
        for row in self.collections.get(collection, []):
            if row["id"] == item_id and row.get("version") == expected_version and all(
                    row.get(field) == value for field, value in (extra_filters or {}).items()):
                row.update(data)
                return dict(row)
        return None

    async def delete_items(self, collection: str, filter_dict: Dict[str, Any], admin_required: bool = False) -> int:
        rows = self.collections.get(collection, [])
        keep = [row for row in rows if not _matches_dict(row, filter_dict)]
        self.collections[collection] = keep
        return len(rows) - len(keep)

    def job(self, operation_id: str) -> Dict[str, Any]:
        (row,) = [row for row in self.collections["image_enhance_jobs"] if row["operation_id"] == operation_id]
        return row


class Encryption:
    """Vault stand-in: reversible, key-bound."""

    async def encrypt_with_user_key(self, plaintext: str, key_id: str):
        return f"vault:{key_id}:" + base64.b64encode(plaintext.encode()).decode(), "1"

    async def decrypt_with_user_key(self, ciphertext: str, key_id: str):
        prefix = f"vault:{key_id}:"
        return base64.b64decode(ciphertext[len(prefix):]).decode() if ciphertext.startswith(prefix) else None


class Redis:
    def __init__(self) -> None:
        self.counters: Dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, ttl: int) -> None:
        return None


class Cache:
    def __init__(self) -> None:
        self.redis = Redis()
        self.events: List[tuple] = []

    @property
    async def client(self) -> Redis:
        return self.redis

    async def publish_event(self, channel: str, event: Dict[str, Any]) -> bool:
        self.events.append((channel, event))
        return True


class S3:
    environment = "development"
    base_domain = "example.org"

    def __init__(self) -> None:
        self.objects: Dict[str, bytes] = {}
        self.deleted: List[str] = []

    async def get_file(self, *, bucket_name: str, object_key: str) -> Optional[bytes]:
        return self.objects.get(object_key)

    async def upload_file(self, *, bucket_key: str, file_key: str, content: bytes, content_type: str):
        self.objects[file_key] = content
        return {"url": f"https://{bucket_key}.example.org/{file_key}"}

    async def delete_file(self, *, bucket_key: str, file_key: str) -> None:
        self.deleted.append(file_key)
        self.objects.pop(file_key, None)


def _pricing_entry() -> Dict[str, Any]:
    models = yaml.safe_load((ROOT / "backend/providers/google.yml").read_text())["models"]
    (entry,) = [model for model in models if model["id"] == provider.ENHANCE_MODEL_ID]
    return entry


class World:
    """One requester with one image embed in one chat, linked into one Personal Project."""

    def __init__(self, *, balance: int = 1000, version: Optional[int] = None) -> None:
        self.source_png = _png(640, 360)
        encrypted = encrypt_media_variants({"original": self.source_png}, write_version=2)
        self.source_aes_key = encrypted.aes_key_b64
        self.s3 = S3()
        self.s3.objects[SOURCE_KEY] = encrypted.payloads["original"]
        self.directus = Directus({
            "embeds": [{
                "id": "row-1", "embed_id": EMBED_ID, "hashed_user_id": _hash(USER_ID), "hashed_chat_id": _hash(CHAT_ID),
                "hashed_team_id": None, "version_number": version, "app_id": None, "skill_id": None,
                "s3_file_keys": json.dumps([{"bucket": "chatfiles", "key": SOURCE_KEY}]),
            }],
            "upload_files": [{"id": "file-1", "embed_id": EMBED_ID, "user_id": USER_ID, "content_type": "image/png"}],
            "projects": [{"id": "p", "project_id": PROJECT_ID, "hashed_user_id": _hash(USER_ID), "hashed_team_id": None}],
            "project_items": [],
            "image_enhance_jobs": [],
        })
        self.cache = Cache()
        self.encryption = Encryption()
        self.balance = balance
        self.dispatched: List[Dict[str, Any]] = []
        self.balance_reads = 0

    def link_to_project(self, *, item_type: str = "embed", deleted_target_state: Optional[str] = None) -> None:
        """Link the embed into the Personal Project as a Project file."""
        self.directus.collections["project_items"].append({
            "id": "pi", "hashed_project_id": _hash(PROJECT_ID), "item_type": item_type,
            "target_id_hash": _hash(EMBED_ID), "deleted_target_state": deleted_target_state})

    def state(self) -> SimpleNamespace:
        return SimpleNamespace(directus_service=self.directus, cache_service=self.cache,
                               encryption_service=self.encryption)

    def body(self, **overrides: Any) -> route.EnhanceRequest:
        data = {
            "operation_id": str(uuid.uuid4()), "embed_id": EMBED_ID,
            "scope": {"kind": "chat", "chat_id": CHAT_ID}, "expected_version": 1,
            "source": {"s3_key": SOURCE_KEY, "aes_key": self.source_aes_key,
                       "encryption": "aes-gcm-nonce-prefixed-v1", "format": "png", "width": 640, "height": 360},
        }
        data.update(overrides)
        return route.EnhanceRequest.model_validate(data)


@pytest.fixture
def world(monkeypatch) -> World:
    w = World()

    class Billing:
        def __init__(self, *_: Any) -> None:
            pass

        async def get_authoritative_personal_balance(self, *, user_id: str, user_id_hash: str) -> int:
            w.balance_reads += 1
            return w.balance

    monkeypatch.setattr(route, "BillingService", Billing)
    monkeypatch.setattr(route, "config_manager", SimpleNamespace(
        get_model_pricing=lambda provider_id, model_id: _pricing_entry() if (provider_id, model_id) == (
            "google", provider.ENHANCE_MODEL_ID) else None))
    from backend.core.api.app.tasks import celery_config

    monkeypatch.setattr(celery_config.app, "send_task",
                        lambda name, kwargs, queue: w.dispatched.append({"name": name, "kwargs": kwargs, "queue": queue}))
    return w


def _user(user_id: str = USER_ID) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, vault_key_id=VAULT_KEY)


async def _post(world: World, body: route.EnhanceRequest, user: Any = None) -> tuple[int, Dict[str, Any]]:
    response = Response()
    payload = await route.start_enhance(SimpleNamespace(app=SimpleNamespace(state=world.state())), response, body,
                                        current_user=user or _user())
    return response.status_code, payload


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
def test_the_price_comes_from_the_provider_pricing_entry() -> None:
    entry = _pricing_entry()
    assert entry["for_app_skill"] == "images.enhance"
    assert entry["costs"]["output_per_image"]["price"] == 0.0504
    assert jobs.enhance_credits(SimpleNamespace(get_model_pricing=lambda *_: entry)) == 80


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.parametrize("change", [
    {"operation_id": "not-a-uuid"},
    {"expected_version": 0},
    {"scope": {"kind": "team", "team_id": "t"}},
    {"source": {"s3_key": SOURCE_KEY, "aes_key": "A" * 44, "format": "gif", "width": 1, "height": 1}},
    {"source": {"s3_key": SOURCE_KEY, "aes_key": "A" * 44, "format": "png", "width": 0, "height": 1}},
    {"unexpected": True},
])
def test_malformed_requests_are_refused_before_any_work(world: World, change: Dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        world.body(**change)


@pytest.mark.asyncio
@pytest.mark.parametrize("case,status,detail", [
    ("bad_key", 422, "invalid_source_key"),
    ("legacy_without_nonce", 422, "invalid_source_nonce"),
    ("foreign_file", 422, "source_not_owned"),
    ("not_image", 422, "not_an_image"),
    ("team_scope", 403, "team_enhance_unavailable"),
    ("other_chat", 404, "embed_not_found"),
    ("other_user", 404, "embed_not_found"),
    ("project_not_linked", 404, "embed_not_in_project"),
    ("project_link_deleted", 404, "embed_not_in_project"),
    ("project_link_is_a_chat", 404, "embed_not_in_project"),
    ("chat_scope_of_project_file", 403, "project_context_required"),
])
# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
async def test_access_and_source_checks_refuse_without_a_job_or_charge(world: World, case: str, status: int,
                                                                       detail: str) -> None:
    body, user = world.body(), _user()
    source = body.source.model_dump()
    if case == "bad_key":
        body = world.body(source={**source, "aes_key": base64.b64encode(b"x" * 31).decode().ljust(44, "=")})
    elif case == "legacy_without_nonce":
        body = world.body(source={**source, "encryption": None})
    elif case == "foreign_file":
        body = world.body(source={**source, "s3_key": f"{OTHER_USER}/someone_else.png"})
    elif case == "not_image":
        world.directus.collections["upload_files"][0]["content_type"] = "application/pdf"
    elif case == "team_scope":
        body = world.body(scope={"kind": "chat", "chat_id": CHAT_ID, "team_id": "team-1"})
    elif case == "other_chat":
        body = world.body(scope={"kind": "chat", "chat_id": "chat-2"})
    elif case == "other_user":
        user = _user(OTHER_USER)
    elif case == "project_not_linked":
        body = world.body(scope={"kind": "project", "project_id": PROJECT_ID})
    elif case == "project_link_deleted":
        world.link_to_project(deleted_target_state="deleted")
        body = world.body(scope={"kind": "project", "project_id": PROJECT_ID})
    elif case == "project_link_is_a_chat":
        world.link_to_project(item_type="chat")
        body = world.body(scope={"kind": "project", "project_id": PROJECT_ID})
    elif case == "chat_scope_of_project_file":
        world.link_to_project(item_type="upload")
    with pytest.raises(HTTPException) as refused:
        await _post(world, body, user)
    assert (refused.value.status_code, refused.value.detail) == (status, detail)
    assert world.directus.collections["image_enhance_jobs"] == [] and world.dispatched == []


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
@pytest.mark.parametrize("link,scope_kind", [
    (None, "chat"), ({"deleted_target_state": "deleted"}, "chat"), ({"item_type": "embed"}, "project"),
    ({"item_type": "upload"}, "project"),
])
async def test_a_job_records_the_scope_under_the_shared_project_link_rule(world: World, link: Optional[Dict[str, Any]],
                                                                          scope_kind: str) -> None:
    # A soft-deleted link neither blocks a chat-scope Enhance nor authorizes a Project-scope one.
    if link is not None:
        world.link_to_project(**link)
    scope = {"kind": "chat", "chat_id": CHAT_ID} if scope_kind == "chat" else {"kind": "project", "project_id": PROJECT_ID}
    body = world.body(scope=scope)
    assert (await _post(world, body))[0] == 202
    job = world.directus.job(body.operation_id)
    assert (job["scope_kind"], job["scope_id_hash"]) == (
        scope_kind, _hash(CHAT_ID if scope_kind == "chat" else PROJECT_ID))
    assert jobs.PROJECT_FILE_ITEM_TYPES == ("embed", "upload")
    extension = (ROOT / "backend/core/directus/extensions/embed-version-transaction/src/project-items.js").read_text()
    assert "PROJECT_FILE_ITEM_TYPES = Object.freeze(['embed', 'upload'])" in extension


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_a_stale_version_is_a_conflict_without_a_job_or_charge(world: World) -> None:
    world.directus.collections["embeds"][0]["version_number"] = 3
    with pytest.raises(HTTPException) as refused:
        await _post(world, world.body(expected_version=2))
    assert refused.value.status_code == 409
    assert refused.value.detail == {"code": "embed_version_conflict", "current_version": 3}
    assert world.directus.collections["image_enhance_jobs"] == [] and world.dispatched == []
    assert world.balance_reads == 0


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_too_few_credits_is_402_without_a_job(world: World) -> None:
    world.balance = 62
    with pytest.raises(HTTPException) as refused:
        await _post(world, world.body())
    assert (refused.value.status_code, refused.value.detail) == (402, "insufficient_credits")
    assert world.directus.collections["image_enhance_jobs"] == [] and world.dispatched == []


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_a_replay_returns_the_same_job_and_dispatches_once(world: World) -> None:
    body = world.body()
    status, first = await _post(world, body)
    assert status == 202 and first["state"] == "pending" and first["credits"] == 80
    assert (first["base_version"], first["target_version"]) == (1, 2)
    status, again = await _post(world, body)
    assert status == 200 and again == first
    assert len(world.directus.collections["image_enhance_jobs"]) == 1 and len(world.dispatched) == 1
    job = world.directus.job(body.operation_id)
    assert job["billing_event_id"] == billing_event_id(EMBED_ID, 2, body.operation_id)
    dispatched = world.dispatched[0]
    assert (dispatched["name"], dispatched["queue"]) == ("apps.images.tasks.enhance", "app_images")
    # The source key travels Vault-wrapped and is not stored on the job.
    assert world.source_aes_key not in json.dumps(dispatched["kwargs"])
    assert world.source_aes_key not in json.dumps(job)
    with pytest.raises(HTTPException) as foreign:
        await _post(world, body, _user(OTHER_USER))
    assert (foreign.value.status_code, foreign.value.detail) == (409, "operation_id_conflict")


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_new_jobs_are_limited_per_user_per_minute(world: World) -> None:
    for _ in range(route.USER_LIMIT_PER_MINUTE):
        assert (await _post(world, world.body()))[0] == 202
    with pytest.raises(HTTPException) as limited:
        await _post(world, world.body())
    assert limited.value.status_code == 429
    assert len(world.dispatched) == route.USER_LIMIT_PER_MINUTE


class Pipeline:
    def __init__(self, *, input_ok: bool = True, output_ok: bool = True) -> None:
        self.input_ok, self.output_ok = input_ok, output_ok

    @staticmethod
    def _decision(allowed: bool) -> SimpleNamespace:
        return SimpleNamespace(allowed=allowed, rejection=None if allowed else SimpleNamespace(category="x"))

    async def validate_input(self, **_: Any) -> SimpleNamespace:
        return self._decision(self.input_ok)

    async def validate_output(self, **_: Any) -> SimpleNamespace:
        return self._decision(self.output_ok)


class Worker:
    """The task's environment: core services, provider, classifiers and the ledger at their boundary."""

    def __init__(self, world: World, monkeypatch, *, pipeline: Pipeline, provider_error: bool = False,
                 charge_error: Optional[Exception] = None, refund_error: Optional[Exception] = None) -> None:
        self.world = world
        self.charges: List[Dict[str, Any]] = []
        self.refunds: List[Dict[str, Any]] = []
        self.provider_calls: List[Dict[str, Any]] = []
        self.rejections: List[Any] = []
        self.task = SimpleNamespace(
            _directus_service=world.directus, _encryption_service=world.encryption, _cache_service=world.cache,
            _s3_service=world.s3, _secrets_manager=object(),
        )

        async def init() -> None:
            return None

        self.task.initialize_core_services = init

        async def no_probe(_: Any) -> None:
            return None

        async def fake_provider(**kwargs: Any) -> provider.EnhancedImage:
            self.provider_calls.append(kwargs)
            if provider_error:
                raise provider.ImageEnhanceProviderError("HTTP 503")
            ratio = provider.nearest_aspect_ratio(kwargs["width"], kwargs["height"])
            return provider.EnhancedImage(image_bytes=_png(2048, 1152), mime_type="image/png",
                                          model_id=provider.ENHANCE_MODEL_ID, aspect_ratio=ratio, image_size="2K")

        async def fake_charge(*, job: Dict[str, Any], user_id: str, chat_id: Optional[str]) -> None:
            self.charges.append({"event_id": job["billing_event_id"], "credits": job["credits"]})
            if charge_error is not None:
                raise charge_error

        async def fake_refund(*, job: Dict[str, Any], user_id: str, reason: str, log_prefix: str) -> None:
            if refund_error is not None:
                raise refund_error
            self.refunds.append({"event_id": job["billing_event_id"], "credits": job["credits"], "user": user_id})

        async def fake_rejection(task: Any, rejection: Any, **_: Any) -> Dict[str, Any]:
            self.rejections.append(rejection)
            return {}

        from backend.apps.images.tasks import generate_task
        from backend.core.api.app.utils import image_processing

        monkeypatch.setattr(enhance_task, "require_storage_available", no_probe)
        monkeypatch.setattr(enhance_task, "get_pipeline", lambda: pipeline)
        monkeypatch.setattr(enhance_task, "enhance_image_google", fake_provider)
        monkeypatch.setattr(jobs, "charge", fake_charge)
        monkeypatch.setattr(jobs, "refund", fake_refund)
        monkeypatch.setattr(generate_task, "_handle_safety_rejection", fake_rejection)
        monkeypatch.setattr(image_processing, "process_image_for_storage", lambda image, metadata: {
            "original": image, "full_webp": _webp(image), "preview_webp": _webp(_png(640, 360))})

    async def run(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return await enhance_task.run_enhance(self.task, **kwargs)


async def _accepted(world: World) -> tuple[str, Dict[str, Any]]:
    body = world.body()
    await _post(world, body)
    return body.operation_id, world.dispatched[-1]["kwargs"]


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure,embed-user-edits.enhance.faithful-2k
@pytest.mark.asyncio
async def test_a_produced_result_is_charged_once_and_handed_to_the_requester(world: World, monkeypatch) -> None:
    worker = Worker(world, monkeypatch, pipeline=Pipeline())
    operation_id, kwargs = await _accepted(world)
    assert (await worker.run(kwargs))["state"] == "ready"
    # A second delivery of the same task does nothing and never charges again.
    assert (await worker.run(kwargs))["state"] == "ready"
    assert worker.charges == [{"event_id": billing_event_id(EMBED_ID, 2, operation_id), "credits": 80}]
    assert worker.provider_calls[0]["image_bytes"] == world.source_png
    assert (worker.provider_calls[0]["width"], worker.provider_calls[0]["height"]) == (640, 360)

    job = world.directus.job(operation_id)
    assert (job["state"], job["billing_state"], job["charged_credits"]) == ("ready", "charged", 80)
    assert {ref["key"] for ref in job["result_file_keys"]} == {
        meta["s3_key"] for meta in json.loads(await world.encryption.decrypt_with_user_key(
            job["encrypted_result"], VAULT_KEY))["files"].values()}
    channel, event = world.cache.events[-1]
    assert channel == f"user_updates::{_hash(USER_ID)}"
    assert (event["event_for_client"], event["payload"]) == (
        "image_enhance_ready", {"operation_id": operation_id, "embed_id": EMBED_ID})

    response = Response()
    view = await route.get_enhance(SimpleNamespace(app=SimpleNamespace(state=world.state())), response,
                                   operation_id, current_user=_user())
    result = view["result"]
    assert set(result["files"]) == {"original", "full", "preview"}
    assert (result["files"]["original"]["width"], result["files"]["original"]["height"]) == (2048, 1152)
    assert (result["aspect_ratio"], result["image_size"], result["model"]) == ("16:9", "2K", provider.ENHANCE_MODEL_ID)
    assert result["enhanced_from"] == {"embed_id": EMBED_ID, "version": 1}
    from backend.shared.python_utils.media_encryption import decrypt_media_payload

    original = result["files"]["original"]
    decrypted = decrypt_media_payload(encrypted_data=world.s3.objects[original["s3_key"]],
                                      aes_key=base64.b64decode(result["aes_key"]), variant=original,
                                      legacy_nonce_b64=result["aes_nonce"] or None)
    assert Image.open(io.BytesIO(decrypted)).size == (2048, 1152)
    with pytest.raises(HTTPException) as hidden:
        await route.get_enhance(SimpleNamespace(app=SimpleNamespace(state=world.state())), Response(),
                                operation_id, current_user=_user(OTHER_USER))
    assert hidden.value.status_code == 404


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
@pytest.mark.parametrize("failure,code", [
    ("provider", "provider_failed"), ("input_safety", "safety_rejected"), ("output_safety", "safety_rejected"),
])
async def test_a_failed_enhance_costs_nothing_and_leaves_no_files(world: World, monkeypatch, failure: str,
                                                                  code: str) -> None:
    worker = Worker(world, monkeypatch, provider_error=failure == "provider", pipeline=Pipeline(
        input_ok=failure != "input_safety", output_ok=failure != "output_safety"))
    operation_id, kwargs = await _accepted(world)
    assert (await worker.run(kwargs))["error_code"] == code
    job = world.directus.job(operation_id)
    assert (job["state"], job["billing_state"], job["error_code"]) == ("failed", "none", code)
    assert worker.charges == [] and worker.refunds == []
    assert set(world.s3.objects) == {SOURCE_KEY}
    assert world.cache.events[-1][1]["event_for_client"] == "image_enhance_failed"
    assert worker.provider_calls == ([] if failure == "input_safety" else worker.provider_calls)
    assert len(worker.rejections) == (1 if "safety" in failure else 0)


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_a_refused_charge_deletes_the_result_and_charges_nothing(world: World, monkeypatch) -> None:
    refused = httpx.HTTPStatusError("402", request=httpx.Request("POST", "http://api"),
                                    response=httpx.Response(402))
    worker = Worker(world, monkeypatch, pipeline=Pipeline(), charge_error=refused)
    operation_id, kwargs = await _accepted(world)
    assert (await worker.run(kwargs))["error_code"] == "billing_failed"
    job = world.directus.job(operation_id)
    assert (job["state"], job["billing_state"]) == ("failed", "none")
    assert set(world.s3.objects) == {SOURCE_KEY}


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_an_undelivered_uncommitted_result_is_refunded_and_deleted_on_expiry(world: World, monkeypatch) -> None:
    worker = Worker(world, monkeypatch, pipeline=Pipeline())
    expiring, kwargs = await _accepted(world)
    await worker.run(kwargs)
    assert world.directus.job(expiring)["result_delivered_at"] is None
    committed, kwargs = await _accepted(world)
    await worker.run(kwargs)
    world.directus.job(committed)["state"] = "committed"
    unknown, kwargs = await _accepted(world)
    timeout = httpx.ConnectTimeout("no answer")
    worker_unknown = Worker(world, monkeypatch, pipeline=Pipeline(), charge_error=timeout)
    await worker_unknown.run(kwargs)
    assert world.directus.job(unknown)["billing_state"] == "charging"
    expiring_files = [ref["key"] for ref in world.directus.job(expiring)["result_file_keys"]]

    later = world.directus.job(expiring)["expires_at"] + jobs.EXPIRY_GRACE_SECONDS + 1
    worker_sweep = Worker(world, monkeypatch, pipeline=Pipeline())
    counts = await enhance_task.sweep_enhance_jobs(worker_sweep.task, now=later)
    assert counts["expired"] == 1 and counts["reconciled"] == 1 and counts["errors"] == 0
    job = world.directus.job(expiring)
    assert (job["state"], job["billing_state"], job["encrypted_result"]) == ("expired", "refunded", None)
    assert all(key not in world.s3.objects for key in expiring_files)
    # The unknown charge is re-issued under the same identity and then refunded: net nothing.
    assert worker_sweep.charges == [{"event_id": world.directus.job(unknown)["billing_event_id"], "credits": 80}]
    assert sorted(refund["event_id"] for refund in worker_sweep.refunds) == sorted([
        world.directus.job(expiring)["billing_event_id"], world.directus.job(unknown)["billing_event_id"]])
    assert world.directus.job(committed)["state"] == "committed"
    # A second sweep finds nothing left to refund.
    again = Worker(world, monkeypatch, pipeline=Pipeline())
    await enhance_task.sweep_enhance_jobs(again.task, now=later)
    assert again.refunds == [] and again.charges == []


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_a_hard_killed_worker_job_fails_and_is_refunded_once_after_the_stale_limit(
        world: World, monkeypatch) -> None:
    charged, _ = await _accepted(world)
    uncharged, _ = await _accepted(world)
    fresh, _ = await _accepted(world)
    now = jobs.now_ts()
    stale_at = now - jobs.STALE_CLAIM_SECONDS - 1
    for operation_id, billing in ((charged, "charged"), (uncharged, "none"), (fresh, "charged")):
        row = world.directus.job(operation_id)
        row.update(worker_claim="dead-run", billing_state=billing,
                   updated_at=now if operation_id == fresh else stale_at)
    sweep = Worker(world, monkeypatch, pipeline=Pipeline())
    counts = await enhance_task.sweep_enhance_jobs(sweep.task, now=now)
    assert counts["stale_failed"] == 2 and counts["errors"] == 0
    killed = world.directus.job(charged)
    assert (killed["state"], killed["error_code"], killed["billing_state"]) == ("failed", "internal_error", "refunded")
    assert [refund["event_id"] for refund in sweep.refunds] == [killed["billing_event_id"]]
    assert world.directus.job(uncharged)["state"] == "failed" and world.directus.job(uncharged)["billing_state"] == "none"
    assert world.directus.job(fresh)["state"] == "pending"
    assert [event[1]["event_for_client"] for event in world.cache.events].count("image_enhance_failed") == 2
    again = Worker(world, monkeypatch, pipeline=Pipeline())
    await enhance_task.sweep_enhance_jobs(again.task, now=now)
    assert again.refunds == [] and again.charges == []


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_a_job_with_a_result_is_never_refunded_by_the_stale_claim_rule(world: World, monkeypatch) -> None:
    worker = Worker(world, monkeypatch, pipeline=Pipeline())
    operation_id, kwargs = await _accepted(world)
    assert (await worker.run(kwargs))["state"] == "ready"
    row = world.directus.job(operation_id)
    # Even a row still reading pending (result stored, ready write lost) keeps its charge.
    row.update(state="pending", updated_at=jobs.now_ts() - jobs.STALE_CLAIM_SECONDS - 1)
    assert row["encrypted_result"]
    sweep = Worker(world, monkeypatch, pipeline=Pipeline())
    counts = await enhance_task.sweep_enhance_jobs(sweep.task, now=jobs.now_ts())
    assert counts["stale_failed"] == 0
    assert sweep.refunds == [] and world.directus.job(operation_id)["state"] == "pending"
    assert world.directus.job(operation_id)["billing_state"] == "charged"


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.faithful-2k
@pytest.mark.parametrize("size,ratio", [((640, 360), "16:9"), ((1000, 1000), "1:1"), ((1080, 1920), "9:16"),
                                        ((1200, 900), "4:3"), ((2520, 1080), "21:9"), ((800, 1000), "4:5")])
def test_the_provider_keeps_the_nearest_supported_aspect_ratio(size: tuple, ratio: str) -> None:
    assert provider.nearest_aspect_ratio(*size) == ratio
    assert provider.ENHANCE_IMAGE_SIZE == "2K" and provider.ENHANCE_MODEL_ID == "gemini-nano-banana-2.1"


async def _get(world: World, operation_id: str) -> Dict[str, Any]:
    return await route.get_enhance(SimpleNamespace(app=SimpleNamespace(state=world.state())), Response(),
                                   operation_id, current_user=_user())


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_a_delivered_but_unsaved_result_stays_charged_and_saveable_until_expiry(world: World, monkeypatch) -> None:
    worker = Worker(world, monkeypatch, pipeline=Pipeline())
    delivered, kwargs = await _accepted(world)
    await worker.run(kwargs)
    first = await _get(world, delivered)
    delivered_at = world.directus.job(delivered)["result_delivered_at"]
    assert "result" in first and isinstance(delivered_at, int)
    # Re-readable (and so committable) while unexpired; the first delivery time is kept.
    again = await _get(world, delivered)
    assert again["result"] == first["result"] and again["state"] == "ready"
    assert world.directus.job(delivered)["result_delivered_at"] == delivered_at
    late, kwargs = await _accepted(world)
    await worker.run(kwargs)
    job = world.directus.job(late)
    job["expires_at"] = jobs.now_ts() - 1
    # From expires_at on the result is never handed over, so it stays undelivered.
    expired_view = await _get(world, late)
    assert "result" not in expired_view and job["result_delivered_at"] is None
    files = [ref["key"] for ref in world.directus.job(delivered)["result_file_keys"]]

    later = world.directus.job(delivered)["expires_at"] + jobs.EXPIRY_GRACE_SECONDS + 1
    sweep = Worker(world, monkeypatch, pipeline=Pipeline())
    counts = await enhance_task.sweep_enhance_jobs(sweep.task, now=later)
    assert counts["expired"] == 2 and counts["errors"] == 0
    row = world.directus.job(delivered)
    assert (row["state"], row["billing_state"], row["encrypted_result"]) == ("expired", "charged", None)
    assert all(key not in world.s3.objects for key in files)
    # Only the result that never reached the user is refunded.
    assert [refund["event_id"] for refund in sweep.refunds] == [world.directus.job(late)["billing_event_id"]]
    assert world.directus.job(late)["billing_state"] == "refunded"


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_a_replayed_start_hands_over_the_result_and_records_the_delivery(world: World, monkeypatch) -> None:
    worker = Worker(world, monkeypatch, pipeline=Pipeline())
    body = world.body()
    await _post(world, body)
    await worker.run(world.dispatched[-1]["kwargs"])
    status, replay = await _post(world, body)
    assert status == 200 and "result" in replay
    assert isinstance(world.directus.job(body.operation_id)["result_delivered_at"], int)


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_a_duplicate_delivery_that_cannot_claim_the_job_touches_nothing(world: World, monkeypatch) -> None:
    worker = Worker(world, monkeypatch, pipeline=Pipeline())
    operation_id, kwargs = await _accepted(world)
    stale = dict(world.directus.job(operation_id))
    assert (await worker.run(kwargs))["state"] == "ready"
    finished = dict(world.directus.job(operation_id))
    objects = dict(world.s3.objects)
    events = len(world.cache.events)

    # The second delivery read the row while it was still pending and unclaimed.
    real_get_job = jobs.get_job

    async def stale_read(directus: Any, op_id: str) -> Optional[Dict[str, Any]]:
        return dict(stale) if op_id == operation_id else await real_get_job(directus, op_id)

    monkeypatch.setattr(jobs, "get_job", stale_read)
    assert (await worker.run(kwargs))["state"] == "pending"
    monkeypatch.setattr(jobs, "get_job", real_get_job)
    assert len(worker.provider_calls) == 1 and len(worker.charges) == 1 and worker.refunds == []
    assert world.directus.job(operation_id) == finished and world.s3.objects == objects
    assert len(world.cache.events) == events

    # A pending row another run already claimed is left alone too.
    other, kwargs = await _accepted(world)
    world.directus.job(other)["worker_claim"] = "another-run"
    claimed = dict(world.directus.job(other))
    await worker.run(kwargs)
    assert world.directus.job(other) == claimed and len(worker.provider_calls) == 1


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
async def test_an_unexpected_failure_fails_only_the_row_this_run_owns(world: World, monkeypatch) -> None:
    worker = Worker(world, monkeypatch, pipeline=Pipeline())
    operation_id, kwargs = await _accepted(world)

    async def broken_upload(**_: Any) -> Dict[str, Any]:
        raise RuntimeError("storage went away")

    monkeypatch.setattr(world.s3, "upload_file", broken_upload)
    with pytest.raises(RuntimeError):
        await worker.run(kwargs)
    job = world.directus.job(operation_id)
    assert (job["state"], job["error_code"], job["billing_state"]) == ("failed", "internal_error", "none")
    assert worker.charges == [] and set(world.s3.objects) == {SOURCE_KEY}

    # Another writer took the row while this run worked: the cleanup leaves it alone.
    taken, kwargs = await _accepted(world)

    async def upload_then_lose_the_row(**_: Any) -> Dict[str, Any]:
        row = world.directus.job(taken)
        row.update({"worker_claim": "another-run", "version": row["version"] + 1})
        raise RuntimeError("storage went away")

    monkeypatch.setattr(world.s3, "upload_file", upload_then_lose_the_row)
    with pytest.raises(RuntimeError):
        await worker.run(kwargs)
    assert (world.directus.job(taken)["state"], world.directus.job(taken)["worker_claim"]) == ("pending", "another-run")


# contract-test: direct surface=rest_api assertions=embed-user-edits.enhance.billed-once-refunded-on-failure
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["ready_write", "refund"])
async def test_a_transport_failure_after_the_charge_fails_the_job_for_the_sweep_to_refund(
        world: World, monkeypatch, failure: str) -> None:
    lost = httpx.ConnectError("directus unreachable")
    worker = Worker(world, monkeypatch, pipeline=Pipeline(), refund_error=lost if failure == "refund" else None)
    operation_id, kwargs = await _accepted(world)
    if failure == "ready_write":
        real_update = world.directus.update_item_if_version

        async def lose_ready_write(collection: str, item_id: str, data: Dict[str, Any], expected_version: int,
                                   **kwargs: Any):
            if data.get("state") == "ready":
                raise lost
            return await real_update(collection, item_id, data, expected_version, **kwargs)

        monkeypatch.setattr(world.directus, "update_item_if_version", lose_ready_write)
    else:
        async def unsealable(*_: Any, **__: Any) -> jobs.SealedResult:
            raise jobs.EnhanceJobError("vault unavailable")

        monkeypatch.setattr(jobs, "seal_result", unsealable)
    outcome = await worker.run(kwargs)
    assert outcome["error_code"] == "storage_failed"
    job = world.directus.job(operation_id)
    # Not left pending for 24 hours: failed now, charge outcome left for the sweep.
    assert (job["state"], job["billing_state"]) == ("failed", "charging")
    assert world.cache.events[-1][1]["event_for_client"] == "image_enhance_failed"
    assert set(world.s3.objects) == {SOURCE_KEY}
    assert len(worker.charges) == 1 and worker.refunds == []

    sweep = Worker(world, monkeypatch, pipeline=Pipeline())
    counts = await enhance_task.sweep_enhance_jobs(sweep.task, now=jobs.now_ts())
    assert counts["reconciled"] == 1 and counts["errors"] == 0
    assert [refund["event_id"] for refund in sweep.refunds] == [job["billing_event_id"]]
    assert world.directus.job(operation_id)["billing_state"] == "refunded"
