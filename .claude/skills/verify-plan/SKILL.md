---
name: verify-plan
description: Check implemented work against an executable Plan before completion or deploy by validating Specification traceability, acceptance criteria coverage, and red/green evidence
user-invocable: true
argument-hint: "docs/plans/<slug>/plan.yml [--phase red|green|complete]"
---

## Instructions

You are performing a conformance check for Plan-driven work. This does not
replace tests; it confirms implementation evidence matches the Plan and its
linked approved Specifications.

### Step 1: Read Inputs

Read the provided `docs/plans/<slug>/plan.yml`, linked Specifications, tasks,
and the spec-driven-development guide. Review current session status and related
test tracking with `sessions.py status` and `sessions.py check-tests`.

### Step 2: Build The Coverage Table

Run:

```bash
python3 scripts/plan_validate.py docs/plans/<slug>/plan.yml
python3 scripts/plan_verify.py docs/plans/<slug>/plan.yml --phase complete
```

For every scenario and acceptance criterion, record implementation status,
coverage, evidence, and risk.

### Step 3: Validate Required Evidence

Pass only when:

- Linked Specification references resolve, changed assertions have current
  matching fingerprints, and required surface proof is direct and current.
- Every required acceptance criterion is covered by green evidence, a documented
  user confirmation, accepted waiver, or accepted blocker. Ambiguous or uncovered
  criteria fail.
- Required red and green phases have evidence, and evidence subject commits match
  the Plan implementation state.
- Shared product surfaces have evidence in required order: REST API/WebSocket,
  CLI, npm/pip SDKs, CI/daily reproduction, web, deployed Playwright visual smoke,
  user confirmation, then Apple.
- Larger user-visible web/UI work has a passing or explicitly skipped
  `V-UI-VISUAL-SMOKE` review before user confirmation or completion.
- CLI and SDK evidence uses real commands or calls against the real dev API/WebSocket
  path. Mocks, fixture replay, and direct function calls do not satisfy the gate.
- Privacy/security criteria, documentation impact, assumptions, open questions,
  and required proof-video evidence are resolved or explicitly accepted.

Failed required checks keep the Plan active until traceable follow-up work is
complete or the user accepts a waiver or blocker. Playwright green evidence is
only valid after deployment to dev and execution against `app.dev.openmates.org`.

### Step 4: Output Report

```markdown
## Plan Verification

Plan: docs/plans/<slug>/plan.yml
Specifications: <approved references>
Status: pass | fail | partial

| ID | Status | Evidence | Risk |
| --- | --- | --- | --- |
| S-1 | pass | `frontend/...spec.ts` | none |
| AC-1 | pass | `python3 scripts/tests.py run ...` | none |

Gaps:
- <gap or none>
```

### Step 5: Continue On Failure

If status is `fail`, resume the smallest actionable task, fix the gap, and update
the durable handoff. Ask the user only for a genuinely unresolved decision.

## Rules

- Do not mark criteria complete based on intent alone.
- Do not weaken or remove acceptance criteria to make verification pass.
- Do not mark a Plan verified while required green evidence is missing.
