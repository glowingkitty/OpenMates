---
phase: quick-260326-k4u
plan: 01
subsystem: devops/linear-integration
tags: [linear, automation, investigation-pipeline, agent-triggers]
dependency_graph:
  requires: [agent-trigger-watcher, admin-sidecar-patterns]
  provides: [linear-polling, linear-post-investigation, linear-archive]
  affects: [scripts/agent-trigger-watcher.sh]
tech_stack:
  added: [Linear GraphQL API]
  patterns: [atomic-file-write, read-then-write-labels, systemd-user-services]
key_files:
  created:
    - scripts/linear-poller.py
    - scripts/linear-update-issue.py
    - scripts/linear-archive-issues.py
    - scripts/prompts/linear-issue-investigation.md
    - scripts/linear-cron-setup.sh
  modified:
    - scripts/agent-trigger-watcher.sh
decisions:
  - "Used httpx for all Linear API calls (project standard, available in api container)"
  - "Atomic trigger writes via os.rename to prevent watcher reading partial JSON"
  - "Label removal happens immediately after trigger write (not after investigation)"
  - "issueArchive mutation used instead of issueDelete (reversible)"
  - "GSD command recommendation embedded in prompt text, not hardcoded in poller"
metrics:
  duration: "3 minutes"
  completed: "2026-03-26"
---

# Quick Task 260326-k4u: Linear Integration Polling & Post-Investigation Updates Summary

Linear-to-Claude investigation pipeline using 30s polling, atomic trigger files, immediate label swap for duplicate prevention, and post-investigation Linear comments with session resume commands and GSD workflow recommendations.

## What Was Built

### 1. Linear Poller (`scripts/linear-poller.py`)
Single-run script called every 30s by systemd. Queries Linear GraphQL API for issues with `claude-investigate` label, renders the investigation prompt with issue context, writes atomic trigger files (`.tmp` then `os.rename` to `.json`), and immediately removes the label to prevent duplicate processing. Adds `claude-investigated` label using the read-then-write pattern required by Linear's API.

### 2. Post-Investigation Updater (`scripts/linear-update-issue.py`)
Called by `agent-trigger-watcher.sh` after Claude finishes investigating a Linear-sourced issue. Posts a markdown comment to the Linear issue containing the session ID, `claude --resume` command, and GSD workflow recommendations (`/gsd:debug`, `/gsd:quick`, `/gsd:execute-phase`). Also adds the `claude-investigated` label.

### 3. Issue Archiver (`scripts/linear-archive-issues.py`)
Daily sweep that checks total issue count against the 230 threshold (Linear free plan caps at 250). When triggered, exports oldest completed/canceled issues to `.planning/linear-archive.md` with metadata, then calls `issueArchive` mutation. Targets 200 issues (50 buffer).

### 4. Investigation Prompt (`scripts/prompts/linear-issue-investigation.md`)
GSD-aware prompt template based on the admin investigation prompt pattern. Includes 7 placeholders (LINEAR_IDENTIFIER, TITLE, DESCRIPTION, PRIORITY, LABELS, URL, DATE) and a GSD Command Recommendation section that instructs Claude to recommend the right workflow command based on issue nature.

### 5. Systemd Installer (`scripts/linear-cron-setup.sh`)
Dev-server-only installer that creates two systemd user services: a `linear-poller.service` (30s sleep loop with flock) and a `linear-archive.timer` (daily OnCalendar trigger). Both execute scripts via `docker exec api`.

### 6. Watcher Modification (`scripts/agent-trigger-watcher.sh`)
Two additions to `process_trigger()`: extracts `linear_issue_id` from trigger JSON (empty for admin sidecar triggers), and after Claude session completes, calls `linear-update-issue.py` via docker exec if the field is present. Failure is logged as WARNING without breaking the watcher.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 1ae92997d | Add 5 new files: poller, updater, archiver, prompt, systemd installer |
| 2 | 356428562 | Modify agent-trigger-watcher.sh for Linear post-investigation updates |

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None. All scripts are complete implementations ready for use once LINEAR_API_KEY is configured in `.env` and the `claude-investigate` / `claude-investigated` labels are created in the Linear workspace.

## Self-Check: PASSED

- All 6 files verified present on disk
- Both commits (1ae92997d, 356428562) verified in git log
- All Python scripts parse without errors
- All shell scripts pass bash -n syntax check
- All 7 prompt placeholders verified present
