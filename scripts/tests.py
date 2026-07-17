#!/usr/bin/env python3
"""
scripts/tests.py

Unified test control plane for OpenMates test debugging.
It wraps the existing GitHub Actions-backed runner, persists current test state,
records an append-only timeline, deterministically triages failures, and leases
the next failure group so parallel debugging sessions do not collide.

Architecture: docs/architecture/test-orchestration.md
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "test-results"
STATE_FILE = RESULTS_DIR / "tests-state.json"
HISTORY_FILE = RESULTS_DIR / "tests-history.jsonl"
LEASES_FILE = RESULTS_DIR / "failed-test-leases.json"
TRIAGE_FILE = RESULTS_DIR / "test-failure-triage.json"
TEST_FILE_INDEX_FILE = RESULTS_DIR / "test-file-index.json"
RUNS_DIR = RESULTS_DIR / "runs"
LEASE_LOCK_FILE = Path("/tmp/openmates-failed-test-leases.lock")
SPEC_DIR = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"
RUN_TESTS_SCRIPT = PROJECT_ROOT / "scripts" / "run_tests.py"
TEST_STORE = None

PROBLEM_STATUSES = {"failed", "dispatch_error", "timeout", "result_unknown"}
LEASE_TTL_HOURS = 8
MAX_LINKED_FILES = 12

CATEGORY_PRIORITY = {
    "environment_blocked": 5,
    "account_preflight": 10,
    "auth_signup": 20,
    "chat_sync_encryption": 30,
    "chat_send_receive": 40,
    "payments_billing": 50,
    "ai_response": 60,
    "embed_rendering": 70,
    "app_skill": 80,
    "cli_auth": 90,
    "provider_external": 100,
    "github_actions_wrapper": 110,
    "missing_element": 120,
    "timeout": 130,
    "unit_regression": 140,
    "test_infra": 150,
    "unknown": 999,
}

API_KEY_DEVICE_APPROVAL_MARKERS = (
    "approved_device_required",
    "new device detected",
    "device not approved",
    "a new device attempted to use your api key",
    "please review and approve it in developer settings",
)

KEYWORD_LINKS = {
    "chat": [
        "frontend/packages/ui/src/components/ChatHistory.svelte",
        "frontend/packages/ui/src/components/ChatMessage.svelte",
        "frontend/packages/ui/src/components/enter_message/MessageInput.svelte",
    ],
    "send-message": [
        "frontend/packages/ui/src/components/enter_message/MessageInput.svelte",
    ],
    "message-assistant": [
        "frontend/packages/ui/src/components/ChatMessage.svelte",
        "frontend/packages/ui/src/components/ChatHistory.svelte",
    ],
    "chat-header": [
        "frontend/packages/ui/src/components/ChatHeader.svelte",
    ],
    "signup": [
        "frontend/apps/web_app/tests/helpers/signup-flow-helpers.ts",
    ],
    "login": [
        "frontend/apps/web_app/tests/helpers/signup-flow-helpers.ts",
    ],
    "embed": [
        "frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte",
        "frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte",
        "frontend/packages/ui/src/components/embeds/registry.ts",
    ],
    "application-preview": [
        "frontend/packages/ui/src/components/embeds/application/ApplicationPreview.svelte",
    ],
    "focus-mode": [
        "frontend/packages/ui/src/components/focus_modes/FocusModeBar.svelte",
    ],
    "reminder": [
        "backend/apps/reminders/",
    ],
    "api-key": [
        "frontend/apps/web_app/tests/api-keys-flow.spec.ts",
    ],
}

SOURCE_SCAN_ROOTS = (
    "frontend/apps/web_app/tests",
    "frontend/packages/ui/src",
    "frontend/packages/openmates-cli/src",
    "backend/apps",
    "backend/core",
    "backend/shared",
    "backend/tests",
    "scripts",
)

SOURCE_SCAN_SUFFIXES = {".svelte", ".ts", ".tsx", ".js", ".mjs", ".py", ".swift"}
_SOURCE_TEXT_CACHE: dict[str, str] | None = None


def _copy_json(data: Any) -> Any:
    return json.loads(json.dumps(data))


class InMemoryTestControlStore:
    """Directus-shaped test control-plane store used by deterministic tests."""

    def __init__(self) -> None:
        self.test_catalog: dict[str, dict[str, Any]] = {}
        self.test_runs: dict[str, dict[str, Any]] = {}
        self.test_results: dict[str, dict[str, Any]] = {}
        self.current_state: dict[str, dict[str, Any]] = {}
        self.test_claims: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []
        self.state: dict[str, Any] = {"summary": {}, "tests": {}, "updated_at": None}

    def load_state(self) -> dict[str, Any]:
        return _copy_json(self.state)

    def load_history_events(self, days: int = 7) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        events = []
        for event in self.history:
            timestamp = parse_utc(str(event.get("timestamp") or ""))
            if timestamp is None or timestamp >= cutoff:
                events.append(_copy_json(event))
        return events

    def save_current_state(self, state: dict[str, Any], events: list[dict[str, Any]]) -> None:
        self.state = _copy_json(state)
        self.history.extend(_copy_json(events))
        started_by_run: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            if event.get("event") == "started" and event.get("run_id"):
                started_by_run.setdefault(str(event["run_id"]), []).append(event)
        for run_key, run_events in started_by_run.items():
            self.test_runs[run_key] = {
                "run_key": run_key,
                "source": "scripts_tests",
                "status": "running",
                "requested_tests": [event.get("key") for event in run_events],
                "command": run_events[0].get("command"),
                "summary": {},
                "updated_at": state.get("updated_at"),
            }
        for key, record in (state.get("tests") or {}).items():
            self._upsert_catalog(key, record)
            self.current_state[key] = _copy_json(record)

    def record_run_result(self, run_data: dict[str, Any], state: dict[str, Any], events: list[dict[str, Any]], source: str = "scripts_tests", external_run_id: str = "", workflow: str = "") -> None:
        run_key = str(run_data.get("run_id") or state.get("latest_run_id") or utc_now())
        self.test_runs[run_key] = {
            "run_key": run_key,
            "source": source,
            "external_run_id": external_run_id,
            "workflow": workflow,
            "status": "completed",
            "git_sha": run_data.get("git_sha"),
            "git_branch": run_data.get("git_branch"),
            "environment": run_data.get("environment"),
            "requested_tests": run_data.get("requested_tests") or [],
            "summary": run_data.get("summary") or {},
            "record_json": _copy_json(run_data),
            "updated_at": state.get("updated_at"),
        }
        self.save_current_state(state, events)
        for suite, test in iter_tests(run_data):
            key = test_key(suite, test)
            record = (state.get("tests") or {}).get(key, {})
            result_key = f"{run_key}:{key}:attempt-{int(test.get('attempt') or 1)}"
            self.test_results[result_key] = {
                "result_key": result_key,
                "run_key": run_key,
                "test_key": key,
                "suite": suite,
                "test_name": record.get("test") or test_label(suite, test),
                "status": test.get("status") or "unknown",
                "error_summary": test.get("error"),
                "metadata": _copy_json(test),
            }

    def _upsert_catalog(self, key: str, record: dict[str, Any]) -> None:
        self.test_catalog[key] = {
            "test_key": key,
            "suite": record.get("suite"),
            "test_name": record.get("test"),
            "file_path": record.get("test"),
            "verification_command": record.get("verification_command") or verification_command(record),
            "metadata": {"linked_files": record.get("linked_files") or []},
        }

    def list_claims(self) -> list[dict[str, Any]]:
        return [_copy_json(claim) for claim in self.test_claims.values()]

    def create_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        self.test_claims[claim["lease_id"]] = _copy_json(claim)
        return _copy_json(claim)

    def update_claim(self, lease_id: str, status: str, fields: dict[str, Any]) -> dict[str, Any]:
        if lease_id not in self.test_claims:
            raise RuntimeError(f"Unknown lease id: {lease_id}")
        claim = self.test_claims[lease_id]
        claim["status"] = status
        claim["updated_at"] = utc_now()
        claim.update(fields)
        return _copy_json(claim)


class DirectusTestControlStore(InMemoryTestControlStore):
    """Directus REST-backed test control-plane store."""

    def __init__(self) -> None:
        super().__init__()
        self.base_url = self._resolve_base_url()
        self.token = os.getenv("DIRECTUS_TOKEN") or self._mint_local_dev_token()

    def _resolve_base_url(self) -> str:
        configured = os.getenv("CMS_URL")
        if configured:
            return configured.rstrip("/")
        # scripts/tests.py is normally run from the host, where the Docker
        # service hostname `cms` is not resolvable. The local dev compose stack
        # publishes Directus on loopback.
        return "http://127.0.0.1:8055"

    def _mint_local_dev_token(self) -> str | None:
        if os.getenv("OPENMATES_DISABLE_DOCKER_DIRECTUS_TOKEN") == "1":
            return None
        command = [
            "docker",
            "exec",
            "api",
            "python3",
            "-c",
            (
                "import json, os, urllib.request;"
                "base=os.getenv('CMS_URL','http://cms:8055').rstrip('/');"
                "email=os.getenv('DATABASE_ADMIN_EMAIL');"
                "password=os.getenv('DATABASE_ADMIN_PASSWORD');"
                "assert email and password;"
                "body=json.dumps({'email': email, 'password': password}).encode();"
                "req=urllib.request.Request(base + '/auth/login', data=body, "
                "headers={'Content-Type':'application/json'}, method='POST');"
                "print(json.loads(urllib.request.urlopen(req, timeout=10).read().decode())['data']['access_token'])"
            ),
        ]
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return None
        token = result.stdout.strip()
        return token or None

    def _require_token(self) -> str:
        if not self.token:
            self.token = self._mint_local_dev_token()
        if not self.token:
            raise RuntimeError(
                "DIRECTUS_TOKEN is required for the Directus test control plane, "
                "or the local dev Docker api container must be running so scripts/tests.py can mint a short-lived token"
            )
        return self.token

    def _refresh_token_after_unauthorized(self) -> bool:
        refreshed = self._mint_local_dev_token()
        if not refreshed:
            return False
        self.token = refreshed
        return True

    def _request_once(self, method: str, path: str, token: str, data: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> Any:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        body = json.dumps(data).encode("utf-8") if data is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}{query}",
            data=body,
            method=method,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
        if not payload:
            return None
        decoded = json.loads(payload)
        return decoded.get("data") if isinstance(decoded, dict) and "data" in decoded else decoded

    def _request(self, method: str, path: str, data: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> Any:
        token = self._require_token()
        try:
            return self._request_once(method, path, token, data=data, params=params)
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and self._refresh_token_after_unauthorized():
                try:
                    return self._request_once(method, path, self._require_token(), data=data, params=params)
                except urllib.error.URLError as retry_exc:
                    raise RuntimeError(f"Directus test control-plane request failed after token refresh: {method} {path}: {retry_exc}") from retry_exc
            raise RuntimeError(f"Directus test control-plane request failed: {method} {path}: {exc}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Directus test control-plane request failed: {method} {path}: {exc}") from exc

    def _items(self, collection: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        data = self._request("GET", f"/items/{collection}", params=params)
        return data if isinstance(data, list) else []

    def _upsert(self, collection: str, unique_field: str, item: dict[str, Any]) -> dict[str, Any]:
        value = str(item[unique_field])
        params = {"filter": json.dumps({unique_field: {"_eq": value}}), "limit": 1}
        existing = self._items(collection, params=params)
        if existing:
            directus_id = existing[0].get("id")
            return self._request("PATCH", f"/items/{collection}/{directus_id}", data=item)
        item = {"id": str(uuid.uuid4()), **item}
        return self._request("POST", f"/items/{collection}", data=item)

    def load_state(self) -> dict[str, Any]:
        rows = self._items("test_current_state", params={"limit": -1, "sort": "test_key"})
        tests = {str(row.get("test_key")): self._state_row_to_record(row) for row in rows if row.get("test_key")}
        latest_run_id = self._latest_current_state_run(rows)
        return {
            "latest_run_id": latest_run_id,
            "updated_at": utc_now(),
            "summary": summarize_current_tests(tests),
            "tests": tests,
            "recorded_event_ids": [],
        }

    def _latest_current_state_run(self, rows: list[dict[str, Any]]) -> str:
        counts: dict[str, int] = {}
        for row in rows:
            run_key = str(row.get("stable_run_key") or row.get("active_run_key") or "")
            if run_key:
                counts[run_key] = counts.get(run_key, 0) + 1
        if not counts:
            return ""
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def _state_row_to_record(self, row: dict[str, Any]) -> dict[str, Any]:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        status = row.get("stable_status") or row.get("active_status") or "unknown"
        return {
            **metadata,
            "key": row.get("test_key"),
            "suite": row.get("suite"),
            "test": row.get("test_name"),
            "status": status,
            "stable_status": row.get("stable_status"),
            "stable_result_key": row.get("stable_result_key"),
            "stable_run_id": row.get("stable_run_key"),
            "active_status": row.get("active_status"),
            "active_run_id": row.get("active_run_key"),
            "run_id": row.get("stable_run_key") or row.get("active_run_key"),
            "error": row.get("error_summary"),
            "updated_at": row.get("updated_at"),
        }

    def load_history_events(self, days: int = 7) -> list[dict[str, Any]]:
        rows = self._items("test_results", params={"limit": -1, "sort": "-created_at_unix"})
        events = []
        for row in rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            events.append({
                **metadata,
                "suite": row.get("suite"),
                "test": row.get("test_name"),
                "key": row.get("test_key"),
                "event": "failed" if is_problem(str(row.get("status") or "")) else row.get("status"),
                "status": row.get("status"),
                "run_id": row.get("run_key"),
                "timestamp": row.get("created_at") or utc_now(),
                "error": row.get("error_summary"),
            })
        return events

    def save_current_state(self, state: dict[str, Any], events: list[dict[str, Any]]) -> None:
        if len(state.get("tests") or {}) > 100 and self._bulk_local_postgres_import(None, state, events):
            return
        started_by_run: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            if event.get("event") == "started" and event.get("run_id"):
                started_by_run.setdefault(str(event["run_id"]), []).append(event)
        for run_key, run_events in started_by_run.items():
            self._upsert("test_runs", "run_key", {
                "run_key": run_key,
                "source": "scripts_tests",
                "status": "running",
                "requested_tests": [event.get("key") for event in run_events],
                "summary": {},
                "record_json": {"events": run_events, "command": run_events[0].get("command")},
                "updated_at": state.get("updated_at"),
                "updated_at_unix": int(datetime.now(timezone.utc).timestamp()),
            })
        for key, record in (state.get("tests") or {}).items():
            self._upsert("test_catalog", "test_key", self._catalog_item(key, record))
            self._upsert("test_current_state", "test_key", self._current_state_item(key, record))
        for event in events:
            result_key = str(event.get("event_id") or f"{event.get('run_id')}:{event.get('key')}:{event.get('event')}")
            self._upsert("test_results", "result_key", self._result_item(result_key, event))

    def record_run_result(self, run_data: dict[str, Any], state: dict[str, Any], events: list[dict[str, Any]], source: str = "scripts_tests", external_run_id: str = "", workflow: str = "") -> None:
        if len(state.get("tests") or {}) > 100 and self._bulk_local_postgres_import(run_data, state, events, source=source, external_run_id=external_run_id, workflow=workflow):
            return
        run_key = str(run_data.get("run_id") or state.get("latest_run_id") or utc_now())
        self._upsert("test_runs", "run_key", {
            "run_key": run_key,
            "source": source,
            "external_run_id": external_run_id,
            "workflow": workflow,
            "status": "completed",
            "git_sha": run_data.get("git_sha"),
            "git_branch": run_data.get("git_branch"),
            "environment": run_data.get("environment"),
            "requested_tests": run_data.get("requested_tests") or [],
            "summary": run_data.get("summary") or {},
            "record_json": run_data,
            "updated_at": state.get("updated_at"),
            "updated_at_unix": int(datetime.now(timezone.utc).timestamp()),
        })
        self.save_current_state(state, events)

    def _catalog_item(self, key: str, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "test_key": key,
            "suite": record.get("suite"),
            "test_name": record.get("test"),
            "file_path": record.get("test"),
            "verification_command": record.get("verification_command") or verification_command(record),
            "metadata": {"linked_files": record.get("linked_files") or []},
        }

    def _current_state_item(self, key: str, record: dict[str, Any]) -> dict[str, Any]:
        status = record.get("status")
        active_status = record.get("active_status") or ("running" if status == "running" else None)
        stable_status = record.get("stable_status") or (status if status != "running" else None)
        return {
            "test_key": key,
            "suite": record.get("suite"),
            "test_name": record.get("test"),
            "stable_status": stable_status,
            "stable_result_key": record.get("stable_result_key"),
            "stable_run_key": record.get("stable_run_id") or (record.get("run_id") if record.get("status") != "running" else None),
            "active_status": active_status,
            "active_run_key": record.get("active_run_id") or (record.get("run_id") if active_status else None),
            "triage_group_id": record.get("triage_group_id"),
            "error_summary": record.get("error"),
            "metadata": record,
            "updated_at": record.get("updated_at"),
            "updated_at_unix": int(datetime.now(timezone.utc).timestamp()),
        }

    def _result_item(self, result_key: str, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "result_key": result_key,
            "run_key": record.get("run_id"),
            "test_key": record.get("key"),
            "suite": record.get("suite"),
            "test_name": record.get("test"),
            "status": record.get("status") or record.get("event"),
            "error_summary": record.get("error"),
            "metadata": record,
            "created_at": record.get("timestamp"),
            "created_at_unix": int(datetime.now(timezone.utc).timestamp()),
        }

    def _bulk_local_postgres_import(self, run_data: dict[str, Any] | None, state: dict[str, Any], events: list[dict[str, Any]], source: str = "scripts_tests", external_run_id: str = "", workflow: str = "") -> bool:
        if os.getenv("OPENMATES_DISABLE_FAST_TEST_IMPORT") == "1":
            return False
        probe = subprocess.run(["docker", "exec", "cms-database", "true"], check=False, capture_output=True, text=True, timeout=10)
        if probe.returncode != 0:
            return False

        run_key = str((run_data or {}).get("run_id") or state.get("latest_run_id") or utc_now())
        tests = state.get("tests") or {}
        catalog = [self._catalog_item(str(key), record) for key, record in tests.items()]
        current_state = [self._current_state_item(str(key), record) for key, record in tests.items()]
        result_rows = []
        for event in events:
            result_key = str(event.get("event_id") or f"{event.get('run_id')}:{event.get('key')}:{event.get('event')}")
            result_rows.append(self._result_item(result_key, event))
        run_rows = self._bulk_run_rows(run_data, state, events, source, external_run_id, workflow, run_key)
        payload = {
            "runs": run_rows,
            "catalog": catalog,
            "current_state": current_state,
            "results": result_rows,
        }
        host_file = None
        container_file = f"/tmp/openmates-test-import-{uuid.uuid4().hex}.json"
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
                host_file = handle.name
                json.dump(payload, handle, separators=(",", ":"))
                handle.write("\n")
            subprocess.run(["docker", "cp", host_file, f"cms-database:{container_file}"], check=True, capture_output=True, text=True, timeout=30)
            subprocess.run(["docker", "exec", "cms-database", "chmod", "0644", container_file], check=True, capture_output=True, text=True, timeout=10)
            sql = self._bulk_import_sql(container_file)
            result = subprocess.run(
                ["docker", "exec", "-i", "cms-database", "sh", "-lc", 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'],
                input=sql,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                print(result.stderr, file=sys.stderr)
                return False
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"Fast Directus test import unavailable: {exc}", file=sys.stderr)
            return False
        finally:
            if host_file:
                Path(host_file).unlink(missing_ok=True)
            subprocess.run(["docker", "exec", "cms-database", "rm", "-f", container_file], check=False, capture_output=True, text=True, timeout=10)

    def _bulk_run_rows(self, run_data: dict[str, Any] | None, state: dict[str, Any], events: list[dict[str, Any]], source: str, external_run_id: str, workflow: str, run_key: str) -> list[dict[str, Any]]:
        timestamp = state.get("updated_at") or utc_now()
        now_unix = int(datetime.now(timezone.utc).timestamp())
        started_by_run: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            if event.get("event") == "started" and event.get("run_id"):
                started_by_run.setdefault(str(event["run_id"]), []).append(event)
        if started_by_run:
            return [{
                "run_key": key,
                "source": "scripts_tests",
                "external_run_id": "",
                "workflow": "",
                "status": "running",
                "git_sha": state.get("latest_git_sha"),
                "git_branch": state.get("latest_git_branch"),
                "environment": state.get("environment"),
                "requested_tests": [event.get("key") for event in run_events],
                "summary": {},
                "record_json": {"events": run_events, "command": run_events[0].get("command")},
                "updated_at": timestamp,
                "updated_at_unix": now_unix,
            } for key, run_events in started_by_run.items()]
        return [{
            "run_key": run_key,
            "source": source,
            "external_run_id": external_run_id,
            "workflow": workflow,
            "status": "completed" if run_data else "snapshot",
            "git_sha": (run_data or {}).get("git_sha") or state.get("latest_git_sha"),
            "git_branch": (run_data or {}).get("git_branch") or state.get("latest_git_branch"),
            "environment": (run_data or {}).get("environment") or state.get("environment"),
            "requested_tests": (run_data or {}).get("requested_tests") or [],
            "summary": (run_data or {}).get("summary") or state.get("summary") or {},
            "record_json": run_data or {"state_snapshot": {"latest_run_id": run_key, "summary": state.get("summary") or {}}},
            "updated_at": timestamp,
            "updated_at_unix": now_unix,
        }]

    def _bulk_import_sql(self, container_file: str) -> str:
        escaped = container_file.replace("'", "''")
        return f"""
CREATE TEMP TABLE test_control_import_payload(data jsonb);
COPY test_control_import_payload(data) FROM '{escaped}' WITH (FORMAT csv, DELIMITER E'\x02', QUOTE E'\x01', ESCAPE E'\x01');

INSERT INTO test_runs (id, run_key, source, external_run_id, workflow, status, git_sha, git_branch, environment, requested_tests, summary, record_json, updated_at, updated_at_unix)
SELECT gen_random_uuid(), run_key, source, external_run_id, workflow, status, git_sha, git_branch, environment, requested_tests::json, summary::json, record_json::json, updated_at, updated_at_unix
FROM jsonb_to_recordset((SELECT data->'runs' FROM test_control_import_payload)) AS x(run_key text, source text, external_run_id text, workflow text, status text, git_sha text, git_branch text, environment text, requested_tests jsonb, summary jsonb, record_json jsonb, updated_at text, updated_at_unix integer)
ON CONFLICT (run_key) DO UPDATE SET source=EXCLUDED.source, external_run_id=EXCLUDED.external_run_id, workflow=EXCLUDED.workflow, status=EXCLUDED.status, git_sha=EXCLUDED.git_sha, git_branch=EXCLUDED.git_branch, environment=EXCLUDED.environment, requested_tests=EXCLUDED.requested_tests, summary=EXCLUDED.summary, record_json=EXCLUDED.record_json, updated_at=EXCLUDED.updated_at, updated_at_unix=EXCLUDED.updated_at_unix;

INSERT INTO test_catalog (id, test_key, suite, test_name, file_path, verification_command, metadata)
SELECT gen_random_uuid(), test_key, suite, test_name, file_path, verification_command, COALESCE(metadata, '{{}}'::jsonb)::json
FROM jsonb_to_recordset((SELECT data->'catalog' FROM test_control_import_payload)) AS x(test_key text, suite text, test_name text, file_path text, verification_command text, metadata jsonb)
ON CONFLICT (test_key) DO UPDATE SET suite=EXCLUDED.suite, test_name=EXCLUDED.test_name, file_path=EXCLUDED.file_path, verification_command=EXCLUDED.verification_command, metadata=EXCLUDED.metadata;

INSERT INTO test_current_state (id, test_key, suite, test_name, stable_status, stable_result_key, stable_run_key, active_status, active_run_key, triage_group_id, error_summary, metadata, updated_at, updated_at_unix)
SELECT gen_random_uuid(), test_key, suite, test_name, stable_status, stable_result_key, stable_run_key, active_status, active_run_key, triage_group_id, error_summary, COALESCE(metadata, '{{}}'::jsonb)::json, updated_at, updated_at_unix
FROM jsonb_to_recordset((SELECT data->'current_state' FROM test_control_import_payload)) AS x(test_key text, suite text, test_name text, stable_status text, stable_result_key text, stable_run_key text, active_status text, active_run_key text, triage_group_id text, error_summary text, metadata jsonb, updated_at text, updated_at_unix integer)
ON CONFLICT (test_key) DO UPDATE SET suite=EXCLUDED.suite, test_name=EXCLUDED.test_name, stable_status=EXCLUDED.stable_status, stable_result_key=EXCLUDED.stable_result_key, stable_run_key=EXCLUDED.stable_run_key, active_status=EXCLUDED.active_status, active_run_key=EXCLUDED.active_run_key, triage_group_id=EXCLUDED.triage_group_id, error_summary=EXCLUDED.error_summary, metadata=EXCLUDED.metadata, updated_at=EXCLUDED.updated_at, updated_at_unix=EXCLUDED.updated_at_unix;

INSERT INTO test_results (id, result_key, run_key, test_key, suite, test_name, status, error_summary, metadata, created_at, created_at_unix)
SELECT gen_random_uuid(), result_key, run_key, test_key, suite, test_name, status, error_summary, COALESCE(metadata, '{{}}'::jsonb)::json, created_at, created_at_unix
FROM jsonb_to_recordset((SELECT data->'results' FROM test_control_import_payload)) AS x(result_key text, run_key text, test_key text, suite text, test_name text, status text, error_summary text, metadata jsonb, created_at text, created_at_unix integer)
ON CONFLICT (result_key) DO UPDATE SET run_key=EXCLUDED.run_key, test_key=EXCLUDED.test_key, suite=EXCLUDED.suite, test_name=EXCLUDED.test_name, status=EXCLUDED.status, error_summary=EXCLUDED.error_summary, metadata=EXCLUDED.metadata, created_at=EXCLUDED.created_at, created_at_unix=EXCLUDED.created_at_unix;
"""

    def list_claims(self) -> list[dict[str, Any]]:
        return self._items("test_claims", params={"limit": -1, "sort": "leased_at"})

    def create_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        item = {"claim_key": claim["lease_id"], **claim, "entry_json": claim.get("entry") or {}}
        self._upsert("test_claims", "claim_key", item)
        return claim

    def update_claim(self, lease_id: str, status: str, fields: dict[str, Any]) -> dict[str, Any]:
        existing = self._items("test_claims", params={"filter": json.dumps({"claim_key": {"_eq": lease_id}}), "limit": 1})
        if not existing:
            raise RuntimeError(f"Unknown lease id: {lease_id}")
        claim = {**existing[0], "lease_id": lease_id, "status": status, "updated_at": utc_now(), **fields}
        self._upsert("test_claims", "claim_key", {"claim_key": lease_id, **claim})
        return claim


def get_store():
    global TEST_STORE
    if TEST_STORE is None:
        TEST_STORE = DirectusTestControlStore()
    return TEST_STORE


def current_git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to resolve current git commit: {result.stderr.strip()}")
    return result.stdout.strip()


def _matches_commit_prefix(actual_sha: str, expected_sha: str) -> bool:
    actual = actual_sha.strip().lower()
    expected = expected_sha.strip().lower()
    return bool(expected) and (actual.startswith(expected) or expected.startswith(actual))


def parse_control_run_args(args: list[str]) -> tuple[list[str], str]:
    """Remove tests.py-only run flags before delegating to run_tests.py."""
    forwarded: list[str] = []
    expected_commit = ""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"--expected-commit", "--commit"}:
            if index + 1 >= len(args):
                raise RuntimeError(f"{arg} requires a commit SHA")
            expected_commit = args[index + 1]
            index += 2
            continue
        if arg.startswith("--expected-commit="):
            expected_commit = arg.split("=", 1)[1]
            index += 1
            continue
        if arg.startswith("--commit="):
            expected_commit = arg.split("=", 1)[1]
            index += 1
            continue
        forwarded.append(arg)
        index += 1
    return forwarded, expected_commit


def preflight_test_control_plane() -> None:
    store = get_store()
    if isinstance(store, DirectusTestControlStore):
        store._require_token()


def is_api_key_device_approval_blocker(text: str) -> bool:
    normalized = normalize_text(text).lower()
    return any(marker in normalized for marker in API_KEY_DEVICE_APPROVAL_MARKERS)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def run_archive_name(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "") + ".json"


def test_label(suite: str, test: dict[str, Any]) -> str:
    return str(test.get("file") or test.get("name") or "unknown")


def test_key(suite: str, test: dict[str, Any]) -> str:
    return f"{suite}::{test_label(suite, test)}"


def iter_tests(run_data: dict[str, Any]):
    for suite, suite_data in (run_data.get("suites") or {}).items():
        if not isinstance(suite_data, dict):
            continue
        for test in suite_data.get("tests") or []:
            if isinstance(test, dict):
                yield str(suite), test


def is_problem(status: str) -> bool:
    return status in PROBLEM_STATUSES


def summarize_current_tests(tests: dict[str, dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "dispatch_error": 0,
        "timeout": 0,
        "result_unknown": 0,
        "skipped": 0,
        "not_started": 0,
        "running": 0,
    }
    for test in tests.values():
        summary["total"] += 1
        status = str(test.get("status") or "unknown")
        if status in summary:
            summary[status] += 1
        else:
            summary["skipped"] += 1
        active_status = str(test.get("active_status") or "")
        if active_status == "running" and status != "running":
            summary["running"] += 1
    return summary


def record_run_result(run_data: dict[str, Any], source: str = "scripts_tests", external_run_id: str = "", workflow: str = "") -> dict[str, Any]:
    """Persist normalized current state, run archive, and timeline events."""
    run_id = str(run_data.get("run_id") or utc_now())
    timestamp = utc_now()
    state = get_store().load_state()
    recorded_event_ids = set(state.get("recorded_event_ids") or [])
    tests = dict(state.get("tests") or {})
    events: list[dict[str, Any]] = []

    for suite, test in iter_tests(run_data):
        label = test_label(suite, test)
        key = test_key(suite, test)
        status = str(test.get("status") or "unknown")
        event = "failed" if is_problem(status) else status
        event_id = f"{run_id}:{key}:{event}"
        current = {
            "suite": suite,
            "test": label,
            "key": key,
            "status": status,
            "stable_status": status,
            "stable_run_id": run_id,
            "active_status": None,
            "active_run_id": None,
            "stable_result_key": event_id,
            "event": event,
            "run_id": run_id,
            "github_run_id": test.get("run_id"),
            "github_run_url": test.get("github_run_url"),
            "git_sha": run_data.get("git_sha"),
            "git_branch": run_data.get("git_branch"),
            "environment": run_data.get("environment"),
            "duration_seconds": test.get("duration_seconds", 0),
            "flaky": bool(test.get("flaky")),
            "retries": int(test.get("retries") or 0),
            "attempt_statuses": [str(status) for status in test.get("attempt_statuses") or []],
            "error": test.get("error"),
            "verification_command": test.get("verification_command"),
            "updated_at": timestamp,
        }
        tests[key] = current
        if event_id not in recorded_event_ids:
            events.append({**current, "timestamp": timestamp, "event_id": event_id})
            recorded_event_ids.add(event_id)

    normalized_state = {
        "latest_run_id": run_id,
        "latest_git_sha": run_data.get("git_sha"),
        "latest_git_branch": run_data.get("git_branch"),
        "environment": run_data.get("environment"),
        "updated_at": timestamp,
        "summary": summarize_current_tests(tests),
        "latest_run_summary": run_data.get("summary") or {},
        "tests": tests,
        "recorded_event_ids": sorted(recorded_event_ids)[-10000:],
    }
    get_store().record_run_result(run_data, normalized_state, events, source=source, external_run_id=external_run_id, workflow=workflow)
    return normalized_state


def load_state() -> dict[str, Any]:
    state = get_store().load_state()
    if state:
        return state
    return {"summary": {}, "tests": {}, "updated_at": None}


def mark_running(suite: str, tests: list[str], command: list[str]) -> None:
    state = load_state()
    current_tests = dict(state.get("tests") or {})
    timestamp = utc_now()
    run_id = f"manual-{timestamp}"
    events = []
    for label in tests or [suite]:
        key = f"{suite}::{label}"
        previous = dict(current_tests.get(key) or {})
        previous_status = str(previous.get("stable_status") or previous.get("status") or "")
        stable_status = previous_status if previous_status and previous_status != "running" else None
        record = {
            **previous,
            "suite": suite,
            "test": label,
            "key": key,
            "status": stable_status or "running",
            "stable_status": stable_status,
            "stable_run_id": previous.get("stable_run_id") or previous.get("run_id"),
            "stable_result_key": previous.get("stable_result_key"),
            "active_status": "running",
            "active_run_id": run_id,
            "event": "started",
            "run_id": run_id,
            "command": " ".join(command),
            "updated_at": timestamp,
        }
        current_tests[key] = record
        events.append({**record, "timestamp": timestamp, "event_id": f"{run_id}:{key}:started"})
    state["tests"] = current_tests
    state["summary"] = summarize_current_tests(current_tests)
    state["updated_at"] = timestamp
    get_store().save_current_state(state, events)


def normalize_text(value: str) -> str:
    value = re.sub(r"\x1b\[[0-9;]*m", "", value or "")
    value = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,}", "<uuid>", value, flags=re.IGNORECASE)
    value = re.sub(r"\b\d+ms\b|\b\d+\.\d+s\b|\b\d{8,}\b", "<var>", value)
    return " ".join(value.split())


def classify_failure(test: dict[str, Any]) -> str:
    text = normalize_text(" ".join(str(test.get(key) or "") for key in (
        "suite",
        "test",
        "error",
        "environment_blocker",
        "debug_output_summary",
    ))).lower()
    if is_api_key_device_approval_blocker(text):
        return "environment_blocked"
    if "reserved playwright account slot" in text or "preflight" in text:
        return "account_preflight"
    if "not authenticated" in text and "cli" in text:
        return "cli_auth"
    if re.search(r"\b(signup|register|login|passkey|auth)\b", text) or any(token in text for token in ("account-recovery", "backup-code", "recovery-key")):
        return "auth_signup"
    if any(token in text for token in ("client_decrypt", "decrypt", "no chat key", "encrypt", "sync")):
        return "chat_sync_encryption"
    if any(token in text for token in ("embed", "application-preview", "fullscreen", "mermaid", "image-authenticity")):
        return "embed_rendering"
    if any(token in text for token in ("chat", "recent-chats", "fork-conversation", "send-message", "message-assistant", "no new assistant message")):
        return "chat_send_receive"
    if any(token in text for token in ("stripe", "billing", "payment", "credits")):
        return "payments_billing"
    if any(token in text for token in ("ai-response", "model", "inference", "vision", "did not identify", "file-attachment", "pdf-flow")):
        return "ai_response"
    if any(token in text for token in ("focus-mode", "skill", "app_skill", "app-skill")):
        return "app_skill"
    if any(token in text for token in ("mailosaur", "oauth", "calendar", "provider", "quota", "external service")):
        return "provider_external"
    if "github actions conclusion" in text or "process completed with exit code" in text:
        return "github_actions_wrapper"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "element(s) not found" in text or "tobevisible" in text or "locator:" in text:
        return "missing_element"
    if any(token in text for token in ("referenceerror", "assertionerror", "modulenotfounderror", "importerror", "typeerror")):
        return "unit_regression"
    if any(token in text for token in ("dispatch_error", "artifact", "workflow", "runner")):
        return "test_infra"
    return "unknown"


def short_reason(error: str) -> str:
    text = normalize_text(error)
    if not text:
        return "No error detail available"
    locator = re.search(r"Locator:\s*([^\n]+?)(?:Expected:|Timeout:|Error:|$)", text)
    if locator:
        return f"Locator failure: {locator.group(1).strip()[:160]}"
    for marker in ("Error:", "AssertionError", "ReferenceError", "RuntimeError", "ImportError"):
        index = text.find(marker)
        if index >= 0:
            return text[index:index + 220]
    return text[:220]


def root_signature(category: str, reason: str) -> str:
    basis = normalize_text(reason).lower()
    locator = re.search(r"(getbytestid\(['\"][^)]+|data-testid=\"[^\"]+|data-action=\"[^\"]+|locator\([^)]{1,120})", basis)
    if locator:
        basis = locator.group(1)
    return hashlib.sha1(f"{category}:{basis[:160]}".encode("utf-8")).hexdigest()[:10]


def source_text_cache() -> dict[str, str]:
    global _SOURCE_TEXT_CACHE
    if _SOURCE_TEXT_CACHE is not None:
        return _SOURCE_TEXT_CACHE
    cache: dict[str, str] = {}
    for root_name in SOURCE_SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        if not root.exists():
            continue
        if root.is_file():
            paths = [root]
        else:
            paths = [p for p in root.rglob("*") if p.is_file() and p.suffix in SOURCE_SCAN_SUFFIXES]
        for path in paths:
            if "__pycache__" in path.parts:
                continue
            try:
                cache[display_path(path)] = path.read_text(encoding="utf-8", errors="ignore")[:250000]
            except OSError:
                continue
    _SOURCE_TEXT_CACHE = cache
    return cache


def extract_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    patterns = [
        r"getByTestId\(['\"]([^'\"]+)['\"]\)",
        r"data-testid=[\"']([^\"']+)[\"']",
        r"data-action=[\"']([^\"']+)[\"']",
        r"\[data-testid=\\?[\"']([^\"'\]]+)",
        r"\[data-action=\\?[\"']([^\"'\]]+)",
    ]
    for pattern in patterns:
        tokens.update(match.group(1) for match in re.finditer(pattern, text))
    return tokens


def files_containing_tokens(tokens: set[str]) -> list[str]:
    if not tokens:
        return []
    matches: list[str] = []
    for rel_path, content in source_text_cache().items():
        for token in tokens:
            if token and token in content:
                matches.append(rel_path)
                break
    return sorted(set(matches))[:MAX_LINKED_FILES]


def extract_error_paths(text: str) -> list[str]:
    paths = []
    for match in re.finditer(r"(?:/home/runner/work/OpenMates/OpenMates/)?((?:frontend|backend|scripts|docs|apple)/[^\s:)]+)", text):
        candidate = match.group(1).rstrip(".,;'")
        if (PROJECT_ROOT / candidate).exists():
            paths.append(candidate)
    return sorted(set(paths))


def linked_files_for_failure(test: dict[str, Any]) -> list[str]:
    label = str(test.get("test") or test.get("file") or test.get("name") or "")
    error = str(test.get("error") or "")
    haystack = f"{label}\n{error}"
    linked: list[str] = []

    if label.endswith((".spec.ts", ".test.ts")):
        spec_path = SPEC_DIR / label
        if spec_path.is_file():
            linked.append(display_path(spec_path))
    elif label.startswith("tests/"):
        for prefix in ("backend", "."):
            path = PROJECT_ROOT / prefix / label
            if path.is_file():
                linked.append(display_path(path))

    linked.extend(extract_error_paths(haystack))
    lower = haystack.lower()
    for keyword, paths in KEYWORD_LINKS.items():
        if keyword in lower:
            linked.extend(path for path in paths if (PROJECT_ROOT / path).exists() or path.endswith("/"))
    linked.extend(files_containing_tokens(extract_tokens(haystack)))

    seen = set()
    result = []
    for path in linked:
        if path and path not in seen:
            seen.add(path)
            result.append(path)
        if len(result) >= MAX_LINKED_FILES:
            break
    return result


def load_history_events(days: int = 7) -> list[dict[str, Any]]:
    return get_store().load_history_events(days=days)


def recurrence_counts(days: int = 7) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in load_history_events(days=days):
        if event.get("event") == "failed":
            key = str(event.get("key") or f"{event.get('suite')}::{event.get('test')}")
            counts[key] = counts.get(key, 0) + 1
    return counts


def failed_entries_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for key, test in (state.get("tests") or {}).items():
        if is_problem(str(test.get("status") or "")):
            entries.append({**test, "key": key})
    return entries


def build_triage(days: int = 7, category_filter: str = "", suite_filter: str = "", limit: int | None = None) -> dict[str, Any]:
    state = load_state()
    failures = failed_entries_from_state(state)
    recurrence = recurrence_counts(days=days)
    group_sizes: dict[str, int] = {}
    staged_entries = []

    for failure in failures:
        category = classify_failure(failure)
        reason = short_reason(str(failure.get("error") or ""))
        group_id = f"{category}-{root_signature(category, reason)}"
        group_sizes[group_id] = group_sizes.get(group_id, 0) + 1
        staged_entries.append((failure, category, reason, group_id))

    entries = []
    for failure, category, reason, group_id in staged_entries:
        key = str(failure.get("key") or f"{failure.get('suite')}::{failure.get('test')}")
        group_count = group_sizes[group_id]
        recurrence_count = recurrence.get(key, 0)
        priority = CATEGORY_PRIORITY.get(category, CATEGORY_PRIORITY["unknown"])
        score = [priority, -group_count, -recurrence_count, str(failure.get("test") or "")]
        linked_files = linked_files_for_failure(failure)
        entries.append({
            "group_id": group_id,
            "category": category,
            "rank_score": score,
            "priority": priority,
            "group_size": group_count,
            "recurrences_7d": recurrence_count,
            "suite": failure.get("suite"),
            "test": failure.get("test"),
            "key": key,
            "status": failure.get("status"),
            "reason": reason,
            "error": failure.get("error"),
            "run_id": failure.get("run_id"),
            "github_run_id": failure.get("github_run_id"),
            "github_run_url": failure.get("github_run_url"),
            "linked_files": linked_files,
            "verification_command": verification_command(failure),
        })

    entries.sort(key=lambda entry: entry["rank_score"])
    for index, entry in enumerate(entries, start=1):
        entry["rank"] = index

    if category_filter:
        entries = [entry for entry in entries if entry.get("category") == category_filter]
    if suite_filter:
        entries = [entry for entry in entries if entry.get("suite") == suite_filter]
    if limit is not None:
        entries = entries[:max(limit, 0)]

    triage = {
        "run_id": state.get("latest_run_id"),
        "generated_at": utc_now(),
        "summary": state.get("summary") or {},
        "entries": entries,
        "groups": build_group_summary(entries),
    }
    write_json(TRIAGE_FILE, triage)
    write_json(TEST_FILE_INDEX_FILE, {
        "generated_at": triage["generated_at"],
        "tests": {entry["key"]: entry["linked_files"] for entry in entries},
    })
    return triage


def build_group_summary(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for entry in entries:
        group = groups.setdefault(entry["group_id"], {
            "group_id": entry["group_id"],
            "category": entry["category"],
            "priority": entry["priority"],
            "reason": entry["reason"],
            "tests": [],
            "linked_files": [],
        })
        group["tests"].append(entry["test"])
        group["linked_files"].extend(entry.get("linked_files") or [])
    for group in groups.values():
        group["count"] = len(group["tests"])
        group["linked_files"] = sorted(set(group["linked_files"]))[:MAX_LINKED_FILES]
    return sorted(groups.values(), key=lambda group: (group["priority"], -group["count"], group["group_id"]))


def verification_command(failure: dict[str, Any]) -> str:
    if failure.get("verification_command"):
        return str(failure["verification_command"])
    suite = str(failure.get("suite") or "")
    label = str(failure.get("test") or "")
    if suite == "playwright" and label.endswith(".spec.ts"):
        return f"python3 scripts/tests.py run --spec {label}"
    if suite.startswith("pytest"):
        return "python3 scripts/tests.py run --suite pytest"
    if suite.startswith("vitest"):
        return "python3 scripts/tests.py run --suite vitest"
    if suite == "cli":
        return "python3 scripts/tests.py run --suite cli"
    return "python3 scripts/tests.py run --only-failed"


def lease_deadline() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=LEASE_TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def active_group_ids(leases: list[dict[str, Any]]) -> set[str]:
    now = datetime.now(timezone.utc)
    active = set()
    for lease in leases:
        if lease.get("status") != "active":
            continue
        expires_at = parse_utc(str(lease.get("expires_at") or ""))
        if expires_at is None or expires_at > now:
            active.add(str(lease.get("group_id")))
    return active


def with_lease_lock(callback):
    LEASE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LEASE_LOCK_FILE.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        return callback()


def load_leases() -> dict[str, Any]:
    return {"leases": get_store().list_claims()}


def claim_next(session_id: str, worker_id: str = "", days: int = 7) -> dict[str, Any] | None:
    def _claim() -> dict[str, Any] | None:
        triage = build_triage(days=days)
        leases_data = load_leases()
        leases = list(leases_data.get("leases") or [])
        active = active_group_ids(leases)
        for entry in triage.get("entries") or []:
            if entry["group_id"] in active:
                continue
            digest = hashlib.sha1(f"{entry['group_id']}:{session_id}:{utc_now()}".encode("utf-8")).hexdigest()[:8]
            lease_id = f"lease-{entry['group_id']}-{digest}"
            lease = {
                "lease_id": lease_id,
                "claim_key": lease_id,
                "group_id": entry["group_id"],
                "status": "active",
                "session_id": session_id,
                "worker_id": worker_id,
                "leased_at": utc_now(),
                "expires_at": lease_deadline(),
                "expires_at_unix": int((datetime.now(timezone.utc) + timedelta(hours=LEASE_TTL_HOURS)).timestamp()),
                "entry": entry,
            }
            leases.append(lease)
            get_store().create_claim(lease)
            return lease
        return None
    return with_lease_lock(_claim)


def update_lease(lease_id: str, status: str, **fields: Any) -> dict[str, Any]:
    def _update() -> dict[str, Any]:
        return get_store().update_claim(lease_id, status, fields)
    return with_lease_lock(_update)


def _lease_for_id(lease_id: str) -> dict[str, Any] | None:
    for lease in load_leases().get("leases") or []:
        if lease.get("lease_id") == lease_id or lease.get("claim_key") == lease_id:
            return lease
    return None


def _blocking_triage_entry_for_lease(lease: dict[str, Any]) -> dict[str, Any] | None:
    entry = lease.get("entry") if isinstance(lease.get("entry"), dict) else lease.get("entry_json")
    entry = entry if isinstance(entry, dict) else {}
    group_id = str(lease.get("group_id") or entry.get("group_id") or "")
    key = str(entry.get("key") or "")
    for current in build_triage().get("entries") or []:
        if group_id and current.get("group_id") == group_id:
            return current
        if key and current.get("key") == key:
            return current
    return None


def complete_lease(lease_id: str, commit: str = "", require_passing: bool = False) -> dict[str, Any]:
    if require_passing:
        lease = _lease_for_id(lease_id)
        if not lease:
            raise RuntimeError(f"Unknown lease id: {lease_id}")
        blocking_entry = _blocking_triage_entry_for_lease(lease)
        if blocking_entry:
            raise RuntimeError(
                "Refusing to complete lease because its failure group is still failing: "
                f"{blocking_entry.get('test')} — {blocking_entry.get('reason')}"
            )
    return update_lease(lease_id, "completed", completed_at=utc_now(), commit=commit, completed_commit=commit)


def release_lease(lease_id: str, reason: str = "") -> dict[str, Any]:
    return update_lease(lease_id, "released", released_at=utc_now(), release_reason=reason)


def ingest_github_actions_run(run_data: dict[str, Any], external_run_id: str = "", workflow: str = "") -> dict[str, Any]:
    run_data = dict(run_data)
    run_data.setdefault("run_id", external_run_id or utc_now())
    return record_run_result(run_data, source="github_actions", external_run_id=external_run_id, workflow=workflow)


def import_run_artifact(path: Path, source: str = "github_actions", external_run_id: str = "", workflow: str = "") -> dict[str, Any]:
    run_data = read_json(path, {})
    if source == "github_actions":
        return ingest_github_actions_run(run_data, external_run_id=external_run_id, workflow=workflow)
    return record_run_result(run_data)


def import_state_snapshot(path: Path) -> dict[str, Any]:
    state = read_json(path, {})
    if not isinstance(state.get("tests"), dict):
        raise RuntimeError(f"State snapshot must contain a tests object: {path}")
    state.setdefault("updated_at", utc_now())
    state.setdefault("summary", summarize_current_tests(state.get("tests") or {}))
    get_store().save_current_state(state, [])
    return load_state()


def print_status(state: dict[str, Any]) -> None:
    summary = state.get("summary") or {}
    print(f"Run: {state.get('latest_run_id') or 'none'}")
    print(f"Updated: {state.get('updated_at') or 'never'}")
    print(
        "Summary: "
        f"{summary.get('passed', 0)} passed, "
        f"{summary.get('failed', 0)} failed, "
        f"{summary.get('skipped', 0)} skipped, "
        f"{summary.get('not_started', 0)} not started"
    )
    running = [test for test in (state.get("tests") or {}).values() if test.get("status") == "running"]
    if running:
        print(f"Running: {len(running)}")
        for test in running[:10]:
            print(f"  - [{test.get('suite')}] {test.get('test')}")


def print_test_list(statuses: set[str]) -> None:
    state = load_state()
    rows = [test for test in (state.get("tests") or {}).values() if str(test.get("status")) in statuses]
    for test in sorted(rows, key=lambda item: (str(item.get("suite")), str(item.get("test")))):
        reason = short_reason(str(test.get("error") or "")) if test.get("error") else ""
        print(f"[{test.get('suite')}] {test.get('test')} — {test.get('status')}" + (f" — {reason}" if reason else ""))
    if not rows:
        print("No matching tests.")


def print_history(days: int) -> None:
    events = load_history_events(days=days)
    for event in events:
        reason = short_reason(str(event.get("error") or "")) if event.get("error") else ""
        print(
            f"{event.get('timestamp')} [{event.get('suite')}] {event.get('test')} "
            f"{event.get('event')} {event.get('run_id')}" + (f" — {reason}" if reason else "")
        )
    if not events:
        print(f"No history events in the last {days} day(s).")


def print_triage(triage: dict[str, Any], as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(triage, indent=2, sort_keys=True))
        return
    entries = triage.get("entries") or []
    print(f"Run: {triage.get('run_id') or 'none'}")
    print(f"Failures: {len(entries)}")
    for entry in entries:
        print(f"#{entry['rank']} [{entry['category']}] {entry['test']} — {entry['reason']}")
        if entry.get("linked_files"):
            print("  files: " + ", ".join(entry["linked_files"][:5]))


def infer_run_suite_and_tests(args: list[str]) -> tuple[str, list[str]]:
    suite = "all"
    tests: list[str] = []
    if "--hourly-prod" in args or "--prod-free-hourly" in args:
        suite = "prod-free-hourly"
    elif "--prod-paid-chat" in args:
        suite = "prod-paid-chat"
    elif "--prod-app-skill" in args:
        suite = "prod-app-skill"
    elif "--hourly-dev" in args:
        suite = "hourly-dev"
    for index, arg in enumerate(args):
        if arg == "--suite" and index + 1 < len(args):
            suite = args[index + 1]
        if arg == "--spec" and index + 1 < len(args):
            suite = "playwright"
            tests.append(args[index + 1])
    if "--only-failed" in args:
        tests = ["only-failed"]
    return suite, tests


def latest_timestamped_run_artifact(since_mtime: float = 0.0) -> Path | None:
    artifacts = sorted(
        (path for path in RESULTS_DIR.glob("run-*.json") if path.stat().st_mtime >= since_mtime),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return artifacts[0] if artifacts else None


def run_recording_artifacts(since_mtime: float = 0.0) -> list[Path]:
    artifacts = []
    last_run = RESULTS_DIR / "last-run.json"
    if last_run.is_file() and last_run.stat().st_mtime >= since_mtime:
        artifacts.append(last_run)
    latest_timestamped = latest_timestamped_run_artifact(since_mtime=since_mtime)
    if latest_timestamped and latest_timestamped not in artifacts:
        artifacts.append(latest_timestamped)
    return artifacts


def reset_store() -> None:
    global TEST_STORE
    TEST_STORE = None


def record_latest_run_artifact(expected_commit: str = "", since_mtime: float = 0.0) -> bool:
    artifacts = run_recording_artifacts(since_mtime=since_mtime)
    if not artifacts:
        return False
    for index, artifact in enumerate(artifacts):
        if index > 0:
            reset_store()
        try:
            run_data = read_json(artifact, {})
            if expected_commit and not _matches_commit_prefix(str(run_data.get("git_sha") or ""), expected_commit):
                print(
                    "Test run completed for a different commit than requested: "
                    f"expected {expected_commit}, got {run_data.get('git_sha')}",
                    file=sys.stderr,
                )
                return False
            record_run_result(run_data)
            if index > 0:
                print(f"Imported fallback run artifact: {display_path(artifact)}", file=sys.stderr)
            return True
        except Exception as exc:
            print(f"Could not record run artifact {display_path(artifact)}: {exc}", file=sys.stderr)
    print("Run finished, but Directus recording failed for all generated artifacts.", file=sys.stderr)
    return False


def command_run(runner_args: list[str]) -> int:
    forwarded_args, expected_commit = parse_control_run_args(runner_args)
    if expected_commit:
        actual_commit = current_git_sha()
        if not _matches_commit_prefix(actual_commit, expected_commit):
            print(
                "Refusing to dispatch tests for a moving target: "
                f"expected commit {expected_commit}, current HEAD is {actual_commit[:9]}",
                file=sys.stderr,
            )
            return 2
    try:
        preflight_test_control_plane()
    except RuntimeError as exc:
        print(
            "Test control-plane preflight failed before dispatch. "
            f"{exc}",
            file=sys.stderr,
        )
        return 2

    command = [sys.executable, str(RUN_TESTS_SCRIPT), *forwarded_args]
    suite, tests = infer_run_suite_and_tests(forwarded_args)
    mark_running(suite=suite, tests=tests, command=["python3", "scripts/tests.py", "run", *runner_args])
    artifact_start_mtime = datetime.now(timezone.utc).timestamp() - 1
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    if not record_latest_run_artifact(expected_commit=expected_commit, since_mtime=artifact_start_mtime):
        return 2 if expected_commit else result.returncode
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] == "run":
        return command_run(raw_argv[1:])

    parser = argparse.ArgumentParser(description="OpenMates unified test control plane")
    sub = parser.add_subparsers(dest="command", required=True)

    status_parser = sub.add_parser("status", help="Show latest normalized test state")
    status_parser.add_argument("--json", action="store_true")
    sub.add_parser("failed", help="List currently failed/problem tests")
    sub.add_parser("skipped", help="List currently skipped tests")

    history_parser = sub.add_parser("history", help="Show test event timeline")
    history_parser.add_argument("--days", type=int, default=7)

    triage_parser = sub.add_parser("triage", help="Classify and rank current failures")
    triage_parser.add_argument("--days", type=int, default=7)
    triage_parser.add_argument("--limit", type=int)
    triage_parser.add_argument("--category", default="")
    triage_parser.add_argument("--suite", default="")
    triage_parser.add_argument("--json", action="store_true")

    next_parser = sub.add_parser("next", help="Return or lease the next failure group")
    next_parser.add_argument("--lease", action="store_true")
    next_parser.add_argument("--session", default="manual")
    next_parser.add_argument("--worker", default="")
    next_parser.add_argument("--days", type=int, default=7)
    next_parser.add_argument("--json", action="store_true")

    complete_parser = sub.add_parser("complete", help="Mark a failure lease completed")
    complete_parser.add_argument("--lease", required=True)
    complete_parser.add_argument("--commit", default="")
    complete_parser.add_argument("--require-passing", action="store_true")

    release_parser = sub.add_parser("release", help="Release a failure lease")
    release_parser.add_argument("--lease", required=True)
    release_parser.add_argument("--reason", default="")

    import_parser = sub.add_parser("import-run", help="Import a normalized run artifact into the Directus test control plane")
    import_parser.add_argument("path")
    import_parser.add_argument("--source", default="github_actions")
    import_parser.add_argument("--external-run-id", default="")
    import_parser.add_argument("--workflow", default="")

    import_state_parser = sub.add_parser("import-state", help="Import a legacy tests-state.json snapshot into the Directus test control plane")
    import_state_parser.add_argument("path")

    run_parser = sub.add_parser("run", help="Run tests through the unified control plane and record state")
    run_parser.add_argument("runner_args", nargs=argparse.REMAINDER)

    args = parser.parse_args(raw_argv)
    if args.command == "status":
        state = load_state()
        if args.json:
            print(json.dumps(state, indent=2, sort_keys=True))
        else:
            print_status(state)
        return 0
    if args.command == "failed":
        print_test_list(PROBLEM_STATUSES)
        return 0
    if args.command == "skipped":
        print_test_list({"skipped", "not_started"})
        return 0
    if args.command == "history":
        print_history(args.days)
        return 0
    if args.command == "triage":
        print_triage(
            build_triage(days=args.days, category_filter=args.category, suite_filter=args.suite, limit=args.limit),
            as_json=args.json,
        )
        return 0
    if args.command == "next":
        if args.lease:
            lease = claim_next(session_id=args.session, worker_id=args.worker, days=args.days)
            if lease is None:
                print("No unleased failed test groups.")
                return 1
            if args.json:
                print(json.dumps(lease, indent=2, sort_keys=True))
            else:
                entry = lease["entry"]
                print(f"LEASE: {lease['lease_id']}")
                print(f"NEXT: {entry['test']}")
                print(f"CATEGORY: {entry['category']}")
                print(f"REASON: {entry['reason']}")
                print(f"VERIFY: {entry['verification_command']}")
                if entry.get("linked_files"):
                    print("FILES: " + ", ".join(entry["linked_files"][:8]))
            return 0
        triage = build_triage(days=args.days)
        entry = (triage.get("entries") or [None])[0]
        print(json.dumps(entry, indent=2, sort_keys=True) if args.json else (entry or "No failed tests."))
        return 0 if entry else 1
    if args.command == "complete":
        try:
            completed = complete_lease(args.lease, commit=args.commit, require_passing=args.require_passing)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(completed, indent=2, sort_keys=True))
        return 0
    if args.command == "release":
        print(json.dumps(release_lease(args.lease, reason=args.reason), indent=2, sort_keys=True))
        return 0
    if args.command == "import-run":
        state = import_run_artifact(Path(args.path), source=args.source, external_run_id=args.external_run_id, workflow=args.workflow)
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0
    if args.command == "import-state":
        state = import_state_snapshot(Path(args.path))
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0
    if args.command == "run":
        runner_args = list(args.runner_args)
        if runner_args and runner_args[0] == "--":
            runner_args = runner_args[1:]
        return command_run(runner_args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
