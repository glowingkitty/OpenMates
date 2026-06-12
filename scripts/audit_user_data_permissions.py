#!/usr/bin/env python3
"""Audit backend user-data entrypoints against the permission registry.

The registry is the reviewed source of truth for REST route modules and
WebSocket handler files that can touch user data. This script intentionally
fails closed when a backend entrypoint is added, removed, or changes endpoint
count without an explicit registry update. Matrix mode prints the reviewed
actor/access/domain contract for product and security follow-up.
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


@dataclass(frozen=True)
class AuditIssue:
    path: str
    message: str

    def format(self) -> str:
        return f"{self.path}: {self.message}"


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


def route_decorator_name(decorator: ast.expr) -> str | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def count_http_routes(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if route_decorator_name(decorator) in HTTP_ROUTE_DECORATORS:
                count += 1
    return count


def discover_rest_routes(routes_root: Path, repo_root: Path) -> dict[str, int]:
    discovered: dict[str, int] = {}
    for path in sorted(routes_root.rglob("*.py")):
        if path.name == "__init__.py" or "/handlers/" in path.as_posix():
            continue
        route_count = count_http_routes(path)
        if route_count == 0:
            continue
        discovered[relative_path(path, repo_root)] = route_count
    return discovered


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
    discovered_rest_routes = discover_rest_routes(routes_root, repo_root)
    discovered_websocket_handlers = discover_websocket_handlers(ws_root, repo_root)
    issues = audit_registry(
        registry,
        discovered_rest_routes=discovered_rest_routes,
        discovered_websocket_handlers=discovered_websocket_handlers,
    )
    return issues, discovered_rest_routes, discovered_websocket_handlers, registry


def print_matrix(registry: dict[str, Any]) -> None:
    print("# User Data Permission Matrix")
    print()
    print("## REST Modules")
    print("| Path | Actors | Access | Data domains | Rationale |")
    print("| --- | --- | --- | --- | --- |")
    for entry in registry.get("rest_modules") or []:
        print_matrix_row(entry)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit backend user-data permission registry coverage")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY, help="Permission registry YAML path")
    parser.add_argument("--routes-root", type=Path, default=DEFAULT_ROUTES_ROOT, help="Backend REST routes root")
    parser.add_argument("--ws-root", type=Path, default=DEFAULT_WS_ROOT, help="WebSocket handler root")
    parser.add_argument("--matrix", action="store_true", help="Print the reviewed permission matrix after validation")
    args = parser.parse_args()

    issues, discovered_rest_routes, discovered_websocket_handlers, registry = audit_paths(
        args.registry,
        args.routes_root,
        args.ws_root,
        REPO_ROOT,
    )
    if issues:
        print("USER DATA PERMISSION AUDIT ISSUES")
        for issue in issues:
            print(f"- {issue.format()}")
        print(f"Summary: {len(issues)} issue(s).")
        return 1

    if args.matrix:
        print_matrix(registry)
    else:
        print(
            "User data permission audit passed for "
            f"{len(discovered_rest_routes)} REST route module(s) and "
            f"{len(discovered_websocket_handlers)} WebSocket handler file(s)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
