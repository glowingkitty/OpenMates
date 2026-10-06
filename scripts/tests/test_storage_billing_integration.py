# contract-test-file: infrastructure
"""Private selector and isolated profile guards for the real PG/S3 billing probe."""

import json
import hashlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from scripts.storage_billing_integration import (
    _assert_owner_metadata_hold, _billing_operation, _cleanup, _quote, load_selector,
    require_expiry_profile, require_isolated_profile,
)
from scripts import storage_billing_integration as fixture


SOURCE = "a" * 40
USER = str(uuid.uuid4())
PREFIX = f"ci-storage-billing/{uuid.uuid4()}"
PROFILE = {
    "OPENMATES_CI_ISOLATED": "1",
    "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
    "CHAT_MESSAGE_ARCHIVE_READS_ENABLED": "1",
    "S3_ENDPOINT_URL": "http://storage.ci.test:9000",
    "SERVER_ENVIRONMENT": "development",
    "BUILD_COMMIT_SHA": SOURCE,
    "INTERNAL_API_SHARED_TOKEN": "test-only-placeholder",
}


def selector() -> dict[str, str]:
    return {"schema": "storage-billing-selector-v1", "source_commit": SOURCE,
            "user_id": USER, "fixture_prefix": PREFIX}


def test_fixture_task_binds_to_local_celery_without_replacing_current_app(monkeypatch) -> None:
    calls = []
    class LocalApp:
        def __init__(self, name, **settings):
            assert name == "storage_billing_fixture"
            assert settings == {"broker": "memory://", "backend": "cache+memory://",
                                "set_as_current": False}
            calls.append("local_app")
    class Task:
        request_stack = None
        def bind(self, app):
            assert isinstance(app, LocalApp)
            self.app = app
            self.request_stack = [SimpleNamespace(id=None)]
            calls.append("bound")
        @property
        def request(self):
            return self.request_stack[-1]
    monkeypatch.setitem(sys.modules, "celery", SimpleNamespace(Celery=LocalApp))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.base_task",
                        SimpleNamespace(BaseServiceTask=Task))
    task = fixture._new_fixture_task()
    assert task.request.id is None
    assert calls == ["local_app", "bound"]


@pytest.mark.asyncio
async def test_fixture_initializes_only_core_and_storage(monkeypatch) -> None:
    calls = []
    class Task:
        secrets_manager = object()
        directus_service = object()
        async def initialize_core_services(self):
            calls.append("core")
        async def initialize_services(self):
            pytest.fail("Invoice and payment initialization must not run")
    task = Task()
    class S3:
        def __init__(self, *, secrets_manager, directus_service):
            assert secrets_manager is task.secrets_manager
            assert directus_service is task.directus_service
            calls.append("storage_constructor")
        async def initialize(self):
            calls.append("storage_initialize")
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.s3.service",
                        SimpleNamespace(S3UploadService=S3))
    await fixture._initialize_fixture_services(task)
    assert calls == ["core", "storage_constructor", "storage_initialize"]
    assert isinstance(task._s3_service, S3)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["prepare", "cleanup"])
async def test_fixture_closes_partial_initialization(monkeypatch, tmp_path, operation) -> None:
    closed = []
    class Task:
        async def cleanup_services(self):
            closed.append(True)
    monkeypatch.setattr(fixture, "_new_fixture_task", Task)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.chat_message_archive_service",
                        SimpleNamespace(ChatMessageArchiveService=object))
    async def failed_init(_task):
        raise fixture.FixtureInitializationError("s3_initialization_failed")
    monkeypatch.setattr(fixture, "_initialize_fixture_services", failed_init)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps({
        "schema": fixture.RECEIPT_SCHEMA, "source_commit": SOURCE,
        "selector_digest": hashlib.sha256(json.dumps(selector(), sort_keys=True).encode()).hexdigest(),
        "user_id": USER, "fixture_prefix": PREFIX,
    }))
    os.chmod(receipt_path, 0o600)
    with pytest.raises(fixture.FixtureInitializationError):
        await getattr(fixture, operation)(selector(), receipt_path)
    assert closed == [True]


@pytest.mark.parametrize("failure,marker", [
    (RuntimeError("secret-token /private/object " + USER), "prepare_failed"),
    (fixture.FixtureInitializationError("s3_initialization_failed"), "s3_initialization_failed"),
])
def test_fixture_main_emits_only_static_failure_marker(monkeypatch, capsys, failure, marker) -> None:
    monkeypatch.setattr(sys, "argv", ["fixture", "prepare", "--selector-file", "/unused/selector",
                                      "--receipt-file", "/unused/receipt"])
    monkeypatch.setattr(fixture, "require_isolated_profile", lambda _env: SOURCE)
    monkeypatch.setattr(fixture, "private_path", lambda _path: None)
    monkeypatch.setattr(fixture, "load_selector", lambda _path, _source: selector())
    cases = [(failure, marker)]
    if marker == "prepare_failed":
        cases.extend([
            (RuntimeError("storage_billing_page_not_verified"), "storage_billing_page_not_verified"),
            (RuntimeError("storage_billing_expiry_operation_failed:apply_storage_expiry"),
             "storage_billing_expiry_operation_failed_apply_storage_expiry"),
            (RuntimeError("storage_billing_page_not_verified " + USER), "prepare_failed"),
            (RuntimeError("storage_billing_expiry_operation_failed:" + USER), "prepare_failed"),
        ])
    for failure, expected in cases:
        async def failed_prepare(*_args):
            raise failure
        monkeypatch.setattr(fixture, "prepare", failed_prepare)
        with pytest.raises(SystemExit) as exited:
            fixture.main()
        assert exited.value.code == 1
        output = capsys.readouterr()
        assert output.out == ""
        assert output.err == "storage_billing_fixture_failed:" + expected + "\n"


def test_probe_requires_exact_isolated_stack_and_source() -> None:
    assert require_isolated_profile(PROFILE) == SOURCE
    for key, bad in (
        ("OPENMATES_CI_ISOLATED", "0"),
        ("OPENMATES_STORAGE_CAPACITY_FIXTURES", "false"),
        ("S3_ENDPOINT_URL", "https://storage.example.org"),
        ("SERVER_ENVIRONMENT", "production"),
        ("BUILD_COMMIT_SHA", "unknown"),
        ("INTERNAL_API_SHARED_TOKEN", ""),
    ):
        with pytest.raises(ValueError):
            require_isolated_profile({**PROFILE, key: bad})


def test_expiry_requires_logical_private_ci_namespace() -> None:
    logical = {**PROFILE, "STORAGE_LOGICAL_S3_BILLING_ENABLED": "1"}
    require_expiry_profile(logical, selector())
    for env, selection in (
        (PROFILE, selector()),
        ({**logical, "S3_ENDPOINT_URL": "https://real-storage.example.org"}, selector()),
        (logical, {**selector(), "fixture_prefix": "shared/personal"}),
        (logical, {**selector(), "source_commit": "b" * 40}),
    ):
        with pytest.raises(ValueError):
            require_expiry_profile(env, selection)


@pytest.mark.asyncio
async def test_expiry_operations_bind_owner_and_use_only_internal_token(monkeypatch) -> None:
    import hashlib
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-only-placeholder")

    class Directus:
        base_url = "http://directus.test"

        async def _make_api_request(self, method, url, *, headers, json):
            assert method == "POST" and url.endswith("/sub-chat-orchestration-transaction")
            assert headers == {"X-Internal-Service-Token": "test-only-placeholder"}
            assert json == {"operation": "freeze_storage_warning_units", "data": {
                "protocol_version": 1, "user_id": USER,
                "hashed_user_id": hashlib.sha256(USER.encode()).hexdigest(), "now_at": 123,
            }}
            return SimpleNamespace(status_code=200, json=lambda: {"data": {"held": True}})

    assert await _billing_operation(Directus(), "freeze_storage_warning_units", USER,
                                    now_at=123) == {"held": True}


def test_selector_requires_private_bounded_exact_source_and_disposable_prefix(tmp_path: Path) -> None:
    path = tmp_path / "selector.json"
    path.write_text(json.dumps(selector()), encoding="utf-8")
    os.chmod(path, 0o600)
    assert load_selector(path, SOURCE) == selector()
    os.chmod(path, 0o644)
    with pytest.raises(ValueError, match="not_private"):
        load_selector(path, SOURCE)
    os.chmod(path, 0o600)
    for invalid in (
        {**selector(), "source_commit": "b" * 40},
        {**selector(), "fixture_prefix": "shared/example"},
        {**selector(), "user_id": "not-a-uuid"},
        {**selector(), "extra": "field"},
    ):
        path.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(ValueError):
            load_selector(path, SOURCE)


@pytest.mark.asyncio
async def test_probe_quotes_exact_internal_policy_and_conflict(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-only-placeholder")

    class Directus:
        base_url = "http://directus.test"

        async def _make_api_request(self, method, url, *, headers, json):
            assert method == "POST" and url.endswith("/storage-usage-metering")
            assert headers == {"X-Internal-Service-Token": "test-only-placeholder"}
            if json["legacy_only"]:
                assert json["user_ids"] == [USER] and json["team_hashes"] == []
                return SimpleNamespace(status_code=200, json=lambda: {
                    "data": [{"complete": True, "total_bytes": 96}],
                })
            return SimpleNamespace(status_code=409, json=lambda: {
                "error": {"code": "storage_usage_incomplete"},
            })

    assert (await _quote(Directus(), user_id=USER, legacy_only=True))["total_bytes"] == 96
    assert await _quote(Directus(), user_id=USER, expected_status=409) is None


@pytest.mark.asyncio
async def test_owner_metadata_probe_restores_disposable_row_after_incomplete_quote(monkeypatch) -> None:
    patches = []
    quotes = []

    async def patch(_directus, collection, row_id, fields):
        patches.append((collection, row_id, fields))

    async def quote(_directus, **kwargs):
        quotes.append(kwargs)
        return None

    monkeypatch.setattr("scripts.storage_billing_integration._patch", patch)
    monkeypatch.setattr("scripts.storage_billing_integration._quote", quote)
    await _assert_owner_metadata_hold(
        object(), collection="chat_message_archive_pages", row_id="disposable-row",
        field="hashed_user_id", original="owner-hash", invalid="wrong-owner-hash", user_id=USER,
    )
    assert patches == [
        ("chat_message_archive_pages", "disposable-row", {"hashed_user_id": "wrong-owner-hash"}),
        ("chat_message_archive_pages", "disposable-row", {"hashed_user_id": "owner-hash"}),
    ]
    assert quotes == [{"user_id": USER, "team_hash": None, "expected_status": 409}]

    async def rejected_quote(_directus, **_kwargs):
        raise RuntimeError("probe_quote_rejected")

    monkeypatch.setattr("scripts.storage_billing_integration._quote", rejected_quote)
    with pytest.raises(RuntimeError, match="probe_quote_rejected"):
        await _assert_owner_metadata_hold(
            object(), collection="chat_message_archive_segments", row_id="disposable-row",
            field="hashed_team_id", original="team-hash", invalid="wrong-team-hash",
            team_hash="team-hash",
        )
    assert patches[-1] == ("chat_message_archive_segments", "disposable-row",
                           {"hashed_team_id": "team-hash"})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["rejected", "unexpected_status", "mutated_row", "changed_quote"])
async def test_null_owner_probe_requires_constraint_rejection_and_unchanged_row_and_quote(monkeypatch, case):
    calls = []
    baseline = {"id": "disposable-row", "hashed_user_id": "owner-hash", "hashed_team_id": None}
    class Directus:
        base_url = "http://directus.test"
        async def ensure_auth_token(self, **kwargs):
            return "test-only-placeholder"
        async def get_items(self, collection, *, params, **kwargs):
            assert collection == "chat_message_archive_pages"
            assert params["filter"] == {"id": {"_eq": "disposable-row"}}
            assert kwargs == {"admin_required": True, "no_cache": True, "raise_on_error": True}
            reads = calls.count("read")
            calls.append("read")
            return [{**baseline, "hashed_user_id": None}] if reads and case == "mutated_row" else [dict(baseline)]
        async def _make_api_request(self, method, url, *, headers, json):
            assert method == "PATCH" and url.endswith("/chat_message_archive_pages/disposable-row")
            assert json == {"hashed_user_id": None}
            calls.append("patch")
            return SimpleNamespace(status_code=200 if case == "unexpected_status" else 500)
    async def quote(_directus, **kwargs):
        assert kwargs == {"user_id": USER, "team_hash": None}
        count = calls.count("quote")
        calls.append("quote")
        return {"complete": True, "total_bytes": 99 if count and case == "changed_quote" else 96,
                "categories": {"legacy_uploads": 96}, "measurement_at": count}
    monkeypatch.setattr(fixture, "_quote", quote)
    if case == "rejected":
        await fixture._assert_owner_metadata_hold(Directus(), collection="chat_message_archive_pages",
            row_id="disposable-row", field="hashed_user_id", original="owner-hash", invalid=None, user_id=USER)
        assert calls == ["read", "quote", "patch", "read", "quote"]
    else:
        expected = {"unexpected_status": "fixture_patch_failed", "mutated_row": "constraint_row_changed",
                    "changed_quote": "constraint_quote_changed"}[case]
        with pytest.raises(RuntimeError, match=expected):
            await fixture._assert_owner_metadata_hold(Directus(), collection="chat_message_archive_pages",
                row_id="disposable-row", field="hashed_user_id", original="owner-hash", invalid=None, user_id=USER)


@pytest.mark.asyncio
async def test_cleanup_reverses_owned_rows_and_skips_already_pruned_messages() -> None:
    deleted: list[tuple[str, str]] = []

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            assert kwargs["admin_required"] is True and kwargs["raise_on_error"] is True
            if collection in {"chat_message_archive_segments", "chat_message_archive_pages"}:
                return []
            if collection == "messages":
                return []  # The real isolated activation already pruned it.
            return [{"id": params["filter"]["id"]["_eq"]}]

        async def delete_item(self, collection, row_id, **kwargs):
            deleted.append((collection, row_id))
            return True

    class S3:
        async def delete_file(self, bucket, key):
            deleted.append((bucket, key))

    receipt = {"created": [("chats", USER), ("messages", "message-1"),
                           ("upload_files", "upload-1")],
               "objects": [["chatfiles", "ci-storage-billing/file.enc"]]}
    assert (await _cleanup(Directus(), S3(), receipt))["cleaned"] is True
    assert deleted == [("upload_files", "upload-1"), ("chats", USER),
                       ("chatfiles", "ci-storage-billing/file.enc")]


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_team_contact_bootstrap_preserves_real_crypto_guard(monkeypatch, existing) -> None:
    import base64
    email = "ci-contact-fixture@example.com"
    hashed = base64.b64encode(hashlib.sha256(email.encode()).digest()).decode()
    user = {"id": USER, "status": "active", "hashed_email": hashed}
    row = {"id": "contact", "user_id": USER, "purpose": "account_lifecycle",
           "hashed_email": hashed, "encrypted_email_address": "vault-encrypted-test-envelope",
           "verified_at": "2026-10-06T00:00:00Z"}
    rows = [row] if existing else []
    calls = []
    class Directus:
        async def get_items(self, collection, *, params, **kwargs):
            assert collection == "account_contact_emails"
            assert params["filter[user_id][_eq]"] == USER
            assert kwargs == {"admin_required": True, "no_cache": True, "raise_on_error": True}
            return list(rows)
    class Encryption:
        async def decrypt_account_contact_email(self, envelope):
            assert envelope == row["encrypted_email_address"]
            calls.append("decrypt")
            return email
    task = SimpleNamespace(directus_service=Directus(), encryption_service=Encryption())
    async def store(directus, encryption, **fields):
        assert directus is task.directus_service and encryption is task.encryption_service
        assert fields["user_id"] == USER and fields["hashed_email"] == hashed
        assert fields["email"] == email and fields["verified_at"]
        calls.append("vault_store")
        rows.append(row)
        return True
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.auth_routes.auth_utils",
                        SimpleNamespace(_account_contact_email_id=lambda user_id: "contact",
                                        store_account_lifecycle_contact_email=store))
    for key, value in {**PROFILE, "STORAGE_LOGICAL_S3_BILLING_ENABLED": "1",
                       "TEAM_STORAGE_BILLING_ENABLED": "1",
                       "OPENMATES_TEST_ACCOUNT_CI_0_EMAIL": email}.items():
        monkeypatch.setenv(key, value)
    created = []
    await fixture._ensure_team_owner_contact(task, selector(), user, created)
    assert calls == (["decrypt"] if existing else ["vault_store", "decrypt"])
    assert created == ([] if existing else [("account_contact_emails", "contact")])


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["source", "production", "profile", "email", "duplicate_email",
                                      "owner", "status", "hash", "purpose", "unverified", "ciphertext",
                                      "contact_hash", "contact_owner", "duplicate_contact", "decrypt"])
async def test_team_contact_refuses_unproven_identity_without_overwrite(monkeypatch, invalid) -> None:
    import base64
    email = "ci-contact-fixture@example.com"
    hashed = base64.b64encode(hashlib.sha256(email.encode()).digest()).decode()
    environ = {**PROFILE, "STORAGE_LOGICAL_S3_BILLING_ENABLED": "1",
               "TEAM_STORAGE_BILLING_ENABLED": "1", "OPENMATES_TEST_ACCOUNT_CI_0_EMAIL": email}
    selected = selector()
    user = {"id": USER, "status": "active", "hashed_email": hashed}
    row = {"id": "contact", "user_id": USER, "purpose": "account_lifecycle",
           "hashed_email": hashed, "encrypted_email_address": "vault-envelope", "verified_at": "verified"}
    if invalid == "source":
        selected["source_commit"] = "b" * 40
    if invalid == "production":
        environ["SERVER_ENVIRONMENT"] = "production"
    if invalid == "profile":
        environ["TEAM_STORAGE_BILLING_ENABLED"] = "0"
    if invalid == "email":
        environ["OPENMATES_TEST_ACCOUNT_CI_0_EMAIL"] = "unknown@example.com"
    if invalid == "duplicate_email":
        environ["OPENMATES_TEST_ACCOUNT_CI_1_EMAIL"] = email
    if invalid == "owner":
        user["id"] = str(uuid.uuid4())
    if invalid == "status":
        user["status"] = "suspended"
    if invalid == "hash":
        user["hashed_email"] = "wrong"
    if invalid == "purpose":
        row["purpose"] = "unknown"
    if invalid == "unverified":
        row["verified_at"] = None
    if invalid == "ciphertext":
        row["encrypted_email_address"] = None
    if invalid == "contact_hash":
        row["hashed_email"] = "wrong"
    if invalid == "contact_owner":
        row["user_id"] = str(uuid.uuid4())
    class Directus:
        async def get_items(self, *args, **kwargs):
            return [row, row] if invalid == "duplicate_contact" else [row]
    class Encryption:
        async def decrypt_account_contact_email(self, envelope):
            return "ci-wrong@example.com" if invalid == "decrypt" else email
    task = SimpleNamespace(directus_service=Directus(), encryption_service=Encryption())
    async def forbidden_store(*args, **kwargs):
        pytest.fail("Existing or unproven contacts must never be overwritten")
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.auth_routes.auth_utils",
                        SimpleNamespace(store_account_lifecycle_contact_email=forbidden_store))
    for key, value in environ.items():
        monkeypatch.setenv(key, value)
    created = []
    with pytest.raises((RuntimeError, ValueError), match="storage_billing_"):
        await fixture._ensure_team_owner_contact(task, selected, user, created)
    assert created == []


@pytest.mark.parametrize("logical,team,source", [("0", "0", SOURCE), ("1", "1", SOURCE),
                                                ("0", "1", SOURCE), ("1", "0", SOURCE),
                                                ("0", None, SOURCE), ("0", "0", "b" * 40)])
def test_team_fixture_profile_requires_exact_source_and_flags(logical, team, source):
    environ = {**PROFILE, "STORAGE_LOGICAL_S3_BILLING_ENABLED": logical,
               "TEAM_STORAGE_BILLING_ENABLED": team, "OPENMATES_DEPLOYMENT_MODE": "self_host",
               "OPENMATES_CLOUD_OVERLAY_ENABLED": "false", "OPENMATES_CLOUD_OVERLAY_PACKAGE": ""}
    selected = {**selector(), "source_commit": source}
    if logical == team and source == SOURCE:
        assert fixture.require_team_fixture_profile(environ, selected) is (logical == "1")
    else:
        with pytest.raises(ValueError, match="storage_billing_team_fixture_profile_mismatch"):
            fixture.require_team_fixture_profile(environ, selected)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,rows", [(409, "team_storage_billing_not_ready", []),
    (200, "team_storage_billing_not_ready", []), (409, "unrelated_error", []),
    (409, "team_storage_billing_not_ready", [{"id": "unexpected"}])])
async def test_disabled_team_claim_requires_exact_guard_and_no_archive_rows(monkeypatch, status, code, rows):
    for key, value in {**PROFILE, "STORAGE_LOGICAL_S3_BILLING_ENABLED": "0",
                       "TEAM_STORAGE_BILLING_ENABLED": "0", "OPENMATES_DEPLOYMENT_MODE": "self_host",
                       "OPENMATES_CLOUD_OVERLAY_ENABLED": "false", "OPENMATES_CLOUD_OVERLAY_PACKAGE": ""}.items():
        monkeypatch.setenv(key, value)
    writes = []
    async def write(directus, collection, row, created):
        writes.append(collection)
        created.append((collection, row["id"]))
        return row
    monkeypatch.setattr(fixture, "_write", write)
    class Directus:
        base_url = "http://cms:8055"
        async def _make_api_request(self, method, url, **kwargs):
            assert method == "POST" and kwargs["json"]["operation"] == "claim_segment"
            assert kwargs["json"]["data"]["checkpoint_id"]
            return SimpleNamespace(status_code=status, json=lambda: {"error": {"code": code}})
        async def get_items(self, collection, **kwargs):
            assert collection in ("chat_message_archive_segments", "chat_message_archive_pages")
            return rows
    class Archive:
        async def copy_segment(self, **kwargs):
            pytest.fail("A disabled Team claim must never copy S3 content")
    call = fixture._archive_page(Directus(), Archive(), owner_hash=None,
                                team_hash="a" * 64, created=[], reject_team_claim=True)
    if status == 409 and code == "team_storage_billing_not_ready" and not rows:
        result = await call
        assert result["claim_rejected"] is True and "page" not in result
    else:
        with pytest.raises(RuntimeError, match="storage_billing_team_disabled_claim_not_rejected"):
            await call
    assert writes == ["chats", "messages", "messages", "messages", "chat_compression_checkpoints"]


@pytest.mark.parametrize("key,value", [("OPENMATES_DEPLOYMENT_MODE", "official_cloud"),
    ("OPENMATES_DEPLOYMENT_MODE", "production"), ("OPENMATES_CLOUD_OVERLAY_ENABLED", "true"),
    ("OPENMATES_CLOUD_OVERLAY_PACKAGE", "OpenMatesCloud")])
def test_disabled_team_fixture_requires_valid_api_self_host_mode(key, value):
    environ = {**PROFILE, "STORAGE_LOGICAL_S3_BILLING_ENABLED": "0", "TEAM_STORAGE_BILLING_ENABLED": "0",
               "OPENMATES_DEPLOYMENT_MODE": "self_host", "OPENMATES_CLOUD_OVERLAY_ENABLED": "false",
               "OPENMATES_CLOUD_OVERLAY_PACKAGE": "", key: value}
    with pytest.raises(ValueError, match="storage_billing_team_fixture_mode_mismatch"):
        fixture.require_team_fixture_profile(environ, selector())
