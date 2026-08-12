---
name: openmates:fix-tests
description: Create or resume a durable failed-test campaign, then fix and verify every selected root-cause group
user-invocable: true
argument-hint: "[--rerun] [spec-name]"
---

## Instructions

You are the orchestrator for a durable failed-test campaign. Continue until every
selected and newly exposed child group is green, or the current group has a
structured blocker requiring user or external input.

Directus is the canonical test state store. Use `scripts/tests.py` commands for
status, triage, claims, history, and reruns. Do not read `test-results/*.json`
as the source of truth; those files are import/export artifacts only.

### Step 1: Create or resume the campaign

```bash
python3 scripts/tests.py campaign list --active --overlap-current-failures --json
python3 scripts/tests.py campaign start --session <session-id> --json
python3 scripts/tests.py campaign status --campaign <campaign-id> --json
```

Always list campaigns first. If the current session already has an active or
blocked campaign, resume that campaign. If another active campaign overlaps the
current failures, do not start a duplicate or take over its session. Use the
listed `status_command` or resume in the original coordinator chat shown by
`session_id`; only create a new campaign when the list is empty or does not
overlap the current failures.

The initial selected manifest is durable. If a campaign-bound verification
exposes a new failure, the control plane adds a child group and records why the
scope expanded. Never substitute `test-results/*.json` or chat notes for this
campaign state.

### Step 2: Lease and prepare one group

```bash
python3 scripts/tests.py campaign next --campaign <campaign-id> --lease --session <session-id> --json
```

Read every member test, its failure evidence, and linked source. Before editing,
derive concrete expected behavior and acceptance criteria from existing
assertions, then persist them:

```bash
python3 scripts/tests.py campaign prepare --group <group-id> \
  --expected-behavior "<observable expected behavior>" \
  --criterion "<first concrete assertion>" \
  --criterion "<second concrete assertion>"
```

If the test and product disagree, or the apparent fix changes auth, encryption,
billing, privacy, permissions, sync, API, or another high-risk contract, block
the group and clarify or create a dedicated product spec. Do not infer behavior.

### Parallel worker dispatch

When the user explicitly requests simultaneous debugging, use the deterministic
dispatcher instead of manually choosing groups:

```bash
python3 scripts/tests.py campaign dispatch --campaign <campaign-id> \
  --session <coordinator-session> --max-workers 3 --json
```

Use `--dry-run --json` first when you need to explain which groups would launch
and why other groups are skipped. The dispatcher leases each exact group before
launching a visible interactive OpenCode chat. It only selects narrow, low-risk
groups with non-overlapping linked-file boundaries. Worker chats may research in
that same chat, but they must submit `campaign intent` and wait for coordinator
approval before source edits. They must not deploy or commit independently; the
coordinator harvests finished workers, integrates their patches serially, then
deploys and verifies. Inspect active workers with `campaign status`, which
includes chat names, leases, groups, intent status, finish status, write sets,
changed files, and expiry.

### Step 3: Investigate and persist every attempt

Apply the smallest root-cause fix. After each rejected, failed, blocked, or
successful approach, append an attempt with its run IDs and changed files:

```bash
python3 scripts/tests.py campaign attempt --group <group-id> \
  --approach "<what was tried>" --outcome <failed|blocked|green|rejected> \
  --summary "<result>" --run-key <run-id> --changed-file <path>
```

Never repeat an approach already recorded as failed or rejected.

For a parallel worker, source edits require an approved fix intent first:

```bash
python3 scripts/tests.py campaign intent --group <group-id> --lease <lease-id> \
  --worker <worker-id> --base-commit <sha> \
  --hypothesis "<root-cause hypothesis>" \
  --write-file <path> --verification-command "<exact group verification>"
```

The coordinator approves only current, non-overlapping write sets:

```bash
python3 scripts/tests.py campaign approve-intent --group <group-id> \
  --lease <lease-id> --session <coordinator-session> --current-commit <sha>
```

If the smallest correct fix needs files outside the leased boundary, the worker
records a boundary request and stops until the coordinator expands or blocks the
scope:

```bash
python3 scripts/tests.py campaign boundary --group <group-id> --lease <lease-id> \
  --worker <worker-id> --requested-file <path> \
  --reason "<why this file is required>" --hypothesis "<updated hypothesis>"
```

The coordinator can approve that explicit expansion before approving the intent:

```bash
python3 scripts/tests.py campaign approve-boundary --group <group-id> \
  --lease <lease-id> --session <coordinator-session>
```

After approved edits, the worker records a harvestable checkpoint rather than
completing the lease or group:

```bash
python3 scripts/tests.py campaign finish-worker --group <group-id> \
  --lease <lease-id> --worker <worker-id> --base-commit <sha> \
  --changed-file <path> --summary "<what changed>" \
  --verification-command "<exact group verification>"
```

`finish-worker` persists `worker_finish.harvest` with the worker OpenCode
session, chat inspection command, exact `sessions.py worktree checkpoint`
command, changed files, and patch diff template. The coordinator should read the
`harvest_command` from `campaign status --json`, checkpoint that worker, review
the resulting patch artifact, and only then integrate and verify serially.

### Step 4: Verify the exact group

```bash
python3 scripts/tests.py run --campaign <campaign-id> --group <group-id>
```

This selection comes from Directus and includes every durable group member. Do
not replace it with `--only-failed` or a single first spec. Playwright changes
still require the normal scoped deploy and expected-commit gate.

If a scoped `sessions.py deploy` integrates the fix before this verification or
any Docker/proof step, treat that worktree as closed for subject-commit-bound
evidence. Start a fresh `sessions.py` session/worktree, then rerun the exact
campaign command against the deployed commit:

```bash
python3 scripts/sessions.py start --mode testing --task "Verify <campaign/group> after deploy"
python3 scripts/tests.py run --campaign <campaign-id> --group <group-id>
```

Do not retry campaign runs, Docker restarts, gate-deploy checks, or proof-video
commands from a worktree after the routing guard reports it is already merged.

After all members have passing evidence:

```bash
python3 scripts/tests.py campaign complete-group --group <group-id> --commit <sha>
python3 scripts/tests.py complete --lease <lease-id> --commit <sha> --require-passing
```

### Step 5: Continue until campaign completion

Read `campaign status`, then run `campaign next` again. Individual group passes
are sufficient; the user explicitly chose not to require an additional combined
campaign-wide run. Do not stop while another selected or child group is pending.

For a genuine user/external blocker:

```bash
python3 scripts/tests.py campaign block --group <group-id> \
  --reason "<why work cannot continue>" --question "<required decision>" \
  --next-action "<exact resume action>"
```

### Rules

- **Campaign state is canonical** — acceptance, attempts, evidence, blockers, and child groups belong in Directus.
- **Always lease the durable group** before debugging so parallel workers do not collide.
- **Visible OpenCode only** — parallel workers use `sessions.py spawn-chat`; never launch Claude or hidden disposable sessions.
- **Centralize integration** — parallel workers do not deploy independently.
- **Intent before worker edits** — worker chats research first, submit a bounded fix intent, and wait for coordinator approval before mutation.
- **Edit gate is deterministic** — worker edits are hook-blocked unless the active lease has an approved intent containing the edited file.
- **Finish before harvest** — worker chats record `finish-worker`; the coordinator integrates and verifies serially.
- **Acceptance before edits** — existing assertions may be derived automatically; ambiguous behavior must be clarified.
- **Fix console errors in app code** — never suppress them in tests
- **NEVER run vitest/playwright locally** — always dispatch via `scripts/tests.py run`
- **Group fixes by root cause** — one commit per root cause group, not per test
- **No partial success** — a blocked required group keeps the campaign blocked and resumable.
