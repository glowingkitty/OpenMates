#!/usr/bin/env python3
"""Opt-in dev CLI proof for a selected Workflow clarification handoff.

Uses an existing authenticated disposable CLI state. Creates one disabled seed,
sends one AI chat turn, and deletes only the seed and its chat.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid


# contract-test: direct surface=cli assertions=focus-modes.activation,focus-modes.full-instruction,workflows.authoring.compact-plan,workflows.access.boundaries
def test_workflow_clarification() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--node", required=True)
    parser.add_argument("--cli", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--allow-inference", action="store_true")
    args = parser.parse_args()
    if not args.allow_inference or os.getenv("CI"):
        raise SystemExit("Explicit dev inference opt-in required; never run in CI")
    if not args.state_dir.is_dir():
        raise SystemExit("Existing authenticated state directory required")

    def call(words: list[str], *, timeout: int = 120, json_output: bool = True):
        with (args.state_dir / ".cli-command.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            start = time.perf_counter()
            result = subprocess.run(
                [args.node, args.cli, "--api-url", "https://api.dev.openmates.org", *words, "--json"],
                env={**os.environ, "OPENMATES_STATE_DIR": str(args.state_dir), "OPENMATES_PROFILE": ""},
                capture_output=True, text=True, timeout=timeout,
            )
            seconds = round(time.perf_counter() - start, 3)
        if result.returncode:
            raise RuntimeError(f"CLI {' '.join(words[:2])} failed: {result.stderr[-500:]}")
        return (json.loads(result.stdout) if json_output else result.stdout), seconds

    def save(receipt: dict) -> None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(receipt, output, indent=2)

    def nested_has(value, target: str) -> bool:
        if isinstance(value, dict):
            return any(nested_has(item, target) for item in value.values())
        if isinstance(value, list):
            return any(nested_has(item, target) for item in value)
        return isinstance(value, str) and target in value

    nonce = uuid.uuid4().hex[:8]
    title = f"Clarify Voice Edit QA {nonce}"
    slug = f"clarify-voice-edit-qa-{nonce}"
    graph = {"version": 2, "trigger_node_id": "trigger", "nodes": [
        {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {
            "type": "daily", "time": "07:00", "timezone": "Europe/Berlin"}}},
        {"id": "weather", "type": "app_skill_action", "config": {"app_id": "weather", "skill_id": "forecast",
            "input": {"location": "Berlin", "start_date": {"$date": "tomorrow", "format": "date"},
                      "end_date": {"$date": "tomorrow", "format": "date"}}}},
        {"id": "send", "type": "send_chat_message", "config": {
            "title": "Berlin daily weather", "message": "Tomorrow's Berlin forecast: {{steps.weather.forecast_day}}",
            "blocks": [{"id": "forecast", "source": "$nodes.weather.output.forecast_day"}]}}],
        "edges": [{"from": "trigger", "to": "weather"}, {"from": "weather", "to": "send"}]}
    receipt = {"revision": args.revision, "title": title, "chat_slug": slug,
               "seed_graph": graph, "chat_turns": 0, "checks": {}, "cleanup": {}}
    workflow_id = chat_id = None
    try:
        before, _ = call(["whoami"])
        receipt["credits_before"] = before.get("credits")
        created, receipt["create_wall_seconds"] = call([
            "workflows", "create", "--title", title, "--graph", json.dumps(graph, separators=(",", ":"))])
        workflow_id = created["id"]
        receipt["workflow_id"] = workflow_id
        receipt["created_workflow"] = created
        assert created["enabled"] is False and created["status"] == "disabled"
        instruction = ("@focus:workflows:clarify_workflows Also add searches for AI meetups and queer meetups.\n\n"
                       f"Workflow editor context: I was changing my existing workflow {json.dumps(title)} "
                       f"(ID {workflow_id}). Keep this workflow as the target. Clarify the change before "
                       "carrying out any of the workflow's future search or delivery actions.")
        receipt["exact_chat_instruction"] = instruction
        save(receipt)

        receipt["chat_turns"] = 1
        response, receipt["chat_wall_seconds"] = call([
            "chats", "send", "--slug", slug, instruction, "--no-task-update-jobs",
            "--response-timeout-seconds", "120"], timeout=180)
        chat_id = response["chatId"]
        assistant = response.get("assistant", "")
        receipt.update(chat_id=chat_id, chat_result=response)
        history, _ = call(["chats", "show", chat_id, "--all"])
        receipt["chat_history"] = history
        call(["chats", "list"])  # Sync encrypted embed metadata before CLI embed reads.
        embed_ids = list(dict.fromkeys(embed_id for message in history.get("messages", [])
                                       for embed_id in message.get("embedIds", [])))
        embeds = []
        for embed_id in embed_ids:
            embed, _ = call(["embeds", "show", embed_id])
            embeds.append(embed)
        receipt["chat_embeds"] = embeds
        after_workflow, _ = call(["workflows", "show", workflow_id])
        receipt["result_workflow"] = after_workflow
        listed, _ = call(["workflows", "list"])
        workflows = listed.get("workflows", []) if isinstance(listed, dict) else listed
        matching_ids = [item.get("id") for item in workflows if item.get("title") == title]
        after, _ = call(["whoami"])
        receipt["credits_after"] = after.get("credits")
        if isinstance(before.get("credits"), int) and isinstance(after.get("credits"), int):
            receipt["actual_credit_debit"] = before["credits"] - after["credits"]

        calls = [json.loads(raw) for raw in re.findall(r"```json\s*(\{[^`]+\})\s*```", assistant)]
        skills = [(item.get("app_id"), item.get("skill_id")) for item in calls
                  if item.get("type") == "app_skill_use"]
        search_embeds = [embed for embed in embeds if embed.get("appId") == "workflows"
                         and embed.get("skillId") == "search"]
        activation = any("focus-mode-activation" in str(embed.get("type", "")) and
                         nested_has(embed, "workflows-clarify_workflows") for embed in embeds)
        selected_loaded = any(nested_has(embed.get("content"), workflow_id) for embed in search_embeds)
        question_text = re.sub(r"```[\s\S]*?```", "", assistant)
        questions = question_text.count("?")
        receipt["checks"] = {
            "focus_activated": activation,
            "selected_workflow_loaded": selected_loaded,
            "only_workflows_search": bool(skills) and all(skill == ("workflows", "search") for skill in skills),
            "no_future_action_skills": not any(app in ("events", "calendar", "maps") for app, _ in skills),
            "original_id_referenced": workflow_id in assistant,
            "original_graph_unchanged": after_workflow.get("graph") == created.get("graph"),
            "no_copy": matching_ids == [workflow_id],
            "single_question": questions == 1,
        }
        receipt.update(app_skill_calls=skills, question_count=questions, matching_title_ids=matching_ids,
                       search_result_counts=[(embed.get("content") or {}).get("result_count") for embed in search_embeds])
        save(receipt)
    except Exception as error:
        receipt["error"] = str(error)
    finally:
        if not chat_id:
            try:
                listed, _ = call(["chats", "list"])
                chats = listed.get("chats", []) if isinstance(listed, dict) else listed
                chat_id = next((item["id"] for item in chats if item.get("slug") == slug), None)
            except Exception as error:
                receipt["cleanup"]["chat_lookup_error"] = str(error)
        for kind, object_id in (("chats", chat_id), ("workflows", workflow_id)):
            if not object_id:
                continue
            try:
                call([kind, "delete", object_id, "--yes"], json_output=False)
                receipt["cleanup"][f"{kind}_deleted"] = True
                try:
                    call([kind, "show", object_id])
                    receipt["cleanup"][f"{kind}_absence_verified"] = False
                except RuntimeError as error:
                    receipt["cleanup"][f"{kind}_absence_verified"] = "not found" in str(error).lower()
            except Exception as error:
                receipt["cleanup"][f"{kind}_error"] = str(error)
        save(receipt)
    print(json.dumps({"receipt": str(args.receipt), "checks": receipt["checks"],
                      "cleanup": receipt["cleanup"], "credits": receipt.get("actual_credit_debit"),
                      "error": receipt.get("error")}, indent=2))
    if (receipt.get("error") or not all(receipt["checks"].values()) or
            not all(receipt["cleanup"].get(f"{kind}_{field}") for kind in ("chats", "workflows")
                    for field in ("deleted", "absence_verified"))):
        raise SystemExit(1)


if __name__ == "__main__":
    test_workflow_clarification()
