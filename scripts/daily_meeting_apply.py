#!/usr/bin/env python3
"""Apply the structured tables of a daily-meeting DECISIONS note and prove every row.

The meeting ends with a note whose `Reminder changes:` and `Task changes:` sections are
Markdown tables (one row per change). This script reads them, resolves every row against
the LIVE Apple Reminders / OpenMates Tasks, applies what is unambiguous, re-reads both
lists and prints one result line per row (OK / FAILED / NEEDS ATTENTION). A row can no
longer be skipped silently: anything not applied and verified makes the exit code non-zero.
Rows of the other sections (Goals, Meeting, Chats, Cleanup, ...) are listed as manual steps.

  plan  --note FILE            dry run: show what each row would do
  apply --note FILE            apply ready rows, then verify against fresh live data

Legacy one-line formats (`- "title" -> move YYYY-MM-DD HH:MM`) are still understood.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import difflib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import daily_meeting_tasks_cache as tasks_cache  # noqa: E402 - sibling script, path set above
import mac_reminders  # noqa: E402 - sibling script, path set above

PRIORITIES = ("none", "low", "medium", "high", "urgent")
HEADING = re.compile(r"^(Check-in|Focus tasks|Focus|Tasks|Task changes|Reminder changes|Reminders|"
                     r"New reminders|Goals|Meeting|Chats|Cleanup|Parking lot|Week goals|Notes):\s*(.*)$", re.I)
MANUAL = ("goals", "meeting", "chats", "cleanup", "parking lot", "week goals")


def norm(text: str) -> str:
    text = (text or "").replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return re.sub(r"\s+", " ", text).strip().casefold()


def parse_sections(note: str) -> dict[str, list[str]]:
    """Section name (lowercase) -> its lines (text after the colon first, then the body)."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in note.splitlines():
        found = HEADING.match(line.strip()) if not line.startswith((" ", "|", "-", "+")) else None
        if found:
            current = found.group(1).lower()
            sections.setdefault(current, [])
            if found.group(2).strip():
                sections[current].append(found.group(2).strip())
        elif current is not None and line.strip():
            sections[current].append(line.strip())
    return sections


def parse_table(lines: list[str]) -> list[dict[str, str]]:
    """Markdown table rows as dicts keyed by the lowercase header cells."""
    header: list[str] | None = None
    rows = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        if header is None:
            header = [norm(c) for c in cells]
            continue
        rows.append({header[i]: cells[i] if i < len(cells) else "" for i in range(len(header))})
    return rows


def _pick(row: dict[str, str], *names: str) -> str:
    for key, value in row.items():
        if any(key.startswith(name) for name in names):
            return value.strip()
    return ""


def reminder_rows(sections: dict[str, list[str]]) -> list[dict]:
    """Rows from the table, plus the legacy `Reminders:` / `New reminders:` lines."""
    rows = []
    for row in parse_table(sections.get("reminder changes", [])):
        rows.append({"action": norm(_pick(row, "action")), "title": _pick(row, "reminder", "title"),
                     "list": _pick(row, "list"), "due": _pick(row, "new due", "due"),
                     "new_title": _pick(row, "new title"), "notes": _pick(row, "notes"), "raw": str(row)})
    for line in sections.get("reminders", []):
        found = re.match(r'^[-*]\s*"(.+?)"\s*->\s*(done|delete|keep|move\s+(\S+(?:\s+\d{1,2}:\d{2})?))', line, re.I)
        if found:
            action = found.group(2).split()[0].lower()
            rows.append({"action": action, "title": found.group(1), "list": "", "due": found.group(3) or "",
                         "new_title": "", "notes": "", "raw": line})
    for line in sections.get("new reminders", []):
        found = re.match(r'^[-*]\s*"(.+?)"\s*\((OpenMates|Personal Tasks),\s*(.+?)\)', line)
        if found:
            rows.append({"action": "create", "title": found.group(1), "list": found.group(2),
                         "due": found.group(3), "new_title": "", "notes": "", "raw": line})
    return rows


def task_rows(sections: dict[str, list[str]]) -> list[dict]:
    rows = []
    for row in parse_table(sections.get("task changes", [])):
        rows.append({"action": norm(_pick(row, "action")), "title": _pick(row, "task"),
                     "new_title": _pick(row, "new title"), "priority": norm(_pick(row, "priority")),
                     "status": norm(_pick(row, "status")), "label": _pick(row, "label"),
                     "due": _pick(row, "due"), "description": _pick(row, "description"),
                     "assign": norm(_pick(row, "assign")), "raw": str(row)})
    return rows


def resolve(title: str, items: list[dict], list_name: str = "") -> tuple[dict | None, str]:
    """(item, "") on a unique match; (None, reason) otherwise. Exact title, else a unique prefix."""
    wanted = norm(title.rstrip("…").rstrip("."))
    if not wanted:
        return None, "no title given"
    pool = [i for i in items if not list_name or i.get("list") == list_name] or items
    exact = [i for i in pool if norm(i["title"]) == wanted]
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return None, f"{len(exact)} reminders/tasks have this exact title; name the list or rename one"
    starts = [i for i in pool if len(wanted) >= 20 and (norm(i["title"]).startswith(wanted)
                                                          or wanted.startswith(norm(i["title"])))]
    if len(starts) == 1:
        return starts[0], ""
    close = difflib.get_close_matches(wanted, [norm(i["title"]) for i in pool], n=3, cutoff=0.6)
    hint = "; closest: " + " | ".join(f'"{c[:70]}"' for c in close) if close else ""
    return None, f"no unique match for this title{hint}"


def berlin(value: str | None) -> str:
    if not value:
        return ""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(mac_reminders.TZ).strftime("%Y-%m-%d %H:%M")


def task_due_epoch(value: str) -> int | None:
    """Epoch seconds for a Task due cell: `YYYY-MM-DD HH:MM` is Berlin time, a bare date is that day
    at 00:00 UTC (what the Tasks CLI stores for a date); None when the cell is not a date."""
    text = value.strip()
    try:
        if len(text) == 10:
            return int(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        return int(datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=mac_reminders.TZ).timestamp())
    except ValueError:
        return None


def plan_reminders(rows: list[dict], items: list[dict]) -> list[dict]:
    """One plan entry per row: status ready | attention | noop, a batch `ops` list and the `expect` check."""
    plan, seen = [], set()
    for number, row in enumerate(rows, 1):
        entry = {"section": "Reminder", "n": number, "label": f'{row["action"]}: {row["title"][:70]}',
                 "status": "ready", "reason": "", "ops": [], "expect": {}}
        action = row["action"]
        try:
            due = mac_reminders.normalize_due(row["due"]) if row["due"] else ""
        except mac_reminders.RemindersError as error:
            due = None
            entry.update(status="attention", reason=str(error).split(": ", 1)[-1])
        if entry["status"] == "ready" and action == "keep":
            entry["status"] = "noop"
        elif entry["status"] == "ready" and action == "create":
            if row["list"] not in mac_reminders.LISTS or not row["title"] or not due:
                entry.update(status="attention", reason="create needs a title, a list (OpenMates or Personal Tasks) and a due with a time")
            else:
                op = {"action": "create", "list": row["list"], "title": row["title"], "due": row["due"]}
                if row["notes"]:
                    op["notes"] = row["notes"]
                entry.update(ops=[op], expect={"kind": "create", "title": row["title"], "list": row["list"],
                                               "due": berlin(due)})
        elif entry["status"] == "ready" and action in ("move", "done", "delete", "update"):
            item, why = resolve(row["title"], items, row["list"])
            if item is None:
                entry.update(status="attention", reason=why)
            elif item["id"] in seen:
                entry.update(status="attention", reason="the same reminder appears in two rows")
            elif action == "move" and not due:
                entry.update(status="attention", reason="move needs a new due with a time (YYYY-MM-DD HH:MM)")
            elif action == "update" and not (row["new_title"] or row["notes"] or due):
                entry.update(status="attention", reason="update needs a new title, notes or a due")
            else:
                seen.add(item["id"])
                ops, expect = [], {"kind": action, "id": item["id"]}
                if action == "move" or (action == "update" and due):
                    ops.append({"action": "set-due", "id": item["id"], "due": row["due"]})
                    expect["due"] = berlin(due)
                if action == "done":
                    ops.append({"action": "complete", "id": item["id"]})
                if action == "delete":
                    ops.append({"action": "delete", "id": item["id"]})
                if action == "update" and (row["new_title"] or row["notes"]):
                    op = {"action": "update", "id": item["id"]}
                    if row["new_title"]:
                        op["title"] = expect["title"] = row["new_title"]
                    if row["notes"]:
                        op["notes"] = row["notes"]
                        expect["notes"] = row["notes"][:200]
                    ops.append(op)
                entry.update(ops=ops, expect=expect)
        elif entry["status"] == "ready":
            entry.update(status="attention", reason=f"unknown action {action!r} (use move, done, delete, create, update, keep)")
        plan.append(entry)
    return plan


def plan_tasks(rows: list[dict], tasks: list[dict]) -> list[dict]:
    """Plan entries for the Task table; `cmds` are `openmates tasks ...` argument lists."""
    plan, seen = [], set()
    for number, row in enumerate(rows, 1):
        entry = {"section": "Task", "n": number, "label": f'{row["action"]}: {row["title"][:70]}',
                 "status": "ready", "reason": "", "cmds": [], "expect": {}}
        action = row["action"]
        due = task_due_epoch(row["due"]) if row["due"] else None
        if row["priority"] and row["priority"] not in PRIORITIES:
            entry.update(status="attention", reason=f"priority must be one of {', '.join(PRIORITIES)}")
        elif row["due"] and due is None:
            entry.update(status="attention", reason="due must be YYYY-MM-DD or YYYY-MM-DD HH:MM (Berlin)")
        elif action == "keep":
            entry["status"] = "noop"
        elif action == "create":
            cmd = ["create", "--title", row["title"]]
            for flag, key in (("--description", "description"), ("--priority", "priority"),
                              ("--status", "status"), ("--label", "label"), ("--assign", "assign")):
                if row[key]:
                    cmd += [flag, row[key]]
            expect = {"kind": "create", "title": row["title"], "priority": row["priority"], "status": row["status"]}
            if due is not None:
                cmd += ["--due", str(due)]
                expect["due_at"] = due
            entry.update(status="ready" if row["title"] else "attention", reason="" if row["title"] else "create needs a title",
                         cmds=[cmd], expect=expect)
        elif action in ("edit", "done", "delete"):
            task, why = resolve(row["title"], tasks)
            if task is None:
                entry.update(status="attention", reason=why)
            elif task["task_id"] in seen:
                entry.update(status="attention", reason="the same Task appears in two rows")
            elif action == "edit" and not any(row[k] for k in ("new_title", "priority", "status", "label", "due", "description")):
                entry.update(status="attention", reason="edit needs at least one of new title, priority, status, label, due, description")
            else:
                seen.add(task["task_id"])
                tid, expect = task["task_id"], {"kind": action, "id": task["task_id"]}
                if action == "done":
                    entry["cmds"] = [["done", tid]]
                    expect["status"] = "done"
                elif action == "delete":
                    entry["cmds"] = [["delete", tid, "--confirm"]]
                else:
                    cmd = ["edit", tid]
                    for flag, key, field in (("--title", "new_title", "title"), ("--description", "description", ""),
                                             ("--priority", "priority", "priority_level"), ("--status", "status", "status")):
                        if row[key]:
                            cmd += [flag, row[key]]
                            if field:
                                expect[field] = row[key]
                    if row["label"]:
                        cmd += ["--add-label", row["label"]]
                        expect["label"] = row["label"]
                    if due is not None:
                        cmd += ["--due", str(due)]
                        expect["due_at"] = due
                    entry["cmds"] = [cmd]
                entry["expect"] = expect
        else:
            entry.update(status="attention", reason=f"unknown action {action!r} (use create, edit, done, delete, keep)")
        plan.append(entry)
    return plan


def verify_reminder(entry: dict, items: list[dict]) -> str:
    """"" when the live list shows the change, else why not."""
    expect, by_id = entry["expect"], {i["id"]: i for i in items}
    kind = expect["kind"]
    if kind == "create":
        match = [i for i in items if i["title"] == expect["title"] and i["list"] == expect["list"]
                 and berlin(i.get("due")) == expect["due"]]
        return "" if match else "created reminder not found with that title, list and time"
    if kind in ("done", "delete"):
        return "still open on the Mac" if expect["id"] in by_id else ""
    item = by_id.get(expect["id"])
    if item is None:
        return "reminder disappeared from the open list"
    if "due" in expect and berlin(item.get("due")) != expect["due"]:
        return f'due is {berlin(item.get("due")) or "empty"}, expected {expect["due"]}'
    if "title" in expect and item["title"] != expect["title"]:
        return "title was not changed"
    if "notes" in expect and (item.get("notes") or "")[:200] != expect["notes"]:
        return "notes were not changed"
    return ""


def verify_task(entry: dict, tasks: list[dict]) -> str:
    expect, by_id = entry["expect"], {t["task_id"]: t for t in tasks}
    kind = expect["kind"]
    if kind == "create":
        match = [t for t in tasks if t["title"] == expect["title"]]
        if not match:
            return "created Task not found"
        if "due_at" in expect and not any(t.get("due_at") == expect["due_at"] for t in match):
            return "created Task has no or another due date"
        return ""
    task = by_id.get(expect["id"])
    if kind == "delete":
        return "Task still exists" if task else ""
    if task is None:
        return "Task disappeared"
    for key in ("status", "priority_level", "title"):
        if key in expect and task.get(key) != expect[key]:
            return f'{key} is {task.get(key)!r}, expected {expect[key]!r}'
    if "label" in expect and expect["label"] not in (task.get("labels") or []):
        return "label was not added"
    if "due_at" in expect and task.get("due_at") != expect["due_at"]:
        return f'due date is {task.get("due_at") or "empty"}, expected {expect["due_at"]} (epoch seconds)'
    return ""


def run_task_cmd(cmd: list[str]) -> str:
    """"" on success, else the CLI's error text."""
    try:
        run = subprocess.run([tasks_cache.find_cli(), "tasks", *cmd], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError, tasks_cache.TasksError) as error:
        return f"{type(error).__name__}: {str(error)[-200:]}"
    return "" if run.returncode == 0 else (run.stderr or run.stdout).strip()[-300:]


def apply_reminders(plan: list[dict], pending_file: Path) -> tuple[list[dict], str]:
    """Run the ready rows as one batch; returns (per-row results, fatal error text)."""
    ready = [e for e in plan if e["status"] == "ready" and e["ops"]]
    if not ready:
        return [], ""
    ops = [op for e in ready for op in e["ops"]]
    try:
        results = mac_reminders.remote({"action": "batch", "ops": mac_reminders.checked_ops(ops)})
    except (mac_reminders.RemindersError, subprocess.TimeoutExpired, OSError) as error:
        pending_file.write_text(json.dumps(ops, indent=1))
        pending_file.chmod(0o600)
        return [], f"Mac unreachable: {error}. The changes were saved to {pending_file} and are NOT applied"
    return list(results) if isinstance(results, list) else [], ""


def report(plan: list[dict], verdicts: dict[tuple, str], manual: dict[str, int]) -> tuple[str, int]:
    lines = ["| Section | Row | Result |", "|---|---|---|"]
    bad = 0
    for entry in plan:
        key = (entry["section"], entry["n"])
        if entry["status"] == "noop":
            result = "kept (no change)"
        elif entry["status"] == "attention":
            result, bad = f'NEEDS ATTENTION: {entry["reason"]}', bad + 1
        elif key in verdicts and verdicts[key]:
            result, bad = f'FAILED: {verdicts[key]}', bad + 1
        elif key in verdicts:
            result = "OK (verified on live data)"
        else:
            result = "planned (dry run)"
        lines.append(f'| {entry["section"]} | {entry["n"]}. {entry["label"]} | {result} |')
    manual_text = ", ".join(f"{name}: {count} line(s)" for name, count in manual.items() if count)
    if manual_text:
        lines += ["", f"Manual steps still to apply from the note ({manual_text}): "
                      "Goals/Meeting/Chats/Cleanup/Parking lot/Week goals are done by the skill, not by this script."]
    return "\n".join(lines), bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--note", type=Path, required=True)
    parser.add_argument("--pending-file", type=Path, help="where unapplied reminder changes are saved if the Mac is offline")
    args = parser.parse_args(argv)

    note = args.note.read_text()
    sections = parse_sections(note)
    date_match = re.match(r"\s*DECISIONS\s+(\d{4}-\d{2}-\d{2})", note)
    pending = args.pending_file or args.note.with_name(f"{date_match.group(1) if date_match else 'undated'}-pending-reminders.json")
    rrows, trows = reminder_rows(sections), task_rows(sections)
    plan: list[dict] = []
    verdicts: dict[tuple, str] = {}

    reminder_plan, mac_error = [], ""
    if rrows:
        try:
            items, _, _ = mac_reminders.load(prefer_live=True)  # live read first, as the skill requires
            reminder_plan = plan_reminders(rrows, items)
        except (mac_reminders.RemindersError, OSError) as error:
            mac_error = str(error)
    task_plan, tasks_error = [], ""
    if trows:
        data, status = tasks_cache.load()
        if data is None or status["source"] != "live":
            tasks_error = f'OpenMates Tasks are not live ({status["error"] or "no copy"}); not applying Task changes'
        else:
            task_plan = plan_tasks(trows, data["tasks"])
    plan = reminder_plan + task_plan

    if args.command == "apply":
        _, fatal = apply_reminders(reminder_plan, pending)
        if fatal:
            mac_error = fatal
        elif reminder_plan:
            items, _, _ = mac_reminders.load(prefer_live=True)  # fresh read after the batch
            for entry in reminder_plan:
                if entry["status"] == "ready" and entry["ops"]:
                    verdicts[(entry["section"], entry["n"])] = verify_reminder(entry, items)
        for entry in task_plan:
            if entry["status"] != "ready":
                continue
            errors = [run_task_cmd(cmd) for cmd in entry["cmds"]]
            if any(errors):
                verdicts[(entry["section"], entry["n"])] = next(e for e in errors if e)
        if task_plan and any(e["status"] == "ready" for e in task_plan):
            data, _ = tasks_cache.load()
            for entry in task_plan:
                key = (entry["section"], entry["n"])
                if entry["status"] == "ready" and not verdicts.get(key) and data:
                    verdicts[key] = verify_task(entry, data["tasks"])
    text, bad = report(plan, verdicts, {name: len(sections.get(name, [])) for name in MANUAL})
    print(text)
    for problem in (mac_error, tasks_error):
        if problem:
            print(f"\nBLOCKED: {problem}")
    return 1 if (bad or mac_error or tasks_error) else 0


if __name__ == "__main__":
    raise SystemExit(main())
