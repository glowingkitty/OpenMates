# Test Orchestration

Status: active
Last verified: 2026-06-19

OpenMates uses `scripts/tests.py` as the deterministic test control plane and
`scripts/run_tests.py` as the execution engine for GitHub Actions-backed test
runs. New workflows should call `scripts/tests.py run ...` rather than calling
the runner directly so status, history, and running-state bookkeeping stay in
sync.

## Responsibilities

- `scripts/tests.py` owns current test state, append-only history, failure
  triage, linked-file hints, and parallel-safe failure leases.
- `scripts/run_tests.py` owns the existing test execution machinery, including
  pytest/vitest GitHub Actions dispatch, Playwright workflow dispatch, artifact
  downloads, screenshots, Markdown reports, and notifications.
- `scripts/auto_fix_failed_tests.py` consumes deterministic triage groups from
  `scripts/tests.py` and verifies through `scripts/tests.py run`.

## State Files

- `test-results/tests-state.json`: latest known status for each test.
- `test-results/tests-history.jsonl`: append-only started/passed/failed/skipped
  events for timeline views.
- `test-results/failed-test-leases.json`: active, completed, and released debug
  leases so parallel workers do not pick the same root-cause group.
- `test-results/test-failure-triage.json`: latest deterministic failure ranking.
- `test-results/test-file-index.json`: deterministic test-to-source hints.
- `test-results/runs/*.json`: normalized run archives.

## Debugging Flow

1. Inspect status with `python3 scripts/tests.py status`.
2. Lease the next failure with `python3 scripts/tests.py next --lease --session <id> --json`.
3. Read only the leased failure details and linked files before editing.
4. Verify through the returned `verification_command`.
5. Mark the lease completed or released after deploy or blocker discovery.
