---
phase: 07-e2e-test-suite-repair
plan: 02
subsystem: testing
tags: [playwright, e2e, embed-preview, display-types]

requires:
  - phase: 07-01
    provides: "Triage categorization identifying Category B (embed display type drift) as root cause for 16 specs"
provides:
  - "Fixed EXPECTED_DT_HEADINGS constant in embed-test-helpers.ts and embed-showcase.spec.ts"
  - "All 15 skill-* specs and embed-showcase.spec.ts unblocked for Phase 1 (embed preview) assertions"
affects: [07-04]

tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - frontend/apps/web_app/tests/helpers/embed-test-helpers.ts
    - frontend/apps/web_app/tests/embed-showcase.spec.ts

key-decisions:
  - "Removed 'Preview -- Large' from EXPECTED_DT_HEADINGS instead of replacing with 'Group -- Large' because Group -- Large is conditional (hidden for app skills with isAppSkill: true)"

patterns-established: []

requirements-completed: []

duration: 2min
completed: 2026-03-27
---

# Phase 7 Plan 2: Fix Embed Display Type Drift in 16 Skill Specs Summary

**Removed stale "Preview -- Large" display type heading from EXPECTED_DT_HEADINGS, fixing Category B failure for all 15 skill-* specs and embed-showcase.spec.ts**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-27T14:02:26Z
- **Completed:** 2026-03-27T14:04:44Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Identified that the embed preview page renamed "Preview -- Large" to "Group -- Large" and made it conditional on `!isAppSkill`
- Removed `'Preview -- Large'` from `EXPECTED_DT_HEADINGS` in both `embed-test-helpers.ts` (shared helper) and `embed-showcase.spec.ts` (local copy)
- All 15 skill-* specs import `verifyEmbedPreviewPage` from the shared helper, so the single-file fix propagates to all 15 specs
- Structural verification confirmed: constant updated correctly in both files, no other references to "Preview -- Large" in assertions

## Task Commits

Each task was committed atomically:

1. **Task 1: Apply batch fix to all 15 skill-* specs** - `4cd81c2b5` (fix)
2. **Task 2: Verify skill-* fix** - structural verification only (GHA runs pending deployment to dev)

**Plan metadata:** pending

## Files Created/Modified

- `frontend/apps/web_app/tests/helpers/embed-test-helpers.ts` - Removed 'Preview -- Large' from EXPECTED_DT_HEADINGS (line 24)
- `frontend/apps/web_app/tests/embed-showcase.spec.ts` - Removed 'Preview -- Large' from local EXPECTED_DT_HEADINGS copy (line 80), updated comment

## Decisions Made

- **Remove vs replace:** Removed `'Preview -- Large'` entirely rather than replacing with `'Group -- Large'` because `Group -- Large` is conditional (`dataVars.length > 1 && !section.isAppSkill`) and all 15 skill specs test app-level skills where `isAppSkill: true`, meaning `Group -- Large` is never rendered for them.

## Deviations from Plan

None - plan executed exactly as written. The triage correctly identified the root cause (Category B: embed display type drift) and the fix location.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 1 (embed preview) assertions in all 15 skill-* specs are now unblocked
- Phase 4 (web UI chat) in skill specs will still fail due to Category A (OTP login failure) -- addressed in Plan 03
- GHA verification of the fix requires deployment to dev branch (pending orchestrator merge)

---
*Phase: 07-e2e-test-suite-repair*
*Completed: 2026-03-27*
