"""Run one AI test-user persona against dev or prod through the in-container worker."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import ai_test_users_accounts as accounts
import ai_test_users_video as video
import dev_test_account
import e2b_dev_capacity

CONTAINER = "api"
CONTAINER_WORKER = "/app/backend/scripts/ai_test_users/session.py"
CONTAINER_OUTPUT = "/tmp/ai-test-users"
TARGETS = {
    "dev": {"app_url": "https://app.dev.openmates.org/", "allowed_hosts": ["app.dev.openmates.org"]},
    "prod": {"app_url": "https://app.openmates.org/", "allowed_hosts": ["app.openmates.org"]},
}
SKIP_STATUSES = ("skipped", "prod_disabled", "no_gift_card", "no_e2b_slot", "budget_exhausted")


@dataclass
class Settings:
    max_steps: int = 40
    max_minutes: float = 22
    harness_cap_usd: float = 0.3
    e2b_cap_usd: float = 0.15
    worker: str = CONTAINER_WORKER
    base: Path | None = None
    report_enabled: bool = True
    skip_titles: tuple[str, ...] = ()


def docker(*args: str, stdin: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=stdin, capture_output=True, text=True, timeout=timeout,
                          check=False)


def make_job(persona: dict | None, target: str, run_id: str, signup: dict, cfg: Settings, name: str,
             mode: str = "run") -> dict:
    info = TARGETS[target]
    job = {
        "run_id": run_id, "target": target, "persona": persona, "app_url": info["app_url"],
        "allowed_hosts": info["allowed_hosts"], "signup": signup,
        "report": {"enabled": cfg.report_enabled and mode == "run", "max_reports": 3, "max_screenshots": 5,
                   "skip_titles": list(cfg.skip_titles)},
        "delete_account": True,
        "output_dir": f"{CONTAINER_OUTPUT}/{run_id}/{name}",
        "stop_file": f"{CONTAINER_OUTPUT}/{run_id}/{name}.stop",
        "max_steps": cfg.max_steps, "max_minutes": cfg.max_minutes,
        "harness_cap_usd": cfg.harness_cap_usd, "e2b_cap_usd": cfg.e2b_cap_usd,
    }
    if mode != "run":
        job["mode"] = mode
    return job


def gate(target: str, base: Path | None) -> tuple[str | None, dict]:
    """Return (blocking status, signup extras). Prod needs the flag file and a gift card code."""
    if target == "prod":
        if not accounts.prod_enabled(base):
            return "prod_disabled", {}
        code, _ = accounts.pop_prod_code(base)
        if code is None:
            return "no_gift_card", {}
        return None, {"gift_card_code": code, "invite_code": ""}
    try:
        return None, accounts.create_dev_card()
    except (RuntimeError, subprocess.SubprocessError) as exc:
        return f"gift_card_failed: {exc}", {}


def run_persona(persona: dict, target: str, run_id: str, run_dir: Path, cfg: Settings) -> dict:
    summary = {"persona": persona["id"], "target": target, "name": persona["name"]}
    if persona.get("required_goals"):
        summary["required_goals"] = True
    blocked = e2b_dev_capacity.budget_exhausted()
    if blocked:
        return {**summary, "status": "budget_exhausted", "error": blocked}
    status, extras = gate(target, cfg.base)
    if status:
        return {**summary, "status": "skipped" if status.startswith("gift_card_failed") else status,
                "error": status if status.startswith("gift_card_failed") else None}
    try:
        domain, inbox = accounts.signup_mailbox(target)
    except RuntimeError as exc:
        return {**summary, "status": "skipped", "error": f"signup_mailbox: {exc}"}
    identity = accounts.new_identity(cfg.base, domain)
    signup = {**identity, **extras, "inbox": inbox}
    accounts.save_secret(identity["email"], signup, cfg.base)
    accounts.register_account(identity["email"], target, run_id, persona["id"], "created", cfg.base)
    out = run_dir / target
    out.mkdir(parents=True, exist_ok=True)
    name = persona["id"]
    job = make_job(persona, target, run_id, signup, cfg, name)
    video_key = video.object_key(run_id, target, name)
    try:  # signed before the session so the reports it files can link the recording
        job["video_url"] = video.sign([video_key])[0]
    except RuntimeError as exc:
        summary["video_error"] = str(exc)[:300]
    slot = e2b_dev_capacity.acquire(f"ai-test-user-{target}-{name}", timeout=900)
    if slot is None:
        accounts.update_status(identity["email"], "delete_failed", cfg.base)  # nothing was created; retry cleans up
        return {**summary, "status": "no_e2b_slot", "email": identity["email"]}
    started = time.monotonic()
    summary["started_at"] = round(time.time(), 1)
    try:
        run = docker("exec", "-i", CONTAINER, "python", cfg.worker, stdin=json.dumps(job),
                     timeout=int(cfg.max_minutes * 60 + 1500))
        (out / f"{name}.worker.log").write_text(run.stderr[-20000:])
        summary["worker_exit"] = run.returncode
    except subprocess.TimeoutExpired:
        summary["worker_exit"] = "timeout"
    finally:
        slot.release()
    summary["wall_seconds"] = round(time.monotonic() - started, 1)
    summary["finished_at"] = round(time.time(), 1)
    copied = docker("cp", f"{CONTAINER}:{CONTAINER_OUTPUT}/{run_id}/{name}", str(out), timeout=300)
    if copied.returncode:
        summary["copy_error"] = copied.stderr[-300:]
    docker("exec", CONTAINER, "rm", "-rf", f"{CONTAINER_OUTPUT}/{run_id}/{name}",
           f"{CONTAINER_OUTPUT}/{run_id}/{name}.stop")
    store_video(summary, out / name / "video.webm", video_key, job.get("video_url"))
    return read_result(summary, out / name / "result.json", identity["email"], cfg)


def store_video(summary: dict, path: Path, key: str, signed_url: str | None) -> None:
    """Upload the session recording (7-day bucket) and keep its link in the persona summary."""
    if not path.exists():
        summary["video_error"] = summary.get("video_error") or "no recording"
        return
    try:
        uploaded = video.upload(path, key)
    except (RuntimeError, OSError) as exc:
        summary["video_error"] = f"upload failed: {str(exc)[:300]}"
        return
    summary["video"] = {"url": signed_url or uploaded["url"], "key": key}


def read_result(summary: dict, result_file: Path, email: str, cfg: Settings) -> dict:
    result: dict = {}
    if result_file.exists():
        result = json.loads(result_file.read_text())
        findings = result.get("findings", [])
        summary.update({k: result.get(k) for k in (
            "status", "steps", "harness_usd", "e2b", "error", "judge_error", "credits_start", "credits_end",
            "answer_quality", "demo_candidate", "goal_outcomes", "video_offset_seconds")})
        summary["findings"] = [{**{k: f.get(k) for k in ("title", "severity", "category", "step",
                                                         "video_seconds", "kept", "at_epoch")},
                                "evidence": str(f.get("evidence") or "")[:300]}
                               for f in findings]
        summary["findings_total"] = len(findings)
        summary["findings_kept"] = sum(1 for f in findings if f.get("kept"))
        summary["reports"] = result.get("reports", [])
        e2b = result.get("e2b") or {}
        if e2b.get("seconds"):
            e2b_dev_capacity.record_spend(e2b["seconds"], e2b.get("cpu", 2), e2b.get("memory_mb", 4096))
        if summary.get("credits_start") is not None and summary.get("credits_end") is not None:
            summary["credits_used"] = summary["credits_start"] - summary["credits_end"]
            summary["app_usd_list_price"] = round(summary["credits_used"] * 0.001, 3)
    else:
        summary.setdefault("status", "worker_failed")
    deletion = result.get("deletion") or {"status": "not_reported"}
    if deletion.get("status") == "host":
        deletion = {"status": host_delete(email)}
    summary["deletion_status"] = deletion.get("status")
    if deletion.get("status") in ("ok", "absent", "deleted"):
        accounts.update_status(email, "deleted", cfg.base)
        accounts.remove_secret(email, cfg.base)
    else:
        accounts.update_status(email, "delete_failed", cfg.base)
    summary["email"] = email
    return summary


def host_delete(email: str) -> str:
    """Delete a dev test account with the dev admin script (dev_test_account.delete_account):
    "deleted", "absent" (never created) or "failed: ..."."""
    try:
        return "deleted" if dev_test_account.delete_account(email) == "ok" else "absent"
    except (dev_test_account.ThrowawayAccountError, subprocess.SubprocessError, OSError) as exc:
        return f"failed: {str(exc)[:200]}"


def retry_deletions(run_id: str, run_dir: Path, cfg: Settings,
                    targets: Collection[str] = ("dev", "prod")) -> list[dict]:
    """Fresh sandbox job in delete-only mode for each account whose deletion failed."""
    outcomes = []
    for entry in accounts.pending_deletions(cfg.base, run_id=run_id):
        if entry["target"] not in targets:
            continue
        if entry["target"] == "prod" and not accounts.prod_enabled(cfg.base):
            continue
        if entry["target"] == "dev":
            status = host_delete(entry["email"])
            if status in ("deleted", "absent"):
                accounts.update_status(entry["email"], "deleted", cfg.base)
                accounts.remove_secret(entry["email"], cfg.base)
            outcomes.append({"email": entry["email"], "target": "dev", "status": status})
            continue
        signup = accounts.load_secret(entry["email"], cfg.base)
        name = "delete-" + entry["email"].split("@")[0][-8:]
        slot = e2b_dev_capacity.acquire(f"ai-test-user-{name}", timeout=900)
        if slot is None:
            continue
        job = make_job(None, entry["target"], run_id, signup, cfg, name, mode="delete_only")
        try:
            docker("exec", "-i", CONTAINER, "python", cfg.worker, stdin=json.dumps(job), timeout=1200)
        except subprocess.TimeoutExpired:
            pass
        finally:
            slot.release()
        out = run_dir / entry["target"]
        out.mkdir(parents=True, exist_ok=True)
        docker("cp", f"{CONTAINER}:{CONTAINER_OUTPUT}/{run_id}/{name}", str(out), timeout=300)
        docker("exec", CONTAINER, "rm", "-rf", f"{CONTAINER_OUTPUT}/{run_id}/{name}")
        result_file = out / name / "result.json"
        status = (json.loads(result_file.read_text()).get("deletion") or {}).get("status") if result_file.exists() else None
        if status in ("ok", "absent", "deleted"):
            accounts.update_status(entry["email"], "deleted", cfg.base)
            accounts.remove_secret(entry["email"], cfg.base)
        outcomes.append({"email": entry["email"], "target": entry["target"], "status": status or "failed"})
    return outcomes
