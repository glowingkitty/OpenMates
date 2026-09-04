#!/usr/bin/env python3
"""Provision and manage the private engineering control plane.

Secrets live in one host-level, mode-0600 configuration shared by managed
worktrees. The lifecycle controls only the dedicated compose project and never
invokes, restarts, or reads credentials from the OpenMates product stack.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = PROJECT_ROOT / "deployment" / "engineering_control_plane" / "compose.yml"
CONFIG_DIR = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "openmates"
ENV_FILE = CONFIG_DIR / "engineering-control-plane.env"
MIGRATED_COLLECTIONS = (
    "test_catalog",
    "test_runs",
    "test_results",
    "test_current_state",
    "test_claims",
    "test_debug_campaigns",
    "test_debug_groups",
)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class ControlPlaneApiError(RuntimeError):
    """A structured non-success response from the private API."""

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"control-plane API returned {status}: {detail}")


def _parse_env_file() -> dict[str, str]:
    if not ENV_FILE.is_file():
        raise RuntimeError(f"Control-plane configuration is missing: {ENV_FILE}; run setup first")
    values: dict[str, str] = {}
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _write_new_configuration(*, rotate: bool) -> None:
    if ENV_FILE.exists() and not rotate:
        current_mode = stat.S_IMODE(ENV_FILE.stat().st_mode)
        if current_mode != 0o600:
            ENV_FILE.chmod(0o600)
        return
    database_password = secrets.token_urlsafe(36)
    api_token = secrets.token_urlsafe(48)
    token_sha256 = hashlib.sha256(api_token.encode("utf-8")).hexdigest()
    identities = json.dumps(
        {
            "host": {
                "token_sha256": token_sha256,
                "scopes": ["read", "ingest", "coordinate", "admin"],
            }
        },
        separators=(",", ":"),
    )
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    content = "\n".join(
        [
            "# Generated private engineering-control-plane configuration.",
            f"ENGINEERING_CONTROL_PLANE_DB_PASSWORD={database_password}",
            "ENGINEERING_CONTROL_PLANE_PORT=8091",
            "ENGINEERING_CONTROL_PLANE_URL=http://127.0.0.1:8091",
            f"ENGINEERING_CONTROL_PLANE_API_TOKEN={api_token}",
            f"ENGINEERING_CONTROL_PLANE_IDENTITIES_JSON='{identities}'",
            "",
        ]
    )
    temporary = ENV_FILE.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(ENV_FILE)


def _compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE), *arguments],
        cwd=PROJECT_ROOT,
        check=check,
        text=True,
    )


def _request_health(*, wait_seconds: float = 0) -> dict[str, object]:
    values = _parse_env_file()
    request = urllib.request.Request(
        f"{values['ENGINEERING_CONTROL_PLANE_URL'].rstrip('/')}/health/ready",
        headers={"Authorization": f"Bearer {values['ENGINEERING_CONTROL_PLANE_API_TOKEN']}"},
    )
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError) as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Control plane is not ready: {exc}") from exc
            time.sleep(0.5)


def _api_request(
    method: str,
    path: str,
    *,
    data: dict[str, object] | None = None,
    expected_status: int = 200,
) -> dict[str, object]:
    try:
        response = control_plane_api_request(method, path, data=data)
        if expected_status != 200:
            raise RuntimeError(f"Control-plane API unexpectedly succeeded; expected status {expected_status}")
        return response
    except ControlPlaneApiError as exc:
        if exc.status == expected_status:
            try:
                return json.loads(exc.detail)
            except json.JSONDecodeError:
                return {"detail": exc.detail}
        raise RuntimeError(f"Control-plane API request failed: {method} {path}: {exc}") from exc


def control_plane_api_request(
    method: str,
    path: str,
    *,
    data: dict[str, object] | None = None,
    timeout: int = 30,
) -> dict[str, object]:
    values = _parse_env_file()
    request = urllib.request.Request(
        f"{values['ENGINEERING_CONTROL_PLANE_URL'].rstrip('/')}{path}",
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {values['ENGINEERING_CONTROL_PLANE_API_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ControlPlaneApiError(exc.code, detail) from exc


def command_setup(args: argparse.Namespace) -> int:
    _write_new_configuration(rotate=args.rotate)
    _compose("up", "-d", "--build")
    print(json.dumps(_request_health(wait_seconds=30), sort_keys=True))
    return 0


def command_start(_: argparse.Namespace) -> int:
    _compose("up", "-d")
    print(json.dumps(_request_health(wait_seconds=30), sort_keys=True))
    return 0


def command_stop(_: argparse.Namespace) -> int:
    _compose("stop")
    return 0


def command_status(_: argparse.Namespace) -> int:
    print(json.dumps(_request_health(), sort_keys=True))
    return 0


def command_verify(_: argparse.Namespace) -> int:
    suffix = secrets.token_hex(6)
    lease_key = f"verify-lease-{suffix}"
    conflicting_lease_key = f"verify-conflict-{suffix}"
    operation_key = f"verify-operation-{suffix}"
    epoch_before = int(_api_request("GET", "/v1/coordination/runtime-epoch")["runtime_epoch"])
    dispatch_payload = {
        "repository": "OpenMates",
        "commit": f"verification-{suffix}",
        "tests": ["control-plane::verification"],
        "profile": "verification",
        "account": "none",
        "mocks": {},
        "required_services": [],
    }
    first_dispatch = _api_request("POST", "/v1/coordination/dispatches", data=dispatch_payload)
    reused_dispatch = _api_request("POST", "/v1/coordination/dispatches", data=dispatch_payload)
    if reused_dispatch["reused"] is not True:
        raise RuntimeError("Equivalent dispatch was not reused")
    dispatch_key = str(first_dispatch["dispatch"]["dispatch_key"])
    if reused_dispatch["dispatch"]["dispatch_key"] != dispatch_key:
        raise RuntimeError("Equivalent dispatch resolved to a different key")
    _api_request(
        "PATCH",
        f"/v1/coordination/dispatches/{dispatch_key}",
        data={"status": "running"},
    )
    _api_request(
        "PATCH",
        f"/v1/coordination/dispatches/{dispatch_key}",
        data={"status": "succeeded"},
    )
    _api_request(
        "POST",
        "/v1/coordination/leases",
        data={
            "lease_key": lease_key,
            "owner_key": "verification",
            "resources": ["verification-runtime"],
            "ttl_seconds": 120,
        },
    )
    queued = _api_request(
        "POST",
        "/v1/coordination/runtime-operations",
        data={
            "operation_key": operation_key,
            "operation_type": "verification",
            "resources": ["verification-runtime"],
            "metadata": {},
        },
    )
    if queued["operation"]["status"] != "queued":
        raise RuntimeError("Runtime operation was not queued behind the active lease")
    _api_request(
        "POST",
        "/v1/coordination/leases",
        data={
            "lease_key": conflicting_lease_key,
            "owner_key": "verification-conflict",
            "resources": ["verification-runtime"],
            "ttl_seconds": 120,
        },
        expected_status=409,
    )
    _api_request("DELETE", f"/v1/coordination/leases/{lease_key}")
    admitted = _api_request(
        "PATCH",
        f"/v1/coordination/runtime-operations/{operation_key}",
        data={"status": "restarting", "metadata": {}},
    )
    if admitted["operation"]["status"] != "restarting":
        raise RuntimeError("Queued runtime operation was not admitted after lease release")
    _api_request(
        "PATCH",
        f"/v1/coordination/runtime-operations/{operation_key}",
        data={"status": "completed", "metadata": {"verification": "passed"}},
    )
    epoch_after = int(_api_request("GET", "/v1/coordination/runtime-epoch")["runtime_epoch"])
    if epoch_after != epoch_before + 1:
        raise RuntimeError("Completed runtime operation did not advance the runtime epoch exactly once")
    after_restart = _api_request("POST", "/v1/coordination/dispatches", data=dispatch_payload)
    if after_restart["reused"] is not False or after_restart["dispatch"]["dispatch_key"] == dispatch_key:
        raise RuntimeError("Runtime epoch did not invalidate the prior dispatch fingerprint")
    event = _api_request(
        "POST",
        "/v1/coordination/events",
        data={
            "event_type": "task.changed",
            "target_type": "session",
            "target_key": f"verification-target-{suffix}",
            "subject_key": f"verification-subject-{suffix}",
            "payload": {"state": "ready"},
        },
    )["event"]
    query = urllib.parse.urlencode(
        {
            "target_type": "session",
            "target_key": f"verification-target-{suffix}",
            "after_cursor": 0,
        }
    )
    events = _api_request("GET", f"/v1/coordination/events?{query}")["events"]
    if [item["event_key"] for item in events] != [event["event_key"]]:
        raise RuntimeError("Cursor event handoff did not return the published event")
    acknowledged = _api_request(
        "POST",
        f"/v1/coordination/events/{event['event_key']}/acknowledgements",
        data={"recipient": "verification-recipient"},
    )
    duplicate_ack = _api_request(
        "POST",
        f"/v1/coordination/events/{event['event_key']}/acknowledgements",
        data={"recipient": "verification-recipient"},
    )
    if acknowledged["acknowledged"] is not True or duplicate_ack["acknowledged"] is not False:
        raise RuntimeError("Event acknowledgement was not idempotent")
    print(
        json.dumps(
            {
                "lease_exclusion": "passed",
                "operation_queue": "passed",
                "dispatch_reuse": "passed",
                "runtime_epoch_invalidation": "passed",
                "event_cursor_acknowledgement": "passed",
                "runtime_epoch_before": epoch_before,
                "runtime_epoch_after": epoch_after,
            },
            sort_keys=True,
        )
    )
    return 0


def command_operation_begin(args: argparse.Namespace) -> int:
    operation_key = args.operation_key or f"{args.operation_type}-{secrets.token_hex(8)}"
    try:
        response = control_plane_api_request(
            "POST",
            "/v1/coordination/runtime-operations",
            data={
                "operation_key": operation_key,
                "operation_type": args.operation_type,
                "resources": args.resource,
                "metadata": {
                    "session_id": args.requested_by,
                    "services": args.service,
                    "owner_pid": os.getpid(),
                    "owner_host": os.uname().nodename,
                },
            },
        )
    except ControlPlaneApiError as exc:
        raise RuntimeError(f"Runtime operation admission failed: {exc.detail}") from exc
    deadline = time.monotonic() + args.timeout
    while response["operation"]["status"] == "queued":
        blockers = control_plane_api_request(
            "GET",
            f"/v1/coordination/runtime-operations/{operation_key}/blocking-leases",
        ).get("leases") or []
        if not blockers:
            break
        if time.monotonic() >= deadline:
            control_plane_api_request(
                "PATCH",
                f"/v1/coordination/runtime-operations/{operation_key}",
                data={"status": "failed", "metadata": {"failure_class": "lease_wait_timeout"}},
            )
            raise RuntimeError(f"Timed out waiting for {len(blockers)} active engineering test lease(s)")
        time.sleep(min(1, max(0.1, deadline - time.monotonic())))
    print(json.dumps({"operation_key": operation_key, "status": "admitted"}, sort_keys=True))
    return 0


def command_operation_update(args: argparse.Namespace) -> int:
    response = control_plane_api_request(
        "PATCH",
        f"/v1/coordination/runtime-operations/{args.operation_key}",
        data={"status": args.status, "metadata": {"failure_class": args.failure_class} if args.failure_class else {}},
    )
    print(
        json.dumps(
            {
                "operation_key": args.operation_key,
                "status": response["operation"]["status"],
            },
            sort_keys=True,
        )
    )
    return 0


def _load_tests_control_module():
    path = PROJECT_ROOT / "scripts" / "tests.py"
    spec = importlib.util.spec_from_file_location("engineering_control_plane_migration_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load test control module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _local_postgres_rows(
    collection: str,
    key_field: str,
    *,
    authoritative_unix: int,
) -> list[dict[str, object]]:
    where_sql = ""
    if collection == "test_results":
        detail_cutoff = authoritative_unix - (14 * 24 * 60 * 60)
        where_sql = (
            f"WHERE created_at_unix >= {detail_cutoff} "
            "OR result_key IN ("
            "SELECT DISTINCT ON (test_key) result_key FROM test_results "
            "WHERE test_key IS NOT NULL ORDER BY test_key, created_at_unix DESC"
            ")"
        )
    sql = (
        "SELECT COALESCE(json_agg(row_to_json(source_rows)), '[]'::json) "
        f"FROM (SELECT * FROM {collection} {where_sql} ORDER BY {key_field}) source_rows;"
    )
    result = subprocess.run(
        [
            "docker",
            "exec",
            "cms-database",
            "sh",
            "-c",
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c "$1"',
            "sh",
            sql,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to export {collection} from local product PostgreSQL: {result.stderr.strip()}")
    payload = json.loads(result.stdout.strip() or "[]")
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected export payload for {collection}")
    return payload


def _normalized_source_records(
    module,
    *,
    source_kind: str,
    authoritative_unix: int,
) -> dict[str, list[dict[str, object]]]:
    from backend.engineering_control_plane.records import schema_for

    source = module.DirectusTestControlStore() if source_kind == "directus" else None
    collections: dict[str, list[dict[str, object]]] = {}
    for collection in MIGRATED_COLLECTIONS:
        schema = schema_for(collection)
        rows = (
            source._items(collection, params={"limit": -1, "sort": schema.key})
            if source is not None
            else _local_postgres_rows(
                collection,
                schema.key,
                authoritative_unix=authoritative_unix,
            )
        )
        normalized = [
            {field: row[field] for field in schema.fields if field in row and row[field] is not None}
            for row in rows
        ]
        if collection == "test_claims":
            for record in normalized:
                expires_at_unix = int(record.get("expires_at_unix") or 0)
                if record.get("status") == "active" and expires_at_unix <= authoritative_unix:
                    record["status"] = "expired"
        collections[collection] = normalized
    return collections


def _parity_digest(records: list[dict[str, object]]) -> str:
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def command_migrate_directus(args: argparse.Namespace) -> int:
    module = _load_tests_control_module()
    authoritative_unix = int(time.time())
    source = _normalized_source_records(
        module,
        source_kind=args.source,
        authoritative_unix=authoritative_unix,
    )
    summary = {collection: len(records) for collection, records in source.items()}
    if args.dry_run:
        print(json.dumps({"source_counts": summary, "applied": False}, sort_keys=True))
        return 0
    target = module.ControlPlaneTestControlStore()
    target._import(source, replace_current_state=True)
    mismatches: dict[str, dict[str, object]] = {}
    from backend.engineering_control_plane.records import schema_for

    for collection, source_records in source.items():
        schema = schema_for(collection)
        target_rows = target._records(collection, sort=schema.key)
        target_by_key = {str(row[schema.key]): row for row in target_rows}
        projected_target = [
            {field: target_by_key[str(record[schema.key])].get(field) for field in record}
            for record in source_records
            if str(record[schema.key]) in target_by_key
        ]
        source_keys = sorted(str(record[schema.key]) for record in source_records)
        target_keys = sorted(target_by_key)
        source_projection = sorted(source_records, key=lambda record: str(record[schema.key]))
        target_projection = sorted(projected_target, key=lambda record: str(record[schema.key]))
        if source_keys != target_keys or _parity_digest(source_projection) != _parity_digest(target_projection):
            mismatches[collection] = {
                "source_count": len(source_records),
                "target_count": len(target_rows),
                "source_digest": _parity_digest(source_projection),
                "target_digest": _parity_digest(target_projection),
            }
    if mismatches:
        print(json.dumps({"source_counts": summary, "mismatches": mismatches}, sort_keys=True), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "source_counts": summary,
                "applied": True,
                "parity": "passed",
                "authoritative_unix": authoritative_unix,
            },
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    setup = subparsers.add_parser("setup", help="Generate dedicated secrets and start the service")
    setup.add_argument("--rotate", action="store_true", help="Replace existing local credentials")
    setup.set_defaults(handler=command_setup)
    start = subparsers.add_parser("start", help="Start an already configured service")
    start.set_defaults(handler=command_start)
    stop = subparsers.add_parser("stop", help="Stop only the engineering control plane")
    stop.set_defaults(handler=command_stop)
    status = subparsers.add_parser("status", help="Check database and migration readiness")
    status.set_defaults(handler=command_status)
    verify = subparsers.add_parser("verify", help="Exercise real lease, queue, and runtime-epoch transactions")
    verify.set_defaults(handler=command_verify)
    operation = subparsers.add_parser("operation", help="Coordinate a product-runtime mutation")
    operation_subparsers = operation.add_subparsers(dest="operation_action", required=True)
    operation_begin = operation_subparsers.add_parser("begin", help="Wait for leases and admit a mutation")
    operation_begin.add_argument("--operation-key", default="")
    operation_begin.add_argument("--operation-type", required=True)
    operation_begin.add_argument("--requested-by", required=True)
    operation_begin.add_argument("--resource", action="append", required=True)
    operation_begin.add_argument("--service", action="append", default=[])
    operation_begin.add_argument("--timeout", type=int, default=900)
    operation_begin.set_defaults(handler=command_operation_begin)
    operation_update = operation_subparsers.add_parser("update", help="Record mutation completion or failure")
    operation_update.add_argument("--operation-key", required=True)
    operation_update.add_argument("--status", choices=("completed", "failed", "cancelled"), required=True)
    operation_update.add_argument("--failure-class", default="")
    operation_update.set_defaults(handler=command_operation_update)
    migrate = subparsers.add_parser("migrate-directus", help="Import and compare the seven legacy Directus collections")
    migrate.add_argument("--dry-run", action="store_true", help="Read and count source records without writing")
    migrate.add_argument("--source", choices=("local-postgres", "directus"), default="local-postgres")
    migrate.set_defaults(handler=command_migrate_directus)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
