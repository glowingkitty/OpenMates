#!/usr/bin/env python3
# contract-test-file: supporting surface=cli assertions=app-skills.execution.registered-validated,app-skills.output.external-semantic
"""Real caption retrieval and summary check, exclusively on dev with isolated CLI state.

First log in with scripts/openmates_cli_test_account.mjs using a temporary
OPENMATES_STATE_DIR, or explicitly authorize the existing personal dev login.
The script records actual product CLI commands in graphical terminals and uses
automatic model routing.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

URL = "https://media.ccc.de/v/39c3-a-post-american-enshittification-resistant-internet"
NO_CAPTIONS = "https://media.ccc.de/v/37c3-other-59123-from-hacker-to-furry"
API = "https://api.dev.openmates.org"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--use-default-dev-login", action="store_true",
                        help="Use the locally logged-in personal dev account when explicitly authorized.")
    args = parser.parse_args()
    assert args.use_default_dev_login or os.environ.get("OPENMATES_STATE_DIR"), "Use isolated CLI state or explicit default-dev-login authorization"
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def cli(*parts, timeout=180, expected_error=None):
        command = ["openmates", "--api-url", API, *parts, "--json"]
        recording = "summary-recording" if parts[:2] == ("chats", "new") else "transcript-recording" if parts[:2] == ("apps", "videos") and not expected_error else None
        if recording:
            directory = args.output_dir / recording
            result = subprocess.run([
                "python3", "scripts/cli_video_capture.py", "--output-dir", str(directory),
                "--target-environment", API, "--classification", "media_ccc_transcript_real_dev",
                "--display-number", "224", "--timeout-seconds", str(timeout), "--no-response-media",
                "--", *command,
            ], capture_output=True, text=True, timeout=timeout + 90)
            (args.output_dir / f"{recording}.log").write_text(result.stdout + "\n" + result.stderr)
            if result.returncode:
                raise RuntimeError(f"Recorded CLI command failed; inspect {recording}.log")
            # PTY evidence merges stderr progress with stdout. Decode the real
            # JSON object, preserving the original terminal recording unchanged.
            output = (directory / "command-output.txt").read_text()
            for match in re.finditer(r"(?m)^\{", output):
                try:
                    value, _ = json.JSONDecoder().raw_decode(output[match.start():])
                    return value
                except json.JSONDecodeError:
                    continue
            raise AssertionError("Recorded CLI command did not return JSON")
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if expected_error:
            assert result.returncode != 0 and expected_error in result.stderr, "CLI must report the expected skill failure"
            return
        if result.returncode:
            (args.output_dir / "cli-failure.log").write_text(result.stderr)
            raise RuntimeError(f"CLI command {parts[0]} {parts[1]} failed (exit {result.returncode}); stderr retained privately")
        return json.loads(result.stdout)

    print("Real dev check: videos.get_transcript / media.ccc.de", flush=True)
    print(f"Deployed revision: {args.revision}", flush=True)
    caption_result = cli("apps", "videos", "get_transcript", "--input", json.dumps({"requests": [{"id": "ccc", "url": URL, "languages": ["en"]}]}))
    data = caption_result["data"]
    caption = data["results"][0]["results"][0]
    assert data["provider"] == "media.ccc.de"
    assert caption["provider"] == "media.ccc.de" and caption["language"] == "en"
    assert caption["word_count"] > 5000
    assert re.search(r"\[\d{2}:\d{2}:\d{2}\.\d{3}\]", caption["transcript"])
    print(f"PASS: actual skill returned {caption['word_count']} English words with timestamps.", flush=True)
    cli("apps", "videos", "get_transcript", "--input", json.dumps({"requests": [{"url": NO_CAPTIONS}]}),
        expected_error="No published captions")
    print("PASS: original talk reports no published captions.", flush=True)

    project = cli("projects", "create", f"CCC captions validation {uuid.uuid4().hex[:8]}", "--write-policy", "always_ask")
    project_id = project.get("project_id") or project.get("projectId") or project.get("project", {}).get("project_id")
    assert project_id, "Disposable Project creation must return its ID"
    print("Summarizing the requested 39C3 talk through the transcript skill (automatic routing)...", flush=True)
    prompt = f"Use the videos get_transcript skill to read the published captions for {URL}, then summarize the talk in five concise English bullet points. Base the summary on the transcript, not the page description."
    response = cli("chats", "new", prompt, "--project", project_id, "--no-task-update-jobs", timeout=360)
    (args.output_dir / "summary-response.json").write_text(json.dumps(response, indent=2))
    assert response.get("status") == "completed"
    assert len(response.get("assistant", "").split()) > 50
    chat_id = response["chatId"]
    chat = cli("chats", "show", chat_id, "--all")
    (args.output_dir / "summary-chat.json").write_text(json.dumps(chat, indent=2))
    embed_ids = {embed_id for message in chat["messages"] for embed_id in message.get("embedIds", [])}
    # Include inline references if a client has not hydrated embedIds yet.
    embed_ids.update(re.findall(r"embed:([0-9a-f-]{36})", response["assistant"]))
    embeds = [cli("embeds", "show", embed_id) for embed_id in sorted(embed_ids)]
    (args.output_dir / "summary-embeds.json").write_text(json.dumps(embeds, indent=2))
    transcripts = [embed for embed in embeds if embed.get("content", {}).get("app_id") == "videos"
                   and embed.get("content", {}).get("skill_id") == "get_transcript"]
    assert transcripts, "Summary must contain real videos.get_transcript execution evidence"
    def has_captions(value):
        if isinstance(value, dict):
            if value.get("url") == URL and isinstance(value.get("transcript"), str) and len(value["transcript"]) > 1000:
                return True
            return any(has_captions(item) for item in value.values())
        if isinstance(value, list):
            return any(has_captions(item) for item in value)
        if isinstance(value, str) and value.startswith(("[", "{")):
            try:
                return has_captions(json.loads(value))
            except json.JSONDecodeError:
                return False
        return False

    assert any(has_captions(embed) for embed in transcripts), "The summary's saved skill embed must contain the actual talk captions"
    print(response["assistant"], flush=True)
    print(f"PASS: real summary used videos.get_transcript; model={response.get('modelName')}", flush=True)
    receipt = {"passed": True, "revision": args.revision, "url": URL, "words": caption["word_count"],
               "project_id": project_id, "chat_id": chat_id, "model": response.get("modelName"),
               "transcript_skill_embeds": len(transcripts), "automatic_routing": True}
    (args.output_dir / "receipt.json").write_text(json.dumps(receipt, indent=2))
    cli("projects", "archive", project_id)


if __name__ == "__main__":
    main()
