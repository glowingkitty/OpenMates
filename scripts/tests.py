#!/usr/bin/env python3
"""
scripts/tests.py

Unified test control plane for OpenMates test debugging.
It wraps the existing GitHub Actions-backed runner, persists current test state,
records an append-only timeline, deterministically triages failures, and leases
the next failure group so parallel debugging sessions do not collide.

Architecture: docs/architecture/test-orchestration.md

Common gates:
    python3 scripts/tests.py next --lease --session ${OPENCODE_SESSION_ID:-manual}
    python3 scripts/tests.py run --spec chat-flow.spec.ts --gate-deploy --expected-commit <sha>
    python3 scripts/tests.py run --spec chat-flow.spec.ts --lease-required --lease-id <lease>
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import sessions as session_control
except ModuleNotFoundError:
    import sessions as session_control


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "test-results"
STATE_FILE = RESULTS_DIR / "tests-state.json"
HISTORY_FILE = RESULTS_DIR / "tests-history.jsonl"
LEASES_FILE = RESULTS_DIR / "failed-test-leases.json"
TRIAGE_FILE = RESULTS_DIR / "test-failure-triage.json"
TEST_FILE_INDEX_FILE = RESULTS_DIR / "test-file-index.json"
SESSIONS_FILE = PROJECT_ROOT / ".claude" / "sessions.json"
RUNS_DIR = RESULTS_DIR / "runs"
LEASE_LOCK_FILE = Path("/tmp/openmates-failed-test-leases.lock")
SPEC_DIR = PROJECT_ROOT / "frontend" / "apps" / "web_app" / "tests"
RUN_TESTS_SCRIPT = PROJECT_ROOT / "scripts" / "run_tests.py"
TEST_STORE = None
DEV_HEALTH_URLS = (
    "https://api.dev.openmates.org/health",
    "https://app.dev.openmates.org/",
)

PROBLEM_STATUSES = {"failed", "dispatch_error", "timeout", "result_unknown"}
LEASE_TTL_HOURS = 8
MAX_LINKED_FILES = 12
MAX_IMPORTED_ERROR_CHARS = 4000

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
        self.test_debug_campaigns: dict[str, dict[str, Any]] = {}
        self.test_debug_groups: dict[str, dict[str, Any]] = {}
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
            "campaign_key": run_data.get("campaign_key"),
            "debug_group_key": run_data.get("debug_group_key"),
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
                "created_at": state.get("updated_at") or utc_now(),
                "created_at_unix": int(datetime.now(timezone.utc).timestamp() * 1000),
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

    def list_debug_campaigns(self) -> list[dict[str, Any]]:
        return [_copy_json(campaign) for campaign in self.test_debug_campaigns.values()]

    def create_debug_campaign(self, campaign: dict[str, Any]) -> dict[str, Any]:
        self.test_debug_campaigns[campaign["campaign_key"]] = _copy_json(campaign)
        return _copy_json(campaign)

    def update_debug_campaign(self, campaign_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        if campaign_key not in self.test_debug_campaigns:
            raise RuntimeError(f"Unknown debug campaign: {campaign_key}")
        self.test_debug_campaigns[campaign_key].update(_copy_json(fields))
        return _copy_json(self.test_debug_campaigns[campaign_key])

    def list_debug_groups(self, campaign_key: str = "") -> list[dict[str, Any]]:
        groups = self.test_debug_groups.values()
        if campaign_key:
            groups = [group for group in groups if group.get("campaign_key") == campaign_key]
        return [_copy_json(group) for group in groups]

    def create_debug_group(self, group: dict[str, Any]) -> dict[str, Any]:
        self.test_debug_groups[group["group_key"]] = _copy_json(group)
        return _copy_json(group)

    def update_debug_group(self, group_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        if group_key not in self.test_debug_groups:
            raise RuntimeError(f"Unknown debug group: {group_key}")
        self.test_debug_groups[group_key].update(_copy_json(fields))
        return _copy_json(self.test_debug_groups[group_key])

    def list_test_results(self, test_keys: list[str] | None = None) -> list[dict[str, Any]]:
        results = self.test_results.values()
        if test_keys:
            selected = set(test_keys)
            results = [result for result in results if result.get("test_key") in selected]
        return [_copy_json(result) for result in results]

    def get_test_run(self, run_key: str) -> dict[str, Any]:
        return _copy_json(self.test_runs.get(run_key) or {})


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
        if method == "GET":
            params = {**(params or {}), "_openmates_cache_bust": str(int(datetime.now(timezone.utc).timestamp() * 1000))}
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        body = json.dumps(data).encode("utf-8") if data is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}{query}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Cache-Control": "no-cache, no-store, max-age=0",
                "Pragma": "no-cache",
            },
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
        rows = self._load_current_state_rows_from_local_postgres()
        rows_loaded_from_postgres = rows is not None
        if rows is None:
            rows = self._items("test_current_state", params={"limit": -1, "sort": "test_key"})
        if not rows_loaded_from_postgres:
            rows = self._fresh_current_state_rows(rows)
        tests = {str(row.get("test_key")): self._state_row_to_record(row) for row in rows if row.get("test_key")}
        latest_run_id = self._latest_current_state_run(rows)
        latest_run_summary = self._run_summary_for_key(latest_run_id)
        return {
            "latest_run_id": latest_run_id,
            "updated_at": utc_now(),
            "summary": latest_run_summary or summarize_current_tests(tests),
            "latest_run_summary": latest_run_summary or {},
            "tests": tests,
            "recorded_event_ids": [],
        }

    def _load_current_state_rows_from_local_postgres(self) -> list[dict[str, Any]] | None:
        if os.getenv("OPENMATES_DISABLE_FAST_TEST_IMPORT") == "1":
            return None
        probe = subprocess.run(["docker", "exec", "cms-database", "true"], check=False, capture_output=True, text=True, timeout=10)
        if probe.returncode != 0:
            return None
        sql = "SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (SELECT * FROM test_current_state ORDER BY test_key) t;"
        result = subprocess.run(
            ["docker", "exec", "cms-database", "sh", "-lc", f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c {json.dumps(sql)}'],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        try:
            rows = json.loads(result.stdout.strip() or "[]")
        except json.JSONDecodeError:
            return None
        return rows if isinstance(rows, list) else None

    def _fresh_current_state_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        problem_filter = {"stable_status": {"_in": sorted(PROBLEM_STATUSES)}}
        fresh_problem_rows = self._items(
            "test_current_state",
            params={"filter": json.dumps(problem_filter), "limit": -1, "sort": "test_key"},
        )
        fresh_problem_by_key: dict[str, dict[str, Any]] = {}
        for row in fresh_problem_rows:
            key = str(row.get("test_key") or "")
            if not key:
                continue
            exact_rows = self._items(
                "test_current_state",
                params={"filter": json.dumps({"test_key": {"_eq": key}}), "limit": 1},
            )
            fresh_problem_by_key[key] = exact_rows[0] if exact_rows else row
        repaired_rows = []
        for row in rows:
            key = str(row.get("test_key") or "")
            if not key:
                repaired_rows.append(row)
                continue
            if key in fresh_problem_by_key:
                repaired_rows.append(fresh_problem_by_key[key])
                continue
            status = str(row.get("stable_status") or row.get("active_status") or "")
            if status in PROBLEM_STATUSES:
                exact_rows = self._items(
                    "test_current_state",
                    params={"filter": json.dumps({"test_key": {"_eq": key}}), "limit": 1},
                )
                repaired_rows.append(exact_rows[0] if exact_rows else row)
                continue
            repaired_rows.append(row)
        return repaired_rows

    def _latest_current_state_run(self, rows: list[dict[str, Any]]) -> str:
        counts: dict[str, int] = {}
        for row in rows:
            run_key = str(row.get("stable_run_key") or row.get("active_run_key") or "")
            if run_key:
                counts[run_key] = counts.get(run_key, 0) + 1
        if not counts:
            return ""
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def _run_summary_for_key(self, run_key: str) -> dict[str, Any]:
        if not run_key:
            return {}
        sql_run_key = run_key.replace("'", "''")
        sql = f"SELECT COALESCE(summary, '{{}}'::json) FROM test_runs WHERE run_key = '{sql_run_key}' LIMIT 1;"
        result = subprocess.run(
            ["docker", "exec", "cms-database", "sh", "-lc", f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c {json.dumps(sql)}'],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            try:
                summary = json.loads(result.stdout.strip() or "{}")
                return summary if isinstance(summary, dict) else {}
            except json.JSONDecodeError:
                pass
        rows = self._items("test_runs", params={"filter": json.dumps({"run_key": {"_eq": run_key}}), "limit": 1})
        summary = rows[0].get("summary") if rows else {}
        return summary if isinstance(summary, dict) else {}

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
        cutoff = int((datetime.now(timezone.utc) - timedelta(days=max(days, 0))).timestamp())
        rows = self._items(
            "test_results",
            params={
                "filter": json.dumps({"created_at_unix": {"_gte": cutoff}}),
                "limit": -1,
                "sort": "-created_at_unix",
            },
        )
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
            "campaign_key": run_data.get("campaign_key"),
            "debug_group_key": run_data.get("debug_group_key"),
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
            "replace_current_state": bool(state.get("replace_current_state")),
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
                "campaign_key": "",
                "debug_group_key": "",
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
            "campaign_key": (run_data or {}).get("campaign_key") or "",
            "debug_group_key": (run_data or {}).get("debug_group_key") or "",
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

DELETE FROM test_current_state
WHERE COALESCE((SELECT (data->>'replace_current_state')::boolean FROM test_control_import_payload), false)
  AND NOT EXISTS (
    SELECT 1
    FROM jsonb_to_recordset((SELECT data->'current_state' FROM test_control_import_payload)) AS x(test_key text)
    WHERE x.test_key = test_current_state.test_key
  );

INSERT INTO test_runs (id, run_key, source, external_run_id, workflow, status, git_sha, git_branch, environment, requested_tests, campaign_key, debug_group_key, summary, record_json, updated_at, updated_at_unix)
SELECT gen_random_uuid(), run_key, source, external_run_id, workflow, status, git_sha, git_branch, environment, requested_tests::json, campaign_key, debug_group_key, summary::json, record_json::json, updated_at, updated_at_unix
FROM jsonb_to_recordset((SELECT data->'runs' FROM test_control_import_payload)) AS x(run_key text, source text, external_run_id text, workflow text, status text, git_sha text, git_branch text, environment text, requested_tests jsonb, campaign_key text, debug_group_key text, summary jsonb, record_json jsonb, updated_at text, updated_at_unix integer)
ON CONFLICT (run_key) DO UPDATE SET source=EXCLUDED.source, external_run_id=EXCLUDED.external_run_id, workflow=EXCLUDED.workflow, status=EXCLUDED.status, git_sha=EXCLUDED.git_sha, git_branch=EXCLUDED.git_branch, environment=EXCLUDED.environment, requested_tests=EXCLUDED.requested_tests, campaign_key=EXCLUDED.campaign_key, debug_group_key=EXCLUDED.debug_group_key, summary=EXCLUDED.summary, record_json=EXCLUDED.record_json, updated_at=EXCLUDED.updated_at, updated_at_unix=EXCLUDED.updated_at_unix;

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

    def list_debug_campaigns(self) -> list[dict[str, Any]]:
        return self._items("test_debug_campaigns", params={"limit": -1, "sort": "created_at"})

    def create_debug_campaign(self, campaign: dict[str, Any]) -> dict[str, Any]:
        return self._upsert("test_debug_campaigns", "campaign_key", campaign)

    def update_debug_campaign(self, campaign_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self._upsert("test_debug_campaigns", "campaign_key", {"campaign_key": campaign_key, **fields})

    def list_debug_groups(self, campaign_key: str = "") -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": -1, "sort": "selected_at"}
        if campaign_key:
            params["filter"] = json.dumps({"campaign_key": {"_eq": campaign_key}})
        return self._items("test_debug_groups", params=params)

    def create_debug_group(self, group: dict[str, Any]) -> dict[str, Any]:
        return self._upsert("test_debug_groups", "group_key", group)

    def update_debug_group(self, group_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self._upsert("test_debug_groups", "group_key", {"group_key": group_key, **fields})

    def list_test_results(self, test_keys: list[str] | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": -1, "sort": "created_at_unix"}
        if test_keys:
            params["filter"] = json.dumps({"test_key": {"_in": test_keys}})
        return self._items("test_results", params=params)

    def get_test_run(self, run_key: str) -> dict[str, Any]:
        rows = self._items("test_runs", params={"filter": json.dumps({"run_key": {"_eq": run_key}}), "limit": 1})
        return rows[0] if rows else {}


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


@dataclass(frozen=True)
class ControlRunOptions:
    forwarded_args: list[str]
    expected_commit: str = ""
    gate_deploy: bool = False
    lease_required: bool = False
    lease_id: str = ""
    campaign_key: str = ""
    debug_group_key: str = ""


def parse_control_run_options(args: list[str]) -> ControlRunOptions:
    """Remove tests.py-only run flags before delegating to run_tests.py."""
    forwarded: list[str] = []
    expected_commit = ""
    gate_deploy = False
    lease_required = False
    lease_id = ""
    campaign_key = ""
    debug_group_key = ""
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
        if arg == "--gate-deploy":
            gate_deploy = True
            index += 1
            continue
        if arg in {"--lease-required", "--require-lease"}:
            lease_required = True
            index += 1
            continue
        if arg == "--lease-id":
            if index + 1 >= len(args):
                raise RuntimeError("--lease-id requires a failed-test lease id")
            lease_id = args[index + 1]
            lease_required = True
            index += 2
            continue
        if arg.startswith("--lease-id="):
            lease_id = arg.split("=", 1)[1]
            lease_required = True
            index += 1
            continue
        if arg in {"--campaign", "--group"}:
            if index + 1 >= len(args):
                raise RuntimeError(f"{arg} requires an identifier")
            if arg == "--campaign":
                campaign_key = args[index + 1]
            else:
                debug_group_key = args[index + 1]
            index += 2
            continue
        if arg.startswith("--campaign="):
            campaign_key = arg.split("=", 1)[1]
            index += 1
            continue
        if arg.startswith("--group="):
            debug_group_key = arg.split("=", 1)[1]
            index += 1
            continue
        forwarded.append(arg)
        index += 1
    return ControlRunOptions(
        forwarded_args=forwarded,
        expected_commit=expected_commit,
        gate_deploy=gate_deploy,
        lease_required=lease_required,
        lease_id=lease_id,
        campaign_key=campaign_key,
        debug_group_key=debug_group_key,
    )


def parse_control_run_args(args: list[str]) -> tuple[list[str], str]:
    options = parse_control_run_options(args)
    return options.forwarded_args, options.expected_commit


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


def normalize_import_run_data(
    run_data: dict[str, Any],
    path: Path,
    external_run_id: str = "",
    workflow: str = "",
) -> dict[str, Any]:
    if isinstance(run_data.get("suites"), dict):
        return run_data
    if isinstance(run_data.get("suites"), list) and isinstance(run_data.get("config"), dict):
        return normalize_playwright_json_report(run_data, path, external_run_id=external_run_id, workflow=workflow)
    if isinstance(run_data.get("tests"), list) and isinstance(run_data.get("summary"), dict):
        return normalize_pytest_json_report(run_data, path, external_run_id=external_run_id, workflow=workflow)
    return run_data


def normalize_playwright_json_report(
    report: dict[str, Any],
    path: Path,
    external_run_id: str = "",
    workflow: str = "",
) -> dict[str, Any]:
    tests_by_file: dict[str, list[dict[str, Any]]] = {}
    for suite in report.get("suites") or []:
        if isinstance(suite, dict):
            _collect_playwright_specs_by_file(suite, tests_by_file, default_file=path.name)

    tests = [
        _normalize_playwright_file_result(file_name, specs, external_run_id=external_run_id)
        for file_name, specs in sorted(tests_by_file.items())
    ]

    top_level_error = _first_playwright_error(report.get("errors") or [])
    if top_level_error and not tests:
        tests.append({
            "name": path.name,
            "file": path.name,
            "status": "failed",
            "duration_seconds": 0,
            "error": top_level_error,
        })

    summary = _summarize_imported_tests(tests)
    metadata = _playwright_report_metadata(report)
    git_commit = metadata.get("gitCommit") if isinstance(metadata.get("gitCommit"), dict) else {}
    ci_metadata = metadata.get("ci") if isinstance(metadata.get("ci"), dict) else {}
    suite_status = "failed" if any(is_problem(str(test.get("status") or "")) for test in tests) else "passed"
    if tests and all(str(test.get("status") or "") == "skipped" for test in tests):
        suite_status = "skipped"
    duration_seconds = round(sum(float(test.get("duration_seconds") or 0) for test in tests), 1)

    return {
        "run_id": str(external_run_id or _first_playwright_start_time(report) or path.stem or utc_now()),
        "git_sha": git_commit.get("hash") or ci_metadata.get("commitHash"),
        "git_branch": git_commit.get("branch"),
        "environment": "development",
        "duration_seconds": duration_seconds,
        "summary": summary,
        "flags": {"suite": "playwright", "imported_format": "playwright-json", "workflow": workflow},
        "suites": {
            "playwright": {
                "status": suite_status,
                "tests": tests,
                "duration_seconds": duration_seconds,
            }
        },
    }


def _collect_playwright_specs_by_file(
    suite: dict[str, Any],
    tests_by_file: dict[str, list[dict[str, Any]]],
    default_file: str,
) -> None:
    suite_file = str(suite.get("file") or suite.get("title") or default_file)
    for spec in suite.get("specs") or []:
        if not isinstance(spec, dict):
            continue
        spec_file = str(spec.get("file") or suite_file or default_file)
        tests_by_file.setdefault(spec_file, []).append(spec)
    for child_suite in suite.get("suites") or []:
        if isinstance(child_suite, dict):
            _collect_playwright_specs_by_file(child_suite, tests_by_file, default_file=suite_file)


def _normalize_playwright_file_result(
    file_name: str,
    specs: list[dict[str, Any]],
    external_run_id: str = "",
) -> dict[str, Any]:
    terminal_statuses: list[str] = []
    attempt_statuses: list[str] = []
    duration_seconds = 0.0
    retries = 0
    flaky = False
    first_error = ""

    for spec in specs:
        for test in spec.get("tests") or []:
            if not isinstance(test, dict):
                continue
            results = [result for result in (test.get("results") or []) if isinstance(result, dict)]
            if not results:
                continue
            statuses = [_map_playwright_status(str(result.get("status") or "")) for result in results if result.get("status")]
            attempt_statuses.extend(statuses)
            retries += max(0, len(results) - 1)
            duration_seconds += sum(float(result.get("duration") or 0) / 1000 for result in results)

            terminal_index = _playwright_terminal_result_index(results)
            terminal_status = _map_playwright_status(str(results[terminal_index].get("status") or ""))
            if terminal_status:
                terminal_statuses.append(terminal_status)
            if terminal_status == "passed" and any(status not in {"passed", "skipped"} for status in statuses[:terminal_index]):
                flaky = True
            if not first_error:
                first_error = _playwright_result_error(results[terminal_index])
            if not first_error:
                for result in results:
                    first_error = _playwright_result_error(result)
                    if first_error:
                        break

    status = _aggregate_playwright_status(terminal_statuses)
    entry: dict[str, Any] = {
        "name": file_name,
        "file": file_name,
        "status": status,
        "duration_seconds": round(duration_seconds, 1),
        "retries": retries,
        "flaky": flaky,
        "attempt_statuses": attempt_statuses,
    }
    if external_run_id:
        entry["run_id"] = external_run_id
        entry["github_run_url"] = f"https://github.com/glowingkitty/OpenMates/actions/runs/{external_run_id}"
    if first_error and is_problem(status):
        entry["error"] = first_error[:MAX_IMPORTED_ERROR_CHARS]
    return entry


def _playwright_terminal_result_index(results: list[dict[str, Any]]) -> int:
    if any("retry" in result for result in results):
        return max(range(len(results)), key=lambda index: int(results[index].get("retry", index) or 0))
    return len(results) - 1


def _map_playwright_status(status: str) -> str:
    normalized = status.strip()
    if normalized == "timedOut":
        return "timeout"
    if normalized in {"failed", "interrupted"}:
        return "failed"
    if normalized in {"passed", "skipped"}:
        return normalized
    return normalized or "result_unknown"


def _aggregate_playwright_status(statuses: list[str]) -> str:
    if not statuses:
        return "not_started"
    if "failed" in statuses:
        return "failed"
    if "timeout" in statuses:
        return "timeout"
    if "result_unknown" in statuses:
        return "result_unknown"
    if all(status == "skipped" for status in statuses):
        return "skipped"
    return "passed"


def _playwright_result_error(result: dict[str, Any]) -> str:
    error = result.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message:
            return message
    for entry in result.get("errors") or []:
        if isinstance(entry, dict):
            message = str(entry.get("message") or "").strip()
            if message:
                return message
    return ""


def _first_playwright_error(errors: list[Any]) -> str:
    for error in errors:
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            if message:
                return message[:MAX_IMPORTED_ERROR_CHARS]
        elif error:
            return str(error)[:MAX_IMPORTED_ERROR_CHARS]
    return ""


def _first_playwright_start_time(report: dict[str, Any]) -> str:
    for suite in report.get("suites") or []:
        if not isinstance(suite, dict):
            continue
        start_time = _first_playwright_start_time_from_suite(suite)
        if start_time:
            return start_time
    return ""


def _first_playwright_start_time_from_suite(suite: dict[str, Any]) -> str:
    for spec in suite.get("specs") or []:
        if not isinstance(spec, dict):
            continue
        for test in spec.get("tests") or []:
            if not isinstance(test, dict):
                continue
            for result in test.get("results") or []:
                if isinstance(result, dict) and result.get("startTime"):
                    return str(result["startTime"])
    for child_suite in suite.get("suites") or []:
        if isinstance(child_suite, dict):
            start_time = _first_playwright_start_time_from_suite(child_suite)
            if start_time:
                return start_time
    return ""


def _playwright_report_metadata(report: dict[str, Any]) -> dict[str, Any]:
    config = report.get("config") if isinstance(report.get("config"), dict) else {}
    metadata = config.get("metadata") if isinstance(config.get("metadata"), dict) else {}
    if metadata:
        return metadata
    for project in config.get("projects") or []:
        if isinstance(project, dict) and isinstance(project.get("metadata"), dict):
            return project["metadata"]
    return {}


def _summarize_imported_tests(tests: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "dispatch_error": 0,
        "timeout": 0,
        "result_unknown": 0,
        "skipped": 0,
        "not_started": 0,
    }
    for test in tests:
        summary["total"] += 1
        status = str(test.get("status") or "unknown")
        if status in summary:
            summary[status] += 1
        else:
            summary["skipped"] += 1
    return summary


def normalize_pytest_json_report(
    report: dict[str, Any],
    path: Path,
    external_run_id: str = "",
    workflow: str = "",
) -> dict[str, Any]:
    tests = []
    for item in report.get("tests") or []:
        if not isinstance(item, dict):
            continue
        outcome = str(item.get("outcome") or "")
        status = "passed" if outcome == "passed" else "failed" if outcome == "failed" else "skipped"
        entry = {
            "name": item.get("nodeid") or "unknown",
            "status": status,
            "duration_seconds": round(float(item.get("duration") or 0), 3),
        }
        if status == "failed":
            longrepr = (item.get("call") or {}).get("longrepr") or item.get("longrepr")
            if longrepr:
                entry["error"] = str(longrepr)[:MAX_IMPORTED_ERROR_CHARS]
        tests.append(entry)
    suite_status = "failed" if any(is_problem(str(test.get("status") or "")) for test in tests) else "passed"
    created = report.get("created")
    if isinstance(created, (int, float)):
        run_id = datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        run_id = str(external_run_id or path.stem or utc_now())
    if external_run_id:
        run_id = str(external_run_id)
    return {
        "run_id": run_id,
        "summary": report.get("summary") or {},
        "flags": {"suite": "pytest"},
        "suites": {
            "pytest_unit": {
                "status": suite_status,
                "tests": tests,
                "full_suite": True,
                "duration_seconds": round(float(report.get("duration") or 0), 1),
            }
        },
    }


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
    is_authoritative_daily = source == "daily_runner" and workflow == "daily"
    tests = {} if is_authoritative_daily else dict(state.get("tests") or {})
    events: list[dict[str, Any]] = []
    observed_keys_by_suite: dict[str, set[str]] = {}

    for suite, test in iter_tests(run_data):
        label = test_label(suite, test)
        key = test_key(suite, test)
        observed_keys_by_suite.setdefault(suite, set()).add(key)
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

    for suite, suite_data in (run_data.get("suites") or {}).items():
        if not isinstance(suite_data, dict):
            continue
        suite_status = str(suite_data.get("status") or "")
        suite_key = f"{suite}::{suite}"
        if suite_key in tests:
            marker_status = "passed" if not is_problem(suite_status) else "passed"
            event_id = f"{run_id}:{suite_key}:{marker_status}"
            tests[suite_key] = {
                **tests[suite_key],
                "suite": suite,
                "test": suite,
                "key": suite_key,
                "status": marker_status,
                "stable_status": marker_status,
                "stable_run_id": run_id,
                "active_status": None,
                "active_run_id": None,
                "stable_result_key": event_id,
                "event": marker_status,
                "run_id": run_id,
                "git_sha": run_data.get("git_sha"),
                "git_branch": run_data.get("git_branch"),
                "environment": run_data.get("environment"),
                "error": None,
                "updated_at": timestamp,
            }
            if event_id not in recorded_event_ids:
                events.append({**tests[suite_key], "timestamp": timestamp, "event_id": event_id})
                recorded_event_ids.add(event_id)

        if suite_status == "passed" and not suite_data.get("tests"):
            for key, previous in list(tests.items()):
                if previous.get("suite") != suite or key == suite_key:
                    continue
                if not is_problem(str(previous.get("status") or "")) and previous.get("active_status") != "running":
                    continue
                event_id = f"{run_id}:{key}:passed"
                tests[key] = {
                    **previous,
                    "status": "passed",
                    "stable_status": "passed",
                    "stable_run_id": run_id,
                    "active_status": None,
                    "active_run_id": None,
                    "stable_result_key": event_id,
                    "event": "passed",
                    "run_id": run_id,
                    "git_sha": run_data.get("git_sha"),
                    "git_branch": run_data.get("git_branch"),
                    "environment": run_data.get("environment"),
                    "error": None,
                    "updated_at": timestamp,
                }
                if event_id not in recorded_event_ids:
                    events.append({**tests[key], "timestamp": timestamp, "event_id": event_id})
                    recorded_event_ids.add(event_id)

        if _is_authoritative_unit_suite_run(run_data, suite, suite_data):
            observed_keys = observed_keys_by_suite.get(suite, set())
            for key, previous in list(tests.items()):
                if previous.get("suite") != suite or key == suite_key or key in observed_keys:
                    continue
                if not is_problem(str(previous.get("status") or "")) and previous.get("active_status") != "running":
                    continue
                event_id = f"{run_id}:{key}:not_started"
                tests[key] = {
                    **previous,
                    "status": "not_started",
                    "stable_status": "not_started",
                    "stable_run_id": run_id,
                    "active_status": None,
                    "active_run_id": None,
                    "stable_result_key": event_id,
                    "event": "not_started",
                    "run_id": run_id,
                    "git_sha": run_data.get("git_sha"),
                    "git_branch": run_data.get("git_branch"),
                    "environment": run_data.get("environment"),
                    "error": None,
                    "updated_at": timestamp,
                }
                if event_id not in recorded_event_ids:
                    events.append({**tests[key], "timestamp": timestamp, "event_id": event_id})
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
    if is_authoritative_daily:
        normalized_state["replace_current_state"] = True
    get_store().record_run_result(run_data, normalized_state, events, source=source, external_run_id=external_run_id, workflow=workflow)
    return normalized_state


def _is_authoritative_unit_suite_run(run_data: dict[str, Any], suite: str, suite_data: dict[str, Any]) -> bool:
    if suite not in {"pytest_unit", "vitest"}:
        return False
    if suite_data.get("full_suite") is True:
        return True
    flags = run_data.get("flags") if isinstance(run_data.get("flags"), dict) else {}
    if flags.get("only_failed"):
        return False
    requested_tests = run_data.get("requested_tests") or []
    if requested_tests:
        return False
    requested_suite = str(flags.get("suite") or "")
    suite_alias = "pytest" if suite == "pytest_unit" else suite
    return requested_suite in {"all", suite, suite_alias}


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


def mark_test_keys_running(test_keys: list[str], command: list[str]) -> None:
    state = load_state()
    current_tests = dict(state.get("tests") or {})
    timestamp = utc_now()
    run_id = f"manual-{timestamp}"
    events = []
    for key in test_keys:
        suite, _, label = key.partition("::")
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


def sanitize_debug_text(value: str) -> str:
    sanitized = normalize_text(value)
    sanitized = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<REDACTED_EMAIL>", sanitized)
    sanitized = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~-]+", "Bearer <REDACTED_TOKEN>", sanitized)
    sanitized = re.sub(r"(?i)(api[_-]?key[=:]\s*)[^\s]+", r"\1<REDACTED_TOKEN>", sanitized)
    sanitized = re.sub(r"#key=[^\s&]+", "#key=<REDACTED>", sanitized)
    return sanitized[:MAX_IMPORTED_ERROR_CHARS]


def sanitize_debug_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return f"<EXTERNAL_PATH>/{path.name}"


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
            "stable_result_key": failure.get("stable_result_key"),
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


def debug_groups_for_campaign(campaign_key: str) -> list[dict[str, Any]]:
    return get_store().list_debug_groups(campaign_key=campaign_key)


def _debug_campaign(campaign_key: str) -> dict[str, Any]:
    for campaign in get_store().list_debug_campaigns():
        if campaign.get("campaign_key") == campaign_key:
            return campaign
    raise RuntimeError(f"Unknown debug campaign: {campaign_key}")


def _debug_group(group_key: str) -> dict[str, Any]:
    for group in get_store().list_debug_groups():
        if group.get("group_key") == group_key:
            return group
    raise RuntimeError(f"Unknown debug group: {group_key}")


def _active_debug_campaign_for_session(session_id: str) -> dict[str, Any] | None:
    matching = [
        campaign
        for campaign in get_store().list_debug_campaigns()
        if campaign.get("session_id") == session_id and campaign.get("status") in {"active", "blocked"}
    ]
    return sorted(matching, key=lambda campaign: str(campaign.get("created_at") or ""))[-1] if matching else None


def _debug_group_key(campaign_key: str, triage_group_id: str, parent_group_key: str = "") -> str:
    digest = hashlib.sha1(f"{campaign_key}:{triage_group_id}:{parent_group_key}".encode("utf-8")).hexdigest()[:12]
    return f"debug-group-{digest}"


def _group_entries_by_signature(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        grouped.setdefault(str(entry["group_id"]), []).append(entry)
    return grouped


def _create_debug_group(
    campaign_key: str,
    triage_group_id: str,
    entries: list[dict[str, Any]],
    parent_group_key: str = "",
    discovery_reason: str = "",
) -> dict[str, Any]:
    now = utc_now()
    selected_at_unix = int(datetime.now(timezone.utc).timestamp())
    member_test_keys = sorted({str(entry["key"]) for entry in entries})
    run_keys = sorted({str(entry.get("run_id") or "") for entry in entries if entry.get("run_id")})
    result_keys = sorted({str(entry.get("stable_result_key") or "") for entry in entries if entry.get("stable_result_key")})
    group_key = _debug_group_key(campaign_key, triage_group_id, parent_group_key)
    group = {
        "group_key": group_key,
        "campaign_key": campaign_key,
        "triage_group_id": triage_group_id,
        "parent_group_key": parent_group_key or None,
        "status": "selected",
        "member_test_keys": member_test_keys,
        "observed_failure": "\n".join(dict.fromkeys(sanitize_debug_text(str(entry.get("reason") or entry.get("error") or "")) for entry in entries)),
        "expected_behavior": "",
        "acceptance_criteria": [],
        "root_cause": {"status": "hypothesis", "summary": "", "confidence": "unknown", "suspect_files": []},
        "attempts": [],
        "red_evidence": {"run_keys": run_keys, "result_keys": result_keys},
        "green_evidence": [],
        "blocker": None,
        "verification_command": f"python3 scripts/tests.py run --campaign {campaign_key} --group {group_key}",
        "selected_at": now,
        "selected_at_unix": selected_at_unix,
        "updated_at": now,
        "metadata": {"discovery_reason": discovery_reason} if discovery_reason else {},
    }
    return get_store().create_debug_group(group)


def start_debug_campaign(
    session_id: str,
    selected_test_keys: list[str] | None = None,
    campaign_key: str = "",
) -> dict[str, Any]:
    if campaign_key:
        campaign = _debug_campaign(campaign_key)
        if campaign.get("status") == "completed":
            raise RuntimeError(f"Debug campaign is already completed: {campaign_key}")
        return get_store().update_debug_campaign(campaign_key, {"session_id": session_id, "updated_at": utc_now()})
    active = _active_debug_campaign_for_session(session_id)
    if active:
        if active.get("selected_group_keys"):
            return active
        triage_entries = list(build_triage().get("entries") or [])
        selected = set(active.get("selected_test_keys") or [])
        entries = [entry for entry in triage_entries if entry.get("key") in selected]
        if not entries:
            raise RuntimeError(f"Active debug campaign has no recoverable failed tests: {active['campaign_key']}")
        groups = [
            _create_debug_group(str(active["campaign_key"]), group_id, group_entries)
            for group_id, group_entries in _group_entries_by_signature(entries).items()
        ]
        return get_store().update_debug_campaign(
            str(active["campaign_key"]),
            {"selected_group_keys": [group["group_key"] for group in groups], "updated_at": utc_now()},
        )
    triage = build_triage()
    entries = list(triage.get("entries") or [])
    if selected_test_keys is not None:
        selected = set(selected_test_keys)
        entries = [entry for entry in entries if entry.get("key") in selected]
    if not entries:
        raise RuntimeError("No failed tests available for a debug campaign")
    requested_keys = {str(entry["key"]) for entry in entries}
    resumable = []
    for campaign in get_store().list_debug_campaigns():
        if campaign.get("status") not in {"active", "blocked"}:
            continue
        pending_keys = {
            str(key)
            for group in debug_groups_for_campaign(str(campaign["campaign_key"]))
            if group.get("status") != "green"
            for key in group.get("member_test_keys") or []
        }
        if requested_keys.intersection(pending_keys):
            resumable.append(campaign)
    if len(resumable) == 1:
        return get_store().update_debug_campaign(
            str(resumable[0]["campaign_key"]),
            {"session_id": session_id, "updated_at": utc_now()},
        )
    if len(resumable) > 1:
        raise RuntimeError("Multiple active campaigns overlap current failures; inspect campaign status and resume one explicitly")

    campaign_key = f"debug-campaign-{uuid.uuid4().hex[:12]}"
    now = utc_now()
    campaign = {
        "campaign_key": campaign_key,
        "title": f"Debug {len(entries)} failed test(s)",
        "status": "active",
        "session_id": session_id,
        "source_run_keys": sorted({str(entry.get("run_id") or "") for entry in entries if entry.get("run_id")}),
        "selected_test_keys": sorted({str(entry["key"]) for entry in entries}),
        "selected_group_keys": [],
        "current_group_key": None,
        "completion_policy": {"group_members_must_pass": True, "combined_final_run_required": False},
        "blocker": None,
        "metadata": {"scope_amendments": []},
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }
    get_store().create_debug_campaign(campaign)
    groups = [
        _create_debug_group(campaign_key, group_id, group_entries)
        for group_id, group_entries in _group_entries_by_signature(entries).items()
    ]
    return get_store().update_debug_campaign(
        campaign_key,
        {"selected_group_keys": [group["group_key"] for group in groups], "updated_at": utc_now()},
    )


def prepare_debug_group(group_key: str, expected_behavior: str, acceptance_criteria: list[str]) -> dict[str, Any]:
    if not expected_behavior.strip() or not acceptance_criteria:
        raise RuntimeError("Expected behavior and at least one acceptance criterion are required")
    return get_store().update_debug_group(group_key, {
        "status": "ready",
        "expected_behavior": sanitize_debug_text(expected_behavior),
        "acceptance_criteria": [sanitize_debug_text(criterion) for criterion in acceptance_criteria if criterion.strip()],
        "updated_at": utc_now(),
    })


def append_debug_group_attempt(
    group_key: str,
    approach: str,
    outcome: str,
    summary: str = "",
    run_keys: list[str] | None = None,
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    group = _debug_group(group_key)
    attempts = list(group.get("attempts") or [])
    attempts.append({
        "attempt": len(attempts) + 1,
        "approach": sanitize_debug_text(approach),
        "outcome": outcome,
        "summary": sanitize_debug_text(summary),
        "run_keys": run_keys or [],
        "changed_files": [sanitize_debug_path(path) for path in changed_files or []],
        "timestamp": utc_now(),
    })
    return get_store().update_debug_group(group_key, {"attempts": attempts, "status": "investigating", "updated_at": utc_now()})


def block_debug_group(group_key: str, reason: str, question: str, next_action: str) -> dict[str, Any]:
    group = _debug_group(group_key)
    blocker = {
        "reason": sanitize_debug_text(reason),
        "question": sanitize_debug_text(question),
        "next_action": sanitize_debug_text(next_action),
        "requires_user_input": True,
        "timestamp": utc_now(),
    }
    updated = get_store().update_debug_group(group_key, {"status": "blocked", "blocker": blocker, "updated_at": utc_now()})
    get_store().update_debug_campaign(group["campaign_key"], {
        "status": "blocked",
        "current_group_key": group_key,
        "blocker": blocker,
        "updated_at": utc_now(),
    })
    return updated


def debug_group_test_keys(campaign_key: str, group_key: str) -> list[str]:
    group = _debug_group(group_key)
    if group.get("campaign_key") != campaign_key:
        raise RuntimeError(f"Debug group {group_key} does not belong to campaign {campaign_key}")
    return sorted({str(key) for key in group.get("member_test_keys") or []})


def _passing_evidence_for_group(group: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    members = list(group.get("member_test_keys") or [])
    red_runs = set((group.get("red_evidence") or {}).get("run_keys") or [])
    passing_by_test: dict[str, dict[str, Any]] = {}
    for result in get_store().list_test_results(members):
        test_key_value = str(result.get("test_key") or "")
        run_key = str(result.get("run_key") or "")
        if result.get("status") != "passed" or run_key in red_runs:
            continue
        if int(result.get("created_at_unix") or 0) < int(group.get("selected_at_unix") or 0):
            continue
        run = get_store().get_test_run(run_key)
        if run.get("campaign_key") != group.get("campaign_key") or run.get("debug_group_key") != group.get("group_key"):
            continue
        if set(run.get("requested_tests") or []) != set(members):
            continue
        passing_by_test[test_key_value] = {
            "test_key": test_key_value,
            "run_key": run_key,
            "result_key": result.get("result_key"),
            "subject_commit": run.get("git_sha") or (result.get("metadata") or {}).get("git_sha"),
            "timestamp": result.get("created_at") or utc_now(),
        }
    missing = [member for member in members if member not in passing_by_test]
    return [passing_by_test[member] for member in members if member in passing_by_test], missing


def complete_debug_group(group_key: str, commit: str = "") -> dict[str, Any]:
    group = _debug_group(group_key)
    evidence, missing = _passing_evidence_for_group(group)
    if missing:
        raise RuntimeError("Cannot complete debug group; missing green evidence for: " + ", ".join(missing))
    completed = get_store().update_debug_group(group_key, {
        "status": "green",
        "green_evidence": evidence,
        "fixing_commit": commit,
        "blocker": None,
        "updated_at": utc_now(),
    })
    debug_campaign_status(str(group["campaign_key"]), persist=True)
    return completed


def add_debug_child_groups(campaign_key: str, parent_group_key: str, run_data: dict[str, Any]) -> list[dict[str, Any]]:
    campaign = _debug_campaign(campaign_key)
    known_keys = {
        str(key)
        for group in debug_groups_for_campaign(campaign_key)
        for key in group.get("member_test_keys") or []
    }
    entries = []
    for suite, test in iter_tests(run_data):
        if not is_problem(str(test.get("status") or "")):
            continue
        key = test_key(suite, test)
        if key in known_keys:
            continue
        failure = {
            **test,
            "suite": suite,
            "test": test_label(suite, test),
            "key": key,
            "run_id": run_data.get("run_id"),
        }
        category = classify_failure(failure)
        reason = short_reason(str(test.get("error") or ""))
        entries.append({
            **failure,
            "category": category,
            "reason": reason,
            "group_id": f"{category}-{root_signature(category, reason)}",
        })
    children = [
        _create_debug_group(
            campaign_key,
            group_id,
            grouped_entries,
            parent_group_key=parent_group_key,
            discovery_reason=f"Exposed by verification of {parent_group_key}",
        )
        for group_id, grouped_entries in _group_entries_by_signature(entries).items()
    ]
    if not children:
        return []
    metadata = dict(campaign.get("metadata") or {})
    amendments = list(metadata.get("scope_amendments") or [])
    amendments.extend({
        "parent_group_key": parent_group_key,
        "child_group_key": child["group_key"],
        "reason": child.get("metadata", {}).get("discovery_reason"),
        "timestamp": utc_now(),
    } for child in children)
    get_store().update_debug_campaign(campaign_key, {
        "status": "active",
        "selected_test_keys": sorted(set(campaign.get("selected_test_keys") or []).union(
            *(set(child.get("member_test_keys") or []) for child in children)
        )),
        "selected_group_keys": list(campaign.get("selected_group_keys") or []) + [child["group_key"] for child in children],
        "metadata": {**metadata, "scope_amendments": amendments},
        "updated_at": utc_now(),
    })
    return children


def debug_campaign_status(campaign_key: str, persist: bool = False) -> dict[str, Any]:
    campaign = _debug_campaign(campaign_key)
    groups = debug_groups_for_campaign(campaign_key)
    blocked = next((group for group in groups if group.get("status") == "blocked"), None)
    all_green = bool(groups) and all(group.get("status") == "green" for group in groups)
    status = "blocked" if blocked else "completed" if all_green else "active"
    blocker = blocked.get("blocker") if blocked else None
    next_group = next((group for group in groups if group.get("status") != "green"), None)
    fields = {
        "status": status,
        "current_group_key": next_group.get("group_key") if next_group else None,
        "blocker": blocker,
        "completed_at": utc_now() if status == "completed" else None,
        "updated_at": utc_now(),
    }
    if persist or campaign.get("status") != status or campaign.get("current_group_key") != fields["current_group_key"]:
        campaign = get_store().update_debug_campaign(campaign_key, fields)
    counts: dict[str, int] = {}
    for group in groups:
        group_status = str(group.get("status") or "selected")
        counts[group_status] = counts.get(group_status, 0) + 1
    return {
        "campaign": campaign,
        "groups": groups,
        "counts": counts,
        "next_action": str((blocker or {}).get("next_action") or (next_group or {}).get("verification_command") or ""),
    }


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


def lease_blocks_entry(lease: dict[str, Any], entry: dict[str, Any], now: datetime | None = None) -> bool:
    """Return whether an unexpired claim makes this failure unavailable to lease."""
    status = str(lease.get("status") or "")
    if status not in {"active", "released", "completed"}:
        return False

    if status in {"active", "released"}:
        expires_at = parse_utc(str(lease.get("expires_at") or ""))
        if expires_at is not None and expires_at <= (now or datetime.now(timezone.utc)):
            return False

    if str(lease.get("group_id") or "") != str(entry.get("group_id") or ""):
        return False
    if status == "active":
        return True

    leased_entry = lease.get("entry") if isinstance(lease.get("entry"), dict) else lease.get("entry_json")
    leased_entry = leased_entry if isinstance(leased_entry, dict) else {}
    if status == "completed":
        leased_run_id = str(leased_entry.get("run_id") or "")
        entry_run_id = str(entry.get("run_id") or "")
        return bool(leased_run_id and entry_run_id and leased_run_id == entry_run_id)
    if str(leased_entry.get("key") or "") != str(entry.get("key") or ""):
        return False
    return True


def active_lease_for_session(session_id: str = "", lease_id: str = "") -> dict[str, Any] | None:
    """Return an active, unexpired failed-test lease for a session or explicit id."""
    now = datetime.now(timezone.utc)
    for lease in load_leases().get("leases") or []:
        if lease.get("status") != "active":
            continue
        expires_at = parse_utc(str(lease.get("expires_at") or ""))
        if expires_at is not None and expires_at <= now:
            continue
        if lease_id and lease_id in {lease.get("lease_id"), lease.get("claim_key")}:
            return lease
        if session_id and lease.get("session_id") == session_id:
            return lease
    return None


def require_active_lease(session_id: str = "", lease_id: str = "") -> dict[str, Any] | None:
    """Require a failed-test lease only when there are current triage entries."""
    active_lease = active_lease_for_session(session_id=session_id, lease_id=lease_id)
    if active_lease:
        return active_lease
    triage = build_triage(limit=1)
    if not triage.get("entries"):
        return None
    hint = "python3 scripts/tests.py next --lease --session ${OPENCODE_SESSION_ID:-manual}"
    target = f" lease {lease_id}" if lease_id else f" session {session_id or 'manual'}"
    raise RuntimeError(
        f"No active failed-test lease for{target}. Claim the next failure group first: {hint}"
    )


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
        now = datetime.now(timezone.utc)
        for entry in triage.get("entries") or []:
            if any(lease_blocks_entry(lease, entry, now=now) for lease in leases):
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


def claim_next_debug_group(campaign_key: str, session_id: str, worker_id: str = "") -> dict[str, Any] | None:
    def _claim() -> dict[str, Any] | None:
        status = debug_campaign_status(campaign_key)
        if status["campaign"].get("status") == "blocked":
            return None
        existing_claims = load_leases().get("leases") or []
        now = datetime.now(timezone.utc)
        active_debug_group_keys = set()
        for claim in existing_claims:
            if claim.get("status") != "active":
                continue
            expires_at = parse_utc(str(claim.get("expires_at") or ""))
            if expires_at is not None and expires_at <= now:
                continue
            active_debug_group_keys.add(str(claim.get("debug_group_key") or ""))
        for group in status["groups"]:
            group_key = str(group["group_key"])
            if group.get("status") in {"green", "blocked"} or group_key in active_debug_group_keys:
                continue
            digest = hashlib.sha1(f"{group_key}:{session_id}:{utc_now()}".encode("utf-8")).hexdigest()[:8]
            lease_id = f"lease-{group.get('triage_group_id')}-{digest}"
            entry = {
                "group_id": group.get("triage_group_id"),
                "group_key": group_key,
                "member_test_keys": group.get("member_test_keys") or [],
                "verification_command": group.get("verification_command"),
            }
            lease = {
                "lease_id": lease_id,
                "claim_key": lease_id,
                "group_id": group.get("triage_group_id"),
                "campaign_key": campaign_key,
                "debug_group_key": group_key,
                "status": "active",
                "session_id": session_id,
                "worker_id": worker_id,
                "leased_at": utc_now(),
                "expires_at": lease_deadline(),
                "expires_at_unix": int((datetime.now(timezone.utc) + timedelta(hours=LEASE_TTL_HOURS)).timestamp()),
                "entry": entry,
            }
            get_store().create_claim(lease)
            get_store().update_debug_campaign(campaign_key, {
                "current_group_key": group_key,
                "session_id": session_id,
                "updated_at": utc_now(),
            })
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
    run_data = normalize_import_run_data(run_data, path, external_run_id=external_run_id, workflow=workflow)
    if source == "github_actions":
        return ingest_github_actions_run(run_data, external_run_id=external_run_id, workflow=workflow)
    return record_run_result(run_data, source=source, external_run_id=external_run_id, workflow=workflow)


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
    elif "--core-journeys" in args:
        suite = "core-journeys"
    for index, arg in enumerate(args):
        if arg == "--suite" and index + 1 < len(args):
            suite = args[index + 1]
        if arg == "--spec" and index + 1 < len(args):
            suite = "playwright"
            tests.append(args[index + 1])
    if "--only-failed" in args:
        tests = ["only-failed"]
    return suite, tests


def campaign_runner_args(test_keys: list[str], forwarded_args: list[str]) -> tuple[list[str], list[str]]:
    if any(arg in {"--spec", "--suite", "--only-failed"} or arg.startswith(("--spec=", "--suite=")) for arg in forwarded_args):
        raise RuntimeError("Campaign group runs cannot combine explicit --spec, --suite, or --only-failed targets")
    suites = {key.partition("::")[0] for key in test_keys}
    if len(suites) != 1:
        raise RuntimeError("A debug group must contain tests from one execution suite")
    suite = next(iter(suites))
    labels = [key.partition("::")[2] for key in test_keys]
    if suite == "playwright":
        return [*forwarded_args, "--suite", "playwright", "--only-failed"], labels
    if suite.startswith("pytest"):
        return [*forwarded_args, "--suite", "pytest"], labels
    if suite.startswith("vitest"):
        invalid = [
            label for label in labels
            if "frontend/packages/ui/" not in label and "frontend/apps/web_app/" not in label
        ]
        if invalid:
            raise RuntimeError("Vitest campaign keys must identify UI or web-app test files: " + ", ".join(invalid))
        return [*forwarded_args, "--suite", "vitest"], labels
    raise RuntimeError(
        f"Exact campaign selection is not available for suite {suite}; "
        "record a structured blocker instead of running a broader suite as false group evidence"
    )


def seeded_only_failed_files_from_lease(lease: dict[str, Any] | None, args: list[str]) -> list[str]:
    if not lease or "--only-failed" not in args:
        return []
    entry = lease.get("entry") if isinstance(lease.get("entry"), dict) else lease.get("entry_json")
    if not isinstance(entry, dict):
        return []
    test_name = str(entry.get("test") or "")
    if not test_name or test_name.endswith(".spec.ts"):
        return []
    return [test_name]


def run_targets_playwright(args: list[str]) -> bool:
    suite, tests = infer_run_suite_and_tests(args)
    return suite in {"playwright", "hourly-dev", "core-journeys"} or any(
        test.endswith(".spec.ts") for test in tests
    )


def docker_resources_for_run(args: list[str]) -> set[str]:
    """Return host Docker resources required for the selected test run."""
    suite, _tests = infer_run_suite_and_tests(args)
    if run_targets_playwright(args) or suite in {"all", "cli"}:
        return {session_control.DOCKER_RESOURCE_DEV_STACK}
    return set()


def acquire_docker_test_lease(lease_id: str, owner: str, resources: set[str]) -> None:
    session_control.acquire_test_resource_lease(lease_id, owner, resources)


def release_docker_test_lease(lease_id: str) -> None:
    session_control.release_test_resource_lease(lease_id)


def check_dev_health_urls(urls: tuple[str, ...] = DEV_HEALTH_URLS, timeout: int = 10) -> list[str]:
    failures: list[str] = []
    for url in urls:
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", response.getcode())
                if int(status) >= 500:
                    failures.append(f"{url} returned HTTP {status}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failures.append(f"{url} failed: {exc}")
    return failures


def check_vercel_ready_for_commit(git_sha: str) -> list[str]:
    """Use the canonical run_tests.py Vercel wait so the gate is tied to a commit."""
    spec = importlib.util.spec_from_file_location("openmates_run_tests_gate", RUN_TESTS_SCRIPT)
    if spec is None or spec.loader is None:
        return [f"Could not load {RUN_TESTS_SCRIPT}"]
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    ok, reason = module._wait_for_vercel_deployment(git_sha, module._read_env_file())
    return [] if ok else [reason or f"Vercel deployment is not Ready for {git_sha}"]


def run_e2e_deploy_gate(options: ControlRunOptions) -> None:
    """Preflight E2E dispatch so agents do not test a stale or unreachable dev app."""
    if not run_targets_playwright(options.forwarded_args):
        print("E2E deploy gate: SKIPPED (run does not target Playwright)")
        return
    expected_commit = options.expected_commit or current_git_sha()
    actual_commit = current_git_sha()
    if not _matches_commit_prefix(actual_commit, expected_commit):
        raise RuntimeError(
            "E2E deploy gate refused a moving target: "
            f"expected {expected_commit}, current HEAD is {actual_commit[:9]}"
        )
    if os.environ.get("OPENMATES_SKIP_E2E_DEPLOY_GATE", "").lower() == "true":
        print("E2E deploy gate: SKIPPED (OPENMATES_SKIP_E2E_DEPLOY_GATE=true)")
        return
    failures = [*check_vercel_ready_for_commit(expected_commit), *check_dev_health_urls()]
    if failures:
        raise RuntimeError("E2E deploy gate failed: " + "; ".join(failures))
    print(f"E2E deploy gate: PASSED ({actual_commit[:9]}, dev endpoints reachable)")


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


def record_latest_run_artifact(
    expected_commit: str = "",
    since_mtime: float = 0.0,
    requested_test_keys: list[str] | None = None,
    campaign_key: str = "",
    debug_group_key: str = "",
) -> str:
    artifacts = run_recording_artifacts(since_mtime=since_mtime)
    if not artifacts:
        return ""
    for index, artifact in enumerate(artifacts):
        if index > 0:
            reset_store()
        try:
            run_data = read_json(artifact, {})
            if requested_test_keys is not None:
                run_data["requested_tests"] = requested_test_keys
            if campaign_key:
                run_data["campaign_key"] = campaign_key
            if debug_group_key:
                run_data["debug_group_key"] = debug_group_key
            run_git_sha = str(run_data.get("git_sha") or "")
            if expected_commit and not _matches_commit_prefix(run_git_sha, expected_commit):
                print(
                    "Test run completed for a different commit than requested: "
                    f"expected {expected_commit}, got {run_data.get('git_sha')}",
                    file=sys.stderr,
                )
                return ""
            record_run_result(run_data)
            if index > 0:
                print(f"Imported fallback run artifact: {display_path(artifact)}", file=sys.stderr)
            return run_git_sha or expected_commit
        except Exception as exc:
            print(f"Could not record run artifact {display_path(artifact)}: {exc}", file=sys.stderr)
    print("Run finished, but Directus recording failed for all generated artifacts.", file=sys.stderr)
    return ""


def command_run(runner_args: list[str]) -> int:
    try:
        options = parse_control_run_options(runner_args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if options.expected_commit:
        actual_commit = current_git_sha()
        if not _matches_commit_prefix(actual_commit, options.expected_commit):
            print(
                "Refusing to dispatch tests for a moving target: "
                f"expected commit {options.expected_commit}, current HEAD is {actual_commit[:9]}",
                file=sys.stderr,
            )
            return 2
    active_lease: dict[str, Any] | None = None
    selected_test_keys: list[str] = []
    selected_test_labels: list[str] = []
    if bool(options.campaign_key) != bool(options.debug_group_key):
        print("Campaign-bound runs require both --campaign and --group.", file=sys.stderr)
        return 2
    if options.campaign_key:
        try:
            selected_test_keys = debug_group_test_keys(options.campaign_key, options.debug_group_key)
            forwarded_args, selected_test_labels = campaign_runner_args(selected_test_keys, options.forwarded_args)
            options = ControlRunOptions(
                forwarded_args=forwarded_args,
                expected_commit=options.expected_commit,
                gate_deploy=options.gate_deploy,
                lease_required=options.lease_required,
                lease_id=options.lease_id,
                campaign_key=options.campaign_key,
                debug_group_key=options.debug_group_key,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if options.lease_required:
        try:
            active_lease = require_active_lease(
                session_id=os.environ.get("OPENCODE_SESSION_ID", "manual"),
                lease_id=options.lease_id,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    resources = docker_resources_for_run(options.forwarded_args)
    docker_lease_id = f"test-{uuid.uuid4().hex[:12]}" if resources else ""
    if docker_lease_id:
        try:
            acquire_docker_test_lease(
                docker_lease_id,
                os.environ.get("OPENCODE_SESSION_ID", "manual"),
                resources,
            )
        except RuntimeError as exc:
            print(f"Test dispatch blocked by Docker restart coordination: {exc}", file=sys.stderr)
            return 2
    if options.gate_deploy:
        try:
            run_e2e_deploy_gate(options)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            if docker_lease_id:
                release_docker_test_lease(docker_lease_id)
            return 2
    try:
        preflight_test_control_plane()
    except RuntimeError as exc:
        print(
            "Test control-plane preflight failed before dispatch. "
            f"{exc}",
            file=sys.stderr,
        )
        if docker_lease_id:
            release_docker_test_lease(docker_lease_id)
        return 2

    command = [sys.executable, str(RUN_TESTS_SCRIPT), *options.forwarded_args]
    run_env = os.environ.copy()
    if docker_lease_id:
        run_env["OPENMATES_DOCKER_TEST_LEASE_HELD"] = "1"
    seeded_failed_files = seeded_only_failed_files_from_lease(active_lease, options.forwarded_args)
    if selected_test_labels:
        run_env["OPENMATES_CAMPAIGN_TEST_LABELS_JSON"] = json.dumps(selected_test_labels)
        if all(key.startswith("playwright::") for key in selected_test_keys):
            seeded_failed_files = selected_test_labels
    if seeded_failed_files:
        run_env["OPENMATES_ONLY_FAILED_FILES_JSON"] = json.dumps(seeded_failed_files)
    try:
        if selected_test_keys:
            mark_test_keys_running(selected_test_keys, command=["python3", "scripts/tests.py", "run", *runner_args])
        else:
            suite, tests = infer_run_suite_and_tests(options.forwarded_args)
            mark_running(suite=suite, tests=tests, command=["python3", "scripts/tests.py", "run", *runner_args])
        artifact_start_mtime = datetime.now(timezone.utc).timestamp() - 1
        result = subprocess.run(command, cwd=PROJECT_ROOT, env=run_env)
        recorded_commit = record_latest_run_artifact(
            expected_commit=options.expected_commit,
            since_mtime=artifact_start_mtime,
            requested_test_keys=selected_test_keys or None,
            campaign_key=options.campaign_key,
            debug_group_key=options.debug_group_key,
        )
        if not recorded_commit:
            return 2 if options.expected_commit else result.returncode
        if options.campaign_key:
            artifacts = run_recording_artifacts(since_mtime=artifact_start_mtime)
            if artifacts:
                add_debug_child_groups(options.campaign_key, options.debug_group_key, read_json(artifacts[0], {}))
        return result.returncode
    finally:
        if docker_lease_id:
            release_docker_test_lease(docker_lease_id)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] == "run":
        runner_args = raw_argv[1:]
        if runner_args and runner_args[0] == "--":
            runner_args = runner_args[1:]
        return command_run(runner_args)

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

    lease_required_parser = sub.add_parser("lease-required", help="Fail when current failed-test work has no active lease")
    lease_required_parser.add_argument("--session", default=os.environ.get("OPENCODE_SESSION_ID", "manual"))
    lease_required_parser.add_argument("--lease-id", default="")
    lease_required_parser.add_argument("--json", action="store_true")

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

    campaign_parser = sub.add_parser("campaign", help="Manage durable failed-test debug campaigns")
    campaign_sub = campaign_parser.add_subparsers(dest="campaign_command", required=True)
    campaign_start = campaign_sub.add_parser("start", help="Create or resume a campaign")
    campaign_start.add_argument("--session", default=os.environ.get("OPENCODE_SESSION_ID", "manual"))
    campaign_start.add_argument("--campaign", default="")
    campaign_start.add_argument("--test-key", action="append", default=[])
    campaign_start.add_argument("--json", action="store_true")
    campaign_status = campaign_sub.add_parser("status", help="Show campaign groups, evidence, and next action")
    campaign_status.add_argument("--campaign", required=True)
    campaign_status.add_argument("--json", action="store_true")
    campaign_next = campaign_sub.add_parser("next", help="Lease the next durable campaign group")
    campaign_next.add_argument("--campaign", required=True)
    campaign_next.add_argument("--session", default=os.environ.get("OPENCODE_SESSION_ID", "manual"))
    campaign_next.add_argument("--worker", default="")
    campaign_next.add_argument("--lease", action="store_true")
    campaign_next.add_argument("--json", action="store_true")
    campaign_prepare = campaign_sub.add_parser("prepare", help="Record expected behavior and acceptance criteria")
    campaign_prepare.add_argument("--group", required=True)
    campaign_prepare.add_argument("--expected-behavior", required=True)
    campaign_prepare.add_argument("--criterion", action="append", required=True)
    campaign_attempt = campaign_sub.add_parser("attempt", help="Append a durable investigation attempt")
    campaign_attempt.add_argument("--group", required=True)
    campaign_attempt.add_argument("--approach", required=True)
    campaign_attempt.add_argument("--outcome", required=True, choices=["failed", "blocked", "green", "rejected"])
    campaign_attempt.add_argument("--summary", default="")
    campaign_attempt.add_argument("--run-key", action="append", default=[])
    campaign_attempt.add_argument("--changed-file", action="append", default=[])
    campaign_block = campaign_sub.add_parser("block", help="Record a structured campaign blocker")
    campaign_block.add_argument("--group", required=True)
    campaign_block.add_argument("--reason", required=True)
    campaign_block.add_argument("--question", required=True)
    campaign_block.add_argument("--next-action", required=True)
    campaign_complete = campaign_sub.add_parser("complete-group", help="Complete a group after all members pass")
    campaign_complete.add_argument("--group", required=True)
    campaign_complete.add_argument("--commit", default="")

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
    if args.command == "lease-required":
        try:
            require_active_lease(session_id=args.session, lease_id=args.lease_id)
        except RuntimeError as exc:
            if args.json:
                print(json.dumps({"ok": False, "reason": str(exc)}, indent=2, sort_keys=True))
            else:
                print(str(exc), file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps({"ok": True}, indent=2, sort_keys=True))
        else:
            print("Failed-test lease gate: PASSED")
        return 0
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
    if args.command == "campaign":
        try:
            if args.campaign_command == "start":
                payload = start_debug_campaign(args.session, selected_test_keys=args.test_key or None, campaign_key=args.campaign)
            elif args.campaign_command == "status":
                payload = debug_campaign_status(args.campaign)
            elif args.campaign_command == "next":
                payload = claim_next_debug_group(args.campaign, args.session, worker_id=args.worker)
                if payload is None:
                    raise RuntimeError("No available campaign group; inspect campaign status for blockers or completion")
            elif args.campaign_command == "prepare":
                payload = prepare_debug_group(args.group, args.expected_behavior, args.criterion)
            elif args.campaign_command == "attempt":
                payload = append_debug_group_attempt(
                    args.group,
                    args.approach,
                    args.outcome,
                    summary=args.summary,
                    run_keys=args.run_key,
                    changed_files=args.changed_file,
                )
            elif args.campaign_command == "block":
                payload = block_debug_group(args.group, args.reason, args.question, args.next_action)
            else:
                payload = complete_debug_group(args.group, commit=args.commit)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.command == "run":
        runner_args = list(args.runner_args)
        if runner_args and runner_args[0] == "--":
            runner_args = runner_args[1:]
        return command_run(runner_args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
