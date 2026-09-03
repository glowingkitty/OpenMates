---
status: active
last_verified: 2026-08-14
key_files:
- .github/dependabot.yml
- pnpm-workspace.yaml
- scripts/check-deploy-status.sh
- scripts/run_tests.py
- scripts/auto_fix_failed_tests.py
- scripts/nightly-dead-code-removal.sh
- scripts/stale_code_daily.py
- scripts/stale-code-cron-setup.sh
- scripts/weekly-codebase-audit.sh
- scripts/weekly-technical-debt.sh
- scripts/technical_debt_scan.py
- scripts/_technical_debt_helper.py
- scripts/security-audit.sh
- scripts/nightly-ui-design-review.sh
- scripts/nightly-apple-parity-review.sh
- scripts/nightly-seo-audit.sh
- scripts/_scheduled_review_helper.py
- scripts/nightly-code-structure.sh
- scripts/weekly-contract-audits.sh
- scripts/run_contract_audits.py
- scripts/contract_audits.py
- scripts/_contract_audit_review_helper.py
- scripts/prompts/contract-audit-review.md
- scripts/daily-meeting.sh
- scripts/update_obsidian_daily_note.py
- scripts/_opencode_daily_meeting.py
- scripts/_daily_meeting_helper.py
- scripts/_opencode_utils.py
- scripts/release-intelligence-cron.sh
- scripts/release_intelligence.py
claims:
- id: arch-infrastructure-cronjobs-behavior
  type: unit
  claim: Scheduled Cronjobs is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - .github/dependabot.yml
  - pnpm-workspace.yaml
  - scripts/check-deploy-status.sh
  - scripts/run_tests.py
  - scripts/auto_fix_failed_tests.py
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-infrastructure-cronjobs-behavior
  verified: '2026-06-11'
- id: arch-infrastructure-cronjobs-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-cronjobs-source-1
  anchors:
  - type: file_exists
    path: .github/dependabot.yml
- id: arch-infrastructure-cronjobs-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-cronjobs-source-2
  anchors:
  - type: file_exists
    path: pnpm-workspace.yaml
- id: arch-infrastructure-cronjobs-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-infrastructure-cronjobs-source-3
  anchors:
  - type: file_exists
    path: scripts/_contract_audit_review_helper.py
---

# Scheduled Cronjobs

> Server-side cron jobs on the dev server (user: `superdev`) that automate deployment monitoring, code quality, testing, security audits, and issue triage. All AI maintenance chats are dispatched via OpenCode CLI (`opencode run`), configured in `scripts/_opencode_utils.py`.

## Why This Exists

Continuous automated maintenance reduces manual toil: deploy failures are monitored, stale-code candidates are reported without automatic edits, tests run daily, and security is audited twice weekly.

## How It Works

### Overview

| Schedule                      | Script                                 | Purpose                                   |
|-------------------------------|----------------------------------------|-------------------------------------------|
| `0 10 * * 1-5` UTC            | `daily-meeting.sh`                     | **Daily standup**: OpenCode chat + email link |
| `*/2 * * * *`                 | `check-deploy-status.sh`               | Watch Vercel for build failures           |
| `02:00 daily`                  | `stale_code_daily.py`                  | Report deletion-ready stale code + Discord |
| `02:00 Mon+Thu`               | `weekly-codebase-audit.sh`             | Top 5 improvement findings (plan only)    |
| `02:15 Mon-Fri`               | `nightly-quick-wins.sh`                | Quick-win improvements (Haiku, plan only) |
| `02:30 Tue+Fri`               | `security-audit.sh`                    | Security code review (plan only)          |
| `02:30 Wed+Sat`               | `red-teaming.sh`                       | External attacker simulation (GET only)   |
| `02:35 Mon-Fri`               | `nightly-pattern-consistency.sh`       | Pattern consistency scan (Haiku, plan only)|
| `02:50 Mon-Fri`               | `nightly-code-structure.sh`            | Code structure cleanup suggestions        |
| `03:00 daily`                 | `tests.py run --daily`                 | Full test suite (Playwright + pytest)     |
| `00:20 daily`                 | `release-intelligence-cron.sh daily`   | Generate yesterday's daily release-intelligence changelog |
| manual only                   | `opencode-workflow-review` skill       | Luna research over recent OpenCode workflow evidence |
| `00:45 Mon`                   | `release-intelligence-cron.sh weekly`  | Generate last-7-days weekly rollup + Discord summary |
| `01:10 1st day`               | `release-intelligence-cron.sh monthly` | Generate previous-month monthly rollup    |
| manual until production gate   | internal events newsletter generator   | Create deterministic biweekly OpenMates Events campaign drafts |
| `04:10 Tue+Fri`               | `nightly-ui-design-review.sh`          | UI design system/code review (plan only)  |
| `04:30 Mon+Thu`               | `nightly-apple-parity-review.sh`       | Apple/web parity review (plan only)       |
| `04:50 Sun`                   | `nightly-seo-audit.sh`                 | Deep SEO optimization review (plan only)  |
| `03:20 Sun`                   | `weekly-technical-debt.sh`             | Deterministic debt scan + OpenCode top 5 recommendations |
| `05:15 Mon`                   | `weekly-contract-audits.sh`            | Deterministic contract audits + OpenCode recommendations |
| `* * * * *`                   | `update_obsidian_daily_note.py`        | Refresh Obsidian daily note stats/activity |
| hourly, 06–23 Berlin          | `tests.py run --prod-free-hourly`      | Free production reachability smoke; dispatches `prod-smoke.yml` and dev server sends alerts |
| 07, 13, 19 Berlin             | `tests.py run --prod-paid-chat`        | Paid production CLI chat smoke with one tiny `PONG` prompt |
| 09 Berlin                     | `tests.py run --prod-app-skill`        | Production CLI `apps web search` app-skill smoke |
| `04:30 daily` (Dependabot)     | `.github/dependabot.yml`               | Daily npm/pnpm version update PRs with cooldown |
| `08:30 daily` (host systemd)   | `openmates server monitoring digest`   | Privacy-safe 24-hour operational email/Discord report |
| `*/1h (xx:30)`                | `check-dependabot-daily.sh`            | Process Dependabot security alerts        |
| `*/1h (xx:35)`                | `check-eu-vulns-daily.sh`              | EU/OSV/NVD vulnerability detection        |
| `02:00 Sun`                   | `docker-cleanup.sh`                    | Remove dangling images, build cache; aggressive mode at >90% disk |
| `01:30 daily`                 | `cleanup-opencode-sessions.sh`         | Delete OpenCode chats after 14 days; TODO chats after a 90-day hard limit |
| `hourly`                      | `sessions.py worktree expire` + reconciliation | Unconditionally delete managed worktrees at 72h; safely reconcile younger work and retain manifests for 30 days |

> **Workflow review:** `scripts/_workflow_review_helper.py collect` remains the explicit aggregate-only collector. The manual `opencode-workflow-review` skill can run bounded Luna research over local transcripts and supporting deterministic sources, but cannot edit tracked files; implementation always requires a user-invoked skill in a new chat.

### Job Details

**Daily standup meeting** (`10:00 UTC` weekdays): `daily-meeting.sh` creates a persisted OpenCode chat titled `daily-meeting YYYY-MM-DD`, asks the `daily-meeting` skill to gather data inline, and emails a deep link to the configured recipient. The OpenCode web URL is built as `${OPENCODE_WEB_BASE_URL}/${base64url(project_path)}/session/${session_id}`. The meeting remains interactive: it presents one agenda section at a time and saves `scripts/.daily-meeting-state.json` plus `scripts/.tmp/daily-meeting-summary-<date>.md` only after the user confirms priorities. Manual: `./scripts/daily-meeting.sh` or `/daily-meeting` skill. Env: `DAILY_MEETING_NOTIFY_EMAIL` (or `SERVER_OWNER_EMAIL`/`ADMIN_NOTIFY_EMAIL` fallback), `OPENCODE_WEB_BASE_URL`, `INTERNAL_API_SHARED_TOKEN`, `INTERNAL_API_URL`.

**Deploy status checker** (`*/2 min`): Checks git log for recent commits; if found, queries Vercel API for build status. On `ERROR`/`CANCELED`, dispatches an OpenCode repair chat with the build log. State: `scripts/.deploy-checker-state.json`. Env: `VERCEL_TOKEN`.

**Deterministic stale-code report** (02:00 daily): Runs `find_dead_code.py` across Python, TypeScript, Svelte, and CSS. Only narrow Ruff safe-fix imports may be `deletion_ready`; ambiguous functions, classes, exports, components, and selectors are `review_only` or `suppressed`, including Vite glob, app metadata, computed class, generated, route, fixture, migration, public API, and compatibility cases. Writes gitignored `logs/nightly-reports/stale-code.json` and `.md`, then posts a redacted count/status summary through optional `DISCORD_WEBHOOK_DEV_NIGHTLY`. Cron never edits source or launches OpenCode. Install idempotently with `bash scripts/stale-code-cron-setup.sh`; manual cleanup uses the `remove-stale-code` skill, which revalidates the commit and fingerprints before editing. The legacy `nightly-dead-code-removal.sh` path is a report-only compatibility wrapper.

**Codebase audit** (Mon+Thu 02:00): Uses 2 weeks of git history to find top 5 improvements (security, performance, reliability, quality). Plan mode only -- no implementation. State: `scripts/.audit-state.json`.

**Daily test run** (03:00): Full Playwright E2E plus pytest, Vitest, CLI, and Apple verification for one exact commit. Independent GitHub/CLI/Apple branches start concurrently; Playwright uses a dynamic account queue, while the resource-constrained Apple host remains strictly single-lane. Sends summary email on completion + Discord fallback post (OPE-76), writes `last-passed-tests.json` / `last-failed-tests.json`, pushes one OpenObserve summary, and archives to `test-results/daily-run-YYYY-MM-DD.json`. The scheduled runner is notification-only: it does not start OpenCode auto-fix, so failed-test remediation can never hold the daily lock and block the next scheduled run. Install or audit the complete test schedule with `python3 scripts/test_schedule_setup.py --install|--check`; the managed entries call the engineering wrapper rather than the public CLI. Manual follow-up can still use `scripts/auto_fix_failed_tests.py --from-daily-run` when an operator intentionally wants controller-owned fixes. Env: `E2E_DAILY_RUN_ENABLED=true`, `ADMIN_NOTIFY_EMAIL`, `INTERNAL_API_SHARED_TOKEN`, `OPENCODE_WEB_BASE_URL`, `DISCORD_WEBHOOK_DEV_NIGHTLY` (optional), `DISCORD_WEBHOOK_TEST_FIXES` (optional dedicated manual auto-fix channel).

**Operational monitoring digest** (08:30 UTC daily, host systemd): The CLI-installed host timer invokes the packaged Docker report command for exactly one environment and only the configured email/Discord channels. Host systemd is the sole scheduler; Celery Beat does not schedule this digest. A separate five-minute host watchdog detects missing accepted reports after 26 hours and uses the retrying API-independent notifier for incident and recovery delivery. State, freshness metrics, and redacted monthly JSONL receipts live under `<install>/.openmates/runtime-health/`.

**Release intelligence** (`00:20 daily`, `00:45 Mon`, `01:10 first day`): `scripts/release-intelligence-cron.sh` creates LLM-backed changelog artifacts from git history and prior rollups. Daily mode writes `docs/releases/daily/YYYY-MM-DD.yml` for the previous UTC day. Weekly mode reads the last seven daily artifacts, writes `docs/releases/weekly/YYYY-Www.yml`, and posts a compact Discord summary. Monthly mode reads weekly artifacts for the previous month and writes `docs/releases/monthly/YYYY-MM.yml`. Artifacts include deterministic release readiness, feature availability gates, newsletter include/exclude candidates, and LLM summaries. Env: `GEMINI_API_KEY` or `SECRET__GOOGLE_AI_STUDIO__API_KEY`; optional `DISCORD_WEBHOOK_RELEASE_INTELLIGENCE` with fallback to `DISCORD_WEBHOOK_DEV_NIGHTLY` for weekly summaries. Manual: `scripts/release-intelligence-cron.sh daily|weekly|monthly`.

**Events newsletter campaign drafts** (manual until production gate): The internal newsletter campaign service can load `shared/events/openmates_events.yml`, select published events starting in the next four weeks, and create or reuse a deterministic `openmates_events` campaign draft for the cadence date. This path is internal-only, does not enumerate subscribers, and does not send previews or broadcasts. Future automation may anchor the cadence every 14 days at 09:00 Europe/Berlin only after the exact-payload production consent gate is satisfied.

**Obsidian daily note updater** (every minute): Refreshes today's local daily note under `vaults/memory/Daily Notes/` with changed note links, same-day git commits, and cached server stats. Preserves manual content outside `<!-- AUTO:* -->` sections. Log: `logs/obsidian-daily-note.log`. State: `vaults/memory/.obsidian-auto/daily-note-state/`.

**Prod smoke** (dev-server cron + GitHub Actions): The dev server dispatches `.github/workflows/prod-smoke.yml`, polls the selected run, parses uploaded JSON artifacts, and sends failure-only Discord + email alerts. The workflow itself only executes the selected suite: free logged-out reachability hourly, paid CLI chat at 07/13/19 Berlin, or direct CLI `apps web search` app-skill daily. GitHub Actions secrets: `PROD_BASE_URL`, `OPENMATES_TEST_ACCOUNT_API_KEY`. Dev-server notification env: `DISCORD_WEBHOOK_PROD_SMOKE`, `ADMIN_NOTIFY_EMAIL`, and either `INTERNAL_API_SHARED_TOKEN` or `BREVO_API_KEY`.

**Dependabot version updates** (GitHub native, daily 04:30 UTC): Opens npm/pnpm version-update PRs against `dev`. Routine patch/minor updates use a 48-hour cooldown (`cooldown.default-days: 2`) to avoid newly published malicious npm versions during supply-chain incidents; major updates use a 14-day cooldown for extra stability. This is separate from security-alert processing below, which remains immediate for critical/high/medium advisories. pnpm also enforces `minimumReleaseAge: 2880` minutes in `pnpm-workspace.yaml` so manual and CI dependency resolution follow the same 48-hour delay.

**Issues check**: _Consolidated into daily meeting (2026-03-27)._ Helper `_issues_checker.py` still available as importable library.

**Admin issue investigation**: automatic OpenCode handoff from admin issue reports is disabled. Admin reports still return an issue ID; copy that ID into OpenCode manually when investigation is needed.

**Dependabot check** (hourly at xx:30): Fetches critical/high/medium alerts via `gh` CLI. Dispatches fix session for new or stale (>7 days) alerts. No-ops in seconds when no new alerts are found (no Claude session spawned). Uses `sessions.py deploy` for commits. Resolved entries auto-pruned after 72h. State: `scripts/dependabot-processed.json`.

**EU vulnerability check** (hourly at xx:35, 5 min after Dependabot): Queries OSV + NVD for vulnerabilities Dependabot misses. Cross-refs against `dependabot-processed.json`. No-ops in seconds when no new vulns found. Uses `sessions.py deploy` for commits. Resolved entries auto-pruned after 72h. State: `scripts/eu-vuln-processed.json`.

**Workflow review**: Maintainer-invoked only. Run `python3 scripts/_workflow_review_helper.py collect --since <UTC_ISO> --until <UTC_ISO>` to create a bounded OpenCode, git, and test evidence report under `test-results/workflow-review/`. It never schedules or launches an agent.

**Manual OpenCode workflow review**: The retired daily `01:45 UTC` Luna analysis is disabled. When a maintainer wants a weekly or on-demand review, invoke the `opencode-workflow-review` skill or run `python3 scripts/opencode_chat_improvement_review.py --hours 168 --dry-run-notify`. The runner reads bounded top-level and subagent transcript/tool evidence from the local OpenCode SQLite store, excluding prior analyzer chats, then starts one persisted `openai/gpt-5.6-luna` session using the `opencode-improvement-research` skill and hidden dedicated `cron-research` agent. That agent remains explicitly runnable by the script but is hidden from normal OpenCode agent/mode selection, and is enforced read-only: edit, Bash, child-agent, question, and todo tools are denied. Luna researches current skills, hooks, agents, instructions, deterministic guards, tests, and official tool documentation where needed. Latest plus dated JSON/Markdown reports are written under gitignored `logs/nightly-reports/opencode-improvements/`; optional Discord notification is available for explicit manual runs. The workflow never edits tracked files, invokes an editing workflow, commits, or deploys. A maintainer later starts a new chat and explicitly invokes `implement-opencode-improvements` to select and revalidate report items before normal verified changes. Remove old managed cron entries with `python3 scripts/opencode_chat_improvement_review.py --uninstall-cron`; `--install-cron` is retired.

**Security audit** (Tue+Fri 02:30): Reviews files changed since last audit. Top 5 critical security issues with OWASP mapping. Monthly full sweep. Acknowledged findings suppressed via `_security_helper.py acknowledge`. State: `.claude/security-audit-state.json` (gitignored).

**Red team probe** (Wed+Sat 02:30): Simulates external attacker against dev endpoints (GET/HEAD/OPTIONS only, max 5 req/endpoint, 20-min timeout). Three phases: reconnaissance, external probing, safe exploitation. No destructive requests. Uses `--permission-mode plan` with `--allowedTools "Read,Grep,Glob,Bash(curl *)"`.

**Code structure cleanup** (02:50 daily): Scans for repository hygiene issues — gitignore gaps, open-source readiness (leaked internal values), folder organization, file consolidation, naming inconsistencies, stale artifacts. Haiku, plan mode, 25-min soft limit / 30-min hard kill. Suggestions only, no code changes. Uses `_nightly_scanner_helper.py` with rotating sector schedule. Output: `logs/nightly-reports/code-structure.json`. Manual: `./scripts/nightly-code-structure.sh [--dry-run]`.

**UI design review** (Tue+Fri 04:10): Starts a read-only OpenCode chat that inspects the current web and Apple UI codebase, using recent UI commits only as prioritization context. Reports top recommendations for design-system consistency, web/Apple UI unification, redundant component/style patterns, readability, settings UI standards, and hook/lint opportunities justified by repeated current-code or recent-commit patterns. Output: `logs/nightly-reports/ui-design-review.json`. Manual: `./scripts/nightly-ui-design-review.sh [--dry-run]`.

**Apple parity review** (Mon+Thu 04:30): Generates `test-results/apple-parity-inventory.json`, then starts a Linux-safe read-only OpenCode chat that inspects current Swift and web source, `apple/SVELTE_SWIFT_COUNTERPARTS.md`, and recent web UI commits to recommend the highest-priority Apple parity follow-ups. Output: `logs/nightly-reports/apple-parity-review.json`. Manual: `./scripts/nightly-apple-parity-review.sh [--dry-run]`.

**SEO audit** (Sun 04:50): Starts a read-only OpenCode chat that combines safe production GET/HEAD checks against `openmates.org` with current SvelteKit source inspection. This is deeper than the daily meeting SEO smoke check and reports prioritized improvements for sitemap coverage, SSR/prerender, metadata, OG/Twitter tags, JSON-LD, hreflang, and internal linking. Output: `logs/nightly-reports/seo-audit.json`. Manual: `./scripts/nightly-seo-audit.sh [--dry-run]`.

**Technical debt scan + recommendations** (Sun 03:20): Runs `technical_debt_scan.py` without AI to rank source hotspots by size, complexity-style signals, suppressions, broad exception/catch use, debug logging, store-internal imports, backend cross-skill imports, duplication fingerprints, test-name proximity, and six-month churn. The scanner compares against `scripts/.technical-debt-state.json` so the follow-up can consider previous-run deltas. After reports are written, `_technical_debt_helper.py` starts a read-only OpenCode chat to recommend the top five next improvement steps. Outputs: `logs/nightly-reports/technical-debt.json`, `logs/nightly-reports/technical-debt.md`, and `logs/nightly-reports/technical-debt-analysis.json` summary metadata. Manual: `./scripts/weekly-technical-debt.sh [--dry-run|--scan-only]`.

**Deterministic contract audits + recommendations** (Mon 05:15): Runs static repo-specific checks without AI or network calls: backend app/skill architecture boundaries, encryption key access patterns, settings UI contract rules, app skill/provider metadata, and export/import invariants. Writes `test-results/contract-audits/latest.json`, a dated weekly JSON artifact, and `logs/nightly-reports/contract-audits.json` for daily-meeting and on-demand agent processing. Sends a compact email summary via Brevo (`BREVO_API_KEY`) or the internal test-summary email endpoint (`INTERNAL_API_SHARED_TOKEN`). After the JSON is written, starts a read-only OpenCode chat via `_contract_audit_review_helper.py` to analyze the report and recommend the top next steps; that chat is referenced from `logs/nightly-reports/contract-audit-review.json`. Manual: `./scripts/weekly-contract-audits.sh [--dry-run]`, `./scripts/weekly-contract-audits.sh --skip-review`, or `python3 scripts/run_contract_audits.py --dry-run`.

**Docker cleanup** (Sun 02:00): `docker system prune` for dangling images, stopped containers, unused volumes.

**OpenCode session cleanup** (01:30 daily): Deletes non-TODO OpenCode chats older than 14 days and TODO chats older than the 90-day hard limit, including archived chats, using `opencode session delete` so session storage is removed with the SQLite row. Override with `OPENMATES_OPENCODE_RETENTION_DAYS` and `OPENMATES_OPENCODE_TODO_RETENTION_DAYS`. Logs to `logs/opencode-cleanup.log` and writes `logs/nightly-reports/session-cleanup.json` for daily meeting consumption. Manual: `./scripts/cleanup-opencode-sessions.sh`.

**Agent worktree hard expiry, checkpoint integration, and reconciliation** (hourly): First runs `python3 scripts/sessions.py worktree expire --max-age-hours 72`, before any network operation. This is a hard storage invariant: every managed worktree at least 72 hours old is deleted regardless of active/merged status, dirty or unique files, holds, leases, or classification. Deletions retain compact source-free manifests for 30 days. Creation also runs expiry and refuses a new worktree at 200 managed directories, below 30 GiB free, or at 85% filesystem use, so a cleanup failure cannot silently exhaust the host. The job then fetches `origin/dev`, runs `python3 scripts/sessions.py worktree auto-integrate`, and runs `python3 scripts/sessions.py worktree reconcile --target origin/dev --idle-hours 48 --apply-safe` for safely classified younger work. Auto-integration processes only current local checkpoint refs from opted-in mutating sessions after the grace period and invokes the normal exact-base deploy path with no gate waivers. Reconciliation without `--apply-safe` remains report-only. If a managed directory still points to Git administrative metadata that no longer exists, safe reconciliation moves the complete directory to the sibling `.openmates-worktree-recovery/` area, retains any checkpoint ref, and records the recovery path before retiring stale session metadata. Missing paths are retired only after the normal idle threshold. Install the tracked user systemd timer (the cron-equivalent used for this job) with `bash scripts/worktree-reconciliation-setup.sh`; the installer selects the stable `.openmates-runtime/product-stack` checkout when it is a worktree of the same canonical repository, so a dirty or stale root copy of `sessions.py` is never the scheduled executable. Manual dry run: `python3 scripts/sessions.py worktree auto-integrate --dry-run`. Manual reconciliation report: `python3 scripts/sessions.py worktree reconcile --target origin/dev`. Immediate reviewed cleanup must be explicitly scoped, for example `--only <SESSION_ID> --approve-obsolete <SESSION_ID> --idle-hours 0 --apply-safe`; never lower the reconciliation threshold without `--only`.

**Agent trigger watcher** (`@reboot`): Polls `scripts/.agent-triggers/` every 5s for JSON trigger files from admin sidecar. Dispatches OpenCode investigation chats; completed triggers moved to `done/`.

### Agent CLI Dispatch

Most background maintenance helpers use `scripts/_opencode_utils.py:run_opencode_session()` which invokes:

```bash
opencode run \
  --title "<session-title>" \
  --format json \
  [--dangerously-skip-permissions] \
  "Read scripts/.tmp/<prompt>.md in full and follow all instructions precisely."
```

Session IDs are extracted from OpenCode JSONL output and logged for traceability. Read-only jobs include explicit no-edit/no-commit instructions in the prompt message; write jobs use `--dangerously-skip-permissions`.

The daily standup is the exception: `scripts/_opencode_daily_meeting.py` invokes `opencode run --format json --title "daily-meeting <date>"` so the chat appears directly in OpenCode web. Cron should configure the public web base URL and recipient via environment, not source code.

### Manual Invocation

Most maintenance scripts support `--dry-run` (show prompt, skip agent) or `--force` (bypass guards):

```bash
./scripts/check-deploy-status.sh --dry-run
python3 scripts/stale_code_daily.py --dry-run-notify
python3 scripts/find_dead_code.py --category python --json
./scripts/run-tests-daily.sh --force
python3 scripts/_workflow_review_helper.py collect --since 2026-07-03T00:00:00Z --until 2026-07-10T00:00:00Z
python3 scripts/opencode_chat_improvement_review.py --hours 168 --dry-run-notify
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
