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
*-with-audio.webm with audible sound (> -50 dB) exists. Any failed leg exits 1 and
pushes the owner (unless --no-push).

  python3 scripts/voice_post_update_check.py run --target dev
  python3 scripts/voice_post_update_check.py run --target prod --legs guest
  python3 scripts/voice_post_update_check.py dev-watch     # systemd timer entry
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

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


def evaluate_leg(out: Path, loudness=_loudness) -> dict:
    """Judge a leg from its receipt.json and videos; returns {status, video, error}."""
    path = out / "receipt.json"
    if not path.is_file():
        return {"status": "failed", "video": None, "error": "no receipt written"}
    receipt = json.loads(path.read_text())
    video = find_video(out, receipt)
    error = None
    if receipt.get("status") != "passed":
        error = f"receipt status {receipt.get('status')}: {receipt.get('error_code', 'no reason')}"
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
    return {"status": "failed" if error else "passed", "video": str(video) if video else None, "error": error}


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
        _write_receipt(out, "failed", error_code=f"playwright exit {code}")


def run_signed_in_dev(revision: str, out: Path) -> None:
    """Dev signed-in call through the existing runner with a throwaway account."""
    command = [sys.executable, str(SCRIPTS / "voice_call_web_real_test.py"), "--session", SESSION_LABEL,
               "--revision", revision, "--output-dir", str(out), "--personal-dev-test-account",
               "--throwaway-account", "--allow-paid-dev-inference", "--scenario", SCENARIO]
    subprocess.run(command, check=False, timeout=RUN_TIMEOUT_SECONDS * 3)


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
        return {"status": "failed", "video": None, "error": f"{type(exc).__name__}: {exc}"[:300]}


def push_failure(target: str, summary: dict) -> None:
    """One short plain push naming the first failed leg."""
    import agent_question
    import discord_webhook
    from pending_work_gate import canonical_root

    name, leg = next((n, leg) for n, leg in summary["legs"].items() if leg["status"] != "passed")
    label = "guest" if name == "guest" else "signed-in"
    reason = (leg.get("error") or "unknown").split(":")[-1].strip()[:40]
    when = "after deploy" if target == "dev" else "after update"
    message = f"{target.capitalize()} voice check failed {when}: {label} call, {reason}."[:108]
    root = canonical_root()
    agent_question.deliver(agent_question.webhook(root), message, discord_webhook.post_message)
    agent_question.record_push(root, message, time.time(), title="Voice check", source=PUSH_SOURCE)


def run_check(target: str, base_url: str | None, revision: str | None, out: Path | None,
              legs: list[str], push: bool = True, leg_runner=run_leg, pusher=push_failure) -> dict:
    """Run the legs, write summary.json, push on failure."""
    base = (base_url or BASE_URLS[target]).rstrip("/")
    revision = revision or fetch_revision(base)
    out = out or Path(tempfile.mkdtemp(prefix=f"voice-check-{target}-", dir="/tmp"))
    results = {name: leg_runner(name, target, base, revision, out / name) for name in legs}
    summary = {"target": target, "revision": revision, "legs": results,
               "passed": all(leg["status"] == "passed" for leg in results.values()),
               "finished_at": datetime.now(UTC).isoformat()}
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    if not summary["passed"] and push:
        pusher(target, summary)
    return summary


# --- dev-watch -----------------------------------------------------------------------


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def dev_watch(state_path: Path = STATE_FILE, now=time.time, revision_fetcher=fetch_revision,
              checker=run_check, base_url: str = BASE_URLS["dev"]) -> int:
    """Run the dev check for each observed served revision, without overlap."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with (state_path.parent / "lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        revision = revision_fetcher(base_url)
        state = _load_state(state_path)
        if revision == state.get("last_revision"):
            return 0
        started = now()
        summary = checker("dev", base_url, revision, None, list(LEGS))
        legs = {name: leg["status"] for name, leg in summary["legs"].items()}
        state_path.write_text(json.dumps({"last_revision": revision, "last_run_at": started,
                                          "last_result": {"passed": summary["passed"], "legs": legs}}))
        return 0 if summary["passed"] else 1


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
