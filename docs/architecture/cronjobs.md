# Scheduled Cronjobs

All cronjobs run on the dev server via `crontab -l` (user: `superdev`). Logs are written to `logs/` at the project root.

---

## Overview

| Time (UTC)        | Script                                  | Log                                  |
| ----------------- | --------------------------------------- | ------------------------------------ |
| `*/2 * * * *`     | `scripts/check-deploy-status.sh`        | `logs/deploy-checker.log`            |
| `02:00 daily`     | `scripts/nightly-dead-code-removal.sh`  | `logs/dead-code-removal.log`         |
| `02:00 Mon + Thu` | `scripts/weekly-codebase-audit.sh`      | `logs/codebase-audit.log`            |
| `03:00 daily`     | `scripts/run-tests-daily.sh`            | `logs/daily-tests.log`               |
| `04:00 daily`     | `scripts/nightly-issues-check.sh`       | `logs/nightly-issues.log`            |
| `04:30 daily`     | `scripts/check-dependabot-daily.sh`     | `logs/dependabot-alerts.log`         |
| `05:00 daily`     | `scripts/nightly-workflow-review.sh`    | `logs/nightly-workflow-review.log`   |
| `02:00 Sun`       | `scripts/docker-cleanup.sh`             | `logs/docker-cleanup.log`            |
| `@reboot`         | `scripts/agent-trigger-watcher.sh`      | `logs/agent-investigations.log`      |

---

## Jobs

### Deploy status checker

**Schedule:** `*/2 * * * *` (every 2 minutes, 24/7)
**Script:** `scripts/check-deploy-status.sh` → `scripts/_deploy_checker_helper.py`
**State:** `scripts/.deploy-checker-state.json`
**Log:** `logs/deploy-checker.log`

Watches the `dev` branch for Vercel build failures caused by recent commits. On each run:

1. Checks local git log for any commit in the last 5 minutes. If none, exits immediately (no API calls).
2. Queries the Vercel REST API for the latest deployment on the `dev` branch.
3. If status is `ERROR` or `CANCELED`, and this deployment ID has not been dispatched before, fetches the build log (errors + warnings, auto-paginated past the Vercel API's ~467-event cap).
4. Dispatches an opencode session in **build mode** with the build log + commit context. The session investigates the root cause and commits a fix.
5. Records the deployment ID in the state file to prevent duplicate dispatches.

The state file keeps the last 50 dispatched deployment IDs. No cooldown period — if the fix commit also triggers a failing build, the next cycle dispatches again.

Relies on `VERCEL_TOKEN` from `.env` and reads `frontend/apps/web_app/.vercel/project.json` for team/project IDs. No other env vars required.

**Crontab entry:**
```
*/2 * * * * /home/superdev/projects/OpenMates/scripts/check-deploy-status.sh >> /home/superdev/projects/OpenMates/logs/deploy-checker.log 2>&1
```

**Manual invocation:**
```bash
./scripts/check-deploy-status.sh              # normal run
./scripts/check-deploy-status.sh --dry-run    # show prompt, skip opencode
./scripts/check-deploy-status.sh --force      # bypass recent-commit guard
```

---

### Nightly dead code removal

**Schedule:** 02:00 UTC daily (1 hour before test run)  
**Script:** `scripts/nightly-dead-code-removal.sh` → `scripts/_dead_code_removal_helper.py`  
**State:** `scripts/.dead-code-removal-state.json`

Runs `scripts/find_dead_code.py` to detect up to 50 dead code items across Python (unused imports/variables), TypeScript (unused exports), Svelte (unreferenced component files), and CSS (unused global classes). Prioritises high-confidence items first. Skips if HEAD SHA is unchanged since the last run.

Builds a structured prompt with per-category instructions and dispatches an opencode session in **build mode** to remove the dead code and commit it. Each category gets its own commit (`chore: remove dead <category> code (automated)`). Runs 1 hour before the daily test suite so any regressions are caught immediately.

State tracks previously-removed items so the same finding is never dispatched twice. Deferred items (beyond the 50-item cap) are picked up on the next nightly run.

No env vars required.

---

### Twice-weekly codebase health audit

**Schedule:** Mon + Thu at 02:00 UTC  
**Script:** `scripts/weekly-codebase-audit.sh` → `scripts/_audit_helper.py`  
**State:** `scripts/.audit-state.json`

Uses the last 2 weeks of git commits as context, then runs an opencode session in `plan` mode to find the **top 5 highest-impact improvements** across security, performance, reliability, and code quality. Each finding includes a file + line number, why it matters, the current code, and a suggested fix. Does not implement anything — findings are for review only.

Skips if HEAD SHA is unchanged since last audit (no new commits).

---

### Daily automated test run

**Schedule:** 03:00 UTC daily  
**Script:** `scripts/run-tests-daily.sh` → `scripts/_daily_runner_helper.py`

Runs the full test suite: Playwright E2E specs, pytest unit tests, and pytest integration tests. Skips if no git commits were made in the last 24 hours (override with `--force`). Sends a summary email on completion via the internal Celery email infrastructure.

On failure, dispatches an opencode analysis session (`scripts/_daily_runner_helper.py start-opencode-analysis`) that reads the failed test output and proposes fixes.

Results are archived to `test-results/daily-run-<YYYY-MM-DD>.json` (last 30 days kept).

**Env vars required:** `E2E_DAILY_RUN_ENABLED=true`, `ADMIN_NOTIFY_EMAIL`, `INTERNAL_API_SHARED_TOKEN`

---

### Nightly issues check

**Schedule:** 04:00 UTC daily  
**Script:** `scripts/nightly-issues-check.sh` → `scripts/_issues_checker.py`

Fetches open user-reported issues from the past 24 hours via the admin debug API (`GET /v1/admin/debug/issues`). For each unresolved issue, checks whether a git commit references the issue ID. Dispatches an opencode investigation session for any issues that haven't been addressed in code.

**Env vars required:** `SECRET__ADMIN__DEBUG_CLI__API_KEY`

---

### Daily Dependabot security alert check

**Schedule:** 04:30 UTC daily  
**Script:** `scripts/check-dependabot-daily.sh` → `scripts/_dependabot_helper.py`  
**State:** `scripts/dependabot-processed.json`

Fetches open Dependabot security alerts (critical/high/medium) via the GitHub `gh` CLI. Deduplicates by GHSA ID, cross-references git history for matching commits, and dispatches an opencode session to fix any new or stale (>7 days old) unresolved alerts. Re-dispatches stale alerts at most once per 7-day window.

**Env vars required:** `gh` CLI authenticated; `GITHUB_REPO` (auto-detected from git remote if not set)

---

### Nightly workflow review

**Schedule:** 05:00 UTC daily  
**Script:** `scripts/nightly-workflow-review.sh` → `scripts/_workflow_review_helper.py`  
**State:** `scripts/.workflow-review-state.json`

Reads the opencode SQLite DB directly (`~/.local/share/opencode/opencode.db`) to extract yesterday's Claude Code sessions for this project. Filters to workflow-relevant sessions by title keyword, extracts conversation text and targeted `sessions.py`/`debug.py` tool outputs, and applies a per-session token budget (~27K tokens total). Runs a single opencode analysis session to produce up to 10 concrete improvement suggestions for `sessions.py`, `debug.py`, and `CLAUDE.md`.

Suggestions are saved to the state JSON and included in the next run's prompt as "already captured — do not repeat."

No env vars required (reads local DB directly).

---

### Weekly Docker cleanup

**Schedule:** 02:00 UTC every Sunday  
**Script:** `scripts/docker-cleanup.sh`

Removes dangling Docker images, stopped containers, and unused volumes to reclaim disk space on the dev server.

---

### Agent trigger watcher

**Schedule:** `@reboot` (starts on server reboot, runs continuously)  
**Script:** `scripts/agent-trigger-watcher.sh`

Polls `scripts/.agent-triggers/` every 5 seconds for JSON trigger files written by the admin sidecar container. When an admin submits a user-reported issue with the "Submit to agent" toggle on, the sidecar writes a trigger file; this watcher picks it up and starts an opencode investigation session automatically. Completed triggers are moved to `scripts/.agent-triggers/done/`.

---

## Manual invocation

All scripts support dry-run mode and can be invoked directly:

```bash
# Test run without calling opencode
DRY_RUN=true bash scripts/nightly-workflow-review.sh
./scripts/weekly-codebase-audit.sh --dry-run
./scripts/check-dependabot-daily.sh --dry-run
./scripts/nightly-dead-code-removal.sh --dry-run

# Run against a specific past date (workflow review only)
REVIEW_DATE=2026-03-17 bash scripts/nightly-workflow-review.sh

# Force dead code removal even if SHA unchanged
./scripts/nightly-dead-code-removal.sh --force

# Scan only one category
./scripts/nightly-dead-code-removal.sh --dry-run --category python

# Force test run even with no recent commits
./scripts/run-tests-daily.sh --force
```

## Adding a new cronjob

1. Write a shell entrypoint in `scripts/` following the existing pattern (header comment with schedule, manual invocation, env vars; source `.env`; delegate to a `_helper.py` for complex logic).
2. Add a Python helper in `scripts/_<name>_helper.py` if needed.
3. Add a prompt template in `scripts/prompts/` if the job calls opencode.
4. Add the crontab entry via `crontab -e` with a comment block matching the style above.
5. Update the overview table and add a section in this file.
