# Implementation Planning (Compact)

Full reference: `sessions.py context --doc planning`

## Steps (required for non-trivial tasks)

1. **State understanding** — Write what you think the user wants. Ask "Is this correct?" Wait for confirmation
2. **Define scope** — In scope, out of scope, dependencies
3. **List affected files** — Every file to create/modify/delete
4. **State assumptions** — Every assumption you're making (verify if unsure)
5. **Processing example** — Concrete step-by-step data flow with real values (CRITICAL — catches misunderstandings)
6. **Acceptance criteria** — Checkboxes, user-perspective, falsifiable. Bug fixes: include Firecrawl verification step
7. **Suggest E2E tests** — `should ...` format, 3-8 per feature. Don't write code, just list descriptions
8. **Flag risks** — Unknowns, potential regressions, concurrent session conflicts

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
