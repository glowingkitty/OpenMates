"""Tests for deployment/verify-caddyfile.py route coverage rules.

The Caddy verifier is the deterministic guard that prevents newly registered
FastAPI routes from being omitted from dev/prod proxy allowlists. These tests
cover route-inventory entries that previously caused Caddy to abort live API
requests before FastAPI could return a normal auth error.
"""

# contract-test-file: infrastructure

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_CADDYFILE_PATH = REPO_ROOT / "deployment/verify-caddyfile.py"
CADDYFILES = (
    REPO_ROOT / "deployment/dev_server/Caddyfile",
    REPO_ROOT / "deployment/prod_server/Caddyfile",
)
ALL_CADDYFILES = (*CADDYFILES, REPO_ROOT / "deployment/Caddyfile.example")


def _load_verify_caddyfile_module():
    spec = importlib.util.spec_from_file_location("verify_caddyfile", VERIFY_CADDYFILE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_electronics_pcb_schematic_route_is_verified_and_allowlisted() -> None:
    verifier = _load_verify_caddyfile_module()
    route_prefix = "/v1/electronics/pcb-schematic"

    assert any(route[0] == route_prefix for route in verifier.FASTAPI_ROUTES)

    for caddyfile in (
        REPO_ROOT / "deployment/dev_server/Caddyfile",
        REPO_ROOT / "deployment/prod_server/Caddyfile",
    ):
        paths = verifier.parse_caddyfile_paths(caddyfile.read_text())
        assert verifier.path_is_covered(route_prefix, paths), caddyfile


def test_native_chats_route_is_verified_and_allowlisted() -> None:
    verifier = _load_verify_caddyfile_module()
    route_prefix = "/v1/chats"

    assert any(route[0] == route_prefix for route in verifier.FASTAPI_ROUTES)

    for caddyfile in (
        REPO_ROOT / "deployment/dev_server/Caddyfile",
        REPO_ROOT / "deployment/prod_server/Caddyfile",
    ):
        paths = verifier.parse_caddyfile_paths(caddyfile.read_text())
        assert verifier.path_is_covered(route_prefix, paths), caddyfile


def test_code_run_routes_are_verified_and_allowlisted() -> None:
    verifier = _load_verify_caddyfile_module()
    route_prefixes = ("/v1/code/run", "/v1/code/notebooks/run")

    for route_prefix in route_prefixes:
        assert any(route[0] == route_prefix for route in verifier.FASTAPI_ROUTES)

    for caddyfile in (
        REPO_ROOT / "deployment/dev_server/Caddyfile",
        REPO_ROOT / "deployment/prod_server/Caddyfile",
    ):
        paths = verifier.parse_caddyfile_paths(caddyfile.read_text())
        for route_prefix in route_prefixes:
            assert verifier.path_is_covered(route_prefix, paths), (caddyfile, route_prefix)


def _nested_handlers(route: dict) -> set[str]:
    handlers: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            handler = value.get("handler")
            if isinstance(handler, str):
                handlers.add(handler)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(route.get("handle", []))
    return handlers


def _matched_paths(route: dict) -> set[str]:
    return {
        path
        for matcher in route.get("match", [])
        for path in matcher.get("path", [])
    }


def _route_lists(value: object):
    if isinstance(value, dict):
        routes = value.get("routes")
        if isinstance(routes, list):
            yield routes
        for nested in value.values():
            yield from _route_lists(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _route_lists(nested)


def test_websocket_handler_precedes_broad_apps_handler_in_all_caddyfiles() -> None:
    for caddyfile in ALL_CADDYFILES:
        content = caddyfile.read_text()
        websocket_handle = "handle @websocket_actual {"
        public_api_handle = "handle @public_api_paths {"

        assert content.count(websocket_handle) == 1, caddyfile
        assert content.count(public_api_handle) == 1, caddyfile
        assert content.index(websocket_handle) < content.index(public_api_handle), caddyfile

        websocket_block = content[
            content.index(websocket_handle) : content.index(public_api_handle)
        ]
        assert "encode gzip zstd" not in websocket_block
        assert "flush_interval -1" in websocket_block


@pytest.mark.parametrize("caddyfile", CADDYFILES)
def test_adapted_audio_websocket_route_precedes_encoded_apps_route(
    caddyfile: Path,
) -> None:
    caddy = shutil.which("caddy")
    if caddy is None:
        pytest.skip("caddy is not installed")

    env = os.environ.copy()
    env.setdefault("GANDI_BEARER_TOKEN", "openmates-caddyfile-syntax-check-token")
    result = subprocess.run(
        [caddy, "adapt", "--config", str(caddyfile), "--adapter", "caddyfile"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if "module not registered: dns.providers.gandi" in result.stderr:
        pytest.skip("installed caddy lacks the Gandi DNS module")
    assert result.returncode == 0, result.stderr

    adapted = json.loads(result.stdout)
    for routes in _route_lists(adapted):
        audio_indexes = [
            index
            for index, route in enumerate(routes)
            if "/v1/apps/audio/realtime-transcription" in _matched_paths(route)
        ]
        apps_indexes = [
            index
            for index, route in enumerate(routes)
            if "/v1/apps/*" in _matched_paths(route)
            and "encode" in _nested_handlers(route)
        ]
        if not audio_indexes or not apps_indexes:
            continue

        audio_route = routes[audio_indexes[0]]
        assert audio_indexes[0] < apps_indexes[0], caddyfile
        assert "reverse_proxy" in _nested_handlers(audio_route)
        assert "encode" not in _nested_handlers(audio_route)
        return

    pytest.fail(f"Could not find sibling audio and encoded apps routes in {caddyfile}")
