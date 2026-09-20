---
name: verify-plan
description: Check implemented work against an executable Plan's accepted scope before completion or deploy, including only its required criteria, waivers, and evidence.
user-invocable: true
argument-hint: "docs/plans/<slug>/plan.yml [--phase red|green|complete]"
---

## Instructions

You are performing a conformance check for Plan-driven work. This does not
replace tests; it confirms implementation evidence matches the Plan and its
linked approved Specifications.

### Step 1: Read Inputs

Read the provided `docs/plans/<slug>/plan.yml`, any Specifications explicitly
linked by that Plan, and its tasks. Review current session status and related
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
- Only surfaces, environments, and ordering explicitly required by the accepted
  Plan are completion gates. Choose evidence appropriate to each affected surface;
  do not add a universal API/CLI/SDK/web/Apple ladder or a generic dev-API check.
- Visual smoke, user confirmation, and demonstration/video evidence are gates only
  when the accepted Plan explicitly marks them required. Preserve explicit user
  waivers and their scoped decision receipts.
- Privacy/security criteria, documentation impact, assumptions, open questions,
  and explicitly required proof evidence are resolved or explicitly accepted.

Failed required checks keep the Plan active until traceable follow-up work is
complete or the user accepts a waiver or blocker. Playwright green evidence is
valid when its receipt binds the exact source and harness to a successful
isolated GitHub run with complete cleanup. Dev deployment and visual-smoke
evidence are separate gates only when the Plan requires them.

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
