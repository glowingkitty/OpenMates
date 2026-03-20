# Implementation Planning (Compact)

Full reference: `sessions.py context --doc planning`

## Steps (required for non-trivial tasks)

0. **State understanding** — Write what you think the user wants. Ask "Is this correct?" Wait for confirmation
0b. **Create task file** (multi-session tasks: spans >1 session or touches >3 files):
    ```bash
    python3 scripts/sessions.py task-create --session <ID> --title "..." --context "..."
    python3 scripts/sessions.py task-step --id <TASK_ID> --add "[ ] Step"
    ```
    Any agent can resume via `sessions.py start --task-id <TASK_ID>`.
    At completion: `sessions.py task-update --id <TASK_ID> --status done --summary "..."`.
1. **Define scope** — In scope, out of scope, dependencies
2. **List affected files** — Every file to create/modify/delete
3. **State assumptions** — Every assumption you're making (verify if unsure)
4. **Processing example** — Concrete step-by-step data flow with real values (CRITICAL — catches misunderstandings)
5. **Acceptance criteria** — Checkboxes, user-perspective, falsifiable. Bug fixes: include Firecrawl verification step
6. **Suggest E2E tests** — `should ...` format, 3-8 per feature. Don't write code, just list descriptions
7. **Flag risks** — Unknowns, potential regressions, concurrent session conflicts

## Template

```
## My Understanding
<2-4 sentences, what you will/won't do>
Is this correct?

## Implementation Plan
**Task:** <one-line>
**Scope:** In: ... | Out: ...
**Affected Files:** <path — what changes>
**Assumptions:** <list>
**Processing Example:** 1. User does X  2. System does Y  3. Result Z
**Acceptance Criteria:** - [ ] <observable outcome>
**Suggested E2E Tests:** - `should <description>`
**Risks:** <list>
```

## Common Mistakes

- Skipping the understanding step
- Jumping to code without planning
- Vague acceptance criteria ("it works")
- Missing processing example
- Planning too long (target 2-5 min)

## Feature Lifecycle

Understand -> Clarify -> Plan -> Test strategy -> Implement -> Verify -> Deploy -> Confirm
