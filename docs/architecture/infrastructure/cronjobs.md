---
status: active
last_verified: 2026-03-24
key_files:
  - scripts/check-deploy-status.sh
  - scripts/run-tests-daily.sh
  - scripts/nightly-dead-code-removal.sh
  - scripts/weekly-codebase-audit.sh
  - scripts/security-audit.sh
---

# Scheduled Cronjobs

> Server-side cron jobs on the dev server (user: `superdev`) that automate deployment monitoring, code quality, testing, security audits, and issue triage.

## Why This Exists

Continuous automated maintenance reduces manual toil: deploy failures are auto-investigated, dead code is removed nightly, tests run daily, and security is audited twice weekly.

## How It Works

### Overview

| Schedule          | Script                                 | Purpose                                   |
|-------------------|----------------------------------------|-------------------------------------------|
| `*/2 * * * *`     | `check-deploy-status.sh`               | Watch Vercel for build failures           |
| `02:00 daily`     | `nightly-dead-code-removal.sh`         | Remove detected dead code                 |
| `02:00 Mon+Thu`   | `weekly-codebase-audit.sh`             | Top 5 improvement findings (plan only)    |
| `03:00 daily`     | `run-tests-daily.sh`                   | Full test suite (Playwright + pytest)     |
| `04:00 daily`     | `nightly-issues-check.sh`              | Triage unresolved user issues             |
| `04:30 daily`     | `check-dependabot-daily.sh`            | Process Dependabot security alerts        |
| `05:00 daily`     | `nightly-workflow-review.sh`           | Analyze yesterday's Claude Code sessions  |
| `02:30 Tue+Fri`   | `security-audit.sh`                    | Security code review (plan only)          |
| `02:30 Wed+Sat`   | `red-teaming.sh`                       | External attacker simulation (GET only)   |
| `02:00 Sun`       | `docker-cleanup.sh`                    | Remove dangling images/containers/volumes |
| `@reboot`         | `agent-trigger-watcher.sh`             | Poll for admin-submitted issue triggers   |

### Job Details

**Deploy status checker** (`*/2 min`): Checks git log for recent commits; if found, queries Vercel API for build status. On `ERROR`/`CANCELED`, dispatches an opencode build-mode session with the build log. State: `scripts/.deploy-checker-state.json`. Env: `VERCEL_TOKEN`.

**Dead code removal** (02:00): Runs `find_dead_code.py` (up to 50 items across Python/TypeScript/Svelte/CSS). Dispatches opencode session to remove and commit. Skips if HEAD unchanged. State: `scripts/.dead-code-removal-state.json`.

**Codebase audit** (Mon+Thu 02:00): Uses 2 weeks of git history to find top 5 improvements (security, performance, reliability, quality). Plan mode only -- no implementation. State: `scripts/.audit-state.json`.

**Daily test run** (03:00): Full Playwright E2E + pytest suite. Sends summary email on completion. On failure, dispatches opencode analysis session. Archives to `test-results/daily-run-YYYY-MM-DD.json`. Env: `E2E_DAILY_RUN_ENABLED=true`, `ADMIN_NOTIFY_EMAIL`, `INTERNAL_API_SHARED_TOKEN`.

**Issues check** (04:00): Fetches open issues from past 24h via admin debug API. Dispatches investigation for unresolved issues. Env: `SECRET__ADMIN__DEBUG_CLI__API_KEY`.

**Dependabot check** (04:30): Fetches critical/high/medium alerts via `gh` CLI. Dispatches fix session for new or stale (>7 days) alerts. State: `scripts/dependabot-processed.json`.

**Workflow review** (05:00): Reads opencode SQLite DB, extracts yesterday's sessions, produces up to 10 improvement suggestions for tooling/instructions. State: `scripts/.workflow-review-state.json`.

**Security audit** (Tue+Fri 02:30): Reviews files changed since last audit. Top 5 critical security issues with OWASP mapping. Monthly full sweep. Acknowledged findings suppressed via `_security_helper.py acknowledge`. State: `.claude/security-audit-state.json` (gitignored).

**Red team probe** (Wed+Sat 02:30): Simulates external attacker against dev endpoints (GET/HEAD/OPTIONS only, max 5 req/endpoint, 20-min timeout). Three phases: reconnaissance, external probing, safe exploitation. No destructive requests.

**Docker cleanup** (Sun 02:00): `docker system prune` for dangling images, stopped containers, unused volumes.

**Agent trigger watcher** (`@reboot`): Polls `scripts/.agent-triggers/` every 5s for JSON trigger files from admin sidecar. Dispatches opencode investigation; completed triggers moved to `done/`.

### Manual Invocation

All scripts support `--dry-run` (show prompt, skip opencode) and `--force` (bypass guards):

```bash
./scripts/check-deploy-status.sh --dry-run
./scripts/nightly-dead-code-removal.sh --force --category python
./scripts/run-tests-daily.sh --force
REVIEW_DATE=2026-03-17 bash scripts/nightly-workflow-review.sh
```

### Adding a New Job

1. Shell entrypoint in `scripts/` (source `.env`, header comment with schedule).
2. Python helper in `scripts/_<name>_helper.py` if needed.
3. Prompt template in `scripts/prompts/` if calling opencode.
4. Crontab entry via `crontab -e`.
5. Update this doc.

## Related Docs

- [Health Checks](./health-checks.md) -- Celery Beat tasks (not cron) for service monitoring
- [Daily Test Run](../../contributing/guides/testing.md) -- test infrastructure details
