#!/usr/bin/env python3
"""Opt-in DEV natural-language maps cutoff proof; never runs in CI.

Reuses a supplied disposable identity in a new private CLI state and Project.
The actual global CLI runs in cli_video_capture's real terminal. Default model
and provider routing stay untouched. Receipts contain public place facts only;
credentials and decrypted chat/embed snapshots remain private local files.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import cli_video_capture, sessions  # noqa: E402

API = "https://api.dev.openmates.org"
ZONE = ZoneInfo("Europe/Berlin")
UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


def private_json(path: Path, value: object) -> None:
    """Persist private local evidence without exposing account material."""
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        json.dump(value, stream, indent=2)


def ids(value: object) -> list[str]:
    """Decode ordinary list or legacy pipe-separated child references."""
    values = value.split("|") if isinstance(value, str) else value if isinstance(value, list) else []
    return [item for item in values if isinstance(item, str) and UUID.fullmatch(item)]


def cli(words: list[str], output: Path, label: str) -> dict:
    """Keep CLI JSON and error details private; never echo credentials."""
    result = subprocess.run(["openmates", "--api-url", API, *words, "--json"],
                            capture_output=True, text=True, timeout=120)
    private_json(output / f"{label}.json", {"stdout": result.stdout, "stderr": result.stderr})
    if result.returncode:
        raise RuntimeError(f"CLI {label} failed with exit {result.returncode}; private diagnostic retained")
    return json.loads(result.stdout)


def check_results(parents: list[dict], places: list[dict], cutoff: datetime) -> list[dict]:
    """Assert actual saved tool arguments and independent provider close timestamps."""
    assert parents, "The assistant did not execute maps.search"
    for parent in parents:
        value = parent.get("input")
        value = json.loads(value) if isinstance(value, str) else value
        assert isinstance(value, dict), "Saved maps tool input is missing"
        requests = value.get("requests", [value])
        assert isinstance(requests, list) and requests, "Saved maps requests are missing"
        for request in requests:
            assert request.get("openUntil") == cutoff.strftime("%H:%M"), "Natural-language cutoff was not propagated"
            assert request.get("openNow") is True, "Currently-open constraint was not propagated"
            assert request.get("openOn") in (None, cutoff.date().isoformat()), "Wrong local filter date"
            if cutoff.date() != datetime.now(ZONE).date():
                assert request.get("openOn") == cutoff.date().isoformat(), "Tomorrow cutoff needs its explicit date"
    assert places, "Empty maps results cannot pass the cutoff proof"
    checked = []
    for place in places:
        assert place.get("open_now") is True, "Returned place is not currently open"
        close = place.get("next_close_time")
        assert isinstance(close, str) and close, "Returned place lacks a known next closing time"
        closing = datetime.fromisoformat(close.replace("Z", "+00:00"))
        assert closing.tzinfo is not None, "Provider closing timestamp lacks a timezone"
        assert closing >= cutoff, "A returned place closes before the requested local cutoff"
        checked.append({"place_id": place.get("place_id"), "name": place.get("name"),
                        "closing_time_local": closing.astimezone(ZONE).isoformat(),
                        "opening_hours": place.get("opening_hours")})
    return checked


# contract-test: direct surface=cli assertions=maps-search.compatibility.regular-search
# Live inference is deliberately DEV-only; the deterministic unit and CI checks remain separate.
def test_maps_closing_time_live() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-state", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--runtime-commit", required=True)
    parser.add_argument("--runtime-health-receipt", type=Path, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--display-number", type=int, default=187)
    parser.add_argument("--allow-dev-inference", action="store_true")
    args = parser.parse_args()
    assert args.allow_dev_inference and not os.environ.get("CI"), "Explicit DEV-only inference opt-in required"
    assert args.output.resolve().is_relative_to(Path("/tmp")), "Proof state must stay outside the repository"
    assert not args.output.exists(), "Use a new private proof output; preserve earlier attempts"
    ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", args.revision, args.runtime_commit],
                              cwd=ROOT, capture_output=True)
    assert ancestry.returncode == 0, "Runtime source does not include the published fix"
    health = args.runtime_health_receipt.read_bytes()
    assert args.runtime_commit.encode() in health and b"healthy" in health.lower(), "Source/health receipt is missing"
    # Credentials are read only in this process, solely to validate identity ownership
    # and ensure none reached the captured terminal. No login/reset/account cycling.
    from dotenv import dotenv_values
    credentials = dotenv_values(args.credentials)
    slots = [re.fullmatch(r"OPENMATES_TEST_ACCOUNT_(\d+)_EMAIL", key) for key in credentials]
    slots = [match.group(1) for match in slots if match]
    assert len(slots) == 1, "Expected one supplied disposable identity"
    source_session = json.loads((args.source_state / "session.json").read_text())
    assert source_session.get("apiUrl") == API and source_session.get("cookies"), "Supplied DEV session is missing"
    args.output.mkdir(mode=0o700)
    state = args.output / "state"
    shutil.copytree(args.source_state, state)
    state.chmod(0o700)
    for name in ("OPENMATES_API_KEY", "CODEX_THREAD_ID"):
        os.environ.pop(name, None)
    os.environ.update(OPENMATES_STATE_DIR=str(state), OPENMATES_PROFILE="", OPENMATES_API_URL=API)
    owner = f"repository-session-{args.session}"
    lease = f"maps-cutoff-{uuid.uuid4().hex}"
    resources = {f"playwright-account:{slots[0]}"}
    sessions.acquire_test_resource_lease(lease, owner, resources, timeout=0, poll=1, mode="exclusive")
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(sessions.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
            sessions.renew_test_resource_lease(lease, owner, resources, mode="exclusive")

    renewal = threading.Thread(target=renew, daemon=True)
    renewal.start()
    now = datetime.now(ZONE)
    cutoff = (now + timedelta(minutes=105)).replace(minute=0, second=0, microsecond=0)
    assert cutoff > now + timedelta(minutes=40), "Cutoff must be later than current local time"
    prompt = (f"Find up to 3 currently open cafes or cafe-bars in Berlin Kreuzberg or Friedrichshain "
              f"that stay open until at least {cutoff:%H:%M} Berlin local time on {cutoff:%Y-%m-%d}. "
              "Only return places with confirmed opening hours covering that cutoff, and include their closing times.")
    receipt = {"revision": args.revision, "runtime_commit": args.runtime_commit,
               "runtime_health_sha256": hashlib.sha256(health).hexdigest(), "environment": "dev",
               "surface": "cli", "routing": "automatic", "model_or_provider_override": False,
               "prompt": prompt, "started_local": now.isoformat(), "cutoff_local": cutoff.isoformat(),
               "checks": {}, "status": "failed"}
    project_id = chat_id = None
    capture = None
    try:
        project = cli(["projects", "create", f"Maps cutoff proof {uuid.uuid4().hex[:8]}",
                       "--write-policy", "always_ask", "--personal"], args.output, "project")
        project_id = project.get("projectId") or project.get("project_id") or project.get("id")
        assert isinstance(project_id, str) and UUID.fullmatch(project_id), "Disposable Project ID missing"
        slug = "maps-cutoff-" + uuid.uuid4().hex[:10]
        capture = cli_video_capture.capture_cli_video(
            argv=["openmates", "--api-url", API, "chats", "new", prompt, "--slug", slug,
                  "--project", project_id, "--no-task-update-jobs"],
            output_dir=args.output / "terminal", target_environment=API,
            classification="maps_closing_time_real_inference", display_number=args.display_number,
            timeout_seconds=600,
        )
        receipt["capture"] = capture
        transcript = Path(capture["transcript_path"]).read_text(errors="replace")
        assert not any(value and value in transcript for value in credentials.values()), "Credential appeared in private capture"
        assert capture["exit_status"] == 0, "Natural-language CLI request failed"
        chat = cli(["chats", "show", slug, "--all"], args.output, "chat")
        chat_id = chat.get("chat", {}).get("id")
        assert isinstance(chat_id, str) and UUID.fullmatch(chat_id), "Saved proof chat ID missing"
        assistants = [message for message in chat.get("messages", []) if message.get("role") == "assistant"]
        assert assistants, "No persisted assistant answer"
        receipt["assistant_models"] = [message.get("modelName") for message in assistants]
        queue = list(dict.fromkeys(ref for message in assistants for ref in ids(message.get("embedIds"))))
        for message in assistants:
            queue.extend(re.findall(r'(?:embed:|"embed_id"\s*:\s*")([0-9a-f-]{36})', message.get("content", "")))
        seen, parents, place_records = set(), [], {}
        while queue:
            embed_id = queue.pop(0)
            if embed_id in seen:
                continue
            seen.add(embed_id)
            assert len(seen) <= 40, "Unbounded result graph"
            embed = cli(["embeds", "show", embed_id, "--chat", chat_id], args.output, f"embed-{len(seen)}")
            content = embed.get("content") or {}
            queue.extend(ids(content.get("parent_embed_id")))
            if ((embed.get("appId") or content.get("app_id")) == "maps"
                    and (embed.get("skillId") or content.get("skill_id")) == "search" and content.get("input")):
                parents.append(content)
                queue.extend(ids(content.get("embed_ids")))
            elif content.get("place_id"):
                place_records[embed_id] = content
        returned_ids = list(dict.fromkeys(ref for parent in parents for ref in ids(parent.get("embed_ids"))))
        assert returned_ids and all(ref in place_records for ref in returned_ids), "Incomplete saved result graph"
        checked = check_results(parents, [place_records[ref] for ref in returned_ids], cutoff)
        receipt.update(maps_request_inputs=[parent["input"] for parent in parents],
                       result_count=len(checked), results_in_returned_order=checked,
                       checks={"natural_language_cutoff_propagated": True, "nonempty_results": True,
                               "every_known_close_at_or_after_cutoff": True, "currently_open": True}, status="passed")
        print(f"PASS: maps.search propagated {cutoff:%H:%M}; {len(checked)} nonempty, known-closing results meet the local cutoff.")
        for row in checked:
            print(f"  {row['name']}: closes {row['closing_time_local']}")
        cli(["chats", "delete", chat_id, "--yes"], args.output, "cleanup-chat")
        cli(["projects", "delete", project_id, "--confirm", project_id, "--personal"], args.output, "cleanup-project")
        receipt["cleanup"] = True
    except Exception as exc:
        receipt.update(status="failed", failure_type=type(exc).__name__, failure=str(exc)[:300])
        print(f"FAIL: {type(exc).__name__}; private receipt retained, no account changes attempted.")
    finally:
        receipt.update(project_id=project_id, chat_id=chat_id, finished_utc=datetime.now(timezone.utc).isoformat())
        stop.set()
        renewal.join(timeout=1)
        sessions.release_test_resource_lease(lease)
        private_json(args.output / "receipt.json", receipt)
    if capture and not any(value and value in Path(capture["transcript_path"]).read_text(errors="replace") for value in credentials.values()):
        try:
            receipt["response_media"] = cli_video_capture.publish_response_media(
                Path(capture["video_path"]), classification="maps_closing_time_real_inference")
        except cli_video_capture.CliCaptureError as exc:
            receipt["evidence_upload_error"] = str(exc)
        private_json(args.output / "receipt.json", receipt)
    raise SystemExit(0 if receipt["status"] == "passed" else 1)


if __name__ == "__main__":
    test_maps_closing_time_live()
