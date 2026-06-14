#!/usr/bin/env python3
"""Audit backend user-data entrypoints against the permission registry.

The registry is the reviewed source of truth for REST endpoints and WebSocket
handler files that can touch user data. This script intentionally fails closed
when backend entrypoints are added, removed, or change auth shape without an
explicit registry update. Matrix mode prints an endpoint-level actor/access
contract for product and security follow-up.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "backend/core/api/app/security/user_data_permissions.yml"
DEFAULT_ROUTES_ROOT = REPO_ROOT / "backend/core/api/app/routes"
DEFAULT_WS_ROOT = REPO_ROOT / "backend/core/api/app/routes/handlers/websocket_handlers"

HTTP_ROUTE_DECORATORS = {
    "api_route",
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
}
REQUIRED_COMMON_FIELDS = ("path", "actors", "access", "data_domains", "rationale")
REQUIRED_ENDPOINT_FIELDS = ("method", "route", "actors", "access", "data_domains", "auth_model", "rationale")
TOKEN_AUTH_MODELS = {
    "download_token",
    "email_token",
    "invite_token",
    "newsletter_token",
    "pair_token",
    "provider_signature",
    "recovery_code",
    "share_id",
    "short_url_token",
    "preview_gateway_token",
}


@dataclass(frozen=True)
class AuditIssue:
    path: str
    message: str

    def format(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class RestEndpoint:
    module_path: str
    method: str
    route: str
    function: str
    auth_guards: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.method} {self.route}"

    @property
    def display_path(self) -> str:
        return f"{self.module_path} {self.key}"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def ast_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return ast_name(node.func)
    return ""


def route_decorator_name(decorator: ast.expr) -> str | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def route_decorator_info(decorator: ast.expr) -> tuple[str, str, list[str]] | None:
    if route_decorator_name(decorator) not in HTTP_ROUTE_DECORATORS:
        return None
    call = decorator if isinstance(decorator, ast.Call) else None
    method = route_decorator_name(decorator) or ""
    route = ""
    auth_guards: list[str] = []
    if call is not None:
        if call.args and isinstance(call.args[0], ast.Constant):
            route = str(call.args[0].value)
        for keyword in call.keywords:
            if keyword.arg == "dependencies" and isinstance(keyword.value, ast.List | ast.Tuple):
                for dependency in keyword.value.elts:
                    if isinstance(dependency, ast.Call) and ast_name(dependency.func) == "Depends" and dependency.args:
                        auth_guards.append(ast_name(dependency.args[0]))
    return method.upper(), route, auth_guards


def depends_guard(default: ast.expr) -> str | None:
    if isinstance(default, ast.Call) and ast_name(default.func) == "Depends" and default.args:
        return ast_name(default.args[0])
    return None


def endpoint_auth_guards(node: ast.AsyncFunctionDef | ast.FunctionDef, decorator_guards: list[str]) -> tuple[str, ...]:
    guards = list(decorator_guards)
    defaults = list(node.args.defaults)
    if defaults:
        args_with_defaults = node.args.args[-len(defaults) :]
        for arg, default in zip(args_with_defaults, defaults):
            guard = depends_guard(default)
            if guard:
                guards.append(guard)
    return tuple(dict.fromkeys(guards))


def discover_file_endpoints(path: Path, repo_root: Path) -> list[RestEndpoint]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_path = relative_path(path, repo_root)
    endpoints: list[RestEndpoint] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            info = route_decorator_info(decorator)
            if info is None:
                continue
            method, route, decorator_guards = info
            endpoints.append(
                RestEndpoint(
                    module_path=module_path,
                    method=method,
                    route=route,
                    function=node.name,
                    auth_guards=endpoint_auth_guards(node, decorator_guards),
                )
            )
    return endpoints


def discover_rest_endpoints(routes_root: Path, repo_root: Path) -> dict[str, list[RestEndpoint]]:
    discovered: dict[str, list[RestEndpoint]] = {}
    for path in sorted(routes_root.rglob("*.py")):
        if path.name == "__init__.py" or "/handlers/" in path.as_posix():
            continue
        endpoints = discover_file_endpoints(path, repo_root)
        if not endpoints:
            continue
        discovered[relative_path(path, repo_root)] = endpoints
    return discovered


def discover_rest_routes(routes_root: Path, repo_root: Path) -> dict[str, int]:
    return {path: len(endpoints) for path, endpoints in discover_rest_endpoints(routes_root, repo_root).items()}


def discover_websocket_handlers(ws_root: Path, repo_root: Path) -> set[str]:
    return {
        relative_path(path, repo_root)
        for path in sorted(ws_root.glob("*.py"))
        if path.name != "__init__.py"
    }


def require_non_empty_list(entry: dict[str, Any], field: str, path: str) -> list[str] | None:
    value = entry.get(field)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        return None
    return value


def endpoint_entries_by_key(
    entries: Any,
    *,
    module_path: str,
) -> tuple[dict[str, dict[str, Any]], list[AuditIssue]]:
    if entries is None:
        return {}, []
    if not isinstance(entries, list):
        return {}, [AuditIssue(module_path, "endpoints must be a list when provided")]

    by_key: dict[str, dict[str, Any]] = {}
    issues: list[AuditIssue] = []
    for entry in entries:
        if not isinstance(entry, dict):
            issues.append(AuditIssue(module_path, "endpoint registry entry must be a mapping"))
            continue
        method = entry.get("method")
        route = entry.get("route")
        if not isinstance(method, str) or not method or not isinstance(route, str):
            issues.append(AuditIssue(module_path, "endpoint entry requires method and route"))
            continue
        key = f"{method.upper()} {route}"
        if key in by_key:
            issues.append(AuditIssue(f"{module_path} {key}", "duplicate endpoint registry entry"))
            continue
        by_key[key] = {**entry, "method": method.upper()}
    return by_key, issues


def validate_common_entry(
    entry: Any,
    *,
    section: str,
    allowed_actors: set[str],
    allowed_access_modes: set[str],
) -> list[AuditIssue]:
    if not isinstance(entry, dict):
        return [AuditIssue(section, "registry entry must be a mapping")]

    raw_path = entry.get("path")
    path = raw_path if isinstance(raw_path, str) and raw_path else section
    issues: list[AuditIssue] = []

    for field in REQUIRED_COMMON_FIELDS:
        if field not in entry:
            issues.append(AuditIssue(path, f"missing required field: {field}"))

    actors = require_non_empty_list(entry, "actors", path)
    if actors is None:
        issues.append(AuditIssue(path, "actors must be a non-empty list of registry actor names"))
    else:
        unknown = sorted(set(actors) - allowed_actors)
        if unknown:
            issues.append(AuditIssue(path, f"unknown actor(s): {', '.join(unknown)}"))

    access = require_non_empty_list(entry, "access", path)
    if access is None:
        issues.append(AuditIssue(path, "access must be a non-empty list of registry access modes"))
    else:
        unknown = sorted(set(access) - allowed_access_modes)
        if unknown:
            issues.append(AuditIssue(path, f"unknown access mode(s): {', '.join(unknown)}"))

    if require_non_empty_list(entry, "data_domains", path) is None:
        issues.append(AuditIssue(path, "data_domains must be a non-empty list"))

    rationale = entry.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(AuditIssue(path, "rationale must be a non-empty string"))

    return issues


def validate_endpoint_entry(
    entry: dict[str, Any],
    *,
    endpoint: RestEndpoint,
    allowed_actors: set[str],
    allowed_access_modes: set[str],
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    path = endpoint.display_path
    for field in REQUIRED_ENDPOINT_FIELDS:
        if field not in entry:
            issues.append(AuditIssue(path, f"endpoint entry missing required field: {field}"))

    function = entry.get("function")
    if function is not None and function != endpoint.function:
        issues.append(AuditIssue(path, f"endpoint function mismatch: registry={function}, discovered={endpoint.function}"))

    actors = require_non_empty_list(entry, "actors", path)
    if actors is None:
        issues.append(AuditIssue(path, "endpoint actors must be a non-empty list"))
    else:
        unknown = sorted(set(actors) - allowed_actors)
        if unknown:
            issues.append(AuditIssue(path, f"unknown endpoint actor(s): {', '.join(unknown)}"))

    access = require_non_empty_list(entry, "access", path)
    if access is None:
        issues.append(AuditIssue(path, "endpoint access must be a non-empty list"))
    else:
        unknown = sorted(set(access) - allowed_access_modes)
        if unknown:
            issues.append(AuditIssue(path, f"unknown endpoint access mode(s): {', '.join(unknown)}"))

    if require_non_empty_list(entry, "data_domains", path) is None:
        issues.append(AuditIssue(path, "endpoint data_domains must be a non-empty list"))

    auth_model = entry.get("auth_model")
    if not isinstance(auth_model, str) or not auth_model.strip():
        issues.append(AuditIssue(path, "endpoint auth_model must be a non-empty string"))

    rationale = entry.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(AuditIssue(path, "endpoint rationale must be a non-empty string"))

    if actors is not None:
        issues.extend(validate_endpoint_auth_shape(endpoint, entry, set(actors), str(auth_model or "")))
    return issues


def validate_endpoint_auth_shape(
    endpoint: RestEndpoint,
    entry: dict[str, Any],
    actors: set[str],
    auth_model: str,
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    path = endpoint.display_path
    guards = set(endpoint.auth_guards)
    if any(guard in guards for guard in ("get_current_user", "get_application_preview_current_user")) and "unauthenticated" in actors:
        issues.append(AuditIssue(path, "endpoint uses required user auth but registry includes unauthenticated"))
    if "get_current_user_or_api_key" in guards and "api_key" not in actors:
        issues.append(AuditIssue(path, "endpoint accepts API keys but registry actors omit api_key"))
    if "get_current_user_optional" in guards and not {"unauthenticated", "authenticated_owner"}.issubset(actors):
        issues.append(AuditIssue(path, "optional-auth endpoint should include unauthenticated and authenticated_owner actors"))
    if not guards and "unauthenticated" not in actors and auth_model not in TOKEN_AUTH_MODELS:
        issues.append(AuditIssue(path, "endpoint has no detected auth guard; use unauthenticated actor or a token/signature auth_model"))
    return issues


def effective_endpoint_entry(module_entry: dict[str, Any], endpoint_entry: dict[str, Any] | None) -> dict[str, Any]:
    if endpoint_entry is not None:
        return endpoint_entry
    return {
        "actors": module_entry.get("actors") or [],
        "access": module_entry.get("access") or [],
        "data_domains": module_entry.get("data_domains") or [],
        "auth_model": module_entry.get("auth_model") or "module_default",
        "rationale": module_entry.get("rationale") or "",
    }


def entries_by_path(entries: Any, *, section: str) -> tuple[dict[str, dict[str, Any]], list[AuditIssue]]:
    if not isinstance(entries, list):
        return {}, [AuditIssue(section, "registry section must be a list")]

    by_path: dict[str, dict[str, Any]] = {}
    issues: list[AuditIssue] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"]:
            issues.append(AuditIssue(section, "registry entry is missing a string path"))
            continue
        path = entry["path"]
        if path in by_path:
            issues.append(AuditIssue(path, "duplicate registry entry"))
            continue
        by_path[path] = entry
    return by_path, issues


def audit_registry(
    registry: dict[str, Any],
    *,
    discovered_rest_routes: dict[str, int],
    discovered_rest_endpoints: dict[str, list[RestEndpoint]] | None = None,
    discovered_websocket_handlers: set[str],
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    allowed_actors = set(registry.get("actors") or [])
    allowed_access_modes = set(registry.get("access_modes") or [])
    if not allowed_actors:
        issues.append(AuditIssue("actors", "registry must define at least one actor"))
    if not allowed_access_modes:
        issues.append(AuditIssue("access_modes", "registry must define at least one access mode"))

    rest_entries, rest_entry_issues = entries_by_path(registry.get("rest_modules"), section="rest_modules")
    ws_entries, ws_entry_issues = entries_by_path(registry.get("websocket_handlers"), section="websocket_handlers")
    issues.extend(rest_entry_issues)
    issues.extend(ws_entry_issues)

    discovered_rest_endpoints = discovered_rest_endpoints or {}

    for path, actual_count in discovered_rest_routes.items():
        entry = rest_entries.get(path)
        if entry is None:
            issues.append(AuditIssue(path, "missing REST route permission registry entry"))
            continue
        issues.extend(
            validate_common_entry(
                entry,
                section="rest_modules",
                allowed_actors=allowed_actors,
                allowed_access_modes=allowed_access_modes,
            )
        )
        expected_count = entry.get("expected_routes")
        if not isinstance(expected_count, int):
            issues.append(AuditIssue(path, "expected_routes must be an integer"))
        elif expected_count != actual_count:
            issues.append(AuditIssue(path, f"expected_routes={expected_count}, discovered={actual_count}"))

        endpoints_by_key, endpoint_issues = endpoint_entries_by_key(entry.get("endpoints"), module_path=path)
        issues.extend(endpoint_issues)
        discovered_endpoints = discovered_rest_endpoints.get(path) or []
        for endpoint in discovered_endpoints:
            endpoint_entry = endpoints_by_key.get(endpoint.key)
            if endpoint_entry is not None:
                issues.extend(
                    validate_endpoint_entry(
                        endpoint_entry,
                        endpoint=endpoint,
                        allowed_actors=allowed_actors,
                        allowed_access_modes=allowed_access_modes,
                    )
                )
                continue
            if entry.get("endpoint_overrides_required") is True:
                issues.append(AuditIssue(endpoint.display_path, "missing endpoint-level permission registry entry"))
                continue
            if entry.get("validate_endpoint_auth_shape") is True:
                effective = effective_endpoint_entry(entry, None)
                actors = set(effective.get("actors") or [])
                issues.extend(validate_endpoint_auth_shape(endpoint, effective, actors, str(effective.get("auth_model") or "")))

        discovered_keys = {endpoint.key for endpoint in discovered_endpoints}
        for key in sorted(set(endpoints_by_key) - discovered_keys):
            issues.append(AuditIssue(f"{path} {key}", "registered endpoint was not discovered"))

    for path in sorted(set(rest_entries) - set(discovered_rest_routes)):
        issues.append(AuditIssue(path, "registered REST route file was not discovered or has no HTTP routes"))

    for path in sorted(discovered_websocket_handlers):
        entry = ws_entries.get(path)
        if entry is None:
            issues.append(AuditIssue(path, "missing WebSocket handler permission registry entry"))
            continue
        issues.extend(
            validate_common_entry(
                entry,
                section="websocket_handlers",
                allowed_actors=allowed_actors,
                allowed_access_modes=allowed_access_modes,
            )
        )

    for path in sorted(set(ws_entries) - discovered_websocket_handlers):
        issues.append(AuditIssue(path, "registered WebSocket handler file was not discovered"))

    return issues


def audit_paths(registry_path: Path, routes_root: Path, ws_root: Path, repo_root: Path) -> tuple[list[AuditIssue], dict[str, int], set[str], dict[str, Any]]:
    registry = load_yaml(registry_path)
    discovered_rest_endpoints = discover_rest_endpoints(routes_root, repo_root)
    discovered_rest_routes = {path: len(endpoints) for path, endpoints in discovered_rest_endpoints.items()}
    discovered_websocket_handlers = discover_websocket_handlers(ws_root, repo_root)
    issues = audit_registry(
        registry,
        discovered_rest_routes=discovered_rest_routes,
        discovered_rest_endpoints=discovered_rest_endpoints,
        discovered_websocket_handlers=discovered_websocket_handlers,
    )
    return issues, discovered_rest_routes, discovered_websocket_handlers, registry


def print_matrix(registry: dict[str, Any], discovered_rest_endpoints: dict[str, list[RestEndpoint]] | None = None) -> None:
    discovered_rest_endpoints = discovered_rest_endpoints or {}
    print("# User Data Permission Matrix")
    print()
    print("## REST Endpoints")
    print("| Module | Method | Route | Function | Auth guards | Auth model | Actors | Access | Data domains | Rationale |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for entry in registry.get("rest_modules") or []:
        endpoints_by_key, _ = endpoint_entries_by_key(entry.get("endpoints"), module_path=str(entry.get("path") or ""))
        for endpoint in discovered_rest_endpoints.get(str(entry.get("path") or ""), []):
            print_endpoint_matrix_row(entry, endpoints_by_key.get(endpoint.key), endpoint)
    print()
    print("## WebSocket Handlers")
    print("| Path | Actors | Access | Data domains | Rationale |")
    print("| --- | --- | --- | --- | --- |")
    for entry in registry.get("websocket_handlers") or []:
        print_matrix_row(entry)


def print_matrix_row(entry: dict[str, Any]) -> None:
    print(
        "| {path} | {actors} | {access} | {domains} | {rationale} |".format(
            path=entry.get("path", ""),
            actors=", ".join(entry.get("actors") or []),
            access=", ".join(entry.get("access") or []),
            domains=", ".join(entry.get("data_domains") or []),
            rationale=str(entry.get("rationale") or "").replace("|", "\\|"),
        )
    )


def print_endpoint_matrix_row(module_entry: dict[str, Any], endpoint_entry: dict[str, Any] | None, endpoint: RestEndpoint) -> None:
    effective = effective_endpoint_entry(module_entry, endpoint_entry)
    print(
        "| {module} | {method} | {route} | {function} | {guards} | {auth_model} | {actors} | {access} | {domains} | {rationale} |".format(
            module=endpoint.module_path,
            method=endpoint.method,
            route=endpoint.route,
            function=endpoint.function,
            guards=", ".join(endpoint.auth_guards) or "none",
            auth_model=effective.get("auth_model") or "module_default",
            actors=", ".join(effective.get("actors") or []),
            access=", ".join(effective.get("access") or []),
            domains=", ".join(effective.get("data_domains") or []),
            rationale=str(effective.get("rationale") or "").replace("|", "\\|"),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit backend user-data permission registry coverage")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY, help="Permission registry YAML path")
    parser.add_argument("--routes-root", type=Path, default=DEFAULT_ROUTES_ROOT, help="Backend REST routes root")
    parser.add_argument("--ws-root", type=Path, default=DEFAULT_WS_ROOT, help="WebSocket handler root")
    parser.add_argument("--matrix", action="store_true", help="Print the reviewed permission matrix after validation")
    args = parser.parse_args()

    registry = load_yaml(args.registry)
    discovered_rest_endpoints = discover_rest_endpoints(args.routes_root, REPO_ROOT)
    discovered_rest_routes = {path: len(endpoints) for path, endpoints in discovered_rest_endpoints.items()}
    discovered_websocket_handlers = discover_websocket_handlers(args.ws_root, REPO_ROOT)
    issues = audit_registry(
        registry,
        discovered_rest_routes=discovered_rest_routes,
        discovered_rest_endpoints=discovered_rest_endpoints,
        discovered_websocket_handlers=discovered_websocket_handlers,
    )
    if issues:
        print("USER DATA PERMISSION AUDIT ISSUES")
        for issue in issues:
            print(f"- {issue.format()}")
        print(f"Summary: {len(issues)} issue(s).")
        return 1

    if args.matrix:
        print_matrix(registry, discovered_rest_endpoints)
    else:
        print(
            "User data permission audit passed for "
            f"{len(discovered_rest_routes)} REST route module(s) and "
            f"{len(discovered_websocket_handlers)} WebSocket handler file(s)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
