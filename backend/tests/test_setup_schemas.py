"""
backend/tests/test_setup_schemas.py

Regression tests for Directus YAML schema setup helpers. The tests keep the
collection bootstrap contract deterministic without a running Directus instance,
especially for singleton collections that store app-generated IDs in string
primary-key columns.
"""

from __future__ import annotations

# contract-test-file: infrastructure

import importlib
import importlib.util
import ast
import sys
from types import ModuleType
from pathlib import Path
from typing import Any

import yaml
import pytest


class FakeResponse:
    def __init__(self, status_code: int, data: dict[str, Any] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.text or f"HTTP {self.status_code}")


def load_setup_schemas_module():
    if "requests" not in sys.modules and importlib.util.find_spec("requests") is None:
        requests_stub = ModuleType("requests")

        def unexpected_request(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("Setup schema unit tests must stub HTTP requests")

        requests_stub.get = unexpected_request
        requests_stub.post = unexpected_request
        requests_stub.patch = unexpected_request
        sys.modules["requests"] = requests_stub
    if "dotenv" not in sys.modules and importlib.util.find_spec("dotenv") is None:
        dotenv_stub = ModuleType("dotenv")
        dotenv_stub.load_dotenv = lambda *_args, **_kwargs: None
        sys.modules["dotenv"] = dotenv_stub
    return importlib.import_module("backend.core.directus.setup.setup_schemas")


def test_dev_cms_setup_mounts_every_default_sql_migration_read_only() -> None:
    """The dev setup image copies SQL to /usr/src/app, so defaults need mounts."""
    backend_dir = Path(__file__).resolve().parents[1]
    setup_source = (backend_dir / "core/directus/setup/setup_schemas.py").read_text()
    compose_file = backend_dir / "core/docker-compose.yml"
    compose = yaml.safe_load(compose_file.read_text())
    mounts = compose["services"]["cms-setup"]["volumes"]

    defaults = []
    for node in ast.parse(setup_source).body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if not any(isinstance(target, ast.Name) and target.id.endswith("_MIGRATION_PATH")
                   for target in node.targets):
            continue
        if len(node.value.args) < 2:
            continue
        default = ast.literal_eval(node.value.args[1])
        if default.startswith("/usr/src/app/migrations/") and default.endswith(".sql"):
            defaults.append(default)

    assert defaults
    for default in defaults:
        basename = Path(default).name
        expected = f"./directus/setup/{basename}:{default}:ro"
        assert mounts.count(expected) == 1, f"cms-setup migration mount missing or not read-only: {basename}"
        assert (compose_file.parent / "directus/setup" / basename).is_file()


def _accountability_schema_fixture(tmp_path, names):
    for name in names:
        (tmp_path / f"{name}.yml").write_text(
            yaml.safe_dump({name: {"type": "collection", "meta": {"accountability": None}}}),
            encoding="utf-8",
        )


def test_accountability_only_updates_existing_metadata_and_verifies_readback(monkeypatch, tmp_path) -> None:
    setup = load_setup_schemas_module()
    names = sorted(setup.REDUCED_ACCOUNTABILITY)
    _accountability_schema_fixture(tmp_path, names)
    state = {name: "all" for name in names}
    events = []

    def get(url, **kwargs):
        assert kwargs["timeout"] == 15
        name = url.rsplit("/", 1)[-1]
        events.append(("get", name))
        return FakeResponse(200, {"data": {"collection": name, "meta": {"accountability": state[name]}}})

    def patch(url, **kwargs):
        name = url.rsplit("/", 1)[-1]
        assert kwargs["json"] == {"meta": {"accountability": None}}
        events.append(("patch", name))
        state[name] = None
        return FakeResponse(200)

    monkeypatch.setattr(setup, "SCHEMAS_DIR", str(tmp_path))
    monkeypatch.setattr(setup, "wait_for_directus", lambda: events.append(("wait", None)))
    monkeypatch.setattr(setup, "login", lambda: "test-token")
    monkeypatch.setattr(setup.requests, "get", get)
    monkeypatch.setattr(setup.requests, "patch", patch)
    monkeypatch.setattr(setup.requests, "post", lambda *_args, **_kwargs: pytest.fail("item or schema creation"))

    setup.reconcile_accountability_only()
    first_patch = next(i for i, event in enumerate(events) if event[0] == "patch")
    assert {name for action, name in events[:first_patch] if action == "get"} == set(names)
    assert [name for action, name in events if action == "patch"] == names
    assert all(value is None for value in state.values())
    events.clear()
    setup.reconcile_accountability_only()
    assert not any(action == "patch" for action, _ in events)


def test_accountability_only_resolves_multiple_reviewed_collections_in_one_file(monkeypatch, tmp_path) -> None:
    setup = load_setup_schemas_module()
    names = sorted(setup.REDUCED_ACCOUNTABILITY)
    _accountability_schema_fixture(tmp_path, names)
    bundled = {name: {"type": "collection", "meta": {"accountability": None}} for name in names[:2]}
    for name in names[:2]:
        (tmp_path / f"{name}.yml").unlink()
    (tmp_path / "archive_collections.yml").write_text(yaml.safe_dump(bundled), encoding="utf-8")
    calls = []
    monkeypatch.setattr(setup, "SCHEMAS_DIR", str(tmp_path))
    monkeypatch.setattr(setup, "wait_for_directus", lambda: None)
    monkeypatch.setattr(setup, "login", lambda: "test-token")
    monkeypatch.setattr(setup.requests, "get", lambda url, **_kwargs: FakeResponse(200, {
        "data": {"collection": url.rsplit("/", 1)[-1], "meta": {"accountability": None}},
    }))
    monkeypatch.setattr(setup.requests, "patch", lambda *_args, **_kwargs: calls.append("patch"))
    setup.reconcile_accountability_only()
    assert calls == []


def test_accountability_only_duplicate_reviewed_collection_fails_before_network(monkeypatch, tmp_path) -> None:
    setup = load_setup_schemas_module()
    names = sorted(setup.REDUCED_ACCOUNTABILITY)
    _accountability_schema_fixture(tmp_path, names)
    (tmp_path / "extra.yml").write_text(yaml.safe_dump({
        names[0]: {"type": "collection", "meta": {"accountability": None}},
    }), encoding="utf-8")
    monkeypatch.setattr(setup, "SCHEMAS_DIR", str(tmp_path))
    monkeypatch.setattr(setup, "wait_for_directus", lambda: pytest.fail("network before duplicate validation"))
    with pytest.raises(RuntimeError, match="Duplicate reviewed accountability collection"):
        setup.reconcile_accountability_only()

    (tmp_path / "extra.yml").unlink()
    (tmp_path / f"{names[0]}.yml").write_text(
        f"{names[0]}:\n  meta:\n    accountability: null\n"
        f"{names[0]}:\n  meta:\n    accountability: null\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="Duplicate reviewed accountability collection"):
        setup.reconcile_accountability_only()


def test_accountability_only_missing_readback_field_fails_closed(monkeypatch, tmp_path) -> None:
    setup = load_setup_schemas_module()
    names = sorted(setup.REDUCED_ACCOUNTABILITY)
    _accountability_schema_fixture(tmp_path, names)
    reads = {name: 0 for name in names}
    patches = []

    def get(url, **_kwargs):
        name = url.rsplit("/", 1)[-1]
        reads[name] += 1
        meta = {"accountability": "all"} if reads[name] == 1 else {}
        return FakeResponse(200, {"data": {"collection": name, "meta": meta}})

    monkeypatch.setattr(setup, "SCHEMAS_DIR", str(tmp_path))
    monkeypatch.setattr(setup, "wait_for_directus", lambda: None)
    monkeypatch.setattr(setup, "login", lambda: "test-token")
    monkeypatch.setattr(setup.requests, "get", get)
    monkeypatch.setattr(setup.requests, "patch", lambda url, **_kwargs: patches.append(url) or FakeResponse(200))
    with pytest.raises(RuntimeError, match="metadata invalid"):
        setup.reconcile_accountability_only()
    assert len(patches) == 1


def test_accountability_only_missing_schema_or_collection_fails_before_write(monkeypatch, tmp_path) -> None:
    setup = load_setup_schemas_module()
    names = sorted(setup.REDUCED_ACCOUNTABILITY)
    _accountability_schema_fixture(tmp_path, names[:-1])
    monkeypatch.setattr(setup, "SCHEMAS_DIR", str(tmp_path))
    monkeypatch.setattr(setup, "wait_for_directus", lambda: pytest.fail("network before schema preflight"))
    with pytest.raises(RuntimeError, match="schema missing"):
        setup.reconcile_accountability_only()

    _accountability_schema_fixture(tmp_path, names[-1:])
    monkeypatch.setattr(setup, "wait_for_directus", lambda: None)
    monkeypatch.setattr(setup, "login", lambda: "test-token")
    def get(url, **_kwargs):
        name = url.rsplit("/", 1)[-1]
        return FakeResponse(404 if name == names[-1] else 200,
                            {"data": {"collection": name, "meta": {"accountability": "all"}}})
    monkeypatch.setattr(setup.requests, "get", get)
    monkeypatch.setattr(setup.requests, "patch", lambda *_args, **_kwargs: pytest.fail("patch before full preflight"))
    with pytest.raises(RuntimeError, match="HTTP 404"):
        setup.reconcile_accountability_only()


def test_accountability_only_rejects_unreviewed_schema_and_failed_readback(monkeypatch, tmp_path) -> None:
    setup = load_setup_schemas_module()
    names = sorted(setup.REDUCED_ACCOUNTABILITY)
    _accountability_schema_fixture(tmp_path, names)
    monkeypatch.setattr(setup, "SCHEMAS_DIR", str(tmp_path))
    (tmp_path / f"{names[0]}.yml").write_text(
        yaml.safe_dump({names[0]: {"type": "collection", "meta": {"accountability": "all"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup, "wait_for_directus", lambda: pytest.fail("network before schema validation"))
    with pytest.raises(ValueError, match="Unreviewed"):
        setup.reconcile_accountability_only()

    _accountability_schema_fixture(tmp_path, names[:1])
    monkeypatch.setattr(setup, "wait_for_directus", lambda: None)
    monkeypatch.setattr(setup, "login", lambda: "test-token")
    monkeypatch.setattr(setup.requests, "get", lambda url, **_kwargs: FakeResponse(200, {
        "data": {"collection": url.rsplit("/", 1)[-1], "meta": {"accountability": "all"}},
    }))
    monkeypatch.setattr(setup.requests, "patch", lambda *_args, **_kwargs: FakeResponse(200))
    with pytest.raises(RuntimeError, match="readback mismatch"):
        setup.reconcile_accountability_only()


def test_ci_fast_schema_setup_reduces_only_defensive_settle(monkeypatch) -> None:
    setup_schemas = load_setup_schemas_module()
    delays = []
    monkeypatch.setattr(setup_schemas.time, "sleep", delays.append)
    monkeypatch.setattr(setup_schemas, "CI_FAST_SCHEMA_SETUP", True)
    setup_schemas.settle(2)
    assert delays == [0.01]
    monkeypatch.setattr(setup_schemas, "CI_FAST_SCHEMA_SETUP", False)
    setup_schemas.settle(2)
    assert delays[-1] == 2


def test_prepared_schema_rotates_bootstrap_password_and_verifies_contract(monkeypatch) -> None:
    setup_schemas = load_setup_schemas_module()
    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(setup_schemas, "CI_PREPARED_SCHEMA_ADMIN_PASSWORD", "bundle-password")
    monkeypatch.setattr(setup_schemas, "ADMIN_PASSWORD", "fresh-job-password")
    monkeypatch.setattr(setup_schemas, "wait_for_directus", lambda: calls.append(("wait", None)))
    monkeypatch.setattr(
        setup_schemas,
        "login",
        lambda password=None: calls.append(("login", password)) or "token",
    )
    monkeypatch.setattr(
        setup_schemas,
        "collection_exists",
        lambda token, collection: calls.append(("collection", collection)) or True,
    )
    monkeypatch.setattr(
        setup_schemas.requests,
        "patch",
        lambda url, **kwargs: calls.append(("patch", kwargs["json"]))
        or FakeResponse(200),
    )
    monkeypatch.setattr(
        setup_schemas,
        "verify_login_rejected",
        lambda password: calls.append(("rejected", password)),
    )
    for name in (
        "verify_chat_recovery_endpoint",
        "verify_sub_chat_orchestration_endpoint",
        "verify_anonymous_usage_endpoint",
    ):
        monkeypatch.setattr(
            setup_schemas, name, lambda name=name: calls.append((name, None))
        )

    setup_schemas.activate_prepared_schema()

    assert ("login", "bundle-password") in calls
    assert ("patch", {"password": "fresh-job-password"}) in calls
    assert ("login", None) in calls
    assert ("rejected", "bundle-password") in calls
    assert {value for kind, value in calls if kind == "collection"} == {
        "invite_codes",
        "chats",
        "directus_users",
    }


def test_prepared_schema_requires_old_bootstrap_login_to_be_rejected(monkeypatch) -> None:
    setup_schemas = load_setup_schemas_module()
    monkeypatch.setattr(
        setup_schemas.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(401),
    )
    setup_schemas.verify_login_rejected("retired-password")
    monkeypatch.setattr(
        setup_schemas.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(200),
    )
    with pytest.raises(RuntimeError, match="remained usable"):
        setup_schemas.verify_login_rejected("retired-password")


def test_create_collection_preserves_string_primary_key(monkeypatch, tmp_path: Path) -> None:
    setup_schemas = load_setup_schemas_module()
    schema_file = tmp_path / "free_testing_credits_budget.yml"
    schema_file.write_text(
        yaml.safe_dump(
            {
                "free_testing_credits_budget": {
                    "type": "collection",
                    "fields": {
                        "id": {"type": "string", "length": 64, "primary": True},
                        "enabled": {"type": "boolean", "default": False},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    posted_payloads: list[dict[str, Any]] = []

    monkeypatch.setattr(setup_schemas, "collection_exists", lambda token, collection_name: False)
    monkeypatch.setattr(setup_schemas, "create_or_update_field", lambda *args, **kwargs: False)

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        posted_payloads.append(json)
        return FakeResponse(200)

    monkeypatch.setattr(setup_schemas.requests, "post", fake_post)
    monkeypatch.setattr(setup_schemas.time, "sleep", lambda seconds: None)

    success, newly_created = setup_schemas.create_collection("token", str(schema_file))

    assert success is True
    assert newly_created is True
    primary_field = posted_payloads[0]["fields"][0]
    assert primary_field["field"] == "id"
    assert primary_field["type"] == "string"
    assert primary_field["meta"]["special"] == []
    assert primary_field["schema"]["data_type"] == "varchar(64)"


def test_create_collection_processes_all_top_level_collections(monkeypatch, tmp_path: Path) -> None:
    setup_schemas = load_setup_schemas_module()
    schema_file = tmp_path / "multi_collection.yml"
    schema_file.write_text(
        yaml.safe_dump(
            {
                "user_tasks": {
                    "type": "collection",
                    "fields": {"encrypted_title": {"type": "text"}},
                },
                "user_task_key_wrappers": {
                    "type": "collection",
                    "fields": {"encrypted_task_key": {"type": "text"}},
                },
            }
        ),
        encoding="utf-8",
    )
    posted_collections: list[str] = []

    monkeypatch.setattr(setup_schemas, "collection_exists", lambda token, collection_name: False)
    monkeypatch.setattr(setup_schemas, "create_or_update_field", lambda *args, **kwargs: False)

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        posted_collections.append(json["collection"])
        return FakeResponse(200)

    monkeypatch.setattr(setup_schemas.requests, "post", fake_post)
    monkeypatch.setattr(setup_schemas.time, "sleep", lambda seconds: None)

    success, newly_created = setup_schemas.create_collection("token", str(schema_file))

    assert success is True
    assert newly_created is True
    assert set(posted_collections) == {"user_tasks", "user_task_key_wrappers"}


def test_reviewed_accountability_is_applied_on_creation_and_reconciled_once(monkeypatch) -> None:
    setup = load_setup_schemas_module()
    config = {"type": "collection", "meta": {"accountability": None}, "fields": {}}
    posted = []
    patched = []
    state = {"exists": False, "accountability": "all"}

    monkeypatch.setattr(setup, "collection_exists", lambda *_: state["exists"])
    monkeypatch.setattr(setup, "settle", lambda *_: None)
    monkeypatch.setattr(setup.requests, "post", lambda url, **kwargs: posted.append(kwargs["json"]) or FakeResponse(200))

    def fake_get(url, **kwargs):
        return FakeResponse(200, {"data": {"meta": {"accountability": state["accountability"], "note": "keep"}}})

    def fake_patch(url, **kwargs):
        patched.append(kwargs["json"])
        state["accountability"] = kwargs["json"]["meta"]["accountability"]
        return FakeResponse(200)

    monkeypatch.setattr(setup.requests, "get", fake_get)
    monkeypatch.setattr(setup.requests, "patch", fake_patch)
    assert setup.create_collection_from_config("token", "messages", config) == (True, True)
    assert posted[0]["meta"]["accountability"] is None

    state["exists"] = True
    assert setup.create_collection_from_config("token", "messages", config) == (True, False)
    assert patched == [{"meta": {"accountability": None}}]
    assert setup.create_collection_from_config("token", "messages", config) == (True, False)
    assert len(patched) == 1


def test_accountability_reconciliation_rejects_unreviewed_and_failed_updates(monkeypatch) -> None:
    setup = load_setup_schemas_module()
    monkeypatch.setattr(setup, "collection_exists", lambda *_: True)
    config = {"meta": {"accountability": None}, "fields": {}}
    assert setup.create_collection_from_config("token", "invoices", config) == (False, False)

    monkeypatch.setattr(
        setup.requests, "get",
        lambda *args, **kwargs: FakeResponse(200, {"data": {"meta": {"accountability": "all"}}}),
    )
    monkeypatch.setattr(setup.requests, "patch", lambda *args, **kwargs: FakeResponse(403, text="denied"))
    assert setup.create_collection_from_config("token", "chats", config) == (False, False)


def test_accountability_schema_matrix_is_explicit() -> None:
    from backend.core.directus.setup.accountability_policy import REDUCED_ACCOUNTABILITY

    schemas = Path(__file__).parents[1] / "core/directus/schemas"
    declared = {}
    for path in schemas.glob("*.yml"):
        for name, config in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).items():
            if "accountability" in (config.get("meta") or {}):
                declared[name] = config["meta"]["accountability"]
    assert declared == REDUCED_ACCOUNTABILITY
    assert declared["embed_diffs"] is None
    assert "directus_users" not in declared


def test_storage_query_indexes_are_applied_and_verified(monkeypatch, tmp_path: Path) -> None:
    setup = load_setup_schemas_module()
    migration = tmp_path / "query.sql"
    migration.write_text("CREATE INDEX IF NOT EXISTS example_idx ON example(id);", encoding="utf-8")
    executed = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchall(self):
            return [(name,) for name in setup.STORAGE_QUERY_INDEXES]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(setup, "STORAGE_QUERY_MIGRATION_PATH", str(migration))
    monkeypatch.setattr(setup, "connect_database", FakeConnection)
    setup.apply_and_verify_storage_query_indexes()
    assert executed[0][0] == migration.read_text(encoding="utf-8")
    assert executed[1][1] == (list(setup.STORAGE_QUERY_INDEXES),)


def test_chat_message_archive_indexes_are_applied_and_verified(monkeypatch, tmp_path: Path) -> None:
    setup = load_setup_schemas_module()
    migration = tmp_path / "archive.sql"
    migration.write_text("CREATE INDEX example_idx ON example(id);", encoding="utf-8")
    executed = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchall(self):
            return [(name,) for name in setup.CHAT_MESSAGE_ARCHIVE_INDEXES]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(setup, "CHAT_MESSAGE_ARCHIVE_MIGRATION_PATH", str(migration))
    monkeypatch.setattr(setup, "connect_database", FakeConnection)
    setup.apply_and_verify_chat_message_archive_indexes()
    assert executed[0][0] == migration.read_text(encoding="utf-8")
    assert executed[1][1] == (list(setup.CHAT_MESSAGE_ARCHIVE_INDEXES),)


def test_chat_recovery_output_indexes_are_applied_and_verified(monkeypatch, tmp_path: Path) -> None:
    setup = load_setup_schemas_module()
    migration = tmp_path / "recovery_outputs.sql"
    migration.write_text("CREATE INDEX example_idx ON example(id);", encoding="utf-8")
    executed = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchall(self):
            return [(name,) for name in setup.CHAT_RECOVERY_OUTPUTS_INDEXES]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(setup, "CHAT_RECOVERY_OUTPUTS_MIGRATION_PATH", str(migration))
    monkeypatch.setattr(setup, "connect_database", FakeConnection)
    setup.apply_and_verify_chat_recovery_outputs_indexes()
    assert executed[0][0] == migration.read_text(encoding="utf-8")
    assert executed[1][1] == (list(setup.CHAT_RECOVERY_OUTPUTS_INDEXES),)


def test_repair_primary_field_metadata_removes_stale_uuid_special(monkeypatch) -> None:
    setup_schemas = load_setup_schemas_module()
    patched_payloads: list[dict[str, Any]] = []

    def fake_get(url: str, headers: dict[str, str]) -> FakeResponse:
        return FakeResponse(
            200,
            {
                "data": {
                    "type": "uuid",
                    "meta": {
                        "hidden": False,
                        "readonly": False,
                        "interface": "input",
                        "special": ["uuid"],
                    },
                }
            },
        )

    def fake_patch(url: str, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        patched_payloads.append(json)
        return FakeResponse(200)

    monkeypatch.setattr(setup_schemas.requests, "get", fake_get)
    monkeypatch.setattr(setup_schemas.requests, "patch", fake_patch)

    setup_schemas.repair_primary_field_metadata(
        "token",
        "free_testing_credits_budget",
        "id",
        {"type": "string", "length": 64, "primary": True},
    )

    assert patched_payloads == [
        {
            "type": "string",
            "meta": {
                "hidden": False,
                "readonly": False,
                "interface": "input",
                "special": [],
            },
        }
    ]


def test_ensure_backend_collection_permissions_creates_missing_crud(monkeypatch) -> None:
    setup_schemas = load_setup_schemas_module()
    posted_payloads: list[dict[str, Any]] = []

    def fake_get(url: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> FakeResponse:
        if url.endswith("/users/me"):
            return FakeResponse(200, {"data": {"role": "role-api"}})
        if url.endswith("/access"):
            return FakeResponse(200, {"data": [{"policy": "policy-api"}]})
        if url.endswith("/permissions"):
            return FakeResponse(200, {"data": []})
        raise AssertionError(f"Unexpected GET {url}")

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        assert url.endswith("/permissions")
        posted_payloads.append(json)
        return FakeResponse(200, {"data": json})

    monkeypatch.setattr(setup_schemas.requests, "get", fake_get)
    monkeypatch.setattr(setup_schemas.requests, "post", fake_post)

    assert setup_schemas.ensure_backend_collection_permissions("token") is True

    actions_by_collection: dict[str, set[str]] = {}
    for payload in posted_payloads:
        actions_by_collection.setdefault(payload["collection"], set()).add(payload["action"])
        assert payload["policy"] == "policy-api"
        assert payload["permissions"] == {}
        assert payload["validation"] is None
        assert payload["presets"] is None
        assert payload["fields"] == ["*"]

    assert actions_by_collection == {
        "account_export_jobs": {"create", "read", "update", "delete"},
        "account_export_parts": {"create", "read", "update", "delete"},
        "anonymous_free_usage_budget": {"create", "read", "update", "delete"},
        "anonymous_free_usage_identity_daily": {"create", "read", "update", "delete"},
        "anonymous_free_usage_reservations": {"create", "read", "update", "delete"},
        "free_testing_credit_grants": {"create", "read", "update", "delete"},
        "free_testing_credits_budget": {"create", "read", "update", "delete"},
        "user_plan_key_wrappers": {"create", "read", "update", "delete"},
        "user_plan_revisions": {"create", "read", "update", "delete"},
        "user_task_key_wrappers": {"create", "read", "update", "delete"},
        "user_chat_preferences": {"create", "read", "update", "delete"},
        "user_work_dependencies": {"create", "read", "update", "delete"},
        "chat_message_archive_segments": {"create", "read", "update", "delete"},
        "chat_message_archive_pages": {"create", "read", "update", "delete"},
        "chat_message_archive_rollout": {"create", "read", "update", "delete"},
        "embed_version_archive_rollout": {"create", "read", "update", "delete"},
        "chat_recovery_outputs": {"create", "read", "update", "delete"},
        "chat_recovery_account_fences": {"create", "read", "update", "delete"},
        "storage_billing_periods": {"create", "read", "update", "delete"},
        "storage_billing_owner_state": {"create", "read", "update", "delete"},
        "storage_billing_warning_units": {"create", "read", "update", "delete"},
        "team_storage_billing_periods": {"create", "read", "update", "delete"},
        "team_storage_billing_owner_state": {"create", "read", "update", "delete"},
        "team_storage_billing_warning_units": {"create", "read", "update", "delete"},
    }


def test_chat_recovery_migration_executes_and_verifies_all_indexes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    setup_schemas = load_setup_schemas_module()
    migration = tmp_path / "migrate_chat_recovery_unique_indexes.sql"
    migration.write_text("CREATE UNIQUE INDEX recovery_test ON test_table (id);", encoding="utf-8")
    executed: list[tuple[str, Any]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=None):
            executed.append((str(query), params))

        def fetchall(self):
            return [(name,) for name in setup_schemas.CHAT_RECOVERY_INDEXES]

    class FakeConnection:
        autocommit = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(setup_schemas, "CHAT_RECOVERY_MIGRATION_PATH", str(migration))
    monkeypatch.setattr(setup_schemas, "connect_database", lambda: FakeConnection())

    setup_schemas.apply_and_verify_chat_recovery_indexes()

    assert executed[0][0] == migration.read_text(encoding="utf-8")
    assert "FROM pg_indexes" in executed[1][0]
    assert executed[1][1] == (list(setup_schemas.CHAT_RECOVERY_INDEXES),)


def test_usage_overview_migration_executes_and_verifies_all_indexes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    setup_schemas = load_setup_schemas_module()
    migration = tmp_path / "migrate_usage_overview_indexes.sql"
    migration.write_text("CREATE INDEX usage_overview_test ON usage (id);", encoding="utf-8")
    executed: list[tuple[str, Any]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=None):
            executed.append((str(query), params))

        def fetchall(self):
            return [(name,) for name in setup_schemas.USAGE_OVERVIEW_INDEXES]

    class FakeConnection:
        autocommit = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(setup_schemas, "USAGE_OVERVIEW_MIGRATION_PATH", str(migration))
    monkeypatch.setattr(setup_schemas, "connect_database", lambda: FakeConnection())

    setup_schemas.apply_and_verify_usage_overview_indexes()

    assert executed[0][0] == migration.read_text(encoding="utf-8")
    assert "FROM pg_indexes" in executed[1][0]
    assert executed[1][1] == (list(setup_schemas.USAGE_OVERVIEW_INDEXES),)


def test_project_owner_context_migration_executes_and_verifies_all_indexes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    setup_schemas = load_setup_schemas_module()
    migration = tmp_path / "migrate_project_owner_context.sql"
    migration.write_text("CREATE INDEX project_context_test ON projects (id);", encoding="utf-8")
    executed: list[tuple[str, Any]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=None):
            executed.append((str(query), params))

        def fetchall(self):
            return [(name,) for name in setup_schemas.PROJECT_OWNER_CONTEXT_INDEXES]

    class FakeConnection:
        autocommit = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(setup_schemas, "PROJECT_OWNER_CONTEXT_MIGRATION_PATH", str(migration))
    monkeypatch.setattr(setup_schemas, "connect_database", lambda: FakeConnection())

    setup_schemas.apply_and_verify_project_owner_context()

    assert executed[0][0] == migration.read_text(encoding="utf-8")
    assert "FROM pg_indexes" in executed[1][0]
    assert executed[1][1] == (list(setup_schemas.PROJECT_OWNER_CONTEXT_INDEXES),)


def test_project_owner_context_migration_backfills_orphaned_personal_child_actors() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "core/directus/setup/migrate_project_owner_context.sql"
    )
    sql = migration_path.read_text(encoding="utf-8")
    child_actor_fields = {
        "project_folders": "created_by_user_hash",
        "project_items": "attached_by_user_hash",
        "project_sources": "attached_by_user_hash",
        "project_settings": "updated_by_user_hash",
    }

    for table, actor_field in child_actor_fields.items():
        personal_backfill = f"""UPDATE public.{table}
SET {actor_field} = hashed_user_id
WHERE {actor_field} IS NULL
  AND hashed_team_id IS NULL
  AND hashed_user_id IS NOT NULL;"""
        not_null_constraint = (
            f"ALTER TABLE public.{table} ALTER COLUMN {actor_field} SET NOT NULL;"
        )

        assert personal_backfill in sql
        assert sql.index(personal_backfill) < sql.index(not_null_constraint)


def test_usage_summary_unique_indexes_are_required() -> None:
    setup_schemas = load_setup_schemas_module()

    required_indexes = {
        "usage_monthly_chat_user_chat_month_uq",
        "usage_monthly_app_user_app_month_uq",
        "usage_monthly_api_key_user_api_key_month_uq",
        "usage_daily_chat_user_chat_date_uq",
        "usage_daily_app_user_app_date_uq",
        "usage_daily_api_key_user_api_key_date_uq",
    }

    assert required_indexes.issubset(set(setup_schemas.USAGE_OVERVIEW_INDEXES))


def test_usage_overview_migration_repairs_duplicates_before_unique_indexes() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "core/directus/setup/migrate_usage_overview_indexes.sql"
    )
    sql = migration_path.read_text(encoding="utf-8")

    requirements = [
        ("usage_monthly_chat_summaries", "chat_id", "year_month", "usage_monthly_chat_user_chat_month_uq"),
        ("usage_monthly_app_summaries", "app_id", "year_month", "usage_monthly_app_user_app_month_uq"),
        ("usage_monthly_api_key_summaries", "api_key_hash", "year_month", "usage_monthly_api_key_user_api_key_month_uq"),
        ("usage_daily_chat_summaries", "chat_id", "date", "usage_daily_chat_user_chat_date_uq"),
        ("usage_daily_app_summaries", "app_id", "date", "usage_daily_app_user_app_date_uq"),
        ("usage_daily_api_key_summaries", "api_key_hash", "date", "usage_daily_api_key_user_api_key_date_uq"),
    ]

    assert "usage_summary_duplicate_groups" in sql
    assert "ROW_NUMBER() OVER" in sql
    assert "DELETE FROM" in sql

    first_unique_index_position = len(sql)
    for table, identifier, period, index_name in requirements:
        create_statement = f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name}"
        index_position = sql.index(create_statement)
        first_unique_index_position = min(first_unique_index_position, index_position)
        assert f"ON {table} (user_id_hash, {identifier}, {period})" in sql
        assert f"{identifier} IS NOT NULL" in sql
        assert f"{identifier} <> ''" in sql

    assert sql.index("usage_summary_duplicate_groups") < first_unique_index_position


def test_chat_recovery_endpoint_health_uses_internal_token(monkeypatch) -> None:
    setup_schemas = load_setup_schemas_module()
    requests_seen: list[dict[str, Any]] = []

    def fake_post(url, headers, json, timeout):
        requests_seen.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(200, {"data": {"jobs": []}})

    monkeypatch.setattr(setup_schemas, "INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    monkeypatch.setattr(setup_schemas.requests, "post", fake_post)

    setup_schemas.verify_chat_recovery_endpoint()

    assert requests_seen == [{
        "url": "http://cms:8055/chat-recovery-transaction/",
        "headers": {"X-Internal-Service-Token": "test-internal-token"},
        "json": {
            "operation": "list_available_jobs",
            "data": {
                "protocol_version": 1,
                "hashed_user_id": "0" * 64,
                "device_hash": "setup-health-check",
            },
        },
        "timeout": 10,
    }]


def test_chat_recovery_migration_is_required(monkeypatch, tmp_path: Path) -> None:
    setup_schemas = load_setup_schemas_module()
    missing_migration = tmp_path / "missing.sql"
    monkeypatch.setattr(
        setup_schemas,
        "CHAT_RECOVERY_MIGRATION_PATH",
        str(missing_migration),
    )

    with pytest.raises(RuntimeError, match="Required chat recovery migration is missing"):
        setup_schemas.apply_and_verify_chat_recovery_indexes()


def test_user_chat_preference_migration_executes_and_verifies_all_indexes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    setup_schemas = load_setup_schemas_module()
    migration = tmp_path / "migrate_user_chat_preferences_indexes.sql"
    migration.write_text(
        "CREATE UNIQUE INDEX user_chat_preference_test ON user_chat_preferences (id);",
        encoding="utf-8",
    )
    executed: list[tuple[str, Any]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=None):
            executed.append((str(query), params))

        def fetchall(self):
            return [(name,) for name in setup_schemas.USER_CHAT_PREFERENCE_INDEXES]

    class FakeConnection:
        autocommit = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(setup_schemas, "USER_CHAT_PREFERENCE_MIGRATION_PATH", str(migration))
    monkeypatch.setattr(setup_schemas, "connect_database", lambda: FakeConnection())

    setup_schemas.apply_and_verify_user_chat_preference_indexes()

    assert executed[0][0] == migration.read_text(encoding="utf-8")
    assert "FROM pg_indexes" in executed[1][0]
    assert executed[1][1] == (list(setup_schemas.USER_CHAT_PREFERENCE_INDEXES),)


def test_user_chat_preference_migration_is_packaged() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    migration_path = "migrate_user_chat_preferences_indexes.sql"
    required_files = [
        repo_root / "backend/core/docker-compose.yml",
        repo_root / "backend/core/docker-compose.selfhost.yml",
        repo_root / "backend/core/directus/Dockerfile.setup.selfhost",
        repo_root / "frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml",
    ]

    for file_path in required_files:
        assert migration_path in file_path.read_text(encoding="utf-8")


def test_user_chat_preference_migration_runs_inside_setup_transaction() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "core/directus/setup/migrate_user_chat_preferences_indexes.sql"
    )

    assert "CONCURRENTLY" not in migration.read_text(encoding="utf-8")






def test_accountability_schema_matrix_is_exact_and_preserves_embed_history() -> None:
    from backend.core.directus.setup.accountability_policy import REDUCED_ACCOUNTABILITY

    schemas = Path(__file__).parents[1] / "core/directus/schemas"
    declared = {}
    for path in schemas.glob("*.yml"):
        for name, config in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).items():
            if "accountability" in (config.get("meta") or {}):
                declared[name] = config["meta"]["accountability"]
    assert declared == REDUCED_ACCOUNTABILITY
    assert set(declared) == {
        "chats", "messages", "embeds", "embed_diffs", "test_results",
        "chat_message_archive_segments", "chat_message_archive_pages",
        "chat_recovery_outputs", "chat_recovery_account_fences",
        "chat_recovery_chat_deletion_fences", "chat_recovery_output_producers",
        "chat_recovery_output_producer_children", "chat_recovery_authorized_rerenders",
        "chat_recovery_authorized_direct_skills",
        "chat_recovery_legacy_output_producers",
        "chat_recovery_legacy_batch_claims",
        "chat_compression_checkpoints",
        "storage_billing_periods", "storage_billing_owner_state", "storage_billing_warning_units",
        "team_storage_billing_periods", "team_storage_billing_owner_state", "team_storage_billing_warning_units",
    }
    assert "directus_users" not in declared
    # Product version history remains a normal collection with its payload/indexes.
    assert "encrypted_snapshot" in yaml.safe_load((schemas / "embed_diffs.yml").read_text())["embed_diffs"]["fields"]
    checkpoints = yaml.safe_load((schemas / "chat_compression_checkpoints.yml").read_text())["chat_compression_checkpoints"]
    assert {"encrypted_summary", "covered_message_ids", "chat_id"} <= set(checkpoints["fields"])
    assert "cold_archive_parts" not in declared
    assert "cold_archive_manifests" not in declared


def test_storage_query_index_only_runs_exact_nonunique_sql_and_readback(monkeypatch, tmp_path) -> None:
    setup = load_setup_schemas_module()
    migration = Path(__file__).resolve().parents[1] / "core/directus/setup/migrate_storage_query_indexes.sql"
    sql = migration.read_text(encoding="utf-8")
    assert sql.count("CREATE INDEX IF NOT EXISTS") == len(setup.STORAGE_QUERY_INDEXES) == 9
    assert "CREATE UNIQUE INDEX" not in sql
    assert "CREATE TRIGGER" not in sql
    assert "ALTER TABLE" not in sql
    assert "DROP " not in sql

    events = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, command, params=None):
            events.append((command, params))

        def fetchall(self):
            return [(name,) for name in setup.STORAGE_QUERY_INDEXES]

    class Connection:
        autocommit = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(setup, "STORAGE_QUERY_MIGRATION_PATH", str(migration))
    monkeypatch.setattr(setup, "connect_database", Connection)
    for name in ("setup_schemas", "activate_prepared_schema", "reconcile_accountability_only"):
        monkeypatch.setattr(setup, name, lambda: pytest.fail("full setup or another mode ran"))
    setup.run_cli(["--storage-query-indexes-only"])
    assert events[0] == ("SET lock_timeout = '5s'", None)
    assert events[1] == ("SET statement_timeout = '5min'", None)
    assert events[2] == (sql, None)
    assert "FROM pg_indexes" in events[3][0]
    assert events[3][1] == (list(setup.STORAGE_QUERY_INDEXES),)


def test_storage_query_index_only_rejects_other_mode_and_missing_migration(monkeypatch, tmp_path) -> None:
    setup = load_setup_schemas_module()
    monkeypatch.setattr(setup, "connect_database", lambda: pytest.fail("database opened"))
    monkeypatch.setattr(setup, "STORAGE_QUERY_MIGRATION_PATH", str(tmp_path / "missing.sql"))
    with pytest.raises(SystemExit, match="2"):
        setup.run_cli(["--storage-query-indexes-only", "--accountability-only"])
    with pytest.raises(RuntimeError, match="Required storage query migration is missing"):
        setup.run_cli(["--storage-query-indexes-only"])


def test_team_grants_schema_loads_through_standard_collection_setup(monkeypatch) -> None:
    """The strict Team exporter must query a declared, Team-scoped collection."""
    setup = load_setup_schemas_module()
    schemas = Path(__file__).resolve().parents[1] / "core/directus/schemas"
    declarations = {}

    def record_collection(token, collection, config):
        assert token == "disposable-unit-token"
        declarations[collection] = config
        return True, True

    monkeypatch.setattr(setup, "create_collection_from_config", record_collection)
    assert setup.create_collection("disposable-unit-token", schemas / "teams.yml") == (True, True)
    grant = declarations["team_connected_account_grants"]
    assert grant["type"] == "collection"
    assert set(grant["fields"]) == {
        "id", "connected_account_id_hash", "hashed_team_id", "hashed_user_id", "role_snapshot",
        "encrypted_account_secret_key", "allowed_actions_hash", "status", "created_at", "revoked_at",
    }
    assert grant["fields"]["hashed_team_id"]["type"] == "string"
    assert grant["fields"]["encrypted_account_secret_key"]["type"] == "text"
    assert grant["fields"]["revoked_at"]["nullable"] is True
    assert "team_id_hash" not in grant["fields"]
