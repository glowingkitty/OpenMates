"""Tests for deployment/verify-caddyfile.py route coverage rules.

The Caddy verifier is the deterministic guard that prevents newly registered
FastAPI routes from being omitted from dev/prod proxy allowlists. These tests
cover route-inventory entries that previously caused Caddy to abort live API
requests before FastAPI could return a normal auth error.
"""

# contract-test-file: infrastructure

from __future__ import annotations

import importlib.util
import ast
from fnmatch import fnmatchcase
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


def test_dev_account_key_ingress_is_exact_and_not_public_wildcard_cors() -> None:
    verifier = _load_verify_caddyfile_module()
    content = CADDYFILES[0].read_text()
    route = "/v1/account/chat-encryption-key"
    paths = verifier.parse_caddyfile_paths(content)
    assert route in paths
    assert content.count(route) == 3
    assert "/v1/account/*" not in paths
    assert not verifier.path_is_covered("/v1/account/unrelated-private-operation", paths)
    assert not verifier.path_is_covered(route + "/unrelated-child", paths)
    for line in content.splitlines():
        if line.strip().startswith("@public_api_paths path "):
            assert route not in line
    public_options = content.split("@public_api_options {", 1)[1].split("}", 1)[0]
    assert route not in public_options


def test_adapted_dev_account_key_preflight_and_requests_preserve_fastapi_cors() -> None:
    """Real Caddy adaptation routes cookies to the existing origin-list policy."""
    caddy = shutil.which("caddy")
    if caddy is None:
        pytest.skip("caddy is not installed")
    env = os.environ.copy()
    env.setdefault("GANDI_BEARER_TOKEN", "openmates-caddyfile-syntax-check-token")
    adapted = subprocess.run(
        [caddy, "adapt", "--config", str(CADDYFILES[0]), "--adapter", "caddyfile"],
        cwd=REPO_ROOT, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if "module not registered: dns.providers.gandi" in adapted.stderr:
        pytest.skip("installed caddy lacks the Gandi DNS module")
    assert adapted.returncode == 0, adapted.stderr
    endpoint = "/v1/account/chat-encryption-key"
    matched = [route for routes in _route_lists(json.loads(adapted.stdout)) for route in routes
               if endpoint in _matched_paths(route)]
    assert len(matched) == 2, "Both OPTIONS and actual requests need proxy routes"
    assert sum(route.get("match", [{}])[0].get("method") == ["OPTIONS"] for route in matched) == 1
    for route in matched:
        assert "reverse_proxy" in _nested_handlers(route)
        assert "static_response" not in _nested_handlers(route)
        # Caddy must preserve FastAPI's specific-origin + credentials response,
        # never substitute the public developer handler's wildcard CORS.
        assert "headers" not in _nested_handlers(route)
        assert "Access-Control-Allow-Origin" not in json.dumps(route)
        assert "Access-Control-Allow-Credentials" not in json.dumps(route)

    # Verify the delegated policy still uses the configured origin list with
    # credentials, rather than allowing wildcard browser origins. Parse only;
    # importing the API would initialize workers and external dependencies.
    source = ast.parse((REPO_ROOT / "backend/core/api/main.py").read_text())
    policies = [node for node in ast.walk(source) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "add_middleware"
                and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "CORSMiddleware"]
    assert len(policies) == 1
    options = {item.arg: item.value for item in policies[0].keywords}
    assert isinstance(options["allow_origins"], ast.Name) and options["allow_origins"].id == "allowed_origins"
    assert isinstance(options["allow_credentials"], ast.Constant) and options["allow_credentials"].value is True


def test_browser_session_controls_use_narrow_credentialed_proxy_routes() -> None:
    content = ALL_CADDYFILES[2].read_text()
    for name in ("@webapp_general_options {", "@webapp_actual {"):
        matcher = content.split(name, 1)[1].split("}", 1)[0]
        assert "/v1/apps/web/browse/*" in matcher.split(), name
        assert "/v1/apps/*" not in matcher.split(), name


@pytest.mark.parametrize("caddyfile", CADDYFILES)
def test_browse_session_controls_preserve_credentialed_cors(caddyfile: Path) -> None:
    """The canonical control path must precede public wildcard CORS handlers."""
    caddy = shutil.which("caddy")
    if caddy is None:
        pytest.skip("caddy is not installed")
    result = subprocess.run(
        [caddy, "adapt", "--config", str(caddyfile), "--adapter", "caddyfile"],
        cwd=REPO_ROOT, env={**os.environ, "GANDI_BEARER_TOKEN": "syntax-check-only"},
        text=True, capture_output=True, check=False,
    )
    if "module not registered: dns.providers.gandi" in result.stderr:
        pytest.skip("installed caddy lacks the Gandi DNS module")
    assert result.returncode == 0, result.stderr
    path = "/v1/apps/web/browse/11111111-1111-4111-8111-111111111111"
    for routes in _route_lists(json.loads(result.stdout)):
        public = {"OPTIONS" if r.get("match", [{}])[0].get("method") == ["OPTIONS"] else "actual": i
                  for i, r in enumerate(routes) if "/v1/apps/*" in _matched_paths(r) and "headers" in _nested_handlers(r)}
        if set(public) != {"OPTIONS", "actual"}:
            continue
        for method, index in public.items():
            matches = [r for r in routes[:index]
                       if any(fnmatchcase(path, pattern) for pattern in _matched_paths(r))
                       and (r.get("match", [{}])[0].get("method") == ["OPTIONS"]) == (method == "OPTIONS")
                       and "reverse_proxy" in _nested_handlers(r) and "headers" not in _nested_handlers(r)]
            assert matches, (caddyfile, method)
        return
    pytest.fail(f"No first-party Browse ingress found in {caddyfile}")


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
        "/v1/apps/workspace/interpret", "/v1/apps/workspace/rank",
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


@pytest.mark.parametrize("caddyfile", ALL_CADDYFILES)
@pytest.mark.parametrize("probe_path", [
    "/v1/embeds/chats/*/references/availability",
    "/v1/embeds/chats/*",
])
def test_chat_embed_reads_and_references_use_credentialed_cors(
    caddyfile: Path, tmp_path: Path, probe_path: str,
) -> None:
    """Chat embed/key reads and reference probes must preserve session CORS."""
    caddy = shutil.which("caddy")
    if caddy is None:
        pytest.skip("caddy is not installed")
    env = os.environ.copy()
    env.setdefault("GANDI_BEARER_TOKEN", "openmates-caddyfile-syntax-check-token")
    source = caddyfile
    if caddyfile.name == "Caddyfile.example":
        source = tmp_path / "Caddyfile"
        content = caddyfile.read_text()
        values = {"YOUR_EMAIL@example.com": "admin@example.test", "API_DOMAIN": "api.example.test", "FRONTEND_DOMAIN": "app.example.test", "UPLOAD_DOMAIN": "upload.example.test", "SERVICE_DOMAIN": "service.example.test", "API_UPSTREAM": "localhost:8000", "WEBAPP_UPSTREAM": "localhost:5173", "UPLOADS_UPSTREAM": "localhost:8001", "LOCAL_UPLOADS_UPSTREAM": "localhost:8002", "SERVICE_UPSTREAM": "localhost:8003"}
        for name, value in values.items():
            content = content.replace(f"<{name}>", value)
        source.write_text(content)
    result = subprocess.run(
        [caddy, "adapt", "--config", str(source), "--adapter", "caddyfile"],
        cwd=REPO_ROOT, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if "module not registered: dns.providers.gandi" in result.stderr:
        pytest.skip("installed caddy lacks the Gandi DNS module")
    assert result.returncode == 0, result.stderr

    for routes in _route_lists(json.loads(result.stdout)):
        public_routes = {
            "OPTIONS" if route.get("match", [{}])[0].get("method") == ["OPTIONS"] else "actual": index
            for index, route in enumerate(routes)
            if "/v1/embeds/*" in _matched_paths(route)
            and "headers" in _nested_handlers(route)
        }
        if set(public_routes) != {"OPTIONS", "actual"}:
            continue
        for method, public_index in public_routes.items():
            matches = [
                (index, route) for index, route in enumerate(routes)
                if probe_path in _matched_paths(route)
                and (route.get("match", [{}])[0].get("method") == ["OPTIONS"]) == (method == "OPTIONS")
            ]
            assert len(matches) == 1, method
            index, route = matches[0]
            assert index < public_index, method
            assert "reverse_proxy" in _nested_handlers(route)
            assert "headers" not in _nested_handlers(route)
        return
    pytest.fail(f"Could not find credentialed and public embed routes in {caddyfile}")


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


def test_production_account_chat_key_uses_exact_first_party_handlers() -> None:
    content = CADDYFILES[1].read_text()
    route = "/v1/account/chat-encryption-key"
    assert content.count(route) == 3
    assert "/v1/account/*" not in content
    for name in ("@webapp_paths path ", "@webapp_general_options {", "@webapp_actual {"):
        assert route in content.split(name, 1)[1].split("\n", 2)[0 if name.endswith("path ") else 1]
    if "@public_api_paths {" in content:
        public = content.split("@public_api_paths {", 1)[1].split("}", 1)[0]
    else:
        public = next(line for line in content.splitlines() if line.strip().startswith("@public_api_paths path "))
    assert route not in public


def test_apps_interpretation_and_ranking_use_exact_first_party_paths() -> None:
    for caddyfile in ALL_CADDYFILES:
        paths = [line.split("#", 1)[0].split() for line in caddyfile.read_text().splitlines()
                 if "/v1/apps/workspace/interpret" in line and not line.lstrip().startswith("#")]
        assert paths, caddyfile
        assert all("/v1/apps/workspace/rank" in line for line in paths), caddyfile
        assert all("/v1/apps/workspace/*" not in line for line in paths), caddyfile
