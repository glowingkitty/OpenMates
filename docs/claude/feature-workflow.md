# Feature Implementation Workflow

Complements `planning.md` with the end-to-end lifecycle. Read `planning.md` first for the planning template.

---

## Lifecycle

1. **Understand** — State your interpretation of the task and wait for confirmation. See step 0 in `planning.md`. Do not search the codebase or write a plan until the user confirms your understanding is correct.
2. **Clarify** — Resolve remaining ambiguities. Ask about scope, expected behavior, error cases, and external dependencies. Search the codebase for similar implementations (DRY). Check `docs/architecture/` for prior decisions.
3. **Plan** — Follow the template in `planning.md`. Additionally: check `sessions.py status` for file conflicts, note which existing tests need updating. The plan must include Acceptance Criteria (checklist format) — including a Firecrawl verification step for any reproducible bug.
4. **Test strategy** — Decide what to test and when (see below).
5. **Implement** — Backend first, then frontend, then integration. Track every file. Run tests and lint incrementally, not in bulk at the end.
6. **Verify** — Work through the Acceptance Criteria checklist. Tick each item explicitly. All tests pass, `pnpm build` succeeds (for frontend), dev server behaves correctly.
7. **Deploy** — `deploy-docs` → `prepare-deploy` → `deploy`. Rebuild Docker if backend changed. Check Vercel if frontend changed.
8. **Confirm** — Task Summary to user → wait for confirmation → delete related issue if any → `end` session.

---

## Test Strategy

Decide testing approach BEFORE implementation — not after.

**Write tests FIRST (TDD) when:**
- Behavior is clearly defined and stable
- Fixing a bug (reproduce it first)
- Complex logic with many edge cases

**Write tests AFTER when:**
- API/interface is still being designed
- UI that may change during implementation

**Test types:**

| Type | When | Command |
|------|------|---------|
| Unit | Pure logic, utils, transforms | `docker exec api pytest tests/test_<mod>.py -v` / `pnpm test -- --run <file>` |
| Integration | API endpoints, service interactions | `docker exec api pytest tests/ -v -k "<test>"` |
| E2E | User-facing flows, critical paths | `npx playwright test tests/<spec>.spec.ts` |

**If a test fails and you're stuck after 2 attempts: STOP and report** (see CLAUDE.md "Debugging Attempt Limit").
