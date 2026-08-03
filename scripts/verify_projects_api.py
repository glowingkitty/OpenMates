#!/usr/bin/env python3
"""Verify Personal and Team Project routes against a real OpenMates API.

The verifier logs into an existing test account with the repository helper,
uses its temporary session only for direct REST requests, and removes every
fixture it creates. Output contains stable check names and classifications,
never cookies, ciphertext, identifiers, response bodies, or private data.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import uuid


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_URL = "https://api.dev.openmates.org"
FORBIDDEN_TEAM_SOURCE_FIELDS = {
    "id",
    "hashed_project_id",
    "hashed_user_id",
    "hashed_team_id",
    "attached_by_user_hash",
    "source_session_id",
    "key_epoch",
}
TEAM_SOURCE_SAFE_FIELDS = {
    "source_id",
    "source_type",
    "encrypted_display_name",
    "encrypted_metadata",
    "capabilities",
    "status",
    "created_at",
    "updated_at",
    "last_indexed_at",
    "ownership_label",
}


class VerificationFailure(RuntimeError):
    """A stable, non-sensitive verification failure."""

    def __init__(self, scenario: str, code: str) -> None:
        super().__init__(code)
        self.scenario = scenario
        self.code = code


@dataclass(frozen=True)
class ApiResponse:
    status: int
    payload: dict[str, Any]


def derive_web_origin(api_url: str) -> str:
    parsed = urlparse(api_url)
    if parsed.hostname == "api.dev.openmates.org":
        return "https://app.dev.openmates.org"
    if parsed.hostname == "api.openmates.org":
        return "https://openmates.org"
    return f"{parsed.scheme}://{parsed.netloc}"


def validate_api_url(api_url: str) -> str:
    parsed = urlparse(api_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise VerificationFailure("setup", "invalid_api_url")
    if parsed.hostname == "api.openmates.org":
        raise VerificationFailure("setup", "production_target_refused")
    return api_url.rstrip("/")


def opaque_ciphertext() -> str:
    payload = b"OM\x01\x00\x00\x00" + os.urandom(40)
    return base64.b64encode(payload).decode("ascii")


def unix_seconds(timestamp: int | None = None) -> int:
    return timestamp if timestamp is not None else int(time.time())


def project_payload(project_id: str, *, team_id: str | None = None, timestamp: int | None = None) -> dict[str, Any]:
    now = unix_seconds(timestamp)
    payload: dict[str, Any] = {
        "project_id": project_id,
        "encrypted_project_key": opaque_ciphertext() if team_id is None else None,
        "encrypted_name": opaque_ciphertext(),
        "encrypted_description": opaque_ciphertext(),
        "created_at": now,
        "updated_at": now,
        "last_opened_at": now,
        "key_wrappers": [],
    }
    if team_id:
        payload["key_wrappers"] = [
            {
                "key_type": "team",
                "hashed_team_id": hashlib.sha256(team_id.encode("utf-8")).hexdigest(),
                "team_key_epoch": 1,
                "encrypted_project_key": opaque_ciphertext(),
                "wrapper_version": 1,
                "created_at": now,
            }
        ]
    return payload


def source_payload(source_id: str, *, timestamp: int | None = None) -> dict[str, Any]:
    now = unix_seconds(timestamp)
    return {
        "source_id": source_id,
        "source_type": "local_folder",
        "encrypted_display_name": opaque_ciphertext(),
        "encrypted_metadata": opaque_ciphertext(),
        "capabilities": ["read", "search"],
        "status": "offline",
        "created_at": now,
        "updated_at": now,
    }


def team_payload(team_id: str, *, timestamp: int | None = None) -> dict[str, Any]:
    return {
        "team_id": team_id,
        "encrypted_name": opaque_ciphertext(),
        "encrypted_team_key": opaque_ciphertext(),
        "created_at": unix_seconds(timestamp),
    }


def project_ids(payload: dict[str, Any]) -> set[str]:
    projects = payload.get("projects")
    if not isinstance(projects, list):
        raise VerificationFailure("response_contract", "projects_list_missing")
    return {
        str(project["project_id"])
        for project in projects
        if isinstance(project, dict) and isinstance(project.get("project_id"), str)
    }


def source_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise VerificationFailure("response_contract", "sources_list_missing")
    return [source for source in sources if isinstance(source, dict)]


def assert_status(response: ApiResponse, expected: int, scenario: str) -> None:
    if response.status != expected:
        raise VerificationFailure(scenario, f"expected_http_{expected}_got_{response.status}")


def assert_detail(response: ApiResponse, expected: str, scenario: str) -> None:
    detail = response.payload.get("detail")
    actual = detail if isinstance(detail, str) else detail.get("error") if isinstance(detail, dict) else None
    if actual != expected:
        raise VerificationFailure(scenario, "unexpected_error_code")


class RestClient:
    def __init__(self, api_url: str, headers: dict[str, str] | None = None) -> None:
        self.api_url = api_url.rstrip("/")
        self.headers = headers or {}

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        scenario: str,
    ) -> ApiResponse:
        suffix = f"?{urlencode(query)}" if query else ""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json", **self.headers}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.api_url}{path}{suffix}", data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=60) as response:
                return ApiResponse(response.status, self._parse_payload(response.read(), scenario))
        except HTTPError as exc:
            return ApiResponse(exc.code, self._parse_payload(exc.read(), scenario))
        except (TimeoutError, URLError) as exc:
            raise VerificationFailure(scenario, "transport_error") from exc

    @staticmethod
    def _parse_payload(raw: bytes, scenario: str) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VerificationFailure(scenario, "invalid_json_response") from exc
        if not isinstance(payload, dict):
            raise VerificationFailure(scenario, "unexpected_json_shape")
        return payload


def login_test_account(api_url: str, home: Path, slot: str | None, web_origin: str) -> dict[str, str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
    }
    command = [
        "node",
        "scripts/openmates_cli_test_account.mjs",
        "login",
        "--api-url",
        api_url,
        "--web-origin",
        web_origin,
    ]
    if slot:
        command.extend(["--slot", slot])
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise VerificationFailure("authentication", "test_account_login_timeout") from exc
    if completed.returncode != 0:
        raise VerificationFailure("authentication", "test_account_login_failed")

    session_path = home / ".openmates" / "session.json"
    try:
        session = json.loads(session_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationFailure("authentication", "test_account_session_missing") from exc
    cookies = session.get("cookies")
    if not isinstance(cookies, dict) or not cookies:
        raise VerificationFailure("authentication", "test_account_cookies_missing")
    cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items() if isinstance(value, str))
    if not cookie_header:
        raise VerificationFailure("authentication", "test_account_cookies_missing")
    return {
        "Cookie": cookie_header,
        "Origin": web_origin,
        "X-OpenMates-SDK": "cli",
        "X-OpenMates-Device-Identity": "cli:projects-api-verifier",
    }


def require_project(response: ApiResponse, project_id: str, scenario: str) -> dict[str, Any]:
    project = response.payload.get("project")
    if not isinstance(project, dict) or project.get("project_id") != project_id:
        raise VerificationFailure(scenario, "project_response_mismatch")
    return project


def verify_source_lifecycle(client: RestClient, project_id: str, team_id: str | None, scenario: str) -> int:
    source_id = str(uuid.uuid4())
    context = {"team_id": team_id} if team_id else None
    created = client.request(
        "POST",
        f"/v1/projects/{project_id}/sources",
        body=source_payload(source_id),
        query=context,
        scenario=f"{scenario}_source_create",
    )
    assert_status(created, 200, f"{scenario}_source_create")

    listed = client.request(
        "GET",
        f"/v1/projects/{project_id}/sources",
        query=context,
        scenario=f"{scenario}_source_list",
    )
    assert_status(listed, 200, f"{scenario}_source_list")
    matching = [source for source in source_records(listed.payload) if source.get("source_id") == source_id]
    if len(matching) != 1:
        raise VerificationFailure(f"{scenario}_source_list", "source_not_listed")
    if team_id and (set(matching[0]) - TEAM_SOURCE_SAFE_FIELDS or set(matching[0]) & FORBIDDEN_TEAM_SOURCE_FIELDS):
        raise VerificationFailure(f"{scenario}_source_list", "unsafe_team_source_projection")
    if team_id and matching[0].get("ownership_label") not in {"attached_by_you", "team_source"}:
        raise VerificationFailure(f"{scenario}_source_list", "team_source_ownership_label_missing")

    deleted = client.request(
        "DELETE",
        f"/v1/projects/{project_id}/sources/{source_id}",
        query={"confirmed": "true", **({"team_id": team_id} if team_id else {})},
        scenario=f"{scenario}_source_delete",
    )
    assert_status(deleted, 200, f"{scenario}_source_delete")
    after = client.request(
        "GET",
        f"/v1/projects/{project_id}/sources",
        query=context,
        scenario=f"{scenario}_source_delete_verify",
    )
    assert_status(after, 200, f"{scenario}_source_delete_verify")
    if any(source.get("source_id") == source_id for source in source_records(after.payload)):
        raise VerificationFailure(f"{scenario}_source_delete_verify", "source_still_listed")
    return 4


def verify_project_lifecycle(client: RestClient, project_id: str, team_id: str | None, scenario: str) -> int:
    context = {"team_id": team_id} if team_id else None
    created = client.request(
        "POST",
        "/v1/projects",
        body=project_payload(project_id, team_id=team_id),
        query=context,
        scenario=f"{scenario}_create",
    )
    assert_status(created, 200, f"{scenario}_create")
    require_project(created, project_id, f"{scenario}_create")

    listed = client.request("GET", "/v1/projects", query=context, scenario=f"{scenario}_list")
    assert_status(listed, 200, f"{scenario}_list")
    if project_id not in project_ids(listed.payload):
        raise VerificationFailure(f"{scenario}_list", "project_not_listed")

    shown = client.request("GET", f"/v1/projects/{project_id}", query=context, scenario=f"{scenario}_get")
    assert_status(shown, 200, f"{scenario}_get")
    require_project(shown, project_id, f"{scenario}_get")
    if not isinstance(shown.payload.get("folders"), list) or not isinstance(shown.payload.get("items"), list):
        raise VerificationFailure(f"{scenario}_get", "project_children_missing")

    updated_ciphertext = opaque_ciphertext()
    updated = client.request(
        "PATCH",
        f"/v1/projects/{project_id}",
        body={"encrypted_name": updated_ciphertext, "updated_at": unix_seconds()},
        query=context,
        scenario=f"{scenario}_update",
    )
    assert_status(updated, 200, f"{scenario}_update")
    if require_project(updated, project_id, f"{scenario}_update").get("encrypted_name") != updated_ciphertext:
        raise VerificationFailure(f"{scenario}_update", "encrypted_update_mismatch")

    archived = client.request(
        "PATCH",
        f"/v1/projects/{project_id}",
        body={"archived": True, "updated_at": unix_seconds()},
        query=context,
        scenario=f"{scenario}_archive",
    )
    assert_status(archived, 200, f"{scenario}_archive")
    if require_project(archived, project_id, f"{scenario}_archive").get("archived") is not True:
        raise VerificationFailure(f"{scenario}_archive", "archive_state_mismatch")
    active = client.request("GET", "/v1/projects", query=context, scenario=f"{scenario}_archive_list")
    assert_status(active, 200, f"{scenario}_archive_list")
    if project_id in project_ids(active.payload):
        raise VerificationFailure(f"{scenario}_archive_list", "archived_project_in_active_list")
    with_archived = client.request(
        "GET",
        "/v1/projects",
        query={"include_archived": "true", **({"team_id": team_id} if team_id else {})},
        scenario=f"{scenario}_archive_list_all",
    )
    assert_status(with_archived, 200, f"{scenario}_archive_list_all")
    if project_id not in project_ids(with_archived.payload):
        raise VerificationFailure(f"{scenario}_archive_list_all", "archived_project_not_listed")

    unarchived = client.request(
        "PATCH",
        f"/v1/projects/{project_id}",
        body={"archived": False, "updated_at": unix_seconds()},
        query=context,
        scenario=f"{scenario}_unarchive",
    )
    assert_status(unarchived, 200, f"{scenario}_unarchive")
    if require_project(unarchived, project_id, f"{scenario}_unarchive").get("archived") is not False:
        raise VerificationFailure(f"{scenario}_unarchive", "unarchive_state_mismatch")

    return 8 + verify_source_lifecycle(client, project_id, team_id, scenario)


def delete_project(client: RestClient, project_id: str, team_id: str | None, scenario: str, *, allow_missing: bool = False) -> None:
    response = client.request(
        "DELETE",
        f"/v1/projects/{project_id}",
        query={"team_id": team_id} if team_id else None,
        scenario=scenario,
    )
    if allow_missing and response.status == 404:
        return
    assert_status(response, 200, scenario)


def cleanup_resources(
    client: RestClient,
    personal_project_id: str | None,
    team_project_id: str | None,
    team_id: str | None,
) -> dict[str, Any]:
    failures: list[str] = []
    for label, project_id, context in (
        ("personal_project", personal_project_id, None),
        ("team_project", team_project_id, team_id),
    ):
        if not project_id:
            continue
        try:
            delete_project(client, project_id, context, f"cleanup_{label}", allow_missing=True)
        except VerificationFailure:
            failures.append(label)
    if team_id:
        try:
            response = client.request("DELETE", f"/v1/teams/{team_id}", scenario="cleanup_team")
        except VerificationFailure:
            failures.append("team")
        else:
            if response.status not in {200, 404}:
                failures.append("team")
    return {"status": "passed" if not failures else "failed", "failed_resources": sorted(failures)}


def classification() -> dict[str, Any]:
    return {
        "access_model": "first_party_client_only",
        "authentication": "approved_test_account_session_cookie",
        "owner_scoping": ["personal_user", "team_role"],
        "data_boundary": "opaque_client_side_encrypted_metadata_only",
        "decrypted_plaintext": "none",
        "credit_budget": "none",
        "rate_limits": {
            "list_get_sources": "60/minute",
            "create_update_source_create": "30/minute",
            "source_delete_project_delete": "20/minute",
        },
    }


def run_verification(api_url: str, headers: dict[str, str]) -> tuple[dict[str, Any], int]:
    client = RestClient(api_url, headers)
    unauthenticated = RestClient(api_url)
    personal_project_id = str(uuid.uuid4())
    team_project_id = str(uuid.uuid4())
    team_id = str(uuid.uuid4())
    personal_create_attempted = False
    team_fixture_created = False
    team_project_create_attempted = False
    scenarios: dict[str, Any] = {}
    failure: VerificationFailure | None = None

    try:
        unauth = unauthenticated.request("GET", "/v1/projects", scenario="unauthenticated")
        assert_status(unauth, 401, "unauthenticated")
        scenarios["unauthenticated"] = {"status": "passed", "checks": 1}

        non_member_team = client.request(
            "GET",
            "/v1/projects",
            query={"team_id": str(uuid.uuid4())},
            scenario="team_role_denial",
        )
        assert_status(non_member_team, 403, "team_role_denial")
        assert_detail(non_member_team, "TEAM_PERMISSION_DENIED", "team_role_denial")
        scenarios["team_role_denial"] = {"status": "passed", "checks": 1, "role": "non_member"}

        team_created = client.request(
            "POST",
            "/v1/teams",
            body=team_payload(team_id),
            scenario="team_fixture_create",
        )
        assert_status(team_created, 200, "team_fixture_create")
        team_fixture_created = True

        personal_create_attempted = True
        personal_checks = verify_project_lifecycle(client, personal_project_id, None, "personal")
        scenarios["personal"] = {"status": "passed", "checks": personal_checks}
        team_project_create_attempted = True
        team_checks = verify_project_lifecycle(client, team_project_id, team_id, "team")
        scenarios["team"] = {"status": "passed", "checks": team_checks}

        personal_in_team = client.request(
            "GET",
            f"/v1/projects/{personal_project_id}",
            query={"team_id": team_id},
            scenario="personal_in_team_context",
        )
        assert_status(personal_in_team, 404, "personal_in_team_context")
        team_in_personal = client.request(
            "GET",
            f"/v1/projects/{team_project_id}",
            scenario="team_in_personal_context",
        )
        assert_status(team_in_personal, 404, "team_in_personal_context")
        scenarios["context_denials"] = {"status": "passed", "checks": 2}

        delete_project(client, personal_project_id, None, "personal_delete")
        delete_project(client, team_project_id, team_id, "team_delete")
        scenarios["delete"] = {"status": "passed", "checks": 2}
    except VerificationFailure as exc:
        failure = exc
        scenarios.setdefault(exc.scenario, {"status": "failed", "code": exc.code})
    finally:
        cleanup = cleanup_resources(
            client,
            personal_project_id if personal_create_attempted else None,
            team_project_id if team_project_create_attempted else None,
            team_id if team_fixture_created else None,
        )

    if cleanup["status"] != "passed" and failure is None:
        failure = VerificationFailure("cleanup", "cleanup_failed")
        scenarios["cleanup"] = {"status": "failed", "code": "cleanup_failed"}
    report = {
        "status": "failed" if failure else "passed",
        "classification": classification(),
        "scenarios": scenarios,
        "cleanup": cleanup,
        "not_run": {
            "multi_account_role_matrix": "requires additional viewer/member account provisioning",
            "rate_limit_exhaustion": "avoids consuming shared dev rate-limit budget",
        },
    }
    return report, 1 if failure else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Personal and Team Project routes through direct REST.")
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", DEFAULT_API_URL), help="Real non-production API URL")
    parser.add_argument("--web-origin", help="Origin used by the existing test-account login helper")
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"), help="Optional configured test-account slot")
    parser.add_argument("--personal-and-team", action="store_true", help="Run both required Project workspace contexts")
    args = parser.parse_args(argv)
    if not args.personal_and_team:
        parser.error("--personal-and-team is required")

    try:
        api_url = validate_api_url(args.api_url)
        web_origin = args.web_origin or derive_web_origin(api_url)
        with tempfile.TemporaryDirectory(prefix="openmates-projects-api-") as home:
            headers = login_test_account(api_url, Path(home), args.slot, web_origin)
            report, exit_code = run_verification(api_url, headers)
    except VerificationFailure as exc:
        report = {
            "status": "failed",
            "classification": classification(),
            "scenarios": {exc.scenario: {"status": "failed", "code": exc.code}},
            "cleanup": {"status": "not_started", "failed_resources": []},
        }
        exit_code = 1
    except Exception:  # noqa: BLE001 - never print unexpected private response or auth data.
        report = {
            "status": "failed",
            "classification": classification(),
            "scenarios": {"internal": {"status": "failed", "code": "unexpected_internal_error"}},
            "cleanup": {"status": "unknown", "failed_resources": []},
        }
        exit_code = 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
