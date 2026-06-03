---
status: active
last_verified: 2026-03-27
key_files:
  - scripts/check-deploy-status.sh
  - scripts/run_tests.py
  - scripts/auto_fix_failed_tests.py
  - scripts/nightly-dead-code-removal.sh
  - scripts/weekly-codebase-audit.sh
  - scripts/security-audit.sh
  - scripts/nightly-code-structure.sh
  - scripts/daily-meeting.sh
  - scripts/update_obsidian_daily_note.py
  - scripts/_opencode_daily_meeting.py
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
| `0 10 * * 1-5` UTC            | `daily-meeting.sh`                     | **Daily standup**: OpenCode chat + email link |
| `*/2 * * * *`                 | `check-deploy-status.sh`               | Watch Vercel for build failures           |
| `02:00 Mon-Fri`               | `nightly-dead-code-removal.sh`         | Remove detected dead code                 |
| `02:00 Mon+Thu`               | `weekly-codebase-audit.sh`             | Top 5 improvement findings (plan only)    |
| `02:15 Mon-Fri`               | `nightly-quick-wins.sh`                | Quick-win improvements (Haiku, plan only) |
| `02:30 Tue+Fri`               | `security-audit.sh`                    | Security code review (plan only)          |
| `02:30 Wed+Sat`               | `red-teaming.sh`                       | External attacker simulation (GET only)   |
| `02:35 Mon-Fri`               | `nightly-pattern-consistency.sh`       | Pattern consistency scan (Haiku, plan only)|
| `02:50 Mon-Fri`               | `nightly-code-structure.sh`            | Code structure cleanup suggestions        |
| `03:00 Mon-Fri`               | `run_tests.py --daily`                 | Full test suite (Playwright + pytest)     |
| `* * * * *`                   | `update_obsidian_daily_note.py`        | Refresh Obsidian daily note stats/activity |
| `0 8-18 * * *` (GHA)          | `.github/workflows/prod-smoke.yml`     | Hourly **prod** smoke (reachability + signup+gift card + login+chat), 10–20 Berlin (OPE-76) |
| `*/1h (xx:30)`                | `check-dependabot-daily.sh`            | Process Dependabot security alerts        |
| `*/1h (xx:35)`                | `check-eu-vulns-daily.sh`              | EU/OSV/NVD vulnerability detection        |
| `02:00 Sun`                   | `docker-cleanup.sh`                    | Remove dangling images, build cache; aggressive mode at >90% disk |
| `@reboot`                     | `agent-trigger-watcher.sh`             | Poll for admin-submitted issue triggers   |

> **Consolidated (2026-03-27):** `nightly-issues-check.sh` and `nightly-workflow-review.sh` have been folded into the daily meeting. Their helpers (`_issues_checker.py`, `_workflow_review_helper.py`) are kept as importable libraries.

### Job Details

**Daily standup meeting** (`10:00 UTC` weekdays): `daily-meeting.sh` creates a persisted OpenCode chat titled `daily-meeting YYYY-MM-DD`, asks the `daily-meeting` skill to gather data inline, and emails a deep link to the configured recipient. The OpenCode web URL is built as `${OPENCODE_WEB_BASE_URL}/${base64url(project_path)}/session/${session_id}`. No Claude launcher and no Zellij session are involved. The meeting remains interactive: it presents one agenda section at a time and saves `scripts/.daily-meeting-state.json` plus `scripts/.tmp/daily-meeting-summary-<date>.md` only after the user confirms priorities. Consolidates former `nightly-workflow-review.sh` and `nightly-issues-check.sh`. Manual: `./scripts/daily-meeting.sh` or `/daily-meeting` skill. Env: `DAILY_MEETING_NOTIFY_EMAIL` (or `SERVER_OWNER_EMAIL`/`ADMIN_NOTIFY_EMAIL` fallback), `OPENCODE_WEB_BASE_URL`, `INTERNAL_API_SHARED_TOKEN`, `INTERNAL_API_URL`.

**Deploy status checker** (`*/2 min`): Checks git log for recent commits; if found, queries Vercel API for build status. On `ERROR`/`CANCELED`, dispatches a claude build-mode session with the build log. State: `scripts/.deploy-checker-state.json`. Env: `VERCEL_TOKEN`.

**Dead code removal** (02:00): Runs `find_dead_code.py` (up to 50 items across Python/TypeScript/Svelte/CSS). Dispatches claude session to remove and commit. Skips if HEAD unchanged. State: `scripts/.dead-code-removal-state.json`.

**Codebase audit** (Mon+Thu 02:00): Uses 2 weeks of git history to find top 5 improvements (security, performance, reliability, quality). Plan mode only -- no implementation. State: `scripts/.audit-state.json`.

**Daily test run** (03:00): Full Playwright E2E + pytest suite. Sends summary email on completion + Discord fallback post (OPE-76). If failures occur, runs `scripts/auto_fix_failed_tests.py --from-daily-run` unless `E2E_AUTO_FIX_FAILED_TESTS=false`: one blocking OpenCode fix run per root-cause group, controller-owned verification, Discord summary after each group, and deploy only after a safe green fix. Auto-fix OpenCode sessions are hidden from the OpenCode web history by default after the controller captures their JSONL output and summary. On-demand status comes from `test-results/auto-fix-state.json`, `logs/auto-fix-failed-tests-manual.log`, and `scripts/.tmp/auto-fix/**/opencode-output-*.jsonl`; set `AUTO_FIX_EXPOSE_OPENCODE_CHATS=true` only for manual debugging when web-visible chats are desired. If auto-fix is disabled, the daily runner sends notifications only. Archives to `test-results/daily-run-YYYY-MM-DD.json`. Env: `E2E_DAILY_RUN_ENABLED=true`, `ADMIN_NOTIFY_EMAIL`, `INTERNAL_API_SHARED_TOKEN`, `OPENCODE_WEB_BASE_URL`, `DISCORD_WEBHOOK_DEV_NIGHTLY` (optional), `DISCORD_WEBHOOK_TEST_FIXES` (optional dedicated auto-fix channel), `E2E_AUTO_FIX_FAILED_TESTS=false` (optional opt-out), `AUTO_FIX_EXPOSE_OPENCODE_CHATS=true` (optional visible debug opt-in).

**Obsidian daily note updater** (every minute): Refreshes today's local daily note under `vaults/memory/Daily Notes/` with changed note links, same-day git commits, and cached server stats. Preserves manual content outside `<!-- AUTO:* -->` sections. Log: `logs/obsidian-daily-note.log`. State: `vaults/memory/.obsidian-auto/daily-note-state/`.

**Prod smoke** (GitHub Actions, hourly 10–20 Europe/Berlin): Runs three Playwright specs against the live production server: (1) reachability pre-flight, (2) fresh signup + reusable domain-bound gift card redemption + first chat (no Stripe), (3) login + chat on a persistent prod test account. On any failure, the shared composite action `.github/actions/notify-test-failure` posts to a Discord webhook **and** sends an email via Brevo — both sends independent so a single channel outage never masks the failure. No dependency on dev server uptime. Secrets: `PROD_BASE_URL`, `PROD_SMOKE_GIFT_CARD_CODE`, `PROD_SMOKE_EMAIL_DOMAIN`, `PROD_SMOKE_MAILOSAUR_API_KEY`, `PROD_SMOKE_MAILOSAUR_SERVER_ID`, `OPENMATES_PROD_TEST_ACCOUNT_{EMAIL,PASSWORD,OTP_KEY}`, `DISCORD_WEBHOOK_PROD_SMOKE`, `PROD_SMOKE_EMAIL_TO`, `BREVO_API_KEY`. The gift card's `allowed_email_domain` must exactly match the Mailosaur server subdomain — suffix matches would let any Mailosaur customer redeem the card.

**Issues check**: _Consolidated into daily meeting (2026-03-27)._ Helper `_issues_checker.py` still available as importable library.

**Dependabot check** (hourly at xx:30): Fetches critical/high/medium alerts via `gh` CLI. Dispatches fix session for new or stale (>7 days) alerts. No-ops in seconds when no new alerts are found (no Claude session spawned). Uses `sessions.py deploy` for commits. Resolved entries auto-pruned after 72h. State: `scripts/dependabot-processed.json`.

**EU vulnerability check** (hourly at xx:35, 5 min after Dependabot): Queries OSV + NVD for vulnerabilities Dependabot misses. Cross-refs against `dependabot-processed.json`. No-ops in seconds when no new vulns found. Uses `sessions.py deploy` for commits. Resolved entries auto-pruned after 72h. State: `scripts/eu-vuln-processed.json`.

**Workflow review**: _Consolidated into daily meeting (2026-03-27)._ Helper `_workflow_review_helper.py` still available as importable library.

**Security audit** (Tue+Fri 02:30): Reviews files changed since last audit. Top 5 critical security issues with OWASP mapping. Monthly full sweep. Acknowledged findings suppressed via `_security_helper.py acknowledge`. State: `.claude/security-audit-state.json` (gitignored).

**Red team probe** (Wed+Sat 02:30): Simulates external attacker against dev endpoints (GET/HEAD/OPTIONS only, max 5 req/endpoint, 20-min timeout). Three phases: reconnaissance, external probing, safe exploitation. No destructive requests. Uses `--permission-mode plan` with `--allowedTools "Read,Grep,Glob,Bash(curl *)"`.

**Code structure cleanup** (02:50 daily): Scans for repository hygiene issues — gitignore gaps, open-source readiness (leaked internal values), folder organization, file consolidation, naming inconsistencies, stale artifacts. Haiku, plan mode, 25-min soft limit / 30-min hard kill. Suggestions only, no code changes. Uses `_nightly_scanner_helper.py` with rotating sector schedule. Output: `logs/nightly-reports/code-structure.json`. Manual: `./scripts/nightly-code-structure.sh [--dry-run]`.

**Docker cleanup** (Sun 02:00): `docker system prune` for dangling images, stopped containers, unused volumes.

**Agent trigger watcher** (`@reboot`): Polls `scripts/.agent-triggers/` every 5s for JSON trigger files from admin sidecar. Dispatches claude investigation; completed triggers moved to `done/`.

### Agent CLI Dispatch

Most background maintenance helpers use `scripts/_claude_utils.py:run_claude_session()` which invokes:

```bash
claude -p "<message>" \
  --model claude-sonnet-4-6 \
  --name "<session-title>" \
  --output-format json \
  --permission-mode plan          # for read-only jobs (audit, security, redteam, issues)
  --dangerously-skip-permissions  # for write jobs (dead code, dependabot, deploy fix, test analysis)
```

Session IDs are extracted from JSON output and logged for traceability.

The daily standup is the exception: `scripts/_opencode_daily_meeting.py` invokes `opencode run --format json --title "daily-meeting <date>"` so the chat appears directly in OpenCode web. Cron should configure the public web base URL and recipient via environment, not source code.

### Manual Invocation

Most maintenance scripts support `--dry-run` (show prompt, skip agent) or `--force` (bypass guards):

```bash
./scripts/check-deploy-status.sh --dry-run
./scripts/nightly-dead-code-removal.sh --force --category python
./scripts/run-tests-daily.sh --force
REVIEW_DATE=2026-03-17 bash scripts/nightly-workflow-review.sh
```

### Adding a New Job

1. Shell entrypoint in `scripts/` (source `.env`, header comment with schedule).
2. Python helper in `scripts/_<name>_helper.py` if needed.
3. Prompt template in `scripts/prompts/` if calling an agent with a large reusable prompt.
4. Crontab entry via `crontab -e`.
5. Update this doc.

## Related Docs

- [Health Checks](./health-checks.md) -- Celery Beat tasks (not cron) for service monitoring
- [Daily Test Run](../../contributing/guides/testing.md) -- test infrastructure details
