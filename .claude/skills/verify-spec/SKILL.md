---
name: verify-spec
description: Check implemented work against executable spec.yml before completion or deploy by validating acceptance criteria coverage and red/green test evidence
user-invocable: true
argument-hint: "docs/specs/<slug>/spec.yml [--phase red|green|complete]"
---

## Instructions

You are performing a conformance check for spec-driven work. This is not a
replacement for tests; it confirms that tests and implementation evidence match
the executable `spec.yml`.

### Step 1: Read Inputs

Read:

1. The provided `docs/specs/<slug>/spec.yml`
2. The `implementation_plan` and `tasks` sections inside that spec
3. `docs/contributing/guides/spec-driven-development.md`
4. Current session status and related test tracking:
   ```bash
   python3 scripts/sessions.py status --json
   python3 scripts/sessions.py check-tests --session <SESSION_ID>
   ```

If there is no active session, ask for the session ID or perform a document-only
review.

### Step 2: Build The Coverage Table

First run:

```bash
python3 scripts/spec_validate.py docs/specs/<slug>/spec.yml
python3 scripts/spec_verify.py docs/specs/<slug>/spec.yml --phase complete
```

For every scenario and acceptance criterion, record:

- Implemented: yes/no/partial/unknown
- Evidence: test file, command, manual verification, code reference, or gap
- Risk: none/low/medium/high

### Step 3: Validate Required Evidence

Pass only when:

- Every completed acceptance criterion has green evidence.
- Every required red phase has failure evidence before implementation.
- Privacy/security criteria have concrete code or test evidence.
- Changed source files have related tests or an explicit skip reason.
- Open questions are resolved or listed as accepted residual risk.

Playwright green evidence is only valid after the implementation has been
deployed to dev, Vercel is Ready, and the spec has run against
`app.dev.openmates.org`.

### Step 4: Output Report

Use this format:

```markdown
## Spec Verification

Spec: docs/specs/<slug>/spec.yml
Status: pass | fail | partial

| ID | Status | Evidence | Risk |
| --- | --- | --- | --- |
| S-1 | pass | `frontend/...spec.ts` | none |
| AC-1 | pass | `python3 scripts/run_tests.py ...` | none |

Gaps:
- <gap or none>

Deploy note:
- Spec: docs/specs/<slug>/spec.yml
- Tests: <commands/results>
- Residual risk: <none or concise note>
```

### Step 5: Stop On Failure

If status is `fail`, do not deploy. Fix the gap, update the spec if product
intent changed, or ask the user to accept a documented risk.

## Rules

- Do not mark criteria complete based on intent alone.
- Do not weaken or remove acceptance criteria to make verification pass.
- Prefer Playwright/pytest/vitest via repo-approved test commands over manual
  browser checks.
- Manual verification is allowed only when automation is impractical and the
  reason is documented.
- Do not mark a full spec verified while required green evidence is missing.
