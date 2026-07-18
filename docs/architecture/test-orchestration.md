# Test Orchestration

Status: active
Last verified: 2026-07-17

OpenMates uses `scripts/tests.py` as the deterministic test control plane,
Directus as the canonical coordination store, and `scripts/run_tests.py` as the
execution engine for GitHub Actions-backed test runs. New workflows should call
`scripts/tests.py run ...` rather than calling the runner directly so status,
history, claims, and running-state bookkeeping stay in sync.

## Responsibilities

- `scripts/tests.py` owns current test state, append-only history, failure
  triage, linked-file hints, and parallel-safe failure claims in Directus.
- Directus collections `test_catalog`, `test_runs`, `test_results`,
  `test_current_state`, and `test_claims` are the shared source of truth across
  assistant chats, dev-server-triggered GitHub Actions, external GitHub Actions
  runs, and Apple tests.
- `scripts/run_tests.py` owns the existing test execution machinery, including
  pytest/vitest GitHub Actions dispatch, Playwright workflow dispatch, artifact
  downloads, screenshots, Markdown reports, and notifications.
- `scripts/auto_fix_failed_tests.py` consumes deterministic triage groups from
  `scripts/tests.py` and verifies through `scripts/tests.py run`.

## State Storage

- `test_current_state`: latest stable status plus any active queued/running run
  for each test. A failed test can show `stable_status=failed` and
  `active_status=running` while a rerun is in progress.
- `test_runs`: one row per dispatched or discovered GitHub Actions/Apple run.
- `test_results`: per-test result events used for history and triage.
- `test_claims`: active, completed, released, and expired debug claims so
  parallel workers do not pick the same root-cause group.
- `test_catalog`: canonical suite/test inventory, including Apple tests.
- `test-results/*.json`: non-authoritative import/export and artifact files only.
  Do not read them as the source of truth for current failures or claims.

## Debugging Flow

1. Inspect Directus-backed status with `python3 scripts/tests.py status --json`.
2. Lease the next failure with `python3 scripts/tests.py next --lease --session <id> --json`.
3. Read only the leased failure details and linked files before editing.
4. Verify through the returned `verification_command`.
5. Mark the lease completed or released after deploy or blocker discovery.

## Importing Runs

- `scripts/sync-test-results.sh --latest` downloads the latest aggregated GitHub
  Actions artifact and imports it into Directus through `scripts/tests.py import-run`.
- For local/dev backfills, authenticate with a valid Directus access token and run
  `CMS_URL=http://127.0.0.1:8055 DIRECTUS_TOKEN=<token> python3 scripts/tests.py import-run test-results/last-run.json --source github_actions`.
