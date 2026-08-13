#!/usr/bin/env python3
"""Orchestrate focused, bounded OpenCode proof-video preparation.

This module resolves existing session/test evidence and computes canonical proof
contracts, marker trims, simple pacing, cache keys, review bundles, and defect
routing. It does not perform OCR, semantic video analysis, product repair, or
unbounded media work; scripts/spec_demo.py remains the media implementation.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


def _resolve_control_plane_root(checkout_root: Path) -> Path:
    """Resolve the root checkout that owns shared session state."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=checkout_root,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return checkout_root
    if result.returncode != 0 or not result.stdout.strip():
        return checkout_root
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = checkout_root / common_dir
    common_dir = common_dir.resolve()
    return common_dir.parent if common_dir.name == ".git" else checkout_root


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE_ROOT = _resolve_control_plane_root(REPO_ROOT)
SESSIONS_FILE = CONTROL_PLANE_ROOT / ".claude/sessions.json"
RESULTS_DIR = REPO_ROOT / "test-results"
APPROVALS_DIR = RESULTS_DIR / "proof-video-approvals"
PROOF_SOURCE_DIR = RESULTS_DIR / "proof-video-sources"
MAX_OUTPUT_SECONDS = 35.0
MAX_ANALYSIS_FRAMES = 12
MAX_REVIEW_FRAMES_PER_DEVICE = 8
MAX_AUTOMATIC_RERENDERS = 1
MIN_PLAYBACK_RATE = 0.75
READING_WORDS_PER_SECOND = 2.5
MARKER_TRIM_LEAD_SECONDS = 0.15


class WorkflowError(RuntimeError):
    """Raised when focused proof preparation cannot continue truthfully."""


@dataclass(frozen=True)
class ProofContext:
    session_id: str
    subject_commit: str
    source_run_id: str
    spec_name: str


@dataclass(frozen=True)
class PacingPlan:
    playback_rate: float
    final_hold_seconds: float
    output_duration_seconds: float


def _commit_matches(candidate: str, expected: str) -> bool:
    return candidate == expected and len(expected) == 40


def resolve_current_context(
    sessions: dict[str, Any],
    *,
    opencode_session_id: str,
    subject_commit: str,
    spec_name: str,
    test_runs: list[dict[str, Any]],
) -> ProofContext:
    session_id, _session = resolve_current_session(sessions, opencode_session_id=opencode_session_id)
    passing_runs = [
        record
        for record in test_runs
        if record.get("status") == "passed"
        and record.get("spec") == spec_name
        and _commit_matches(str(record.get("git_sha") or ""), subject_commit)
        and record.get("source") == "scripts_tests"
        and record.get("deployment_verified") is True
    ]
    if not passing_runs:
        raise WorkflowError(
            f"no deployed passing run matches {spec_name} at {subject_commit}; "
            f"run `python3 scripts/tests.py run --spec {spec_name} --gate-deploy --expected-commit {subject_commit}`"
        )
    unique_run_ids = {str(record.get("source_run_id") or record.get("run_id") or "") for record in passing_runs}
    if len(unique_run_ids) > 1:
        available_run_ids = ", ".join(sorted(unique_run_ids)[:10])
        raise WorkflowError(
            f"multiple passing runs match {spec_name} at {subject_commit}; provide --run-id. "
            f"Available run IDs: {available_run_ids}"
        )
    return ProofContext(session_id, subject_commit, str(passing_runs[0].get("source_run_id") or passing_runs[0]["run_id"]), spec_name)


def resolve_current_session(sessions: dict[str, Any], *, opencode_session_id: str) -> tuple[str, dict[str, Any]]:
    matches = [
        (session_id, record)
        for session_id, record in (sessions.get("sessions") or {}).items()
        if isinstance(record, dict) and record.get("opencode_session_id") == opencode_session_id
    ]
    if len(matches) != 1:
        raise WorkflowError(f"current OpenCode session matches {len(matches)} repository sessions; run sessions.py status")
    return matches[0]


def deployed_subject_commit(session: dict[str, Any]) -> str:
    worktree = session.get("worktree") if isinstance(session.get("worktree"), dict) else {}
    merged_commit = str(worktree.get("merged_commit") or "") if isinstance(worktree, dict) else ""
    if len(merged_commit) == 40:
        return merged_commit
    return ""


def canonical_contract(contract: dict[str, Any]) -> dict[str, Any]:
    title = contract.get("title")
    transcript = contract.get("transcript")
    assertions = contract.get("assertions")
    devices = contract.get("devices")
    if not isinstance(title, str) or not title.strip():
        raise WorkflowError("proof contract requires a title")
    if not isinstance(transcript, list) or not transcript or not all(isinstance(item, str) and item.strip() for item in transcript):
        raise WorkflowError("proof contract requires a non-empty tutorial transcript")
    if not isinstance(assertions, list) or not 1 <= len(assertions) <= 5:
        raise WorkflowError("proof contract requires one to five visible assertions")
    for assertion in assertions:
        if not isinstance(assertion, dict) or not all(
            isinstance(assertion.get(field), str) and assertion[field].strip() for field in ("id", "description")
        ):
            raise WorkflowError("every proof assertion requires id and description")
    if not isinstance(devices, list) or not devices or not all(isinstance(item, str) and item for item in devices):
        raise WorkflowError("proof contract requires at least one device")
    return {
        "title": title.strip(),
        "transcript": [item.strip() for item in transcript],
        "assertions": [{"id": item["id"].strip(), "description": item["description"].strip()} for item in assertions],
        "devices": list(devices),
    }


def contract_hash(contract: dict[str, Any]) -> str:
    payload = json.dumps(canonical_contract(contract), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def write_contract(path: Path, contract: dict[str, Any]) -> dict[str, Any]:
    canonical = canonical_contract(contract)
    record = {**canonical, "contract_hash": contract_hash(canonical)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return record


def require_approved_contract(contract: dict[str, Any], approved_hash: str) -> None:
    actual = contract_hash(contract)
    stored = str(contract.get("contract_hash") or "")
    if stored != actual or approved_hash != actual:
        raise WorkflowError(f"approved contract hash does not match current contract: expected {approved_hash}, got {actual}")


def load_approved_contract(path: Path, approved_hash: str) -> dict[str, Any]:
    contract = _load_json(path)
    require_approved_contract(contract, approved_hash)
    return contract


def approval_record_path(session_id: str, spec_name: str) -> Path:
    return APPROVALS_DIR / session_id / f"{Path(spec_name).stem}.json"


def record_contract_approval(*, session_id: str, spec_name: str, contract_path: Path) -> dict[str, Any]:
    contract = _load_json(contract_path)
    actual_hash = contract_hash(contract)
    if str(contract.get("contract_hash") or "") != actual_hash:
        raise WorkflowError("contract file hash does not match its canonical content")
    record = {
        "session_id": session_id,
        "spec_name": Path(spec_name).name,
        "contract_path": str(contract_path.resolve()),
        "contract_hash": actual_hash,
    }
    path = approval_record_path(session_id, spec_name)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return record


def require_recorded_approval(*, session_id: str, spec_name: str, contract_path: Path) -> dict[str, Any]:
    record = _load_json(approval_record_path(session_id, spec_name))
    if record.get("session_id") != session_id or record.get("spec_name") != Path(spec_name).name:
        raise WorkflowError("no recorded user approval exists for this session and spec")
    if record.get("contract_path") != str(contract_path.resolve()):
        raise WorkflowError("approved contract path does not match the render contract")
    contract = load_approved_contract(contract_path, str(record.get("contract_hash") or ""))
    return contract


def approved_render_claims(contract: dict[str, Any]) -> dict[str, Any]:
    canonical = canonical_contract(contract)
    return {
        "caption_text": " ".join(canonical["transcript"]),
        "expected_proof": " ".join(assertion["description"] for assertion in canonical["assertions"]),
        "acceptance_criteria": [assertion["id"] for assertion in canonical["assertions"]],
    }


def marker_trim_start(*, ready_timestamp_seconds: float, lead_seconds: float = MARKER_TRIM_LEAD_SECONDS) -> float:
    if ready_timestamp_seconds < 0 or lead_seconds < 0:
        raise WorkflowError("capture-ready marker and trim lead must be non-negative")
    return round(max(0.0, ready_timestamp_seconds - lead_seconds), 3)


def calculate_pacing(*, source_duration_seconds: float, transcript_words: int) -> PacingPlan:
    if source_duration_seconds <= 0 or transcript_words <= 0:
        raise WorkflowError("pacing requires positive source duration and transcript word count")
    reading_seconds = transcript_words / READING_WORDS_PER_SECOND
    if reading_seconds > MAX_OUTPUT_SECONDS:
        raise WorkflowError("transcript cannot fit the 35 second output limit; shorten the tutorial transcript")
    playback_rate = max(MIN_PLAYBACK_RATE, min(1.0, source_duration_seconds / reading_seconds))
    slowed_duration = source_duration_seconds / playback_rate
    hold = max(0.0, reading_seconds - slowed_duration)
    output = slowed_duration + hold
    if output > MAX_OUTPUT_SECONDS:
        raise WorkflowError("pacing exceeds the 35 second output limit")
    return PacingPlan(round(playback_rate, 3), round(hold, 3), round(output, 3))


def resource_limits() -> dict[str, Any]:
    return {
        "parallel_device_renders": 1,
        "maximum_output_seconds": int(MAX_OUTPUT_SECONDS),
        "maximum_analysis_frames": MAX_ANALYSIS_FRAMES,
        "maximum_review_frames_per_device": MAX_REVIEW_FRAMES_PER_DEVICE,
        "maximum_automatic_rerenders": MAX_AUTOMATIC_RERENDERS,
        "ocr_enabled": False,
    }


def cache_key(source_hash: str, proof_contract_hash: str, *, renderer_version: str) -> str:
    payload = f"{source_hash}\0{proof_contract_hash}\0{renderer_version}".encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def build_review_bundle(
    *,
    contract: dict[str, Any],
    deterministic_metadata: dict[str, Any],
    frames_by_device: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    if any(not 3 <= len(frames) <= MAX_REVIEW_FRAMES_PER_DEVICE for frames in frames_by_device.values()):
        raise WorkflowError("review requires three to eight frames per device")
    bundle = {
        "contract": contract,
        "deterministic_metadata": deterministic_metadata,
        "frames_by_device": frames_by_device,
    }
    forbidden = {"video", "video_path", "video_bytes", "video_base64", "video_attachment"}

    def inspect(value: Any, key: str = "") -> None:
        if key in forbidden:
            raise WorkflowError("review bundle must not contain the full video")
        if isinstance(value, dict):
            for child_key, child in value.items():
                inspect(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                inspect(child, key)

    inspect(bundle)
    return bundle


def route_defect(defect: str, *, prior_automatic_rerenders: int) -> dict[str, Any]:
    mechanical = defect in {"blank_first_frame", "caption_alignment"}
    if mechanical and prior_automatic_rerenders < MAX_AUTOMATIC_RERENDERS:
        return {
            "verdict": "render_defect",
            "return_stage": "render",
            "automatic_correction": True,
            "next_action": "rerender_once",
        }
    if defect == "unexplained_scroll_state":
        return {
            "verdict": "capture_defect",
            "return_stage": "capture",
            "automatic_correction": False,
            "next_action": "recapture_with_visible_transition",
        }
    if defect == "clipped_header":
        return {
            "verdict": "product_defect",
            "return_stage": "implementation",
            "automatic_correction": False,
            "next_action": "return_to_failing_test",
        }
    return {
        "verdict": "uncertain",
        "return_stage": "render" if mechanical else "review",
        "automatic_correction": False,
        "next_action": "request_bounded_review",
    }


def _current_git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise WorkflowError(f"could not resolve current commit: {result.stderr.strip()}")
    return result.stdout.strip()


def _tracked_worktree_changes() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorkflowError(f"could not inspect tracked worktree state: {result.stderr.strip()}")
    return [line[3:] for line in result.stdout.splitlines() if len(line) > 3]


def require_clean_worktree() -> None:
    changes = _tracked_worktree_changes()
    if changes:
        raise WorkflowError(
            "proof-video provenance requires a clean tracked worktree; tracked changes: " + ", ".join(changes[:5])
        )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"could not read {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _local_test_runs() -> list[dict[str, Any]]:
    return [data for path in sorted(PROOF_SOURCE_DIR.glob("*.json"), reverse=True) if (data := _load_json(path))]


def resolve_deployed_run(*, subject_commit: str, spec_name: str, run_id: str, source_video: Path | None = None) -> dict[str, Any]:
    matches = [
        run
        for run in _local_test_runs()
        if run_id in {str(run.get("run_id") or ""), str(run.get("source_run_id") or "")}
        and run.get("spec") == Path(spec_name).name
        and run.get("status") == "passed"
        and run.get("source") == "scripts_tests"
        and run.get("deployment_verified") is True
        and str(run.get("git_sha") or "") == subject_commit
        and str(run.get("deployment_reference") or "") == subject_commit
        and len(subject_commit) == 40
    ]
    if source_video is not None:
        expected_source = source_video.resolve()
        matches = [
            run
            for run in matches
            if Path(str(run.get("artifact_path") or "")).resolve() == expected_source
        ]
    if len(matches) != 1:
        raise WorkflowError(
            f"expected one deployed passing run for {spec_name} at {subject_commit} with run ID {run_id}, found {len(matches)}"
        )
    artifact_path = Path(str(matches[0].get("artifact_path") or ""))
    if not artifact_path.is_file() or _file_sha256(artifact_path) != matches[0].get("artifact_sha256"):
        raise WorkflowError("deployed passing run video is missing or its content hash changed")
    return matches[0]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def start_current(spec_name: str, *, run_id: str = "") -> dict[str, Any]:
    opencode_session_id = os.environ.get("OPENCODE_SESSION_ID", "")
    if not opencode_session_id:
        raise WorkflowError("OPENCODE_SESSION_ID is not set; run inside the active OpenCode chat")
    sessions = _load_json(SESSIONS_FILE)
    _session_id, session = resolve_current_session(sessions, opencode_session_id=opencode_session_id)
    subject_commit = deployed_subject_commit(session)
    if not subject_commit:
        require_clean_worktree()
        subject_commit = _current_git_sha()
    runs = _local_test_runs()
    if run_id:
        runs = [run for run in runs if run.get("run_id") == run_id]
    context = resolve_current_context(
        sessions,
        opencode_session_id=opencode_session_id,
        subject_commit=subject_commit,
        spec_name=Path(spec_name).name,
        test_runs=runs,
    )
    run_dir = RESULTS_DIR / "proof-videos" / context.session_id / Path(spec_name).stem
    return {
        "status": "awaiting_contract",
        "context": asdict(context),
        "run_dir": str(run_dir.relative_to(REPO_ROOT)),
        "resource_limits": resource_limits(),
        "next_action": "Draft the tutorial transcript and one to five visible assertions, show them to the user, then save the approved contract hash.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a focused, bounded OpenCode proof-video workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="Resolve current proof context and prepare the approval boundary.")
    start.add_argument("--current", action="store_true", help="Infer the current sessions.py session from OPENCODE_SESSION_ID.")
    start.add_argument("--spec", required=True, help="Passing Playwright spec filename.")
    start.add_argument("--run-id", default="", help="Disambiguate matching passing runs when necessary.")
    approve = subparsers.add_parser("approve", help="Persist the user-approved canonical proof contract.")
    approve.add_argument("--session", required=True)
    approve.add_argument("--spec", required=True)
    approve.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            if not args.current:
                raise WorkflowError("start currently requires --current")
            print(json.dumps(start_current(args.spec, run_id=args.run_id), indent=2, sort_keys=True))
            return 0
        if args.command == "approve":
            print(json.dumps(record_contract_approval(session_id=args.session, spec_name=args.spec, contract_path=args.contract), indent=2, sort_keys=True))
            return 0
    except WorkflowError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
