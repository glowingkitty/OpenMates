---
name: stabilize-e2e-pattern
description: Convert repeated Playwright wait/stabilize/lookup/assertion fixes into shared deterministic helpers. Use when the same spec or flow fails repeatedly, commits say wait/stabilize/lookup/assertion, or an E2E fix looks like a one-off timing patch.
user-invocable: true
argument-hint: "<spec or failing flow>"
---

# Stabilize E2E Pattern

Use this skill when an E2E failure is likely part of a recurring readiness or
selector pattern rather than a unique product bug. The goal is to prevent spec
debt from spreading through one-off waits, repeated lookups, and fragile local
assertions.

## When To Use

- A Playwright spec failed more than once for the same flow.
- A proposed fix adds `waitForTimeout`, broad retries, or conditional element lookups.
- Recent commits mention `wait`, `stabilize`, `lookup`, `assertion`, or `selector` for a spec.
- The failure belongs to auth, chat, embeds, settings, mobile header, cold boot, or assistant idle state.

## Workflow

1. Read `test-results/reports/failed/<spec>.md` and the current screenshot folder for the failed spec.
2. Read the failing spec and any helpers it already imports.
3. Classify the failure into one readiness category:
   - auth settled
   - chat hydrated
   - assistant idle
   - embed payload persisted
   - settings loaded
   - mobile header stable
   - IndexedDB/localStorage cold boot complete
   - provider/app skill result rendered
4. Search for existing shared helpers before editing. Prefer extending helpers under `frontend/apps/web_app/tests/helpers/` over editing one spec inline.
5. If no helper exists, add the smallest helper that waits on deterministic UI, network, storage, or debug state. Do not add sleeps.
6. Migrate the failing spec to the shared helper. If nearby specs duplicate the same wait pattern, migrate those too only when the diff stays small.
7. Add useful diagnostics at the helper boundary, such as screenshot step labels, failed-response logging, or state-specific error messages.
8. Run `python3 scripts/tests.py run --spec <name>.spec.ts` through the unified test control plane. Do not run Playwright locally.

## Rules

- Never use CSS class selectors in tests.
- Never add `waitForTimeout` unless there is an explicit allow marker and a documented reason.
- Prefer `data-testid`, role, text, URL, response, IndexedDB, or app debug state waits.
- If the same readiness pattern appears in three or more specs, update `scripts/audit_playwright_determinism.py` or add a focused deterministic check.
- For shared product behavior, verify or propose CLI/SDK coverage before treating the issue as web-only.

## Output

Return a concise report:

```markdown
## E2E Stabilization
Pattern: <category>
Shared helper: <created|updated|existing helper path>
Specs migrated: <list>
Diagnostics added: <list>
Verification: <test command/run id or blocker>
Residual risk: <one sentence>
```
