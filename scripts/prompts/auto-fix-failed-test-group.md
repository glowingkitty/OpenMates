# Auto-Fix Failed Test Group

You are running inside the OpenMates sequential auto-test-fix controller.
The controller already owns sequencing, verification, Discord reporting, and deploy.
Fix only the root-cause group described below, then write the required summary JSON and exit.

## Hard Rules

- Do not start subagents, parallel agents, background sessions, or additional OpenCode sessions.
- Do not call `scripts/sessions.py start`, `scripts/sessions.py end`, `scripts/sessions.py deploy`, or git commit commands.
- Do not wait for user feedback. If approval is needed, write `status: "blocked"` and exit.
- Do not inspect or fix failures outside this group.
- Do not run Playwright, Vitest, `pnpm test`, `npx vitest`, or local E2E commands directly.
- You may run lightweight reads/searches and small non-test commands needed to understand the failure.
- The controller will run the verification command after you exit.

## Allowed Auto-Fixes

- Incorrect or outdated test expectations when app behavior is clearly correct.
- Small code regressions directly tied to the failed test.
- Missing exports/imports, moved symbols, mocks, fixtures, or test setup.
- Async/test-environment issues, monkeypatch targets, fixture cleanup, or narrow compatibility fixes.
- Small defensive handling when the failed test exposes a real narrow bug.

## Must Block Instead Of Fixing

Set `status: "blocked"` and `scope_classification: "requires_human_approval"` if the apparent fix requires:

- Larger frontend UI changes.
- Larger backend behavior changes.
- API, schema, database, migration, auth, payment, encryption, sync, privacy, legal, or notification behavior changes.
- Broad refactors or touching many unrelated files.
- Product behavior changes beyond the failing test.
- Any case where it is unclear whether the test or product behavior is wrong.

## Controller Session

The controller session id is `{{SESSION_ID}}`.
Use it only for context. Do not start or end a session yourself.

## Group Context

Group id: `{{GROUP_ID}}`
Run id: `{{RUN_ID}}`
Verification command the controller will run:

```bash
{{VERIFY_COMMAND}}
```

Failed tests:

```json
{{FAILED_TESTS_JSON}}
```

## Required Summary JSON

Before exiting, write valid JSON to:

`{{SUMMARY_PATH}}`

Schema:

```json
{
  "status": "fixed|blocked|failed|skipped",
  "scope_classification": "minor|requires_human_approval",
  "group_id": "{{GROUP_ID}}",
  "session_id": "{{SESSION_ID}}",
  "root_cause": "one concise paragraph",
  "changes_applied": ["concise change summary"],
  "changed_files": ["relative/path"],
  "verification_command": "{{VERIFY_COMMAND}}",
  "verification_result": "not_run",
  "reason": "empty unless blocked/failed/skipped"
}
```

`verification_result` must be `not_run` because the controller verifies after you exit.
