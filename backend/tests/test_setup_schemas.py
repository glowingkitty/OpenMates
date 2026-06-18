"""
backend/tests/test_setup_schemas.py

Regression tests for Directus YAML schema setup helpers. The tests keep the
collection bootstrap contract deterministic without a running Directus instance,
especially for singleton collections that store app-generated IDs in string
primary-key columns.
"""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from pathlib import Path
from typing import Any

import yaml


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
    sys.modules.setdefault("dotenv", SimpleNamespace(load_dotenv=lambda: None))
    return importlib.import_module("backend.core.directus.setup.setup_schemas")


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
        "anonymous_free_usage_budget": {"create", "read", "update", "delete"},
        "anonymous_free_usage_identity_daily": {"create", "read", "update", "delete"},
        "anonymous_free_usage_reservations": {"create", "read", "update", "delete"},
        "free_testing_credit_grants": {"create", "read", "update", "delete"},
        "free_testing_credits_budget": {"create", "read", "update", "delete"},
    }
