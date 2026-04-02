---
status: active
last_verified: 2026-03-27
key_files:
  - scripts/check-deploy-status.sh
  - scripts/run-tests-daily.sh
  - scripts/nightly-dead-code-removal.sh
  - scripts/weekly-codebase-audit.sh
  - scripts/security-audit.sh
  - scripts/nightly-code-structure.sh
  - scripts/daily-meeting.sh
  - scripts/_daily_meeting_helper.py
  - scripts/_claude_utils.py
---

# Scheduled Cronjobs

> Server-side cron jobs on the dev server (user: `superdev`) that automate deployment monitoring, code quality, testing, security audits, and issue triage. All AI sessions are dispatched via Claude Code CLI (`claude -p`), configured in `scripts/_claude_utils.py`.

## Why This Exists

Continuous automated maintenance reduces manual toil: deploy failures are auto-investigated, dead code is removed nightly, tests run daily, and security is audited twice weekly.

## How It Works

### Overview

| Schedule                      | Script                                 | Purpose                                   |
|-------------------------------|----------------------------------------|-------------------------------------------|
| on-demand                     | `daily-meeting.sh`                     | **Daily standup**: review, health, priorities |
| `*/2 * * * *`                 | `check-deploy-status.sh`               | Watch Vercel for build failures           |
| `02:00 Mon-Fri`               | `nightly-dead-code-removal.sh`         | Remove detected dead code                 |
| `02:00 Mon+Thu`               | `weekly-codebase-audit.sh`             | Top 5 improvement findings (plan only)    |
| `02:15 Mon-Fri`               | `nightly-quick-wins.sh`                | Quick-win improvements (Haiku, plan only) |
| `02:30 Tue+Fri`               | `security-audit.sh`                    | Security code review (plan only)          |
| `02:30 Wed+Sat`               | `red-teaming.sh`                       | External attacker simulation (GET only)   |
| `02:35 Mon-Fri`               | `nightly-pattern-consistency.sh`       | Pattern consistency scan (Haiku, plan only)|
| `02:50 Mon-Fri`               | `nightly-code-structure.sh`            | Code structure cleanup suggestions        |
| `03:00 Mon-Fri`               | `run-tests-daily.sh`                   | Full test suite (Playwright + pytest)     |
| `*/1h (xx:30)`                | `check-dependabot-daily.sh`            | Process Dependabot security alerts        |
| `*/1h (xx:35)`                | `check-eu-vulns-daily.sh`              | EU/OSV/NVD vulnerability detection        |
| `02:00 Sun`                   | `docker-cleanup.sh`                    | Remove dangling images, build cache; aggressive mode at >90% disk |
| `@reboot`                     | `agent-trigger-watcher.sh`             | Poll for admin-submitted issue triggers   |

> **Consolidated (2026-03-27):** `nightly-issues-check.sh` and `nightly-workflow-review.sh` have been folded into the daily meeting. Their helpers (`_issues_checker.py`, `_workflow_review_helper.py`) are kept as importable libraries.

### Job Details

**Daily standup meeting** (on-demand via `/daily-meeting` skill): Gathers data from 11 sources (nightly reports, git, tests, health, OpenObserve, server stats, user issues, session quality, milestone state) and starts a single interactive meeting session with all data injected directly into the prompt. No subagents — the meeting reads nightly cronjob reports as-is, avoiding redundant summarization. Queries Linear live via MCP tools. Proposes up to 10 daily priorities (goal: complete top 3). Auto-confirms after 70 min if user doesn't join. Consolidates former `nightly-workflow-review.sh` and `nightly-issues-check.sh`. State: `scripts/.daily-meeting-state.json`. Manual: `./scripts/daily-meeting.sh` or `/daily-meeting` skill. Env: `INTERNAL_API_URL`, `SECRET__ADMIN__DEBUG_CLI__API_KEY`, `INTERNAL_API_SHARED_TOKEN`.

**Deploy status checker** (`*/2 min`): Checks git log for recent commits; if found, queries Vercel API for build status. On `ERROR`/`CANCELED`, dispatches a claude build-mode session with the build log. State: `scripts/.deploy-checker-state.json`. Env: `VERCEL_TOKEN`.

**Dead code removal** (02:00): Runs `find_dead_code.py` (up to 50 items across Python/TypeScript/Svelte/CSS). Dispatches claude session to remove and commit. Skips if HEAD unchanged. State: `scripts/.dead-code-removal-state.json`.

**Codebase audit** (Mon+Thu 02:00): Uses 2 weeks of git history to find top 5 improvements (security, performance, reliability, quality). Plan mode only -- no implementation. State: `scripts/.audit-state.json`.

**Daily test run** (03:00): Full Playwright E2E + pytest suite. Sends summary email on completion. On failure, dispatches claude analysis session. Archives to `test-results/daily-run-YYYY-MM-DD.json`. Env: `E2E_DAILY_RUN_ENABLED=true`, `ADMIN_NOTIFY_EMAIL`, `INTERNAL_API_SHARED_TOKEN`.

**Issues check**: _Consolidated into daily meeting (2026-03-27)._ Helper `_issues_checker.py` still available as importable library.

**Dependabot check** (hourly at xx:30): Fetches critical/high/medium alerts via `gh` CLI. Dispatches fix session for new or stale (>7 days) alerts. No-ops in seconds when no new alerts are found (no Claude session spawned). Uses `sessions.py deploy` for commits. Resolved entries auto-pruned after 72h. State: `scripts/dependabot-processed.json`.

**EU vulnerability check** (hourly at xx:35, 5 min after Dependabot): Queries OSV + NVD for vulnerabilities Dependabot misses. Cross-refs against `dependabot-processed.json`. No-ops in seconds when no new vulns found. Uses `sessions.py deploy` for commits. Resolved entries auto-pruned after 72h. State: `scripts/eu-vuln-processed.json`.

**Workflow review**: _Consolidated into daily meeting (2026-03-27)._ Helper `_workflow_review_helper.py` still available as importable library.

**Security audit** (Tue+Fri 02:30): Reviews files changed since last audit. Top 5 critical security issues with OWASP mapping. Monthly full sweep. Acknowledged findings suppressed via `_security_helper.py acknowledge`. State: `.claude/security-audit-state.json` (gitignored).

**Red team probe** (Wed+Sat 02:30): Simulates external attacker against dev endpoints (GET/HEAD/OPTIONS only, max 5 req/endpoint, 20-min timeout). Three phases: reconnaissance, external probing, safe exploitation. No destructive requests. Uses `--permission-mode plan` with `--allowedTools "Read,Grep,Glob,Bash(curl *)"`.

**Code structure cleanup** (02:50 daily): Scans for repository hygiene issues — gitignore gaps, open-source readiness (leaked internal values), folder organization, file consolidation, naming inconsistencies, stale artifacts. Haiku, plan mode, 25-min soft limit / 30-min hard kill. Suggestions only, no code changes. Uses `_nightly_scanner_helper.py` with rotating sector schedule. Output: `logs/nightly-reports/code-structure.json`. Manual: `./scripts/nightly-code-structure.sh [--dry-run]`.

**Docker cleanup** (Sun 02:00): `docker system prune` for dangling images, stopped containers, unused volumes.

**Agent trigger watcher** (`@reboot`): Polls `scripts/.agent-triggers/` every 5s for JSON trigger files from admin sidecar. Dispatches claude investigation; completed triggers moved to `done/`.

### Claude CLI Dispatch

All Python helpers use `scripts/_claude_utils.py:run_claude_session()` which invokes:

```bash
claude -p "<message>" \
  --model claude-sonnet-4-6 \
  --name "<session-title>" \
  --output-format json \
  --permission-mode plan          # for read-only jobs (audit, security, redteam, issues)
  --dangerously-skip-permissions  # for write jobs (dead code, dependabot, deploy fix, test analysis)
```

Session IDs are extracted from JSON output and logged for traceability.

### Manual Invocation

All scripts support `--dry-run` (show prompt, skip claude) and `--force` (bypass guards):

```bash
./scripts/check-deploy-status.sh --dry-run
./scripts/nightly-dead-code-removal.sh --force --category python
./scripts/run-tests-daily.sh --force
REVIEW_DATE=2026-03-17 bash scripts/nightly-workflow-review.sh
```

### Adding a New Job

1. Shell entrypoint in `scripts/` (source `.env`, header comment with schedule).
2. Python helper in `scripts/_<name>_helper.py` if needed.
3. Prompt template in `scripts/prompts/` if calling claude.
4. Crontab entry via `crontab -e`.
5. Update this doc.

## Related Docs

- [Health Checks](./health-checks.md) -- Celery Beat tasks (not cron) for service monitoring
- [Daily Test Run](../../contributing/guides/testing.md) -- test infrastructure details
