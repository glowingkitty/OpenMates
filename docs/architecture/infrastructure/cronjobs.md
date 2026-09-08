---
status: active
last_verified: 2026-09-07
key_files:
- .github/dependabot.yml
- pnpm-workspace.yaml
- scripts/_dependabot_helper.py
- scripts/run_tests.py
- scripts/nightly-dead-code-removal.sh
- scripts/stale_code_daily.py
- scripts/stale-code-cron-setup.sh
- scripts/weekly-technical-debt.sh
- scripts/technical_debt_scan.py
- scripts/security-audit.sh
- scripts/weekly-contract-audits.sh
- scripts/run_contract_audits.py
- scripts/contract_audits.py
- scripts/prompts/contract-audit-review.md
- scripts/update_obsidian_daily_note.py
- scripts/_daily_meeting_helper.py
- scripts/release-intelligence-cron.sh
- scripts/release_intelligence.py
claims:
- id: arch-infrastructure-cronjobs-behavior
  type: unit
  claim: Scheduled Cronjobs is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - .github/dependabot.yml
  - pnpm-workspace.yaml
  - scripts/_dependabot_helper.py
  - scripts/run_tests.py
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
    path: scripts/run_contract_audits.py
---

# Scheduled jobs and retired OpenCode automation

Automatic OpenCode launches were turned off and their obsolete scheduling implementations removed under TASK-7543 on September 7, 2026. Do not reinstall old launcher units or copy historical cron examples into a live crontab. The new `openmates-ci-coordinator` is an independent GitHub queue/service and remains intact.

## Retained jobs and manual tools

| Surface | Retained responsibility |
| --- | --- |
| `stale_code_daily.py`, `stale-code-cron-setup.sh` | Deterministic stale-code report; no automatic source edits |
| `technical_debt_scan.py`, `weekly-technical-debt.sh` | Deterministic JSON/Markdown scan; `--scan-only` remains accepted |
| `run_contract_audits.py`, `weekly-contract-audits.sh` | Deterministic contract audits and reports; `--skip-review` remains accepted |
| `apple_parity_audit.py` | Deterministic Apple/web parity inventory |
| Dependency/container security scanners and digest | Preserve collection, state, reports and notification delivery |
| `release-intelligence-cron.sh` | Daily, weekly and monthly changelog collection |
| `update_obsidian_daily_note.py` | Daily-note statistics and activity |
| Managed GitHub test schedules | Separate CI ownership; scheduler removal does not dispatch or relocate tests |
| Linear archive and artifact maintenance | Retained installer: `linear-cron-setup.sh` |
| `sessions.py` routing/deploy and worktree reconciliation | Shared repository lifecycle, separate from OpenCode automatic chat scheduling |
| `_daily_meeting_helper.py dry-run` | Manual data gathering and prompt preview without launching AI |
| Manual OpenCode transcript/review tools and Claude compatibility | Preserved for existing records and explicit use |

## Removed implementations

The `sessions.py monitor` command, cadence helper, `monitor_ready` operation and hook timer delivery are removed. General continuations remain for Task reconciliation, media and scoped decisions; they are shared infrastructure, not the retired monitor. Historical monitor metadata is retained but cannot be claimed for delivery.

The Vercel failure-to-repair launcher, deep AI security review and legal/compliance AI review launchers are removed; their prompt/folder requirements and historical findings remain for TASK-8338.

The Linear label poller, host trigger watcher, weekday meeting launcher, nightly issue review, codebase audit, nightly quick-win/pattern/code-structure/UI/Apple/SEO launchers and weekly AI recommendation helpers are retired. Their historical reports, original task/worktree records and prompt requirements remain available. Removing a launcher does not remove its deterministic scanner. EU vulnerability entry points retain deterministic collection and reporting, without remediation chats or legacy dispatch tracking. The Dependabot launcher tail is removed; its automatic schedule stays off and deterministic digest collection stays intact. Security audit/red-team entry points ingest existing snapshots through the digest adapter, which retains missing/stale snapshot checks; they do not create a fresh AI review.

OpenCode-only runtime registrations are narrowly removed after inspecting their actual definitions and dependencies. Recoverable local unit/crontab copies are in `logs/codex-orchestration/2026-09-07-6989/scheduler-registration-backup/`. No product service or shared work-life `allowed` guard is part of this removal.

## Future workflow requirements — TASK-8338

The replacement is backlog work due September 14, 2026; no new durable scheduler is introduced here. Review useful scheduled security reviews, marketing review, contract review and event-triggered investigations as OpenMates workflows. Preserve explicit schedules, bounded costs, deduplication, quiet unchanged-state behavior and a daily digest where appropriate. Discover Specifications and Plans before implementing replacement behavior.

Historical cadence for migration review, **not active installation instructions**:

| Retired AI activity | Previous cadence |
| --- | --- |
| Daily meeting | Weekdays 10:00 UTC |
| Codebase recommendations | Monday/Thursday 02:00 UTC |
| Quick wins, pattern consistency, code structure | Weekdays 02:15 / 02:35 / 02:50 UTC |
| Security code review / red-team review | Twice weekly |
| Deep security review | Weekdays 04:00 UTC |
| Legal/compliance review | Monday full scan, Thursday delta |
| UI design review | Tuesday/Friday 04:10 UTC |
| Apple parity review | Monday/Thursday 04:30 UTC |
| SEO review | Sunday 04:50 UTC |
| Technical-debt recommendations | Sunday 03:20 UTC |
| Contract recommendations | Monday 05:15 UTC |

Read the real current runtime definitions before changing any retained schedule. Historical cron documentation is not proof that a job is installed or authorized to run.

## Retained worktree maintenance

The independent `worktree-reconciliation-setup.sh` service retains its existing
`sessions.py worktree expire --max-age-hours 72` and
`sessions.py worktree reconcile --target origin/dev --idle-hours 48 --apply-safe`
operations. It preserves source-free manifests for 30 days. This shared
repository maintenance is outside OpenCode scheduler retirement; no registration
or runtime state is changed by this removal.
