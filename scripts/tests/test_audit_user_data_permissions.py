"""Tests for the user-data permission registry audit.

The audit is a fail-closed guard for backend entrypoints that can access user
data. These fixture tests cover missing REST modules, changed endpoint counts,
missing WebSocket handlers, stale registry entries, invalid classifications, and
a fully covered clean registry without depending on production route files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.audit_user_data_permissions import (
    RestEndpoint,
    audit_registry,
    discover_file_endpoints,
    discover_rest_endpoints,
    discover_rest_routes,
    discover_websocket_handlers,
)


ACTORS = ["authenticated_owner", "admin"]
ACCESS_MODES = ["owner_read", "owner_write", "admin_read"]


def write_file(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def route_file(body: str = "") -> str:
    return f"""
from fastapi import APIRouter

router = APIRouter()

@router.get("/items")
async def list_items():
    return []

{body}
"""


def valid_registry(rest_path: str, ws_path: str, *, expected_routes: int = 1) -> dict[str, Any]:
    return {
        "actors": ACTORS,
        "access_modes": ACCESS_MODES,
        "rest_modules": [
            {
                "path": rest_path,
                "expected_routes": expected_routes,
                "actors": ["authenticated_owner"],
                "access": ["owner_read"],
                "data_domains": ["chats"],
                "rationale": "Reads owner chat data.",
            }
        ],
        "websocket_handlers": [
            {
                "path": ws_path,
                "actors": ["authenticated_owner"],
                "access": ["owner_write"],
                "data_domains": ["messages"],
                "rationale": "Writes owner message data.",
            }
        ],
    }


def fixture_discovery(tmp_path: Path) -> tuple[dict[str, int], set[str], str, str]:
    rest_path = "backend/core/api/app/routes/example.py"
    ws_path = "backend/core/api/app/routes/handlers/websocket_handlers/example_handler.py"
    write_file(tmp_path / rest_path, route_file())
    write_file(tmp_path / ws_path, "async def handle_example():\n    return None\n")

    discovered_endpoints = discover_rest_endpoints(tmp_path / "backend/core/api/app/routes", tmp_path)
    discovered_rest = {path: len(endpoints) for path, endpoints in discovered_endpoints.items()}
    discovered_ws = discover_websocket_handlers(
        tmp_path / "backend/core/api/app/routes/handlers/websocket_handlers",
        tmp_path,
    )
    return discovered_rest, discovered_ws, rest_path, ws_path


def test_fully_covered_registry_passes(tmp_path: Path) -> None:
    discovered_rest, discovered_ws, rest_path, ws_path = fixture_discovery(tmp_path)

    issues = audit_registry(
        valid_registry(rest_path, ws_path),
        discovered_rest_routes=discovered_rest,
        discovered_websocket_handlers=discovered_ws,
    )

    assert issues == []


def test_missing_rest_route_module_is_reported(tmp_path: Path) -> None:
    discovered_rest, discovered_ws, _rest_path, ws_path = fixture_discovery(tmp_path)
    registry = valid_registry("backend/core/api/app/routes/other.py", ws_path)

    issues = audit_registry(
        registry,
        discovered_rest_routes=discovered_rest,
        discovered_websocket_handlers=discovered_ws,
    )

    messages = [issue.format() for issue in issues]
    assert any("missing REST route permission registry entry" in message for message in messages)
    assert any("registered REST route file was not discovered" in message for message in messages)


def test_endpoint_count_mismatch_is_reported(tmp_path: Path) -> None:
    discovered_rest, discovered_ws, rest_path, ws_path = fixture_discovery(tmp_path)
    registry = valid_registry(rest_path, ws_path, expected_routes=2)

    issues = audit_registry(
        registry,
        discovered_rest_routes=discovered_rest,
        discovered_websocket_handlers=discovered_ws,
    )

    assert any("expected_routes=2, discovered=1" in issue.message for issue in issues)


def test_missing_websocket_handler_is_reported(tmp_path: Path) -> None:
    discovered_rest, discovered_ws, rest_path, _ws_path = fixture_discovery(tmp_path)
    registry = valid_registry(rest_path, "backend/core/api/app/routes/handlers/websocket_handlers/other_handler.py")

    issues = audit_registry(
        registry,
        discovered_rest_routes=discovered_rest,
        discovered_websocket_handlers=discovered_ws,
    )

    messages = [issue.format() for issue in issues]
    assert any("missing WebSocket handler permission registry entry" in message for message in messages)
    assert any("registered WebSocket handler file was not discovered" in message for message in messages)


def test_invalid_classification_is_reported(tmp_path: Path) -> None:
    discovered_rest, discovered_ws, rest_path, ws_path = fixture_discovery(tmp_path)
    registry = valid_registry(rest_path, ws_path)
    rest_entry = registry["rest_modules"][0]
    rest_entry["actors"] = ["unknown_actor"]
    rest_entry["data_domains"] = []
    rest_entry["rationale"] = ""

    issues = audit_registry(
        registry,
        discovered_rest_routes=discovered_rest,
        discovered_websocket_handlers=discovered_ws,
    )

    messages = [issue.format() for issue in issues]
    assert any("unknown actor" in message for message in messages)
    assert any("data_domains must be a non-empty list" in message for message in messages)
    assert any("rationale must be a non-empty string" in message for message in messages)


def test_api_route_decorator_counts_as_http_route(tmp_path: Path) -> None:
    rest_path = "backend/core/api/app/routes/proxy.py"
    write_file(
        tmp_path / rest_path,
        route_file(
            """
@router.api_route("/{path:path}", methods=["GET", "POST"])
async def proxy(path: str):
    return {"path": path}

@router.websocket("/stream")
async def stream():
    return None
"""
        ),
    )

    discovered_rest = discover_rest_routes(tmp_path / "backend/core/api/app/routes", tmp_path)

    assert discovered_rest[rest_path] == 2


def test_endpoint_overrides_required_reports_missing_endpoint(tmp_path: Path) -> None:
    discovered_rest, discovered_ws, rest_path, ws_path = fixture_discovery(tmp_path)
    discovered_endpoints = {
        rest_path: [RestEndpoint(rest_path, "GET", "/items", "list_items", tuple())]
    }
    registry = valid_registry(rest_path, ws_path)
    registry["rest_modules"][0]["endpoint_overrides_required"] = True

    issues = audit_registry(
        registry,
        discovered_rest_routes=discovered_rest,
        discovered_rest_endpoints=discovered_endpoints,
        discovered_websocket_handlers=discovered_ws,
    )

    assert any("missing endpoint-level permission registry entry" in issue.message for issue in issues)


def test_stale_endpoint_override_is_reported(tmp_path: Path) -> None:
    discovered_rest, discovered_ws, rest_path, ws_path = fixture_discovery(tmp_path)
    registry = valid_registry(rest_path, ws_path)
    registry["rest_modules"][0]["endpoints"] = [
        {
            "method": "POST",
            "route": "/missing",
            "function": "missing",
            "actors": ["authenticated_owner"],
            "access": ["owner_write"],
            "data_domains": ["chats"],
            "auth_model": "session_required",
            "rationale": "Fixture stale endpoint.",
        }
    ]

    issues = audit_registry(
        registry,
        discovered_rest_routes=discovered_rest,
        discovered_rest_endpoints={rest_path: [RestEndpoint(rest_path, "GET", "/items", "list_items", tuple())]},
        discovered_websocket_handlers=discovered_ws,
    )

    assert any("registered endpoint was not discovered" in issue.message for issue in issues)


def test_endpoint_auth_shape_mismatch_is_reported(tmp_path: Path) -> None:
    discovered_rest, discovered_ws, rest_path, ws_path = fixture_discovery(tmp_path)
    registry = valid_registry(rest_path, ws_path)
    registry["rest_modules"][0]["endpoints"] = [
        {
            "method": "GET",
            "route": "/items",
            "function": "list_items",
            "actors": ["unauthenticated"],
            "access": ["owner_read"],
            "data_domains": ["chats"],
            "auth_model": "session_required",
            "rationale": "Fixture intentionally wrong actor.",
        }
    ]

    issues = audit_registry(
        registry,
        discovered_rest_routes=discovered_rest,
        discovered_rest_endpoints={
            rest_path: [RestEndpoint(rest_path, "GET", "/items", "list_items", ("get_current_user",))]
        },
        discovered_websocket_handlers=discovered_ws,
    )

    assert any("uses required user auth" in issue.message for issue in issues)


def test_settings_sensitive_endpoints_are_session_only() -> None:
    settings_path = Path("backend/core/api/app/routes/settings.py")
    endpoints = {endpoint.key: endpoint for endpoint in discover_file_endpoints(settings_path, Path.cwd())}
    sensitive_endpoint_keys = {
        "POST /auto-topup/low-balance",
        "GET /api-keys",
        "GET /api-key-devices",
        "GET /usage/export",
        "GET /billing",
    }

    for key in sensitive_endpoint_keys:
        assert key in endpoints
        assert "get_current_user" in endpoints[key].auth_guards
        assert "get_current_user_or_api_key" not in endpoints[key].auth_guards
