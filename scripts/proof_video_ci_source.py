#!/usr/bin/env python3
"""Read proof recordings from canonical, already-fetched isolated CI receipts.

This adapter does not dispatch jobs or manufacture shared-dev attestations.
It checks the receipt against the extracted runner reports, binds original
recordings and timeline bytes, and leaves rendering and visual review to the
existing proof workflow. Historical artifact caches remain untouched.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any


class CIProofError(RuntimeError):
    """A fetched receipt cannot supply trustworthy proof input."""


def _read(path: Path) -> Any:
    return json.loads(path.read_text())


def _hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _results(value: Any):
    if isinstance(value, dict):
        if "attachments" in value:
            yield value
        for child in value.values():
            yield from _results(child)
    elif isinstance(value, list):
        for child in value:
            yield from _results(child)


def _attached_file(root: Path, attachment: dict[str, Any], *, label: str) -> Path:
    parts = str(attachment.get("path", "")).split("/subject/", 1)
    if len(parts) != 2:
        raise CIProofError(f"{label} lacks canonical runner subject path")
    path = (root / parts[1]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise CIProofError(f"{label} is missing or escapes extracted CI artifact")
    return path


def _cli_capture_timing(root: Path, manifest: dict[str, Any], timeline: dict[str, Any]) -> dict[str, Any]:
    """Use only hash-bound input steps to locate stable CLI screens.

    The capture driver records each checkpoint after its hold, whereas the
    screen became ready before that hold. The timing file from ``script -T``
    has its own PTY-relative clock, so it is bound here but not mixed with
    the screen recorder's monotonic timestamps.
    """
    plan_path = _attached_file(root, {"path": manifest.get("input_plan_path")}, label="CLI input plan")
    events_path = _attached_file(root, {"path": manifest.get("events_path")}, label="CLI PTY timing events")
    if (manifest.get("input_plan_sha256") != "sha256:" + _hash(plan_path)
            or manifest.get("events_sha256") != "sha256:" + _hash(events_path)):
        raise CIProofError("CLI capture plan or PTY timing events changed")
    plan = _read(plan_path)
    steps = plan.get("steps") if isinstance(plan, dict) else None
    checkpoints = manifest.get("input_checkpoints")
    timeline_events = timeline.get("events")
    if (not isinstance(steps, list) or not isinstance(checkpoints, list)
            or not isinstance(timeline_events, list)
            or not steps or len(steps) != len(checkpoints) or len(steps) != len(timeline_events)
            or not events_path.stat().st_size):
        raise CIProofError("CLI capture timing lacks matching input steps and checkpoints")
    starts: dict[str, float] = {}
    ends: dict[str, float] = {}
    previous_at_ms = -1
    for step, checkpoint, event in zip(steps, checkpoints, timeline_events):
        if not all(isinstance(value, dict) for value in (step, checkpoint, event)):
            raise CIProofError("CLI capture timing contains malformed steps")
        name = step.get("name")
        hold_ms = step.get("hold_ms", 0)
        at_ms = checkpoint.get("at_ms")
        if (not isinstance(name, str) or not name or name in starts
                or name != checkpoint.get("name") or name != event.get("id")
                or event.get("kind") != "checkpoint" or event.get("at_ms") != at_ms
                or not isinstance(hold_ms, int) or isinstance(hold_ms, bool) or hold_ms < 0
                or not isinstance(at_ms, int) or isinstance(at_ms, bool)
                or at_ms <= previous_at_ms or at_ms < hold_ms
                or step.get("wait_for") != checkpoint.get("marker")):
            raise CIProofError("CLI capture plan, timeline and checkpoints disagree")
        starts[name] = round((at_ms - hold_ms) / 1000, 3)
        ends[name] = round(at_ms / 1000, 3)
        previous_at_ms = at_ms
    anchors: dict[str, float] = {}
    for assertion in timeline.get("contract", {}).get("assertions", []):
        if not isinstance(assertion, dict) or not assertion.get("id"):
            raise CIProofError("CLI proof contract contains an invalid assertion")
        checkpoint_name = assertion.get("checkpoint")
        if checkpoint_name not in starts:
            raise CIProofError("CLI assertion lacks an attested input checkpoint")
        anchors[str(assertion["id"])] = starts[checkpoint_name]
    if not anchors or len(anchors) != len(timeline.get("assertion_results", [])):
        raise CIProofError("CLI assertions lack distinct attested screen starts")
    for result in timeline["assertion_results"]:
        claim = result.get("id") if isinstance(result, dict) else None
        checkpoint_name = next((a.get("checkpoint") for a in timeline["contract"]["assertions"]
                                if a.get("id") == claim), None)
        if claim not in anchors or result.get("at_ms") != round(ends[checkpoint_name] * 1000):
            raise CIProofError("CLI assertion timestamp differs from its attested checkpoint")
    first_name = steps[0]["name"]
    last_assertion_name = timeline["contract"]["assertions"][-1]["checkpoint"]
    if not steps[0].get("wait_for") or "text" in steps[0] or "key" in steps[0]:
        raise CIProofError("CLI proof lacks an initial no-input readiness marker")
    return {
        # Sample frames after a short X11 paint allowance; captions start at
        # the attested text-ready instant below, before the checkpoint hold.
        "state_change_timestamps": [round(value + 0.2, 3) for value in anchors.values()],
        "state_change_timestamps_by_id": anchors,
        "capture_ready_timestamp_seconds": ends[first_name],
        **({"closed_screen_checkpoint_seconds": ends["welcome-hold"]} if "welcome-hold" in ends else {}),
        "source_end_timestamp_seconds": ends[last_assertion_name],
        "input_plan_sha256": manifest["input_plan_sha256"],
        "events_sha256": manifest["events_sha256"],
    }


def receipt_sources(receipt_path: Path) -> list[dict[str, Any]]:
    """Validate a canonical CI extraction before exposing any proof recording."""
    root = receipt_path.parent.resolve()
    receipt = _read(receipt_path)
    report = _read(root / "test-results/ci-results.json")
    environment = _read(root / "test-results/ci-environment.json")
    source = receipt.get("source_commit")
    run_id = str(receipt.get("run_id", ""))
    harness = receipt.get("harness_commit")
    if receipt.get("state") != "success":
        return []
    if report != receipt.get("report") or environment != receipt.get("environment"):
        raise CIProofError("CI receipt differs from its extracted source reports")
    if not all(isinstance(v, str) and len(v) == 40 for v in (source, harness)):
        raise CIProofError("CI receipt lacks full source/harness identities")
    for identity in (report, environment):
        if (identity.get("source_commit") != source or str(identity.get("run_id")) != run_id
                or identity.get("harness_commit") != harness):
            raise CIProofError("CI source/run/harness identity mismatch")
    jobs = receipt.get("runner_jobs", [])
    if not jobs or any("ubuntu-latest" not in j.get("labels", [])
                       or not j.get("runner_name", "").startswith("GitHub Actions") for j in jobs):
        raise CIProofError("Proof requires exclusively GitHub-hosted runners")
    if (report.get("success") is not True or environment.get("runner_environment") != "github-hosted"
            or environment.get("shared_dev_https") != "rejected"
            or environment.get("frontend", {}).get("source_commit") != source):
        raise CIProofError("CI proof lacks successful isolated frontend evidence")
    declared_profile = report.get("proof_profile")
    if declared_profile not in ("", "web-phone", "web-laptop"):
        return []
    records = []
    for index, spec in enumerate(report.get("results", [])):
        stats = spec.get("stats", {})
        if (spec.get("exit_code") != 0 or spec.get("coverage_complete") is not True
                or not stats.get("expected") or any(stats.get(k, 0) for k in ("skipped", "unexpected", "flaky"))):
            raise CIProofError("CI proof requires complete passing, unskipped spec coverage")
        report_path = root / f"test-results/ci-spec-{index}.json"
        for result_index, result in enumerate(_results(_read(report_path))):
            attachments = result.get("attachments", [])
            timelines = [a for a in attachments if a.get("name") == "openmates-proof-timeline"]
            if not timelines:
                continue
            timeline_bytes = base64.b64decode(timelines[0].get("body", ""), validate=True) if len(timelines) == 1 else b""
            timeline = json.loads(timeline_bytes) if timeline_bytes else {}
            profile = declared_profile or (
                "cli-terminal" if timeline.get("device") == "cli-terminal"
                and isinstance(timeline.get("contract"), dict)
                and timeline["contract"].get("surface") == "cli" else ""
            )
            if not profile:
                continue
            video_name = "openmates-cli-real-terminal-video" if profile == "cli-terminal" else "video"
            videos = [a for a in attachments if a.get("name") == video_name]
            if result.get("status") != "passed" or len(timelines) != 1 or len(videos) != 1:
                raise CIProofError("Proof timeline must belong to one passing recorded test")
            if timeline.get("device") != profile:
                raise CIProofError("Proof timeline disagrees with requested runner profile")
            assertions = timeline.get("assertion_results", [])
            if not assertions or any(a.get("status") != "passed" for a in assertions):
                raise CIProofError("Proof timeline contains incomplete assertions")
            video = _attached_file(root, videos[0], label="Recording")
            cli_timing: dict[str, Any] = {}
            if profile == "cli-terminal":
                manifests = [a for a in attachments if a.get("name") == "openmates-cli-real-terminal-manifest"]
                if len(manifests) != 1:
                    raise CIProofError("CLI proof requires one real-terminal capture manifest")
                manifest = _read(_attached_file(root, manifests[0], label="CLI capture manifest"))
                video_hash = "sha256:" + _hash(video)
                source_video = _attached_file(root, {"path": manifest.get("video_path")}, label="CLI source recording")
                if (manifest.get("capture_kind") != "real_terminal_screen" or manifest.get("reconstructed") is not False
                        or manifest.get("exit_status") != 0 or (manifest.get("width"), manifest.get("height")) != (1280, 720)
                        or manifest.get("video_sha256") != video_hash
                        or "sha256:" + _hash(source_video) != video_hash
                        or timeline.get("source_video_sha256") != video_hash
                        or timeline.get("source_video_path") != manifest.get("video_path")):
                    raise CIProofError("CLI proof manifest and timeline do not bind the real 1280x720 recording")
                cli_timing = _cli_capture_timing(root, manifest, timeline)
            cache = root / "proof-source-bindings" / f"{index}-{result_index}"
            identity = {"receipt_sha256": _hash(receipt_path), "report_sha256": _hash(report_path),
                        "artifact_sha256": _hash(video), "timeline_sha256": hashlib.sha256(timeline_bytes).hexdigest()}
            binding = cache / "binding.json"
            if binding.exists() and _read(binding) != identity:
                raise CIProofError("Previously bound CI proof input has changed")
            cache.mkdir(parents=True, exist_ok=True)
            timeline_path = cache / "timeline.json"
            if not binding.exists():
                timeline_path.write_bytes(timeline_bytes)
                binding.write_text(json.dumps(identity, sort_keys=True) + "\n")
            if not timeline_path.is_file() or _hash(timeline_path) != identity["timeline_sha256"]:
                raise CIProofError("Bound timeline hash changed")
            checkpoint_paths = {}
            for frame in timeline.get("checkpoint_frames", []):
                attached = [a for a in attachments if a.get("name") == frame.get("attachment_name")]
                if len(attached) != 1:
                    raise CIProofError("Timeline checkpoint lacks its exact attached frame")
                frame_bytes = base64.b64decode(attached[0].get("body", ""), validate=True)
                frame_hash = "sha256:" + hashlib.sha256(frame_bytes).hexdigest()
                if frame_hash != frame.get("sha256"):
                    raise CIProofError("Attached checkpoint frame hash differs from timeline")
                frame_path = cache / (frame_hash.removeprefix("sha256:") + ".png")
                if not frame_path.exists():
                    frame_path.write_bytes(frame_bytes)
                if "sha256:" + _hash(frame_path) != frame_hash:
                    raise CIProofError("Bound checkpoint frame changed")
                checkpoint_paths[str(frame["checkpoint"])] = str(frame_path)
            records.append({"run_id": f"{run_id}:{index}-{result_index}", "source_run_id": run_id,
                            "git_sha": source, "spec": spec["spec"], "status": "passed",
                            "source": "github_isolated", "isolation_verified": True,
                            "deployment_reference": source, "target": "github-isolated",
                            "artifact_path": str(video), "artifact_sha256": "sha256:" + identity["artifact_sha256"],
                            "proof_timeline_path": str(timeline_path), "proof_timeline_sha256": "sha256:" + identity["timeline_sha256"],
                            "proof_video_profile": profile, "ci_receipt_path": str(receipt_path),
                            "ci_receipt_sha256": identity["receipt_sha256"],
                            "proof_checkpoint_paths": checkpoint_paths,
                            **cli_timing})
    return records
