#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference proof for the design.embroidery app skill.

One CLI chat: turn 1 asks for a simple flat three-colour SVG logo, turn 2 asks
to make it ready for the embroidery machine at 9 cm width. The saved chat's
embeds must hold a finished design.embroidery result with the five machine
files (dst, pes, exp, jef, vp3), a stitch count above zero, a width close to
90 mm and a non-empty thread list.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/design_embroidery_real_test.py --session ID --revision FULL_SHA \
    --state-dir /tmp/design-embroidery-state-UNIQUE \
    --receipt /tmp/design-embroidery-proof/receipt.json \
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI. Receipts stay outside the repository. Only this invocation's
chat and Project are deleted, also on failure.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from code_run_real_test import (
    ROOT, command, delete_owned_chat, personal_test_environment, personal_test_leases, require_runtime_revision,
)
from personal_dev_draft_guard import DraftGuard, DraftGuardError, record_leftovers
from verify_chat_sidebar_title_live import safe_failure
from workflow_schedule_real_test import API_URL, ProofError, sessions, write_receipt

MODEL = "@Gemini-3.8-Flash"
FORMATS = ("dst", "pes", "exp", "jef", "vp3")
UUID = r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"
LOGO_PROMPT = (f"{MODEL} Create a simple flat three-colour logo of a fox head as an SVG graphic. "
               "No gradients, no text, no outlines thinner than a few millimetres.")
EMBROIDERY_PROMPT = f"{MODEL} Make this ready for our embroidery machine, 9 cm wide."


def chat_embed_ids(shown: dict) -> list[str]:
    """Embed ids referenced by messages of a ``chats show --all --json`` payload."""
    found: list[str] = []
    for message in shown.get("messages", []):
        if not isinstance(message, dict):
            continue
        found.extend(str(ref) for ref in message.get("embedIds") or [])
        found.extend(re.findall(rf'(?:embed:|"embed_id"\s*:\s*")({UUID})', str(message.get("content") or "")))
    return list(dict.fromkeys(found))


def collect_embeds(cli: str, chat_id: str, seeds: list[str]) -> list[dict]:
    """Read the embed graph (parents list children in content.embed_ids), bounded."""
    queue, seen, embeds = list(seeds), set(), []
    while queue:
        embed_id = queue.pop(0)
        if embed_id in seen:
            continue
        seen.add(embed_id)
        if len(seen) > 40:
            raise ProofError("embed_graph_unbounded")
        embed = command(cli, ["embeds", "show", embed_id, "--chat", chat_id, "--personal"])
        if not isinstance(embed, dict):
            raise ProofError("embed_shape_unexpected")
        embed.setdefault("embedId", embed_id)
        embeds.append(embed)
        content = embed.get("content") if isinstance(embed.get("content"), dict) else {}
        for key in ("embed_ids", "embedIds"):
            queue.extend(str(ref) for ref in content.get(key) or [])
    return embeds


def embroidery_results(embeds: list[dict]) -> list[dict]:
    """Embeds whose content carries an embroidery file set (the design-embroidery child)."""
    results = []
    for embed in embeds:
        content = embed.get("content") if isinstance(embed.get("content"), dict) else {}
        files = content.get("files")
        if isinstance(files, dict) and "stitch_count" in content and any(key in files for key in FORMATS):
            results.append({"embed_id": embed.get("embedId"), "status": content.get("status") or embed.get("status"),
                            "content": content})
    return results


def normalise(name: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def verify(shown: dict, embeds: list[dict]) -> dict:
    """Return the numbers to record, or raise a ProofError naming what is missing."""
    assistants = [m for m in shown.get("messages", []) if isinstance(m, dict) and m.get("role") == "assistant"]
    if not assistants:
        raise ProofError("assistant_reply_missing")
    models = [str(m.get("modelName") or "") for m in assistants]
    if any("gemini38flash" not in normalise(model) for model in models):
        raise ProofError("assistant_model_mismatch")
    results = embroidery_results(embeds)
    if not results:
        raise ProofError("embroidery_result_embed_missing")
    finished = [r for r in results if r["status"] == "finished"]
    if not finished:
        raise ProofError("embroidery_result_not_finished")
    content = finished[-1]["content"]
    missing = [fmt for fmt in FORMATS if not content["files"].get(fmt)]
    if missing:
        raise ProofError("embroidery_files_missing_" + "_".join(missing))
    stitches, width, threads = content.get("stitch_count"), content.get("width_mm"), content.get("threads")
    if not isinstance(stitches, int) or stitches <= 0:
        raise ProofError("embroidery_stitch_count_invalid")
    if not isinstance(width, (int, float)) or abs(width - 90) > 4.5:
        raise ProofError("embroidery_width_not_90mm")
    if not isinstance(threads, list) or not threads:
        raise ProofError("embroidery_threads_missing")
    return {"embed_id": finished[-1]["embed_id"], "files": sorted(content["files"]), "stitch_count": stitches,
            "width_mm": width, "height_mm": content.get("height_mm"), "thread_count": len(threads),
            "thread_changes": content.get("thread_changes"), "assistant_models": models}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--revision", required=True, help="Exact deployed dev SHA")
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--cli", default="openmates", help="Installed global CLI executable")
    parser.add_argument("--personal-dev-test-account", action="store_true", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=420, help="Response wait per turn")
    parser.add_argument("--allow-paid-dev-inference", action="store_true")
    args = parser.parse_args()
    if any(os.getenv(key) for key in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI")):
        parser.error("real inference is dev-only and cannot run in CI")
    if not args.allow_paid_dev_inference or not 60 <= args.timeout_seconds <= 900:
        parser.error("explicit paid-dev opt-in and a 60-900 second timeout required")
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be the full deployed dev SHA")
    state, receipt_path = args.state_dir.resolve(), args.receipt.resolve()
    if state == Path("/tmp") or not state.is_relative_to(Path("/tmp")) or state.exists():
        parser.error("--state-dir must be a fresh path below /tmp")
    if not receipt_path.is_relative_to(Path("/tmp")) or receipt_path.is_relative_to(state) \
            or receipt_path.is_relative_to(ROOT):
        parser.error("private receipt must be below /tmp and outside CLI state/repository")
    cli = shutil.which(args.cli)
    if not cli:
        parser.error("installed global openmates executable missing")
    slug = f"design-embroidery-proof-{uuid4().hex[:12]}"
    receipt: dict = {"status": "started", "target": API_URL, "session": args.session, "model": MODEL,
                     "deployed_revision": args.revision, "started_at": datetime.now(UTC).isoformat(),
                     "slug": slug, "cleanup": {}}
    leases, project_id, chat_id, created_state, draft_guard = [], None, None, False, None
    stop, errors = threading.Event(), []
    heartbeat = None
    old_umask = os.umask(0o077)
    try:
        state.mkdir(mode=0o700)
        created_state = True
        receipt_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.environ.update(OPENMATES_STATE_DIR=str(state), OPENMATES_PROFILE="", OPENMATES_API_URL=API_URL)
        for key in ("OPENMATES_API_KEY", "OPENMATES_CLI_HOME", "OPENMATES_CLI_SESSION_PATH"):
            os.environ.pop(key, None)
        login_env = personal_test_environment()
        leases = personal_test_leases(args.session)
        require_runtime_revision(args.revision)

        def renew() -> None:
            while not stop.wait(sessions.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
                for lease_id, owner, resources, mode in leases:
                    try:
                        sessions.renew_test_resource_lease(lease_id, owner, resources, mode=mode)
                    except RuntimeError:
                        errors.append("lease_renewal_failed")
                        return

        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        login = subprocess.run(["node", str(ROOT / "scripts/openmates_cli_test_account.mjs"), "login",
                                "--slot", "", "--api-url", API_URL], cwd=ROOT, env=login_env,
                               capture_output=True, text=True, check=False, timeout=180)
        if login.returncode:
            receipt["bootstrap_failure"] = safe_failure(login.stderr)
            raise ProofError("personal_account_bootstrap_failed")
        # The personal account is shared: a run must not leave drafts there.
        try:
            draft_guard = DraftGuard.start(cli, api_url=API_URL)
        except DraftGuardError as exc:
            raise ProofError(str(exc)) from exc
        project = command(cli, ["projects", "create", f"Embroidery proof {uuid4().hex[:10]}",
                               "--write-policy", "apply_and_show", "--personal"])
        project_id = (project.get("project") or {}).get("project_id") if isinstance(project, dict) else None
        if not isinstance(project_id, str) or not project_id:
            raise ProofError("disposable_project_missing")
        receipt["project_id"] = project_id

        timeout = args.timeout_seconds
        sent = command(cli, ["chats", "new", LOGO_PROMPT, "--project", project_id, "--slug", slug, "--personal",
                             "--response-timeout-seconds", str(timeout)], timeout=timeout + 30)
        chat_id = sent.get("chatId") if isinstance(sent, dict) else None
        if not isinstance(chat_id, str) or not chat_id:
            raise ProofError("created_chat_id_missing")
        receipt["chat_id"] = chat_id
        if sent.get("status") == "waiting_for_user":
            raise ProofError("assistant_action_approval_required")
        if errors:
            raise ProofError(errors[0])
        sent = command(cli, ["chats", "send", "--chat", chat_id, EMBROIDERY_PROMPT, "--personal",
                             "--response-timeout-seconds", str(timeout)], timeout=timeout + 30)
        if isinstance(sent, dict) and sent.get("status") == "waiting_for_user":
            raise ProofError("assistant_action_approval_required")

        shown = command(cli, ["chats", "show", chat_id, "--all", "--personal"])
        # Syncs encrypted embed metadata so the embed reads below can resolve.
        command(cli, ["chats", "list", "--personal"])
        embeds = collect_embeds(cli, chat_id, chat_embed_ids(shown))
        receipt["embed_count"] = len(embeds)
        receipt.update(verify(shown, embeds))
        require_runtime_revision(args.revision)
        receipt["status"] = "passed"
    except BaseException as exc:
        receipt["status"] = "failed"
        receipt["error_code"] = str(exc) if isinstance(exc, ProofError) else type(exc).__name__
    finally:
        try:
            owned = chat_id
            if not owned:
                shown = command(cli, ["chats", "show", slug, "--personal"])
                owned = shown.get("chat", {}).get("id") if isinstance(shown, dict) else None
            if owned:
                delete_owned_chat(cli, owned)
                receipt["cleanup"]["chat"] = "deleted"
        except (ProofError, subprocess.TimeoutExpired, json.JSONDecodeError):
            # A chat that was never created cannot be shown; only flag when one existed.
            if chat_id:
                receipt["cleanup"]["chat"] = "failed"
                receipt["status"] = "failed"
        if project_id:
            try:
                command(cli, ["projects", "delete", project_id, "--confirm", project_id, "--personal"])
                receipt["cleanup"]["project"] = "deleted"
            except (ProofError, subprocess.TimeoutExpired):
                receipt["cleanup"]["project"] = "failed"
                receipt["status"] = "failed"
        record_leftovers(receipt, draft_guard)
        stop.set()
        if heartbeat:
            heartbeat.join(timeout=2)
        for lease_id, *_ in reversed(leases):
            try:
                sessions.release_test_resource_lease(lease_id)
            except RuntimeError:
                receipt["cleanup"]["lease"] = "failed"
                receipt["status"] = "failed"
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_receipt(receipt_path, receipt)
        if created_state:
            shutil.rmtree(state)
        os.umask(old_umask)
        print(f"Design embroidery real proof {receipt['status']}; receipt: {receipt_path}", flush=True)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
