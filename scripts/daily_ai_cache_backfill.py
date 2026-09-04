#!/usr/bin/env python3
"""Host-side, receipt-gated nightly live-cache backfill orchestration.

This module deliberately does not call git. Cache source changes are left for
the existing sessions.py deploy integration, which owns scoped commit locking.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


RECEIPT_SCHEMA_VERSION = 1
FORBIDDEN_RECEIPT_FIELDS = frozenset({
    "authorization", "cache_key", "cookie", "credential", "email", "headers",
    "prompt", "response", "tool_payload", "user_id", "chat_id", "account_id",
    "identifier", "request_id", "provider_request_id", "x-api-key",
})
RUN_ID_PATTERN = re.compile(r"^daily-cache-backfill-[0-9]{8}-[a-f0-9]{12}$")
SAFE_GROUP_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
SENSITIVE_CONTENT_PATTERN = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._-]{16,}|(?:api[_ -]?key|password|secret|token)\s*[:=]\s*[^\s]{8,}|\bsk-[a-z0-9_-]{12,})"
)
FORBIDDEN_CACHE_FIELDS = frozenset({
    "access_token", "account_id", "authorization", "chat_id", "cookie", "credential",
    "email", "password", "refresh_token", "secret", "set-cookie", "user_id", "x-api-key",
})


@dataclass(frozen=True)
class BackfillPlan:
    spec: str
    cache_group: str
    candidate_run_id: str


class BackfillValidationError(RuntimeError):
    """A candidate cannot safely be promoted."""


def candidate_run_id(utc_date: str, spec: str) -> str:
    """Return a deterministic, non-identifying run ID for one UTC daily plan."""
    digest = hashlib.sha256(f"{utc_date}:{spec}".encode("utf-8")).hexdigest()[:12]
    return f"daily-cache-backfill-{utc_date.replace('-', '')}-{digest}"


def select_backfill_plan(entries: list[dict[str, str]], utc_date: str) -> BackfillPlan | None:
    """Select one stable pending entry; no pending group means no-op."""
    pending = sorted(
        (entry for entry in entries if entry.get("classification") == "backfill_pending"),
        key=lambda entry: (entry.get("spec", ""), entry.get("cache_group", "")),
    )
    if not pending:
        return None
    selected = pending[int(utc_date.replace("-", "")) % len(pending)]
    spec = selected.get("spec", "")
    group = selected.get("cache_group", "")
    if not spec or not group:
        raise BackfillValidationError("backfill_pending entry requires spec and cache_group")
    if not SAFE_GROUP_PATTERN.fullmatch(group):
        raise BackfillValidationError("backfill_pending cache_group is unsafe")
    return BackfillPlan(spec=spec, cache_group=group, candidate_run_id=candidate_run_id(utc_date, spec))


def _receipt_digest(receipt: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    return hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _reject_private_fields(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_RECEIPT_FIELDS & set(value)
        if forbidden:
            raise BackfillValidationError(f"receipt contains forbidden fields: {', '.join(sorted(forbidden))}")
        for child in value.values():
            _reject_private_fields(child)
    elif isinstance(value, list):
        for child in value:
            _reject_private_fields(child)


def _reject_private_cache_content(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_CACHE_FIELDS & {str(key).lower() for key in value}
        if forbidden:
            raise BackfillValidationError(f"candidate cache contains forbidden fields: {', '.join(sorted(forbidden))}")
        for child in value.values():
            _reject_private_cache_content(child)
    elif isinstance(value, list):
        for child in value:
            _reject_private_cache_content(child)
    elif isinstance(value, str) and SENSITIVE_CONTENT_PATTERN.search(value):
        raise BackfillValidationError("candidate cache contains secret-like content")


def _cache_digest(candidate_group: Path, cache_files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in cache_files:
        digest.update(str(path.relative_to(candidate_group)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_group_path(root: Path, group: str) -> Path:
    if not SAFE_GROUP_PATTERN.fullmatch(group):
        raise BackfillValidationError("cache group is unsafe")
    resolved_root = root.resolve()
    destination = (resolved_root / group).resolve()
    if destination.parent != resolved_root:
        raise BackfillValidationError("cache group escapes its cache root")
    return destination


def validate_receipt(receipt: dict[str, Any], plan: BackfillPlan, *, mode: str) -> None:
    """Validate a hash-bound, structural receipt without accepting cache content."""
    _reject_private_fields(receipt)
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise BackfillValidationError("unsupported cache backfill receipt schema")
    if receipt.get("receipt_sha256") != _receipt_digest(receipt):
        raise BackfillValidationError("receipt hash does not match its content")
    expected = {
        "mode": mode,
        "candidate_run_id": plan.candidate_run_id,
        "spec": plan.spec,
        "cache_group": plan.cache_group,
        "status": "passed",
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise BackfillValidationError(f"receipt {key} does not match the candidate plan")
    if receipt.get("expected_groups") != [plan.cache_group]:
        raise BackfillValidationError("receipt expected_groups must contain exactly the candidate group")
    if not isinstance(receipt.get("cache_files"), int) or receipt["cache_files"] <= 0:
        raise BackfillValidationError("receipt must report at least one cache file")
    if not isinstance(receipt.get("estimated_eur"), (int, float)) or receipt["estimated_eur"] < 0:
        raise BackfillValidationError("receipt estimated_eur must be a non-negative number")
    if receipt["estimated_eur"] > 0.25:
        raise BackfillValidationError("receipt exceeds the EUR 0.25 cap")
    if not isinstance(receipt.get("cache_sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", receipt["cache_sha256"]):
        raise BackfillValidationError("receipt must identify the exact cache content")
    if mode == "record" and receipt.get("real_provider_calls", 0) <= 0:
        raise BackfillValidationError("record receipt must prove a real provider call")
    if mode == "replay" and (receipt.get("real_provider_calls") != 0 or receipt.get("replay_misses") != 0):
        raise BackfillValidationError("replay receipt must prove zero real calls and zero replay misses")


def build_receipt(run_root: Path, plan: BackfillPlan, *, mode: str) -> tuple[dict[str, Any], Path]:
    """Aggregate worker receipts and validate the exact candidate cache group."""
    if not RUN_ID_PATTERN.fullmatch(plan.candidate_run_id):
        raise BackfillValidationError("candidate run ID is invalid")
    receipt_dir = run_root / "receipts"
    task_receipts: list[dict[str, Any]] = []
    for path in sorted(receipt_dir.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackfillValidationError("worker receipt is invalid JSON") from exc
        if value.get("mode") == mode and value.get("run_id") == plan.candidate_run_id:
            _reject_private_fields(value)
            task_receipts.append(value)
    if not task_receipts:
        raise BackfillValidationError(f"no {mode} worker receipts were produced")

    candidate_group = _safe_group_path(run_root / "cache", plan.cache_group)
    cache_files = sorted(candidate_group.rglob("*.json")) if candidate_group.is_dir() else []
    if not cache_files:
        raise BackfillValidationError("candidate cache group contains no JSON files")
    for path in cache_files:
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackfillValidationError(f"invalid candidate cache JSON: {path.name}") from exc
        if entry.get("group_id") != plan.cache_group:
            raise BackfillValidationError("candidate cache group ID mismatch")
        _reject_private_cache_content(entry)
        headers = (entry.get("response") or {}).get("headers") or {}
        if any(str(name).lower() in {"authorization", "cookie", "set-cookie", "x-api-key"} for name in headers):
            raise BackfillValidationError("candidate cache contains a sensitive response header")

    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "mode": mode,
        "candidate_run_id": plan.candidate_run_id,
        "spec": plan.spec,
        "cache_group": plan.cache_group,
        "expected_groups": [plan.cache_group],
        "status": "passed",
        "cache_files": len(cache_files),
        "cache_sha256": _cache_digest(candidate_group, cache_files),
        "cache_hits": sum(int(item.get("cache_hits") or 0) for item in task_receipts),
        "replay_misses": sum(int(item.get("cache_misses") or 0) for item in task_receipts) if mode == "replay" else 0,
        "real_provider_calls": sum(int(item.get("real_provider_calls") or 0) for item in task_receipts),
        "estimated_eur": sum(float(item.get("estimated_eur") or 0) for item in task_receipts),
    }
    receipt["receipt_sha256"] = _receipt_digest(receipt)
    validate_receipt(receipt, plan, mode=mode)
    return receipt, candidate_group


def promote_candidate(
    candidate_group: Path,
    runtime_cache_root: Path,
    source_cache_root: Path | None,
    group: str,
    *,
    expected_cache_sha256: str,
    persist: Callable[[str], str] | None = None,
) -> list[str]:
    """Replace cache roots and roll them back if scoped dev persistence fails."""
    if not candidate_group.is_dir():
        raise BackfillValidationError("candidate cache group is missing")
    candidate_files = sorted(candidate_group.rglob("*.json"))
    if _cache_digest(candidate_group, candidate_files) != expected_cache_sha256:
        raise BackfillValidationError("candidate cache changed after replay validation")
    staged: list[tuple[Path, Path, Path]] = []
    transaction = tempfile.mkdtemp(prefix="openmates-cache-backfill-")
    try:
        roots = [runtime_cache_root.resolve()]
        if source_cache_root is not None:
            roots.append(source_cache_root.resolve())
        for root in dict.fromkeys(roots):
            root.mkdir(parents=True, exist_ok=True)
            destination = _safe_group_path(root, group)
            stage = root / f".{group}.staging-{Path(transaction).name}"
            backup = root / f".{group}.backup-{Path(transaction).name}"
            shutil.copytree(candidate_group, stage)
            staged_files = sorted(stage.rglob("*.json"))
            if _cache_digest(stage, staged_files) != expected_cache_sha256:
                raise BackfillValidationError("staged cache content does not match the replay receipt")
            staged.append((destination, stage, backup))
        promoted: list[tuple[Path, Path, Path]] = []
        try:
            for destination, stage, backup in staged:
                if destination.exists():
                    destination.rename(backup)
                stage.rename(destination)
                promoted.append((destination, stage, backup))
            if persist is not None:
                persist(expected_cache_sha256)
        except Exception as exc:
            for destination, _stage, backup in reversed(staged):
                shutil.rmtree(destination, ignore_errors=True)
                if backup.exists():
                    backup.rename(destination)
            raise BackfillValidationError(f"atomic cache promotion failed: {exc}") from exc
        for _destination, _stage, backup in staged:
            shutil.rmtree(backup, ignore_errors=True)
        return [str(destination) for destination, _stage, _backup in staged]
    finally:
        for _destination, stage, _backup in staged:
            shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(transaction, ignore_errors=True)


def run_backfill(
    plan: BackfillPlan | None,
    *,
    dispatch: Callable[[str, bool, str], tuple[dict[str, Any], Path]],
    runtime_cache_root: Path,
    source_cache_root: Path | None,
    claim_root: Path | None = None,
    candidate_run_root: Path | None = None,
    persist: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Record then replay one candidate; failures are returned for daily reporting."""
    if plan is None:
        return {"status": "skipped", "reason": "no_backfill_pending_specs"}
    claim_path = claim_root / "backfill-claim.json" if claim_root is not None else None
    claim: dict[str, Any] = {}
    claim_created = False
    try:
        if claim_path is not None:
            claim_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                claim = json.loads(claim_path.read_text(encoding="utf-8"))
            else:
                claim_created = True
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump({"candidate_run_id": plan.candidate_run_id, "phase": "record_started"}, handle)
                claim = {"candidate_run_id": plan.candidate_run_id, "phase": "record_started"}
            if claim.get("candidate_run_id") != plan.candidate_run_id:
                raise BackfillValidationError("daily backfill claim does not match the selected candidate")
            if claim.get("phase") == "promoted":
                return {"status": "skipped", "reason": "daily_backfill_already_promoted"}
            if claim.get("phase") == "record_failed":
                raise BackfillValidationError("daily backfill record attempt already failed")

        if claim.get("phase") == "record_passed":
            record_receipt = json.loads((claim_root / "aggregate-record.json").read_text(encoding="utf-8"))
            if candidate_run_root is None:
                raise BackfillValidationError("candidate run root is required to resume replay")
            candidate_group = _safe_group_path(candidate_run_root / "cache", plan.cache_group)
        elif claim.get("phase") == "record_started" and not claim_created:
            if candidate_run_root is None:
                raise BackfillValidationError("candidate run root is required to recover recording")
            record_receipt, candidate_group = build_receipt(candidate_run_root, plan, mode="record")
        else:
            record_receipt, candidate_group = dispatch(plan.spec, True, plan.candidate_run_id)
        validate_receipt(record_receipt, plan, mode="record")
        if claim_path is not None:
            (claim_root / "aggregate-record.json").write_text(
                json.dumps(record_receipt, sort_keys=True, separators=(",", ":")), encoding="utf-8"
            )
            claim = {"candidate_run_id": plan.candidate_run_id, "phase": "record_passed"}
            claim_path.write_text(json.dumps(claim, sort_keys=True), encoding="utf-8")
        replay_receipt, _ = dispatch(plan.spec, False, plan.candidate_run_id)
        validate_receipt(replay_receipt, plan, mode="replay")
        if replay_receipt["cache_sha256"] != record_receipt["cache_sha256"]:
            raise BackfillValidationError("candidate cache changed between record and replay")
        destinations = promote_candidate(
            candidate_group,
            runtime_cache_root,
            source_cache_root,
            plan.cache_group,
            expected_cache_sha256=replay_receipt["cache_sha256"],
            persist=persist,
        )
        if claim_path is not None:
            claim_path.write_text(
                json.dumps({"candidate_run_id": plan.candidate_run_id, "phase": "promoted"}, sort_keys=True),
                encoding="utf-8",
            )
        return {
            "status": "runtime_promoted",
            "spec": plan.spec,
            "cache_group": plan.cache_group,
            "candidate_run_id": plan.candidate_run_id,
            "destinations": destinations,
            "record_receipt_sha256": record_receipt["receipt_sha256"],
            "replay_receipt_sha256": replay_receipt["receipt_sha256"],
        }
    except Exception as exc:
        if claim_path is not None and claim.get("phase") == "record_started":
            claim_path.write_text(
                json.dumps({"candidate_run_id": plan.candidate_run_id, "phase": "record_failed"}, sort_keys=True),
                encoding="utf-8",
            )
        return {"status": "failed", "spec": plan.spec, "cache_group": plan.cache_group, "detail": str(exc)}


def deploy_candidate_cache(
    project_root: Path,
    candidate_group: Path,
    plan: BackfillPlan,
    expected_cache_sha256: str,
) -> str:
    """Persist one verified group through an isolated sessions.py deployment."""
    candidate_files = sorted(candidate_group.rglob("*.json"))
    if _cache_digest(candidate_group, candidate_files) != expected_cache_sha256:
        raise BackfillValidationError("runtime cache changed before scoped deployment")
    sessions_script = project_root / "scripts" / "sessions.py"
    opencode_session = f"ses_{plan.candidate_run_id.replace('-', '_')}"
    start = subprocess.run(
        [
            sys.executable,
            str(sessions_script),
            "start",
            "--mode",
            "feature",
            "--task",
            f"Promote verified daily cache for {plan.spec}",
            "--opencode-session",
            opencode_session,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if start.returncode != 0:
        raise BackfillValidationError("could not create cache promotion session")
    session_match = re.search(r"^== SESSION ([0-9a-f]{4})\b", start.stdout, re.MULTILINE)
    worktree_match = re.search(r"^\s*Worktree:\s+(.+?)\s*$", start.stdout, re.MULTILINE)
    if not session_match or not worktree_match:
        raise BackfillValidationError("cache promotion session did not report its worktree")
    session_id = session_match.group(1)
    worktree = Path(worktree_match.group(1)).resolve()
    destination = _safe_group_path(worktree / "backend/apps/ai/testing/api_cache", plan.cache_group)
    shutil.rmtree(destination, ignore_errors=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(candidate_group, destination)
    if _cache_digest(destination, sorted(destination.rglob("*.json"))) != expected_cache_sha256:
        raise BackfillValidationError("deployment cache copy does not match the verified runtime group")

    manifest_path = worktree / "scripts" / "daily_ai_test_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["specs"].get(plan.spec)
    if not isinstance(entry, dict) or entry.get("classification") != "backfill_pending":
        raise BackfillValidationError("cache promotion manifest entry is no longer pending")
    entry["classification"] = "replay"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    selected_files = [
        "scripts/daily_ai_test_manifest.json",
        *(
            str(path.relative_to(worktree))
            for path in sorted(destination.rglob("*.json"))
        ),
    ]
    deploy = subprocess.run(
        [
            sys.executable,
            str(sessions_script),
            "deploy",
            "--session",
            session_id,
            "--title",
            f"Promote daily cache for {plan.spec}",
            "--message",
            f"Promote verified daily cache for {plan.spec}",
            "--only",
            *selected_files,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if deploy.returncode != 0:
        raise BackfillValidationError("verified runtime cache could not be deployed to dev")
    commit_match = re.search(r"^Full commit:\s+([a-f0-9]{40})$", deploy.stdout, re.MULTILINE)
    remote = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/dev"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    remote_commit = remote.stdout.split(maxsplit=1)[0] if remote.returncode == 0 and remote.stdout.strip() else ""
    commit = commit_match.group(1) if commit_match else remote_commit
    if not re.fullmatch(r"[a-f0-9]{40}", commit) or not re.fullmatch(r"[a-f0-9]{40}", remote_commit):
        raise BackfillValidationError("cache promotion deploy succeeded without a verifiable dev commit")
    if commit != remote_commit:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, remote_commit],
            cwd=project_root,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if ancestor.returncode != 0:
            raise BackfillValidationError("cache promotion commit is not retained on remote dev")
    _verify_deployed_group(project_root, commit, plan, expected_cache_sha256)
    return commit


def _verify_deployed_group(
    project_root: Path,
    commit: str,
    plan: BackfillPlan,
    expected_cache_sha256: str,
) -> None:
    prefix = f"backend/apps/ai/testing/api_cache/{plan.cache_group}/"
    tree = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit, "--", prefix],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    paths = sorted(path for path in tree.stdout.splitlines() if path.endswith(".json"))
    if tree.returncode != 0 or not paths:
        raise BackfillValidationError("deployed cache group is absent from the dev commit")
    digest = hashlib.sha256()
    for path in paths:
        blob = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=project_root,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if blob.returncode != 0:
            raise BackfillValidationError("deployed cache blob could not be verified")
        digest.update(path.removeprefix(prefix).encode("utf-8"))
        digest.update(b"\0")
        digest.update(blob.stdout)
        digest.update(b"\0")
    if digest.hexdigest() != expected_cache_sha256:
        raise BackfillValidationError("deployed cache bytes do not match the verified replay candidate")
    manifest_blob = subprocess.run(
        ["git", "show", f"{commit}:scripts/daily_ai_test_manifest.json"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        manifest = json.loads(manifest_blob.stdout)
    except json.JSONDecodeError as exc:
        raise BackfillValidationError("deployed manifest could not be verified") from exc
    if manifest_blob.returncode != 0 or manifest.get("specs", {}).get(plan.spec, {}).get("classification") != "replay":
        raise BackfillValidationError("deployed manifest did not promote the verified spec to replay")
