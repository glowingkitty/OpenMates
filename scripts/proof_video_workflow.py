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
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any

try:
    from scripts._zellij_utils import _resolve_opencode_bin
except ModuleNotFoundError:
    from _zellij_utils import _resolve_opencode_bin


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
REVIEW_BUDGETS_DIR = CONTROL_PLANE_ROOT / "test-results" / "proof-video-review-budgets"
MAX_OUTPUT_SECONDS = 35.0
MAX_ANALYSIS_FRAMES = 12
PERIODIC_FRAME_INTERVAL_SECONDS = 5
MAX_REVIEW_FRAMES_PER_DEVICE = 12
MAX_AI_REVIEW_CALLS = 6
MAX_CUMULATIVE_SUBMITTED_FRAMES = 48
MAX_AUTOMATIC_CORRECTION_ROUNDS = 2
MAX_PRODUCT_CODE_CORRECTION_ROUNDS = 1
MIN_PLAYBACK_RATE = 0.75
MAX_PLAYBACK_RATE = 4.0
READING_WORDS_PER_SECOND = 2.5
MARKER_TRIM_LEAD_SECONDS = 0.15
SUPPORTED_DEVICE_PROFILES = {
    "apple-ipad-landscape",
    "apple-iphone-portrait",
    "cli-terminal",
    "web-laptop",
    "web-phone",
}


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
    if len(candidate) != 40 or len(expected) != 40:
        return False
    if candidate == expected:
        return True
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", expected, candidate],
            cwd=CONTROL_PLANE_ROOT,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


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
    schema_version = contract.get("schema_version", 1)
    title = contract.get("title")
    transcript = contract.get("transcript")
    assertions = contract.get("assertions")
    devices = contract.get("devices")
    if not isinstance(title, str) or not title.strip():
        raise WorkflowError("proof contract requires a title")
    if schema_version not in {1, 2}:
        raise WorkflowError("proof contract schema_version must be 1 or 2")
    if not isinstance(assertions, list) or not 1 <= len(assertions) <= 5:
        raise WorkflowError("proof contract requires one to five visible assertions")
    if not isinstance(devices, list) or not devices or not all(isinstance(item, str) and item.strip() for item in devices):
        raise WorkflowError("proof contract requires at least one device")
    canonical_devices = [item.strip() for item in devices]
    if len(canonical_devices) != len(set(canonical_devices)):
        raise WorkflowError("proof contract devices must be unique")
    unknown_devices = set(canonical_devices) - SUPPORTED_DEVICE_PROFILES
    if unknown_devices:
        raise WorkflowError(f"proof contract contains unsupported device: {sorted(unknown_devices)[0]}")
    if schema_version == 1:
        if len(canonical_devices) > 1:
            raise WorkflowError("multi-device proof contracts require schema_version 2 with device-scoped transcript and assertions")
        if not isinstance(transcript, list) or not transcript or not all(isinstance(item, str) and item.strip() for item in transcript):
            raise WorkflowError("proof contract requires a non-empty tutorial transcript")
        for assertion in assertions:
            if not isinstance(assertion, dict) or not all(
                isinstance(assertion.get(field), str) and assertion[field].strip() for field in ("id", "description")
            ):
                raise WorkflowError("every proof assertion requires id and description")
        return {
            "title": title.strip(),
            "transcript": [item.strip() for item in transcript],
            "assertions": [{"id": item["id"].strip(), "description": item["description"].strip()} for item in assertions],
            "devices": canonical_devices,
        }

    def scoped_items(items: Any, *, label: str, text_fields: tuple[str, ...]) -> list[dict[str, Any]]:
        if not isinstance(items, list) or not items:
            raise WorkflowError(f"proof contract requires a non-empty {label}")
        canonical_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(field), str) and item[field].strip() for field in text_fields
            ):
                raise WorkflowError(f"every proof {label} item requires {', '.join(text_fields)}")
            item_devices = item.get("devices")
            if not isinstance(item_devices, list) or not item_devices or not all(
                isinstance(device, str) and device.strip() for device in item_devices
            ):
                raise WorkflowError(f"every proof {label} item requires target devices")
            targets = [device.strip() for device in item_devices]
            if len(targets) != len(set(targets)) or not set(targets).issubset(canonical_devices):
                raise WorkflowError(f"proof {label} target devices must be unique members of the contract devices")
            canonical_items.append({**{field: item[field].strip() for field in text_fields}, "devices": targets})
        return canonical_items

    canonical_transcript = scoped_items(transcript, label="transcript", text_fields=("text",))
    canonical_assertions = scoped_items(assertions, label="assertion", text_fields=("id", "description"))
    assertion_ids = [item["id"] for item in canonical_assertions]
    if len(assertion_ids) != len(set(assertion_ids)):
        raise WorkflowError("proof assertion ids must be unique")
    for device in canonical_devices:
        if not any(device in item["devices"] for item in canonical_assertions):
            raise WorkflowError(f"proof device {device} requires at least one assertion")
        if not any(device in item["devices"] for item in canonical_transcript):
            raise WorkflowError(f"proof device {device} requires at least one transcript item")
    return {
        "schema_version": 2,
        "title": title.strip(),
        "transcript": canonical_transcript,
        "assertions": canonical_assertions,
        "devices": canonical_devices,
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


def approved_render_claims(contract: dict[str, Any], *, device_profile: str | None = None) -> dict[str, Any]:
    canonical = canonical_contract(contract)
    if canonical.get("schema_version") == 2:
        if device_profile not in canonical["devices"]:
            raise WorkflowError("render device must be one of the approved proof contract devices")
        transcript = [item["text"] for item in canonical["transcript"] if device_profile in item["devices"]]
        assertions = [
            {"id": item["id"], "description": item["description"]}
            for item in canonical["assertions"]
            if device_profile in item["devices"]
        ]
    else:
        transcript = canonical["transcript"]
        assertions = canonical["assertions"]
    return {
        "caption_text": " ".join(transcript),
        "expected_proof": " ".join(assertion["description"] for assertion in assertions),
        "acceptance_criteria": [assertion["id"] for assertion in assertions],
        "assertions": assertions,
        "contract_hash": contract_hash(canonical),
    }


def spec_timeline_render_claims(timeline: dict[str, Any], *, device_profile: str | None = None) -> dict[str, Any]:
    """Render proof-video claims from a Playwright-attached spec timeline."""

    contract = timeline.get("contract") if isinstance(timeline.get("contract"), dict) else {}
    if not contract:
        raise WorkflowError("spec proof timeline requires an embedded contract")
    transcript_items = contract.get("transcript")
    assertion_items = contract.get("assertions")
    if not isinstance(transcript_items, list) or not transcript_items:
        raise WorkflowError("spec proof timeline requires transcript items")
    if not isinstance(assertion_items, list) or not assertion_items:
        raise WorkflowError("spec proof timeline requires assertion items")

    def targets_device(item: dict[str, Any]) -> bool:
        devices = item.get("devices")
        if device_profile and isinstance(devices, list):
            return device_profile in {str(device) for device in devices}
        return True

    transcript: list[str] = []
    for item in transcript_items:
        if isinstance(item, str):
            transcript.append(item.strip())
        elif isinstance(item, dict) and targets_device(item):
            transcript.append(str(item.get("text") or "").strip())
    transcript = [text for text in transcript if text]

    assertions: list[dict[str, str]] = []
    for item in assertion_items:
        if not isinstance(item, dict) or not targets_device(item):
            continue
        assertion_id = str(item.get("id") or "").strip()
        description = str(item.get("description") or item.get("visual") or item.get("text") or "").strip()
        if assertion_id and description:
            assertions.append({"id": assertion_id, "description": description})
    if not transcript or not assertions:
        raise WorkflowError("spec proof timeline has no claims for the requested device")
    contract_payload = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "caption_text": " ".join(transcript),
        "expected_proof": " ".join(assertion["description"] for assertion in assertions),
        "acceptance_criteria": [assertion["id"] for assertion in assertions],
        "assertions": assertions,
        "contract_hash": str(contract.get("contract_hash") or f"sha256:{hashlib.sha256(contract_payload).hexdigest()}"),
        "domain": str(contract.get("domain") or ""),
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
    playback_rate = max(playback_rate, source_duration_seconds / MAX_OUTPUT_SECONDS)
    if playback_rate > MAX_PLAYBACK_RATE:
        raise WorkflowError("source recording cannot fit the 35 second output limit")
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
        "periodic_frame_interval_seconds": PERIODIC_FRAME_INTERVAL_SECONDS,
        "maximum_review_frames_per_device": MAX_REVIEW_FRAMES_PER_DEVICE,
        "maximum_ai_review_calls": MAX_AI_REVIEW_CALLS,
        "maximum_cumulative_submitted_frames": MAX_CUMULATIVE_SUBMITTED_FRAMES,
        "maximum_automatic_correction_rounds": MAX_AUTOMATIC_CORRECTION_ROUNDS,
        "maximum_product_code_correction_rounds": MAX_PRODUCT_CODE_CORRECTION_ROUNDS,
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
        raise WorkflowError("review requires three to twelve frames per device")
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
    mechanical = defect == "blank_first_frame"
    if mechanical and prior_automatic_rerenders < MAX_AUTOMATIC_CORRECTION_ROUNDS:
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
            "automatic_correction": True,
            "next_action": "return_to_failing_test",
        }
    return {
        "verdict": "uncertain",
        "return_stage": "render" if mechanical else "review",
        "automatic_correction": False,
        "next_action": "request_bounded_review",
    }


def reserve_review_budget(
    budget: dict[str, Any],
    *,
    device: str,
    frame_count: int,
    correction_round: int,
    correction_kind: str,
    frame_index_hash: str = "",
    source_artifact_hash: str = "",
    caption_artifact_hash: str = "",
) -> dict[str, Any]:
    """Reserve one persisted AI review call before inference starts."""
    if correction_round not in range(MAX_AUTOMATIC_CORRECTION_ROUNDS + 1):
        raise WorkflowError("automatic correction round limit reached; ask the user what to do next")
    if correction_kind not in {"none", "mechanical", "capture", "product"}:
        raise WorkflowError(f"unsupported correction kind: {correction_kind}")
    if correction_round == 0 and correction_kind != "none":
        raise WorkflowError("initial review must use correction kind none")
    if correction_round > 0 and correction_kind == "none":
        raise WorkflowError("correction reviews must declare their correction kind")
    if not 1 <= frame_count <= MAX_REVIEW_FRAMES_PER_DEVICE:
        raise WorkflowError(f"review frame count must be between 1 and {MAX_REVIEW_FRAMES_PER_DEVICE}")

    result = json.loads(json.dumps(budget)) if budget else {}
    calls = int(result.get("ai_review_calls", 0)) + 1
    submitted = int(result.get("submitted_frames", 0)) + frame_count
    if calls > MAX_AI_REVIEW_CALLS:
        if not _roll_over_review_budget(result, device, source_artifact_hash, correction_round, correction_kind):
            raise WorkflowError("AI review call budget is exhausted; ask the user what to do next")
        calls = 1
        submitted = frame_count
    if submitted > MAX_CUMULATIVE_SUBMITTED_FRAMES:
        if not _roll_over_review_budget(result, device, source_artifact_hash, correction_round, correction_kind):
            raise WorkflowError("cumulative frame budget is exhausted; ask the user what to do next")
        calls = 1
        submitted = frame_count

    product_rounds = [int(value) for value in result.get("product_code_correction_rounds", [])]
    if correction_kind == "product" and correction_round not in product_rounds:
        if len(product_rounds) >= MAX_PRODUCT_CODE_CORRECTION_ROUNDS:
            raise WorkflowError("product-code correction budget is exhausted; ask the user what to do next")
        product_rounds.append(correction_round)
    reservations = result.setdefault("reservations", [])
    if frame_index_hash and source_artifact_hash and any(
        item.get("device") == device
        and item.get("frame_index_hash") == frame_index_hash
        and item.get("source_artifact_hash") == source_artifact_hash
        and item.get("caption_artifact_hash", "") == caption_artifact_hash
        and item.get("receipt_path")
        for item in reservations
        if isinstance(item, dict)
    ):
        raise WorkflowError("unchanged device evidence is already reviewed; use its cached receipt")
    reservation = {
        "device": device,
        "correction_round": correction_round,
        "frame_index_hash": frame_index_hash,
        "source_artifact_hash": source_artifact_hash,
        "caption_artifact_hash": caption_artifact_hash,
        "budget_epoch": int(result.get("active_epoch", 0)),
    }
    if reservation in reservations:
        raise WorkflowError("this device and correction round were already reviewed")
    reservations.append(reservation)
    result.update(
        {
            "ai_review_calls": calls,
            "submitted_frames": submitted,
            "product_code_correction_rounds": sorted(product_rounds),
        }
    )
    return result


def _roll_over_review_budget(
    budget: dict[str, Any],
    device: str,
    source_artifact_hash: str,
    correction_round: int,
    correction_kind: str,
) -> bool:
    if correction_round != 0 or correction_kind != "none" or not source_artifact_hash:
        return False
    reservations = [item for item in budget.get("reservations", []) if isinstance(item, dict)]
    if not reservations:
        return False
    device_reservations = [item for item in reservations if item.get("device") == device]
    latest_device_status = str(device_reservations[-1].get("status") or "") if device_reservations else ""
    if device_reservations and (not latest_device_status or latest_device_status == "passed"):
        return False
    prior_sources = {str(item.get("source_artifact_hash") or "") for item in device_reservations}
    if source_artifact_hash in prior_sources:
        return False
    reason = (
        "new_source_after_nonpassing_device_reviews"
        if device_reservations
        else "first_review_for_new_device"
    )
    prior_epoch = int(budget.get("active_epoch", 0))
    budget.setdefault("superseded_review_epochs", []).append(
        {
            "budget_epoch": prior_epoch,
            "reason": reason,
            "device": device,
            "reservation_count": len(reservations),
            "ai_review_calls": int(budget.get("ai_review_calls", 0)),
            "submitted_frames": int(budget.get("submitted_frames", 0)),
            "superseded_by_source_artifact_hash": source_artifact_hash,
        }
    )
    budget["active_epoch"] = prior_epoch + 1
    budget["ai_review_calls"] = 0
    budget["submitted_frames"] = 0
    budget["product_code_correction_rounds"] = []
    return True


def reserve_persisted_review_budget(
    path: Path,
    *,
    proof_identity: str,
    device: str,
    frame_count: int,
    correction_round: int,
    correction_kind: str,
    frame_index_hash: str,
    source_artifact_hash: str,
    caption_artifact_hash: str,
) -> dict[str, Any]:
    """Atomically reserve shared proof-review budget across device processes."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        existing = _load_json(path)
        if existing and existing.get("proof_identity") != proof_identity:
            raise WorkflowError("stored review budget does not match this proof identity")
        budget = reserve_review_budget(
            existing,
            device=device,
            frame_count=frame_count,
            correction_round=correction_round,
            correction_kind=correction_kind,
            frame_index_hash=frame_index_hash,
            source_artifact_hash=source_artifact_hash,
            caption_artifact_hash=caption_artifact_hash,
        )
        budget["proof_identity"] = proof_identity
        path.write_text(json.dumps(budget, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return budget


def append_persisted_defect_fingerprint(path: Path, fingerprint: str) -> dict[str, Any]:
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        budget = _load_json(path)
        fingerprints = [str(value) for value in budget.get("defect_fingerprints", [])]
        fingerprints.append(fingerprint)
        budget["defect_fingerprints"] = fingerprints
        path.write_text(json.dumps(budget, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return budget


def load_cached_review(
    path: Path,
    *,
    proof_identity: str,
    device: str,
    frame_index_hash: str,
    source_artifact_hash: str,
    subject_commit: str,
    proof_contract_hash: str,
    caption_artifact_hash: str,
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        budget = _load_json(path)
        if budget.get("proof_identity") != proof_identity:
            raise WorkflowError("stored review cache does not match this proof identity")
        for reservation in budget.get("reservations", []):
            if not isinstance(reservation, dict) or (
                reservation.get("device") != device
                or reservation.get("frame_index_hash") != frame_index_hash
                or reservation.get("source_artifact_hash") != source_artifact_hash
                or reservation.get("caption_artifact_hash", "") != caption_artifact_hash
            ):
                continue
            receipt_path = Path(str(reservation.get("receipt_path") or ""))
            manifest_path = Path(str(reservation.get("manifest_path") or ""))
            if not receipt_path.is_file() or not manifest_path.is_file():
                continue
            if _file_sha256(receipt_path) != reservation.get("receipt_sha256"):
                raise WorkflowError("stored review cache receipt hash changed")
            cached_run_dir = manifest_path.parent
            try:
                from scripts.spec_demo import require_review_receipt_integrity, validate_review_request_files
            except ModuleNotFoundError:
                from spec_demo import require_review_receipt_integrity, validate_review_request_files
            cached_manifest = _load_json(manifest_path)
            cached_request = _load_json(cached_run_dir / "review-request.json")
            cached_receipt = _load_json(receipt_path)
            try:
                validate_review_request_files(cached_run_dir, cached_request)
                require_review_receipt_integrity(cached_run_dir, cached_manifest)
            except Exception as exc:
                raise WorkflowError(f"stored review cache failed integrity validation: {exc}") from exc
            cached_device = str((cached_request.get("video_metadata") or {}).get("device_profile") or "unspecified-device")
            if (
                cached_request.get("proof_group_id") != proof_identity
                or cached_request.get("frame_index_hash") != frame_index_hash
                or (cached_request.get("video_metadata") or {}).get("sha256") != source_artifact_hash
                or str((cached_request.get("video_metadata") or {}).get("captions_sha256") or "") != caption_artifact_hash
                or cached_request.get("subject_commit") != subject_commit
                or cached_request.get("proof_contract_hash") != proof_contract_hash
                or cached_request.get("subject_commit") != cached_manifest.get("subject_commit")
                or cached_request.get("proof_contract_hash") != cached_manifest.get("proof_contract_hash")
                or cached_request.get("frame_index_hash") != (cached_manifest.get("review") or {}).get("frame_index_hash")
                or cached_request.get("frame_index_hash") != cached_receipt.get("frame_index_hash")
                or cached_device != device
            ):
                raise WorkflowError("stored review cache provenance does not match this review request")
            return {
                "status": reservation.get("status"),
                "receipt": cached_receipt,
                "manifest": cached_manifest,
                "budget": budget,
                "cached": True,
            }
    return None


def record_cached_review(
    path: Path,
    *,
    device: str,
    correction_round: int,
    frame_index_hash: str,
    source_artifact_hash: str,
    caption_artifact_hash: str,
    run_dir: Path,
    status: str,
) -> dict[str, Any]:
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        budget = _load_json(path)
        for reservation in budget.get("reservations", []):
            if not isinstance(reservation, dict) or (
                reservation.get("device") != device
                or reservation.get("correction_round") != correction_round
                or reservation.get("frame_index_hash") != frame_index_hash
                or reservation.get("source_artifact_hash") != source_artifact_hash
                or reservation.get("caption_artifact_hash", "") != caption_artifact_hash
            ):
                continue
            receipt_path = run_dir / "review-receipt.json"
            manifest_path = run_dir / "manifest.json"
            reservation.update(
                {
                    "receipt_path": str(receipt_path.resolve()),
                    "receipt_sha256": _file_sha256(receipt_path),
                    "manifest_path": str(manifest_path.resolve()),
                    "status": status,
                }
            )
            path.write_text(json.dumps(budget, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            path.chmod(0o600)
            return budget
    raise WorkflowError("could not attach the review receipt to its budget reservation")


def review_defect_fingerprint(review: dict[str, Any]) -> str:
    failed_assertions = [
        {
            "id": item.get("id"),
            "verdict": item.get("verdict"),
            "frames": sorted(map(str, item.get("frames") or [])),
        }
        for item in review.get("assertions", [])
        if isinstance(item, dict) and item.get("verdict") != "supported"
    ]
    incidental = [
        {
            "id": item.get("id"),
            "category": item.get("category"),
            "severity": item.get("severity"),
            "intent": item.get("intent"),
            "quality_categories": sorted(map(str, item.get("quality_categories") or [])),
            "frames": sorted(map(str, item.get("frames") or [])),
        }
        for item in review.get("incidental_findings", [])
        if isinstance(item, dict)
    ]
    payload = json.dumps(
        {"status": review.get("status"), "assertions": failed_assertions, "incidental_findings": incidental},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def review_next_action(review: dict[str, Any], *, prior_defect_fingerprints: list[str]) -> dict[str, Any]:
    status = str(review.get("status") or "")
    if status == "passed":
        return {
            "requires_user_input": False,
            "automatic_correction": False,
            "return_stage": "complete",
            "disposition": "publish",
        }
    fingerprint = review_defect_fingerprint(review)
    repeated = fingerprint in prior_defect_fingerprints
    uncertain = status == "uncertain"
    confidence = review.get("confidence")
    findings = [item for item in review.get("incidental_findings", []) if isinstance(item, dict)]
    unclear_intent = any(item.get("intent") == "unclear" for item in findings)
    uncertain_quality = any(
        result == "uncertain"
        for frame_review in review.get("frame_reviews", [])
        if isinstance(frame_review, dict)
        for result in (frame_review.get("checks") or {}).values()
    )
    low_confidence_finding = any(
        isinstance(item.get("confidence"), bool)
        or not isinstance(item.get("confidence"), (int, float))
        or item["confidence"] < 0.9
        for item in findings
    )
    low_confidence_product = status == "product_defect" and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or confidence < 0.9
        or low_confidence_finding
    )
    requires_user = uncertain or repeated or low_confidence_product or unclear_intent or uncertain_quality
    disposition = "ask_user" if requires_user else {
        "capture_defect": "recapture",
        "render_defect": "rerender",
        "product_defect": "auto_fix",
    }.get(status, "review")
    return_stage = {
        "recapture": "capture",
        "rerender": "render",
        "auto_fix": "implementation",
        "ask_user": "review",
    }.get(disposition, "review")
    next_action = {
        "recapture": "Recapture the required product state with visible transitions.",
        "rerender": "Rerender the proof without changing product pixels or assertions.",
        "auto_fix": "Add or strengthen a failing test, fix the product, deploy, and recapture replacement proof.",
        "ask_user": "Show the representative blocker frame and ask the user for consent before product-code changes.",
    }.get(disposition, "Review the classified defect.")
    return {
        "requires_user_input": requires_user,
        "automatic_correction": not requires_user and status in {"capture_defect", "render_defect", "product_defect"},
        "return_stage": return_stage,
        "disposition": disposition,
        "defect_fingerprint": fingerprint,
        "next_action": next_action,
    }


def proof_blocker_media(run_dir: Path, manifest: dict[str, Any], review_status: str) -> dict[str, Any]:
    """Return response-ready media metadata for failed or blocked proof reviews."""

    if review_status == "passed":
        return {}
    video_value = str(manifest.get("video_path") or "")
    if not video_value:
        source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
        video_value = str(source.get("artifact_path") or "")
    video_path = Path(video_value)
    if video_value and not video_path.is_absolute():
        video_path = run_dir / video_path

    record: dict[str, Any] = {
        "status": "required",
        "reason": "Proof review did not pass; include this recording when reporting the blocker.",
        "response_requirement": "Run upload_command and paste the returned video HTML in the blocker response.",
    }
    if not video_value or not video_path.is_file():
        return {**record, "media_status": "missing", "video_path": str(video_path) if video_value else ""}

    caption_artifact = manifest.get("caption_artifact") if isinstance(manifest.get("caption_artifact"), dict) else {}
    captions_value = str(caption_artifact.get("path") or "")
    captions_path = Path(captions_value) if captions_value else None
    if captions_path is not None and not captions_path.is_absolute():
        captions_path = run_dir / captions_path

    alt = f"Blocked proof video for {manifest.get('spec_id', 'session-proof')} ({review_status})"
    command = ["python3", "scripts/opencode_response_media.py", str(video_path)]
    if captions_path is not None and captions_path.is_file():
        command.extend(
            [
                "--captions",
                str(captions_path),
                "--captions-language",
                str(caption_artifact.get("language") or "und"),
                "--captions-label",
                str(caption_artifact.get("label") or "Captions"),
            ]
        )
        record["captions_path"] = str(captions_path)
    command.extend(["--alt", alt])
    return {
        **record,
        "media_status": "available",
        "video_path": str(video_path),
        "upload_command": " ".join(shlex.quote(part) for part in command),
    }


def _parse_reviewer_output(output: str) -> dict[str, Any]:
    candidates: list[str] = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part") if isinstance(event, dict) else None
        text = part.get("text") if isinstance(part, dict) else None
        if event.get("type") == "text" and isinstance(text, str):
            candidates.append(text.strip())
    for candidate in reversed(candidates):
        if candidate.startswith("```"):
            candidate = candidate.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise WorkflowError("proof-video reviewer did not return one valid JSON object")


def _default_reviewer_runner(prompt_path: Path, *, run_dir: Path, correction_round: int) -> tuple[dict[str, Any], str]:
    output_path = run_dir / f"review-output-round-{correction_round}.jsonl"
    opencode_bin = _resolve_opencode_bin()
    if not opencode_bin:
        raise WorkflowError("proof-video reviewer requires OPENCODE_BIN or an installed OpenCode executable")
    staged_prompt = REPO_ROOT / prompt_path.name
    staged_frames = REPO_ROOT / "frames"
    if staged_prompt.exists() or staged_prompt.is_symlink() or staged_frames.exists() or staged_frames.is_symlink():
        raise WorkflowError("proof-video reviewer staging paths already exist; remove stale review-prompt or frames symlink")
    command = [
        opencode_bin,
        "run",
        "--title",
        f"Review proof frames round {correction_round}",
        "--format",
        "json",
        "--agent",
        "proof-video-reviewer",
        "--dir",
        str(REPO_ROOT),
        f"Read {prompt_path.name} in full and return only the required JSON review receipt.",
    ]
    try:
        staged_prompt.symlink_to(prompt_path.resolve())
        staged_frames.symlink_to((run_dir / "frames").resolve(), target_is_directory=True)
        result = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, timeout=600, check=False)
    finally:
        for staged in (staged_prompt, staged_frames):
            if staged.is_symlink():
                staged.unlink()
    output = (result.stdout + result.stderr).strip()
    output_path.write_text(output + ("\n" if output else ""), encoding="utf-8")
    output_path.chmod(0o600)
    if result.returncode != 0:
        raise WorkflowError(f"proof-video reviewer failed with exit code {result.returncode}")
    session_id = ""
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("sessionID"):
            session_id = str(event["sessionID"])
            break
    return _parse_reviewer_output(output), session_id


def review_run(
    *,
    run_dir: Path,
    correction_round: int,
    correction_kind: str,
    reviewer_runner: Any = _default_reviewer_runner,
) -> dict[str, Any]:
    try:
        from scripts.spec_demo import record_review_receipt, review_request_hash, validate_review_request_files
    except ModuleNotFoundError:
        from spec_demo import record_review_receipt, review_request_hash, validate_review_request_files

    canonical_runs_root = (RESULTS_DIR / "proof-videos").resolve()
    if not run_dir.resolve().is_relative_to(canonical_runs_root):
        raise WorkflowError(f"review run directory must be inside {canonical_runs_root}")
    request = _load_json(run_dir / "review-request.json")
    existing_manifest = _load_json(run_dir / "manifest.json")
    try:
        validate_review_request_files(run_dir, request)
    except Exception as exc:
        raise WorkflowError(str(exc)) from exc
    frames = request.get("frames")
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_REVIEW_FRAMES_PER_DEVICE:
        raise WorkflowError("review request must contain one to twelve canonical frames")
    device = str((request.get("video_metadata") or {}).get("device_profile") or "unspecified-device")
    prompt_request = json.loads(json.dumps(request))
    for frame in prompt_request["frames"]:
        relative_path = Path(str(frame["path"]))
        if relative_path.is_absolute():
            raise WorkflowError("review frame paths must be relative to the run directory")
        resolved_path = (run_dir / relative_path).resolve()
        if not resolved_path.is_relative_to(run_dir.resolve()):
            raise WorkflowError("review frame path escapes the run directory")
        if not resolved_path.is_file() or _file_sha256(resolved_path) != frame.get("sha256"):
            raise WorkflowError(f"review frame is missing or its hash changed: {relative_path}")
        frame["read_path"] = str(relative_path)
    proof_identity = str(request.get("proof_group_id") or "")
    budget_path = REVIEW_BUDGETS_DIR / f"{proof_identity.removeprefix('sha256:')}.json"
    frame_hash = str(request.get("frame_index_hash") or "")
    source_hash = str((request.get("video_metadata") or {}).get("sha256") or "")
    caption_hash = str((request.get("video_metadata") or {}).get("captions_sha256") or "")
    cached = load_cached_review(
        budget_path,
        proof_identity=proof_identity,
        device=device,
        frame_index_hash=frame_hash,
        source_artifact_hash=source_hash,
        subject_commit=str(request.get("subject_commit") or ""),
        proof_contract_hash=str(request.get("proof_contract_hash") or ""),
        caption_artifact_hash=caption_hash,
    )
    if cached is not None:
        cached_receipt = {
            key: value
            for key, value in cached["receipt"].items()
            if key != "attempt_number"
        }
        blocker_media = proof_blocker_media(run_dir, existing_manifest, str(cached_receipt.get("status") or ""))
        if blocker_media:
            workflow_record = cached_receipt.get("workflow") if isinstance(cached_receipt.get("workflow"), dict) else {}
            workflow_record["blocker_media"] = blocker_media
            cached_receipt["workflow"] = workflow_record
            cached["blocker_media"] = blocker_media
        cached["receipt"] = cached_receipt
        cached["manifest"] = record_review_receipt(run_dir, cached_receipt)
        return cached
    budget = reserve_persisted_review_budget(
        budget_path,
        proof_identity=proof_identity,
        device=device,
        frame_count=len(frames),
        correction_round=correction_round,
        correction_kind=correction_kind,
        frame_index_hash=frame_hash,
        source_artifact_hash=source_hash,
        caption_artifact_hash=caption_hash,
    )

    prompt = {
        "instructions": (
            "Review every supplied frame. Before evaluating assertions, inspect each frame as a critical UI quality reviewer whose "
            "goal is to find reasons the proof must not pass. Record every required frame_reviews category, then separately evaluate "
            "the expected assertions and narration alignment. Scan for clipping, overlap, overflow, suspicious unused container space, "
            "incorrect geometry or colors, low contrast or unreadable text, stale loading, raw implementation text, broken navigation, "
            "missing or malformed icons, broken media, and unresponsive controls. Classify visible product defects as obvious only when "
            "the UI is objectively broken; use unclear when design intent is plausible and user consent is required before code changes. "
            "Never omit a supplied frame or inspect the full video."
            " Captions may be delivered as toggleable sidecar metadata rather than burned into the reviewed frames; do not report "
            "missing burned-in caption pixels as a defect unless the approved contract explicitly requires visible in-frame captions."
            " For every incidental finding, every listed quality category must be fail or uncertain on every cited frame; split findings "
            "when cited frames have different non-passing category sets. Read each image from read_path, but cite its canonical path field "
            "in the JSON response."
        ),
        "required_output": {
            "status": "passed|capture_defect|render_defect|product_defect|uncertain",
            "confidence": "number from 0 to 1",
            "frame_index_hash": request.get("frame_index_hash"),
            "reviewed_frames": "every canonical frame path exactly once",
            "frame_reviews": (
                "one item per frame with frame, checks, and observation; checks must include layout, readability, geometry, controls, "
                "visual_assets, application_state, consistency, and proof_alignment, each pass|fail|uncertain"
            ),
            "assertions": "one verdict for each expected_proof claim_id with id, verdict, frames, observation",
            "incidental_findings": (
                "list of id, category, severity, confidence, intent=obvious|unclear, quality_categories, frames, observation; "
                "every quality_categories value must be fail or uncertain on every cited frame, so split findings when category sets differ"
            ),
            "return_stage": "complete|capture|render|implementation|review",
            "next_action": "one bounded next action",
        },
        "review_request": prompt_request,
    }
    prompt_path = run_dir / f"review-prompt-round-{correction_round}.json"
    prompt_path.write_text(json.dumps(prompt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    prompt_path.chmod(0o600)
    receipt, reviewer_session_id = reviewer_runner(prompt_path, run_dir=run_dir, correction_round=correction_round)
    if receipt.get("frame_index_hash") != request.get("frame_index_hash"):
        raise WorkflowError("reviewer receipt did not preserve the canonical frame-index hash")
    if not reviewer_session_id:
        raise WorkflowError("proof-video reviewer did not return a persisted session ID")
    receipt["reviewer_session_id"] = reviewer_session_id
    receipt["device"] = device
    receipt["proof_contract_hash"] = request.get("proof_contract_hash")
    receipt["proof_group_id"] = request.get("proof_group_id")
    receipt["source_artifact_hash"] = (request.get("video_metadata") or {}).get("sha256")
    receipt["caption_artifact_hash"] = (request.get("video_metadata") or {}).get("captions_sha256")
    receipt["review_request_hash"] = review_request_hash(request)
    receipt["subject_commit"] = request.get("subject_commit")
    receipt["correction_round"] = correction_round
    receipt["correction_kind"] = correction_kind
    prior_fingerprints = [str(value) for value in budget.get("defect_fingerprints", [])]
    decision = review_next_action(receipt, prior_defect_fingerprints=prior_fingerprints)
    blocker_media = proof_blocker_media(run_dir, existing_manifest, str(receipt.get("status") or ""))
    if blocker_media:
        decision["blocker_media"] = blocker_media
    receipt["workflow"] = decision
    if receipt.get("status") != "passed":
        budget = append_persisted_defect_fingerprint(budget_path, decision["defect_fingerprint"])
    manifest = record_review_receipt(run_dir, receipt)
    budget = record_cached_review(
        budget_path,
        device=device,
        correction_round=correction_round,
        frame_index_hash=frame_hash,
        source_artifact_hash=source_hash,
        caption_artifact_hash=caption_hash,
        run_dir=run_dir,
        status=str(receipt.get("status") or ""),
    )
    result = {"status": receipt.get("status"), "receipt": receipt, "manifest": manifest, "budget": budget}
    if blocker_media:
        result["blocker_media"] = blocker_media
    return result


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


def require_clean_worktree(subject_commit: str = "", tracked_paths: list[str] | None = None) -> None:
    pathspec = [str(path) for path in tracked_paths or [] if str(path)]
    if subject_commit and pathspec:
        changes = []
        for relative_path in pathspec:
            local_path = REPO_ROOT / relative_path
            result = subprocess.run(
                ["git", "show", f"{subject_commit}:{relative_path}"],
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0 or not local_path.is_file() or local_path.read_bytes() != result.stdout:
                changes.append(relative_path)
    elif subject_commit:
        result = subprocess.run(
            ["git", "diff", "--name-only", subject_commit, "--"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise WorkflowError(f"could not compare worktree with subject commit: {result.stderr.strip()}")
        changes = [line for line in result.stdout.splitlines() if line]
    else:
        changes = _tracked_worktree_changes()
    if changes:
        raise WorkflowError(
            "proof-video provenance requires tracked files to match the subject commit; tracked changes: "
            + ", ".join(changes[:5])
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
        and _commit_matches(str(run.get("git_sha") or ""), subject_commit)
        and _commit_matches(str(run.get("deployment_reference") or ""), subject_commit)
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
            f"expected one deployed passing run for {spec_name} at or after {subject_commit} with run ID {run_id}, found {len(matches)}"
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
        runs = [
            run
            for run in runs
            if run_id in {str(run.get("run_id") or ""), str(run.get("source_run_id") or "")}
        ]
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
    review = subparsers.add_parser("review", help="Run the bounded AI frame review and persist its receipt.")
    review.add_argument("--run-dir", type=Path, required=True)
    review.add_argument("--correction-round", type=int, choices=range(MAX_AUTOMATIC_CORRECTION_ROUNDS + 1), default=0)
    review.add_argument(
        "--correction-kind",
        choices=("none", "mechanical", "capture", "product"),
        default="none",
    )
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
        if args.command == "review":
            print(
                json.dumps(
                    review_run(
                        run_dir=args.run_dir,
                        correction_round=args.correction_round,
                        correction_kind=args.correction_kind,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
    except WorkflowError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
