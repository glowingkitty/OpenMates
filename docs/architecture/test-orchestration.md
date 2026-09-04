# Test Orchestration

Status: active
Last verified: 2026-08-27

OpenMates uses `scripts/tests.py` as the deterministic test entry point, the
private engineering control plane as the canonical coordination store, and
`scripts/run_tests.py` as the execution engine for GitHub Actions-backed test
runs. New workflows should call
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

## Nightly Subject And Backend Preconditions

Delayed `--daily` runs test the latest `origin/dev` commit, not whichever commit
the dev host checkout happened to have when the cron command started. The runner
refreshes `origin/dev`, records that SHA as the subject, gates Vercel against the
same SHA, and passes the full subject through `checkout_ref` to Playwright jobs.
`OPENMATES_TEST_SUBJECT_COMMIT` remains the explicit override for commit-bound
verification sessions.

Default development Playwright runs use real dev backend containers with cached
external-provider replay enabled (`MOCK_EXTERNAL_APIS=true`). The live-mock
preflight fails closed when required running containers such as `api`,
`app-ai-worker`, or `task-worker` would ignore those markers. Conditional worker
containers that are intentionally absent from a reduced dev service set are
reported as warnings rather than blocking every spec before dispatch; specs that
actually require one of those queues still fail normally and are triaged as real
test/runtime failures.

The reusable Playwright workflow is branch-defined but checks out a subject
commit supplied by the runner. Workflow-local guard scripts must therefore be
backward-compatible with historical `checkout_ref`s: if a guard script is absent
from the checked-out subject, the workflow must warn or use a stable inline
fallback instead of failing before Playwright starts.

## Release Core Journeys

`.github/workflows/release-core-journeys.yml` is the deliberate exception to the
local `scripts/tests.py` entry point. A required PR status must belong directly
to the pull request, while GitHub-hosted runners cannot use the dev host's Docker
and Directus control plane. The workflow therefore reads the canonical matrix
from `scripts/run_tests.py`, calls the reusable single-spec workflow, and emits
one aggregate `Release Gate / Core Journeys` result.

The Docker-backed backend remains under dev-host control. An operator runs
`scripts/prepare_release_candidate.py` under the sessions.py Docker lock; only
after core services are recreated and healthy does that command publish the
`Dev Release Candidate / Prepared` status on the exact commit. The preparation
command uses the existing local Vercel API gate to prove the exact dev SHA is
Ready before it recreates Docker services with the root `.env` interpolation
contract. It then runs the cloud-overlay boot check so disabled billing routes or
missing worker markers fail before success is published. GitHub reads this
attestation and the Vercel commit status before browser jobs start; it receives
neither credential.

The release workflow uses accounts 1-4 and the reusable Playwright workflow
serializes all runs by account number. This prevents release, hourly, nightly,
and manual jobs from using the same persistent account concurrently.

## Concurrency And Resource Admission

- Read-only browser phases take shared `dev-stack` leases. Docker restart,
  rebuild, migration, and restore operations take exclusive leases for the same
  resource, so independent browser jobs overlap but runtime mutation does not.
- Every Playwright dispatch also takes one exclusive `playwright-account:<slot>`
  lease. Normal slots are allocated dynamically; credential-mutating specs keep
  their fixed reserved slots. A successful per-slot preflight is cached for 15
  minutes, while a failure invalidates it.
- The full Playwright run is a dynamic queue rather than fixed waves: an account
  receives its next spec as soon as its current spec and artifact collection
  finish. There is no batch-wide wait for the slowest spec.
- Nightly pytest, Vitest, Apple, CLI, and browser branches start independently.
  GitHub workflows check out the exact subject SHA. Production smoke dispatch is
  independent of dev Docker restart state.
- Daily browser coverage is partitioned from the source-controlled
  `CRITICAL_TEST_REGISTRY`: core chat, signup/auth, and billing run first, then
  the disjoint broad set runs even when a critical product assertion fails.
  `audit_critical_test_registry()` fails closed for duplicates, missing files,
  invalid metadata, or newly discovered release-critical specs without a
  classification.
- GitHub-backed daily suites share one thread-safe dispatch circuit. The runner
  checks the bounded core request budget before bulk Playwright dispatch and
  opens the circuit on a hard 403 rate limit. Exactly one infrastructure parent
  is emitted; remaining specs are `blocked_by_parent` and are not retried.
- The 8 GB Apple host is intentionally one lane. Repository sync and every iOS,
  macOS, and watchOS native command share `/tmp/openmates-apple-xcode.lock`.
  Do not add parallel simulators, concurrent Xcode builds, persistent per-chat
  Mac worktrees, or duplicate DerivedData caches.

The tracked host schedule is installed and audited with
`python3 scripts/test_schedule_setup.py --install|--check`. It invokes only the
engineering `scripts/tests.py` wrapper and is not part of self-hosted images or
the public OpenMates CLI.

## State Storage

- `test_current_state`: latest stable status plus any active queued/running run
  for each test. A failed test can show `stable_status=failed` and
  `active_status=running` while a rerun is in progress.
- `test_runs`: one row per dispatched or discovered GitHub Actions/Apple run.
- `test_results`: per-test result events used for history and triage.
- `test_claims`: active, completed, released, and expired debug claims so
  parallel workers do not pick the same root-cause group.
- `test_debug_campaigns`: durable selected scope, lifecycle, blockers, and
  completion summaries for failed-test work across OpenCode sessions.
- `test_debug_groups`: complete group membership, expected behavior,
  acceptance criteria, root-cause attempts, child relationships, and red/green
  evidence. Claims reference these records but do not replace them.
- `test_catalog`: canonical suite/test inventory, including Apple tests.
- `test-results/*.json`: non-authoritative import/export and artifact files only.
  Do not read them as the source of truth for current failures or claims.

Run summaries keep executed product failures, infrastructure incidents, and
blocked dependants separate. Notification attempts happen after test execution
and record bounded per-channel receipts under `flags.notification_channels`.
Direct Brevo and Discord 2xx responses are `provider_accepted`; internal email
queue acceptance is `queued_unconfirmed`. Channel exceptions never alter test
counts or prevent the other channel from being attempted, and the dated daily
archive is written only after these receipts are persisted.

## Debugging Flow

1. Create or resume scope with `python3 scripts/tests.py campaign start --session <id> --json`.
2. Inspect the durable campaign with `python3 scripts/tests.py campaign status --campaign <id> --json`.
3. Lease one complete group with `python3 scripts/tests.py campaign next --campaign <id> --lease --session <id> --json`.
4. Read every member test and persist expected behavior plus concrete acceptance criteria with `campaign prepare` before source edits.
5. Persist every failed, rejected, blocked, or successful approach with `campaign attempt`.
6. Verify exact Directus-backed membership with `python3 scripts/tests.py run --campaign <id> --group <id>`.
7. Complete the group only after every member has passing run/result evidence, then continue until all selected and child groups are green.

Create the bounded campaign with `campaign start --daily-recovery`; ordinary
campaigns cannot opt into its completion policy after creation. It then uses
`python3 scripts/tests.py campaign milestone --campaign <id> --run <run-id>`.
It completes only from a full daily run with all critical tests green, no
dispatch/infrastructure blockers, direct provider acceptance for configured
email and Discord, at most 50 executed product failures, and ownership of every
remaining failed canonical key by a durable campaign group. Normal campaigns
retain their stricter zero-failure finalization policy.

For explicitly requested parallel work, `campaign dispatch` selects only narrow
groups whose deterministic linked-file boundaries do not overlap, atomically
leases each group, and launches one visible OpenCode chat per group. Worker chats
investigate and edit in isolated session worktrees but do not deploy; the
coordinator reviews and integrates the resulting patches before commit-scoped
verification. `campaign status` exposes every active worker and lease.

New failures exposed by a campaign-bound verification become explicit child
groups. A required human or external decision leaves the campaign `blocked`
with a question and exact next action; there is no partially-successful terminal
state. Campaign completion uses individual group evidence and does not require
an additional combined selected-set run.

## Importing Runs

- `scripts/sync-test-results.sh --latest` downloads the latest aggregated GitHub
  Actions artifact and imports it into Directus through `scripts/tests.py import-run`.
- For local/dev backfills, authenticate with a valid Directus access token and run
  `CMS_URL=http://127.0.0.1:8055 DIRECTUS_TOKEN=<token> python3 scripts/tests.py import-run test-results/last-run.json --source github_actions`.
