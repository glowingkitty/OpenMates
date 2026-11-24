#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Real voice-call check after every dev deploy and production update.

Two legs, each starting a real call, speaking one sentence and confirming that a
spoken reply arrives, recorded with sound:
  signed_in  a temporary signed-in test user
  guest      a signed-out visitor (tests/voice-call-guest-real.spec.ts)

Dev signed-in leg: scripts/voice_call_web_real_test.py --throwaway-account.
Prod signed-in leg: a labelled gift-card signup from scripts/post_update_test_account.py
is created, tests/voice-call-real.spec.ts runs against production with its
credentials, and the account is always deleted afterwards (a failed cleanup is a
warning). A leg passes when its receipt says passed, a reply was played and a
*-with-audio.webm with audible sound (> -50 dB) exists. The dev timer retries
unresolved legs once and reports a remaining gap after the retry window.

  python3 scripts/voice_post_update_check.py run --target dev
  python3 scripts/voice_post_update_check.py run --target prod --legs guest
  python3 scripts/voice_post_update_check.py dev-watch     # systemd timer entry
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from resource_budget import MIN_FREE

SCRIPTS = Path(__file__).resolve().parent
BASE_URLS = {"dev": "https://app.dev.openmates.org", "prod": "https://app.openmates.org"}
LEGS = ("signed_in", "guest")
MIN_LOUDNESS_DB = -50.0
STATE_DIR = Path.home() / ".openmates" / "voice-post-update-check"
STATE_FILE = STATE_DIR / "state.json"
PUSH_SOURCE = "voice-post-update-check"
SESSION_LABEL = "voice-post-update-check"
RUN_TIMEOUT_SECONDS = 1800
ACCOUNT_TIMEOUT_SECONDS = 2250
GUEST_SPEC = "tests/voice-call-guest-real.spec.ts"
SIGNED_IN_SPEC = "tests/voice-call-real.spec.ts"
SCENARIO = "capital"
AUDIO_GLOB = "*with-audio.webm"
DEV_API_HEALTH = "https://api.dev.openmates.org/health"
RETRY_DELAY = 5 * 60
RETRY_WINDOW = 2 * 60 * 60
SETUP_ERRORS = {"lease_unavailable", "lease_renewal_failed", "heavy_slot_unavailable", "no_test_passed",
                "deployed_runtime_revision_mismatch", "deployed_frontend_revision_mismatch"}


class CheckError(RuntimeError):
    """A leg failed for a reason that is safe to put in a summary and a push."""


# --- revision ------------------------------------------------------------------------


def fetch_revision(base_url: str) -> str:
    """The served web app version (`/_app/version.json`)."""
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/_app/version.json", timeout=20) as response:
            version = json.load(response).get("version")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CheckError(f"version_unreadable: {type(exc).__name__}") from exc
    if not isinstance(version, str) or not version:
        raise CheckError("version_missing")
    return version


# --- evaluation ----------------------------------------------------------------------


def find_video(out: Path, receipt: dict) -> Path | None:
    """The with-audio proof video of a leg: from the receipt, else searched below `out`."""
    listed = [Path(v) for v in receipt.get("videos_with_audio") or [] if Path(v).is_file()]
    found = listed or sorted(out.rglob(AUDIO_GLOB))
    return found[-1] if found else None


def _loudness(video: Path) -> float:
    import proof_video_audio

    try:
        return proof_video_audio.loudness(video)
    except proof_video_audio.MuxError as exc:
        raise CheckError(f"video_has_no_audio: {exc}") from exc


def _disk_error(*details: object) -> bool:
    return any(re.search(r"\b(?:ENOSPC|no space left on device|waiting for disk capacity)\b",
                         str(detail or ""), re.IGNORECASE) for detail in details)


def _runner_disk_error(out: Path) -> bool:
    for name in ("run.log", "wrapper.log"):
        try:
            with (out / name).open("rb") as log:
                log.seek(max(0, os.fstat(log.fileno()).st_size - 16384))
                if _disk_error(log.read().decode(errors="replace")):
                    return True
        except FileNotFoundError:
            continue
    return False


def _blocked_disk() -> dict:
    return {"status": "blocked", "video": None, "error": "disk space unavailable", "reason": "disk_space"}


def evaluate_leg(out: Path, loudness=_loudness) -> dict:
    """Judge a leg from its receipt.json and videos; returns {status, video, error}."""
    path = out / "receipt.json"
    if not path.is_file():
        if _runner_disk_error(out):
            return _blocked_disk()
        return {"status": "blocked", "video": None, "error": "no receipt written", "reason": "setup"}
    receipt = json.loads(path.read_text())
    video = find_video(out, receipt)
    status, reason, error = "passed", "", None
    if receipt.get("status") != "passed":
        code = receipt.get("error_code") or "no reason"
        error = f"receipt status {receipt.get('status')}: {code}"
        raw_error = str(receipt.get("error") or "")
        if code == "disk_space" or _disk_error(code, raw_error, receipt.get("error_detail")) or _runner_disk_error(out):
            return _blocked_disk()
        if (receipt.get("status") == "blocked" or code in SETUP_ERRORS
                or ("deployed_revision" in receipt and "playwright_exit_code" not in receipt)):
            status, reason = "blocked", "setup"
            detail = str(receipt.get("error_detail") or "").lower()
            if code == "lease_unavailable" and "docker exec api" in detail and "is not running" in detail:
                reason = "dev_api_unavailable"
        elif "message-user" in raw_error and "toBeVisible" in raw_error:
            status, reason = "failed", "message_missing"
        else:
            status, reason = "failed", "call_flow"
    elif not (receipt.get("played_audio") or receipt.get("speech_status") == 200):
        error = "no spoken reply was played"
    elif video is None:
        error = "no with-audio video"
    else:
        try:
            level = loudness(video)
        except CheckError as exc:
            error = str(exc)
        else:
            if level <= MIN_LOUDNESS_DB:
                error = f"video is silent ({level:.1f} dB)"
    if error and status == "passed":
        status, reason = ("blocked", "proof_missing") if (
            receipt.get("played_audio") or receipt.get("speech_status") == 200
        ) else ("failed", "reply_missing")
    return {"status": status, "video": str(video) if video else None, "error": error, "reason": reason}


# --- playwright / runner launches -----------------------------------------------------


def run_playwright(spec: str, out: Path, env: dict[str, str], remote_env: list[str]) -> int:
    """Run one spec through heavy_slot with the proof config; muxes the page sound afterwards."""
    import design_embroidery_web_real_test as harness
    import proof_video_audio

    out.mkdir(parents=True, exist_ok=True)
    chrome = harness.installed_chromium()
    config = out / "playwright.proof.config.cjs"
    config.write_text(harness.CONFIG.format(
        base=json.dumps(str(harness.WEB_APP / "playwright.config.ts")),
        test_dir=json.dumps(str(harness.WEB_APP / "tests")), results=json.dumps(str(out / "results")),
        report=json.dumps(str(out / "report.json")), chrome=json.dumps(str(chrome))))
    full_env = {**os.environ, **env, "PLAYWRIGHT_VIDEO_MODE": "on", "OPENMATES_PROOF_CHROME": str(chrome),
                "OPENMATES_HEAVY_REMOTE_ENV": ",".join(remote_env),
                "OPENMATES_HEAVY_REMOTE_DIRS": ",".join([str(out), env.get("VOICE_CALL_REAL_SPEECH_DIR", "")])}
    link = harness.WEB_APP / "node_modules"
    created = not link.exists()
    if created:
        link.symlink_to(harness.CANONICAL_NODE_MODULES, target_is_directory=True)
    try:
        command = harness.heavy_slot_command(config, spec, RUN_TIMEOUT_SECONDS, None)
        with (out / "run.log").open("w") as log:
            run = subprocess.run(command, cwd=out, env=full_env, stdout=log, stderr=subprocess.STDOUT,
                                 check=False, timeout=harness.HEAVY_SLOT_WAIT_SECONDS + RUN_TIMEOUT_SECONDS
                                 + harness.REMOTE_SETUP_SECONDS)
    finally:
        if created:
            link.unlink()
    try:
        proof_video_audio.mux_all(out / "results")
    except proof_video_audio.MuxError as exc:
        print(f"WARNING: could not mux audio: {exc}", file=sys.stderr)
    return run.returncode


def _write_receipt(out: Path, status: str, **fields) -> None:
    """Receipt for runs where the spec itself did not write one."""
    videos = sorted(str(p) for p in (out / "results").rglob(AUDIO_GLOB))
    (out / "receipt.json").write_text(json.dumps({"status": status, "videos_with_audio": videos, **fields}))


def run_guest(base_url: str, out: Path) -> None:
    """Signed-out call: the spec reads VOICE_GUEST_REAL_BASE_URL and writes VOICE_CHECK_RECEIPT."""
    import voice_call_web_real_test as voice

    speech = Path(tempfile.mkdtemp(prefix="voice-check-speech-", dir="/tmp"))
    voice.generate_speech(speech, SCENARIO)
    out.mkdir(parents=True, exist_ok=True)
    env = {"VOICE_GUEST_REAL_BASE_URL": base_url, "VOICE_CHECK_RECEIPT": str(out / "receipt.json"),
           "VOICE_CALL_REAL_SPEECH_DIR": str(speech), "VOICE_CALL_REAL_SCENARIO": SCENARIO,
           "VOICE_CALL_REAL_DEV": "1", "PLAYWRIGHT_TEST_BASE_URL": base_url}
    code = run_playwright(GUEST_SPEC, out, env, list(env))
    if code != 0 and not (out / "receipt.json").is_file():
        _write_receipt(out, "blocked", error_code=f"playwright exit {code}")


def run_signed_in_dev(revision: str, out: Path) -> None:
    """Dev signed-in call through the existing runner with a throwaway account."""
    command = [sys.executable, str(SCRIPTS / "voice_call_web_real_test.py"), "--session", SESSION_LABEL,
               "--revision", revision, "--output-dir", str(out), "--personal-dev-test-account",
               "--throwaway-account", "--allow-paid-dev-inference", "--scenario", SCENARIO]
    out.mkdir(parents=True, exist_ok=True)
    with (out / "wrapper.log").open("w") as log:
        subprocess.run(command, check=False, timeout=RUN_TIMEOUT_SECONDS * 3,
                       stdout=log, stderr=subprocess.STDOUT)


def create_account(target: str, credentials: Path) -> dict:
    run = subprocess.run([sys.executable, str(SCRIPTS / "post_update_test_account.py"), "--target", target,
                          "create", "--out", str(credentials)], capture_output=True, text=True,
                         check=False, timeout=ACCOUNT_TIMEOUT_SECONDS)
    if run.returncode:
        raise CheckError(f"test account could not be created: {run.stderr.strip()[-200:]}")
    return json.loads(run.stdout.strip().splitlines()[-1])


def delete_account(target: str, email: str) -> None:
    """Record failed cleanup without hiding the call result."""
    try:
        run = subprocess.run([sys.executable, str(SCRIPTS / "post_update_test_account.py"), "--target", target,
                              "delete", "--email", email], capture_output=True, text=True, check=False,
                             timeout=ACCOUNT_TIMEOUT_SECONDS)
    except subprocess.SubprocessError as exc:
        print(f"WARNING: test account cleanup failed: {exc}", file=sys.stderr)
        return
    if run.returncode:
        print(f"WARNING: test account cleanup failed: {run.stderr.strip()[-200:]}", file=sys.stderr)


def run_signed_in_prod(base_url: str, out: Path) -> None:
    """Prod signed-in call: temporary labelled account, voice-call-real.spec.ts, deletion in `finally`.

    The dev runner is hard-wired to the dev URL, so the spec is launched directly with the
    account in OPENMATES_TEST_ACCOUNT_1_* and PLAYWRIGHT_TEST_BASE_URL set to production."""
    import voice_call_web_real_test as voice

    if base_url.rstrip("/") != BASE_URLS["prod"]:
        raise CheckError("production test accounts may only sign in on the production app")
    out.mkdir(parents=True, exist_ok=True)
    private = Path(tempfile.mkdtemp(prefix="voice-check-account-"))
    os.chmod(private, 0o700)
    email = None
    try:
        email = create_account("prod", private / "credentials.json")["email"]
        creds = json.loads((private / "credentials.json").read_text())
        speech = Path(tempfile.mkdtemp(prefix="voice-check-speech-", dir="/tmp"))
        voice.generate_speech(speech, SCENARIO)
        env = {"OPENMATES_TEST_ACCOUNT_1_EMAIL": creds["email"],
               "OPENMATES_TEST_ACCOUNT_1_PASSWORD": creds["password"],
               "OPENMATES_TEST_ACCOUNT_1_OTP_KEY": creds.get("otp_key", ""), "PLAYWRIGHT_TEST_BASE_URL": base_url,
               "VOICE_CALL_REAL_DEV": "1", "VOICE_CALL_REAL_SPEECH_DIR": str(speech),
               "VOICE_CALL_REAL_SCENARIO": SCENARIO}
        code = run_playwright(SIGNED_IN_SPEC, out, env, list(env))
        log = (out / "run.log").read_text(errors="replace") if (out / "run.log").exists() else ""
        played = [m.strip() for m in re.findall(r"played audio: ([^\n]+)", log)]
        _write_receipt(out, "passed" if code == 0 and played else "failed", played_audio=played,
                       error_code=None if code == 0 else f"playwright exit {code}")
    finally:
        if email:
            delete_account("prod", email)
        for leftover in private.glob("*"):
            leftover.unlink()
        private.rmdir()


# --- orchestration -------------------------------------------------------------------


def run_leg(name: str, target: str, base_url: str, revision: str, out: Path) -> dict:
    """Run one leg and judge it; launch failures become a failed result, never a crash."""
    try:
        if name == "guest":
            run_guest(base_url, out)
        elif target == "dev":
            run_signed_in_dev(revision, out)
        else:
            run_signed_in_prod(base_url, out)
        return evaluate_leg(out)
    except (CheckError, subprocess.SubprocessError, OSError, SystemExit, KeyError, ValueError) as exc:
        if (isinstance(exc, OSError) and exc.errno == errno.ENOSPC) or _disk_error(exc):
            return _blocked_disk()
        return {"status": "blocked", "video": None, "error": f"{type(exc).__name__}: {exc}"[:300], "reason": "setup"}


def failure_message(target: str, summary: dict) -> str:
    """Format a phone preview and one combined report without exposing runner output."""
    environment = "dev" if target == "dev" else "production"
    legs = summary["legs"]
    labels = {"signed_in": "signed-in", "guest": "guest"}
    failed = [name for name, leg in legs.items() if leg["status"] == "failed"]
    if "disk_recovered_bytes" in summary:
        recovered = summary["disk_recovered_bytes"] / 10**9
        first = f"Dev disk almost full, cleanup recovered {recovered:.1f} GB."
    elif any(leg["status"] == "blocked" for leg in legs.values()):
        first = f"The {environment} voice check is incomplete after the update."
    else:
        subject = f" {labels[failed[0]]}" if len(failed) == 1 else ""
        result = "still fails after a retry" if summary.get("retried") else "failed after the update"
        first = f"The {environment}{subject} voice check {result}."
    phrases = {
        "disk_space": "could not write its test files because disk space was too low",
        "dev_api_unavailable": "could not start while the dev API was unavailable",
        "proof_missing": "played a reply, but the recording could not verify the result",
        "message_missing": "timed out waiting for the user's message",
        "reply_missing": "did not play a spoken reply",
    }
    statuses = {"passed": "passed", "blocked": "could not start or finish verification",
                "failed": "ran but did not pass"}
    details = [
        f"The {labels[name]} call check {phrases.get(leg.get('reason'), statuses[leg['status']])}."
        for name, leg in legs.items()
    ]
    if "disk_recovered_bytes" in summary:
        details.append("The checker will retry when there is enough space.")
    elif summary.get("retried"):
        details.append("The checker retried the unresolved checks.")
    elif summary.get("retry_expired"):
        details.append("The checker waited for the service to be ready, and the retry window ended.")
    details.append("A voice outage is unconfirmed.")
    if target == "prod":
        details.append("Verify calls on production now.")
    elif failed:
        details.append("Hold the next production rollout until the dev voice check passes.")
    else:
        details.append("Nothing needed from you. The incomplete check is recorded for follow-up.")
    return first + "\n" + " ".join(details)


def push_failure(target: str, summary: dict) -> None:
    """Send the combined voice check result as one alert."""
    import agent_question
    import discord_webhook
    from pending_work_gate import canonical_root

    message = failure_message(target, summary)
    root = canonical_root()
    agent_question.deliver(agent_question.webhook(root), message, discord_webhook.post_message)
    agent_question.record_push(root, message, time.time(), title="Voice check", asks=message.splitlines()[0],
                               source=PUSH_SOURCE)


def run_check(target: str, base_url: str | None, revision: str | None, out: Path | None,
              legs: list[str], push: bool = True, leg_runner=run_leg, pusher=push_failure) -> dict:
    """Run the legs, write summary.json, push on failure."""
    base = (base_url or BASE_URLS[target]).rstrip("/")
    revision = revision or fetch_revision(base)
    try:
        out = out or Path(tempfile.mkdtemp(prefix=f"voice-check-{target}-", dir="/tmp"))
        results = {name: leg_runner(name, target, base, revision, out / name) for name in legs}
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if exc.errno != errno.ENOSPC:
            raise
        results = {name: _blocked_disk() for name in legs}
        out = None
    summary = {"target": target, "revision": revision, "legs": results,
               "passed": all(leg["status"] == "passed" for leg in results.values()),
               "finished_at": datetime.now(UTC).isoformat()}
    if out is not None:
        try:
            (out / "summary.json").write_text(json.dumps(summary, indent=2))
        except OSError as exc:
            if exc.errno != errno.ENOSPC:
                raise
            print("Voice summary could not be saved because the filesystem is full.", file=sys.stderr)
    if not summary["passed"] and push:
        pusher(target, summary)
    return summary


# --- dev-watch -----------------------------------------------------------------------


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def dev_runtime_ready(revision: str) -> bool:
    """Wait for aligned dev frontend and backend before claiming a paid check."""
    from design_embroidery_web_real_test import ProofError, require_runtime_revision

    try:
        require_runtime_revision(revision)
        with urllib.request.urlopen(DEV_API_HEALTH, timeout=10) as response:
            return response.status == 200
    except (ProofError, OSError, subprocess.SubprocessError):
        return False


def _write_state(path: Path, state: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.replace(path)


def _send_pending_alert(path: Path, state: dict, pusher) -> int:
    summary = state["alert_pending"]
    pusher("dev", summary)
    state["last_alert_legs"] = summary["legs"]
    state.pop("alert_pending")
    _write_state(path, state)
    return 1


def _notice_summary(summary: dict) -> dict:
    """Persist only the information used to decide whether and what to alert."""
    return {
        "passed": summary["passed"],
        "legs": {name: {"status": leg["status"], "reason": leg.get("reason")}
                 for name, leg in summary["legs"].items()},
        "retried": bool(summary.get("retried")),
        "retry_expired": bool(summary.get("retry_expired")),
    }


def _record_watch_result(path: Path, state: dict, summary: dict) -> None:
    report = _notice_summary(summary)
    state["last_result"] = {"passed": report["passed"],
                            "legs": {name: leg["status"] for name, leg in report["legs"].items()}}
    if report["passed"]:
        state.pop("last_alert_legs", None)
    elif state.get("last_alert_legs") != report["legs"]:
        state["alert_pending"] = report
    _write_state(path, state)


def _free_space() -> int:
    return shutil.disk_usage("/tmp").free


def _request_disk_cleanup() -> None:
    from disk_coordinator import KINDS, configured

    try:
        repository = SCRIPTS.parent
        coordinator = configured(repository)
        if coordinator:
            for kind in KINDS:
                coordinator.enqueue_maintenance(repository, kind)
    except (OSError, RuntimeError, sqlite3.Error) as error:
        print(f"Voice check could not queue disk cleanup: {type(error).__name__}", file=sys.stderr)


def _disk_retry(summary: dict) -> dict:
    if not any(leg.get("reason") == "disk_space" for leg in summary["legs"].values()):
        return {}
    free = _free_space()
    if free >= MIN_FREE:
        return {}
    _request_disk_cleanup()
    return {"disk": {"free_before": free, "alerted": False}}


def _retry_watch(path: Path, state: dict, revision: str, base_url: str, now: float,
                 runtime_ready, checker, revision_fetcher) -> None:
    retry = state["retry"]
    if now < retry["due_at"]:
        return
    before = retry["summary"]
    disk = retry.get("disk")
    if disk:
        free = _free_space()
        if free < MIN_FREE:
            if not disk["alerted"]:
                state["alert_pending"] = {**before, "disk_recovered_bytes": max(0, free - disk["free_before"])}
                disk["alerted"] = True
                _write_state(path, state)
            return
    elif now >= retry["deadline_at"]:
        state.pop("retry")
        _record_watch_result(path, state, {**before, "retry_expired": True})
        return
    if not runtime_ready(revision):
        return
    unresolved = [name for name, leg in before["legs"].items() if leg["status"] != "passed"]
    state.pop("retry")
    state["last_result"] = {"status": "retry_started"}
    _write_state(path, state)
    result = checker("dev", base_url, revision, None, unresolved, False)
    legs = {**before["legs"], **result["legs"]}
    summary = {**result, "legs": legs, "retried": True,
               "passed": all(leg["status"] == "passed" for leg in legs.values())}
    try:
        served = revision_fetcher(base_url)
    except CheckError:
        if not summary["passed"]:
            # A later timer can send the result only if this is still the served revision.
            _record_watch_result(path, state, summary)
        raise
    if served != revision:
        state["last_result"] = {"status": "superseded"}
        _write_state(path, state)
    elif new_disk := _disk_retry(summary):
        state["retry"] = {**retry, "disk": disk or new_disk["disk"], "summary": _notice_summary(summary),
                          "due_at": now + RETRY_DELAY}
        _write_state(path, state)
    else:
        _record_watch_result(path, state, summary)


def dev_watch(state_path: Path = STATE_FILE, now=time.time, revision_fetcher=fetch_revision,
              checker=run_check, base_url: str = BASE_URLS["dev"], runtime_ready=dev_runtime_ready,
              pusher=push_failure) -> int:
    """Run each new revision and retry only unresolved legs while it is still served."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with (state_path.parent / "lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        revision = revision_fetcher(base_url)
        state = _load_state(state_path)
        checked = set(state.get("checked_revisions", []))
        prior = state.get("last_revision")
        if prior:
            checked.add(prior)
        if prior != revision and ("retry" in state or "alert_pending" in state):
            state.pop("retry", None)
            state.pop("alert_pending", None)
            state["last_result"] = {"status": "superseded"}
            _write_state(state_path, state)
        if "retry" in state:
            _retry_watch(state_path, state, revision, base_url, now(), runtime_ready, checker, revision_fetcher)
        if "alert_pending" in state:
            return _send_pending_alert(state_path, state, pusher)
        if revision in checked or not runtime_ready(revision):
            return 0
        checked.add(revision)
        state.update(checked_revisions=sorted(checked), last_revision=revision,
                     last_run_at=now(), last_result={"status": "started"})
        # Claim before spending provider credits. A killed run or a rollback
        # to a previously served revision must not repeat the same paid attempt.
        _write_state(state_path, state)
        summary = checker("dev", base_url, revision, None, list(LEGS), False)
        if summary["passed"]:
            _record_watch_result(state_path, state, summary)
            return 0
        finished = now()
        state["last_result"] = {"passed": False, "status": "waiting_to_retry",
                                "legs": {name: leg["status"] for name, leg in summary["legs"].items()}}
        state["retry"] = {"summary": _notice_summary(summary), "due_at": finished + RETRY_DELAY,
                          "deadline_at": finished + RETRY_WINDOW, **_disk_retry(summary)}
        _write_state(state_path, state)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--target", choices=["dev", "prod"], required=True)
    run.add_argument("--base-url")
    run.add_argument("--revision")
    run.add_argument("--out", type=Path)
    run.add_argument("--legs", default="signed-in,guest")
    run.add_argument("--no-push", action="store_true")
    sub.add_parser("dev-watch")
    args = parser.parse_args(argv)
    if args.command == "dev-watch":
        return dev_watch()
    legs = [leg.strip().replace("-", "_") for leg in args.legs.split(",") if leg.strip()]
    if not legs or any(leg not in LEGS for leg in legs):
        parser.error("--legs must be a list of signed-in, guest")
    try:
        summary = run_check(args.target, args.base_url, args.revision, args.out, legs, not args.no_push)
    except CheckError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
