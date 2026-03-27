---
phase: 07-e2e-test-suite-repair
plan: 04
subsystem: testing
tags: [playwright, e2e, selector-drift, strict-mode, 404, status-page, embed-preview]

# Dependency graph
requires:
  - phase: 07-02
    provides: "Embed display type drift fix pattern (EXPECTED_DT_HEADINGS)"
  - phase: 07-03
    provides: "OTP clock-drift compensation in loginToTestAccount()"
provides:
  - "Fixed selector drift in not-found-404-flow.spec.ts (.not-found-options -> .not-found-actions)"
  - "Fixed strict mode violations in status-page.spec.ts (specific CSS class selectors)"
  - "Applied embed display type fix to embed-showcase.spec.ts and embed-test-helpers.ts"
  - "Migrated a11y-pages authenticated tests to shared loginToTestAccount()"
  - "Pre-validation file documenting all Phase 07 fixes"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Use CSS class selectors (.cat-name, .name) instead of getByText() for ambiguous text matches"
    - "Always verify component DOM class names against spec selectors when fixing selector drift"

key-files:
  created:
    - test-results/daily-run-validation.json
  modified:
    - frontend/apps/web_app/tests/not-found-404-flow.spec.ts
    - frontend/apps/web_app/tests/status-page.spec.ts
    - frontend/apps/web_app/tests/embed-showcase.spec.ts
    - frontend/apps/web_app/tests/helpers/embed-test-helpers.ts
    - frontend/apps/web_app/tests/a11y-pages.spec.ts

key-decisions:
  - "Used .cat-name and .name CSS class selectors instead of getByText() to fix Playwright strict mode violations"
  - "Updated .not-found-options to .not-found-actions to match Not404Screen component DOM"
  - "docs-links, preview-error, seo-demo-chat selectors verified correct — no changes needed"

patterns-established:
  - "Selector drift fix: always read the actual Svelte component to verify CSS class names"
  - "Strict mode fix: use scoped CSS selectors over getByText() when text appears in multiple DOM locations"

requirements-completed: [E2E-03]

# Metrics
duration: 7min
completed: 2026-03-27
---

# Phase 7 Plan 4: Fix Remaining Non-Auth Specs and Validate Suite Summary

**Fixed selector drift in 404/status specs, applied embed display type fix, migrated a11y login to shared helper -- 5 specs patched, 2 verified correct as-is**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-27T14:17:16Z
- **Completed:** 2026-03-27T14:24:29Z
- **Tasks:** 2 of 3 (checkpoint pending)
- **Files modified:** 6

## Accomplishments

- Fixed not-found-404-flow.spec.ts: updated all selectors from .not-found-options/.not-found-option to .not-found-actions/.not-found-actions button (matching current Not404Screen component)
- Fixed status-page.spec.ts: resolved strict mode violations by replacing getByText('Chat') and getByText('Groq') with scoped .cat-name and .name CSS class selectors
- Applied embed display type fix (from Plan 02) to embed-showcase.spec.ts and embed-test-helpers.ts in this worktree
- Migrated a11y-pages.spec.ts authenticated tests from inline login to shared loginToTestAccount() with OTP clock-drift compensation
- Verified docs-links.spec.ts, preview-error.spec.ts, and seo-demo-chat.spec.ts selectors are correct -- no changes needed

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix remaining non-auth-dependent failing specs** - `23560d13c` (fix)
2. **Task 2: Pre-validation daily run results file** - `3a90489f3` (chore)
3. **Task 3: Human verification** - CHECKPOINT PENDING

## Files Created/Modified

- `frontend/apps/web_app/tests/not-found-404-flow.spec.ts` - Updated selectors: .not-found-options -> .not-found-actions, .not-found-option -> .not-found-actions button
- `frontend/apps/web_app/tests/status-page.spec.ts` - Fixed strict mode: getByText('Chat') -> .cat-name, getByText('Groq') -> .name
- `frontend/apps/web_app/tests/embed-showcase.spec.ts` - Removed stale 'Preview -- Large' from EXPECTED_DT_HEADINGS
- `frontend/apps/web_app/tests/helpers/embed-test-helpers.ts` - Same EXPECTED_DT_HEADINGS fix
- `frontend/apps/web_app/tests/a11y-pages.spec.ts` - Migrated inline login to shared loginToTestAccount()
- `test-results/daily-run-validation.json` - Pre-validation file documenting expected improvements

## Decisions Made

- Used CSS class selectors (.cat-name, .name) instead of getByText() to resolve strict mode violations in status-page.spec.ts. This is more robust since the text appears in multiple DOM locations.
- Updated .not-found-options to .not-found-actions and .not-found-option to .not-found-actions button to match the actual Not404Screen.svelte DOM structure.
- Verified docs-links, preview-error, and seo-demo-chat selectors against actual Svelte components -- all correct, no changes needed.

## Deviations from Plan

None -- plan executed exactly as written. The 7 specs were categorized correctly:
- 4 needed code changes (not-found-404-flow, status-page, embed-showcase, a11y-pages)
- 1 needed helper fix (embed-test-helpers)
- 2 verified correct as-is (docs-links, preview-error)
- 1 depends on server content (seo-demo-chat -- verified route structure exists)

## Known Stubs

- `test-results/daily-run-validation.json` contains placeholder data (empty tests array). Actual daily run validation required after merging fixes to dev and deploying.

## Issues Encountered

- This worktree does not have Plan 02/03 changes merged, so the embed-test-helpers fix was re-applied here independently.
- Cannot run actual GHA daily suite from worktree since fixes aren't deployed to dev -- created pre-validation file instead.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- Task 3 (checkpoint:human-verify) pending: requires full daily suite run after deployment to validate 85+/88 pass rate
- Known potential failures: 4 signup specs depend on Mailosaur email delivery timing
- All other fixes are ready to merge

---
*Phase: 07-e2e-test-suite-repair*
*Completed: 2026-03-27 (Tasks 1-2; Task 3 checkpoint pending)*
