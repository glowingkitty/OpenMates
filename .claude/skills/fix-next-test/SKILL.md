---
name: openmates:fix-next-test
description: Resume the next root-cause group in a durable failed-test campaign
user-invocable: true
argument-hint: "[spec-name] [--skip-session] [--rerun-only]"
---

## Instructions

This is a thin resume wrapper around `fix-tests`, not an independent workflow.
It processes one durable root-cause group, then leaves the campaign ready for the
next invocation.

Directus is the canonical test state and claim store. Use `scripts/tests.py`
commands for current failures, triage, claims, and reruns. Do not use
`test-results/*.json` as the source of truth; those files are import/export
artifacts only.

### Step 1: Create or resume campaign state

```bash
python3 scripts/tests.py campaign start --session <session-id> --json
python3 scripts/tests.py campaign status --campaign <campaign-id> --json
python3 scripts/tests.py campaign next --campaign <campaign-id> --lease --session <session-id> --json
```

If a specific spec was supplied, pass its canonical key with `campaign start
--test-key playwright::<spec-name>` when creating a new campaign. Do not bypass
campaign persistence.

- `<spec-name>`: Override auto-pick — fix this specific spec instead
- `--skip-session`: Skip `sessions.py start` (already in a session)
- `--rerun-only`: Just rerun all currently-failed tests and report results, don't fix anything

### Step 2: Execute one group through the shared contract

Follow `fix-tests` Steps 2-4 exactly:

```bash
python3 scripts/tests.py campaign prepare --group <group-id> --expected-behavior "..." --criterion "..."
python3 scripts/tests.py campaign attempt --group <group-id> --approach "..." --outcome <outcome>
python3 scripts/tests.py run --campaign <campaign-id> --group <group-id>
python3 scripts/tests.py campaign complete-group --group <group-id> --commit <sha>
```

Persist acceptance criteria before source edits and every attempt after it is
known. Verify all group members, not only the first test returned by triage.

If a scoped `sessions.py deploy` integrates the fix before the group rerun,
the current worktree is closed for subject-commit-bound evidence. Start a fresh
`sessions.py` session/worktree, then rerun the same campaign/group command from
that new session. Do not retry campaign runs, Docker restarts, gate-deploy
checks, or proof-video commands from a worktree after the routing guard reports
it is already merged.

### Step 3: Return campaign state

Print `campaign status` after the group becomes green or blocked. Do not claim
the campaign is complete unless its status is `completed`; newly exposed child
groups remain part of the same campaign.

### Rules

- **One root cause per invocation** — process one durable group, then return campaign state
- **Never run vitest/playwright locally** — always dispatch via `scripts/tests.py run`
- **Directus campaigns are canonical** — do not maintain separate chat or local progress state.
- **Attempts are durable** — inspect prior attempts and do not repeat rejected approaches.
- **Read before writing** — always read the failure report and source code before changing anything
- **Console errors are real bugs** — fix them in app code, never suppress
- **Keep live-probe failures visible** — group them under their provider parent incident and continue independent groups
- **Block structurally** — required unresolved input keeps the campaign active and blocked, never partially successful.
