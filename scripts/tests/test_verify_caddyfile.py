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


def test_dev_apps_workspace_credentialed_cors_precedes_public_api() -> None:
    """Direct Apps requests with cookies must reach FastAPI's CORS middleware."""
    caddy = shutil.which("caddy")
    if caddy is None:
        pytest.skip("caddy is not installed")

    env = os.environ.copy()
    env.setdefault("GANDI_BEARER_TOKEN", "openmates-caddyfile-syntax-check-token")
    result = subprocess.run(
        [caddy, "adapt", "--config", str(CADDYFILES[0]), "--adapter", "caddyfile"],
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

    direct_paths = {
        "/v1/apps/workspace/results", "/v1/apps/workspace/results/*",
        "/v1/apps/*/skills/*", "/v1/tasks/*", "/v1/anonymous/apps/*",
    }
    for routes in _route_lists(json.loads(result.stdout)):
        public_options = next((i for i, route in enumerate(routes)
            if "/v1/apps/*" in _matched_paths(route)
            and route.get("match", [{}])[0].get("method") == ["OPTIONS"]), None)
        public_actual = next((i for i, route in enumerate(routes)
            if "/v1/apps/*" in _matched_paths(route)
            and "encode" in _nested_handlers(route)
            and not route.get("match", [{}])[0].get("method")), None)
        if public_options is None or public_actual is None:
            continue

        for method, public_index in (("OPTIONS", public_options), ("actual", public_actual)):
            matches = [(i, route) for i, route in enumerate(routes)
                if direct_paths.issubset(_matched_paths(route))
                and route.get("match", [{}])[0].get("header", {}).get("Origin")
                    == ["https://app.dev.openmates.org"]
                and (route.get("match", [{}])[0].get("method") == ["OPTIONS"]) == (method == "OPTIONS")]
            assert len(matches) == 1, method
            index, route = matches[0]
            assert index < public_index, method
            assert "reverse_proxy" in _nested_handlers(route)
            assert "headers" not in _nested_handlers(route), method
        return

    pytest.fail("Could not find credentialed and public Apps routes in adapted dev Caddyfile")


@pytest.mark.parametrize("caddyfile", CADDYFILES)
def test_hosted_project_file_routes_retain_credentialed_cors(caddyfile: Path) -> None:
    """Project ciphertext reads must never fall into public wildcard CORS."""
    caddy = shutil.which("caddy")
    if caddy is None:
        pytest.skip("caddy is not installed")
    env = os.environ.copy()
    env.setdefault("GANDI_BEARER_TOKEN", "openmates-caddyfile-syntax-check-token")
    result = subprocess.run(
        [caddy, "adapt", "--config", str(caddyfile), "--adapter", "caddyfile"],
        cwd=REPO_ROOT, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if "module not registered: dns.providers.gandi" in result.stderr:
        pytest.skip("installed caddy lacks the Gandi DNS module")
    assert result.returncode == 0, result.stderr
    hosted_paths = {"/v1/embeds/*/encrypted", "/v1/embeds/*/revision-receipts/*"}
    for routes in _route_lists(json.loads(result.stdout)):
        public_routes = {
            "OPTIONS" if route.get("match", [{}])[0].get("method") == ["OPTIONS"] else "actual": index
            for index, route in enumerate(routes)
            if "/v1/embeds/*" in _matched_paths(route)
            and "headers" in _nested_handlers(route)
        }
        if set(public_routes) != {"OPTIONS", "actual"}:
            continue
        matched_methods = set()
        for index, route in enumerate(routes):
            if not hosted_paths.issubset(_matched_paths(route)):
                continue
            method = "OPTIONS" if route.get("match", [{}])[0].get("method") == ["OPTIONS"] else "actual"
            assert index < public_routes[method]
            assert "reverse_proxy" in _nested_handlers(route)
            assert "headers" not in _nested_handlers(route)
            matched_methods.add(method)
        assert matched_methods == {"OPTIONS", "actual"}
        return
    pytest.fail(f"Could not find public and first-party embed routes in {caddyfile}")
