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
python3 scripts/tests.py campaign start --session <session-id> --json
python3 scripts/tests.py campaign status --campaign <campaign-id> --json
```

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

### Step 3: Investigate and persist every attempt

Apply the smallest root-cause fix. After each rejected, failed, blocked, or
successful approach, append an attempt with its run IDs and changed files:

```bash
python3 scripts/tests.py campaign attempt --group <group-id> \
  --approach "<what was tried>" --outcome <failed|blocked|green|rejected> \
  --summary "<result>" --run-key <run-id> --changed-file <path>
```

Never repeat an approach already recorded as failed or rejected.

### Step 4: Verify the exact group

```bash
python3 scripts/tests.py run --campaign <campaign-id> --group <group-id>
```

This selection comes from Directus and includes every durable group member. Do
not replace it with `--only-failed` or a single first spec. Playwright changes
still require the normal scoped deploy and expected-commit gate.

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
- **Acceptance before edits** — existing assertions may be derived automatically; ambiguous behavior must be clarified.
- **Fix console errors in app code** — never suppress them in tests
- **NEVER run vitest/playwright locally** — always dispatch via `scripts/tests.py run`
- **Group fixes by root cause** — one commit per root cause group, not per test
- **No partial success** — a blocked required group keeps the campaign blocked and resumable.
