---
phase: 07-e2e-test-suite-repair
plan: 01
subsystem: testing
tags: [playwright, e2e, github-actions, triage, totp, embed-preview]

# Dependency graph
requires: []
provides:
  - "Categorized failure list for all 46 broken E2E specs with root causes and fix strategies"
  - "GHA triage data with actual Playwright error messages for 6 representative specs"
affects: [07-02-PLAN, 07-03-PLAN, 07-04-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns: ["GHA dispatch + artifact download for E2E triage"]

key-files:
  created:
    - test-results/triage-07-01.json
    - .planning/phases/07-e2e-test-suite-repair/07-01-TRIAGE.md
  modified: []

key-decisions:
  - "5 failure categories identified: OTP login (20), embed display drift (16), selector drift (5), signup timeout (4), strict mode (1)"
  - "Skill specs confirmed same root cause -- batch fix all 15 via embed-test-helpers.ts constant update"
  - "Fix priority: embed display (highest ROI) > OTP login (most specs) > selector drift > strict mode > signup timeout"

patterns-established:
  - "GHA spec dispatch pattern: gh workflow run + artifact download for triage"

requirements-completed: [E2E-01, E2E-02, E2E-03]

# Metrics
duration: 15min
completed: 2026-03-27
---

# Phase 7 Plan 01: E2E Failure Triage Summary

**Dispatched 6 representative specs to GHA capturing actual Playwright errors, categorized all 46 failures into 5 root-cause groups with fix strategies for Plans 02-04**

## Performance

- **Duration:** 15 min
- **Started:** 2026-03-27T13:43:55Z
- **Completed:** 2026-03-27T13:59:11Z
- **Tasks:** 2
- **Files created:** 2

## Accomplishments
- Dispatched 6 representative specs (skill-web-search, skill-news-search, signup-flow, api-keys-flow, status-page, not-found-404-flow) to GitHub Actions and captured actual Playwright error messages
- Categorized all 46 failing specs into 5 root-cause categories with specific fix strategies
- Confirmed skill-* specs share the same root cause (missing "Preview -- Large" display type heading) -- batch fixable
- Identified login OTP failure as the single largest category (20 specs), likely caused by TOTP clock drift on GHA runners

## Task Commits

Each task was committed atomically:

1. **Task 1: Run 6 representative failing specs on GHA** - `5810215be` (chore)
2. **Task 2: Categorize all 46 specs by root cause** - `439aa61d3` (docs)

## Files Created/Modified
- `test-results/triage-07-01.json` - GHA run results with per-test Playwright error messages for 6 specs
- `.planning/phases/07-e2e-test-suite-repair/07-01-TRIAGE.md` - Full categorization of 46 failures with root causes and fix strategies

## Decisions Made
- Used 6 specs across 3 categories (skill, signup, other) for representative sampling per plan
- Categorized specs into 5 groups: OTP login failure (20), embed display drift (16), selector drift (5), signup timeout (4), strict mode violations (1)
- Prioritized fixes by ROI: embed display type fix first (single constant change fixes 16 specs), then OTP login investigation (fixes 20 specs)
- Confirmed skill-* specs share identical Phase 1 error -- batch fix viable via embed-test-helpers.ts

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] test-results directory gitignored, used git add -f**
- **Found during:** Task 1
- **Issue:** test-results/ is in .gitignore, preventing normal git add
- **Fix:** Used `git add -f` to force-add the triage JSON
- **Files modified:** test-results/triage-07-01.json
- **Verification:** File committed successfully

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Minor git workflow adjustment, no scope impact.

## Issues Encountered
- signup-flow run took ~6 minutes (longer than other specs) due to the 240s test timeout expiring
- GHA workflow runs take 2-4 minutes each for dependency installation before tests even start

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Triage data is complete and actionable for Plans 02-04
- Category B (embed display type) is the quickest win -- single constant update in 2 files
- Category A (OTP login) requires deeper investigation into TOTP timing
- Category C specs each need individual DOM inspection to find correct selectors
- Category D (signup timeout) may need Mailosaur optimization or timeout increase

## Self-Check: PASSED

- test-results/triage-07-01.json: FOUND
- .planning/phases/07-e2e-test-suite-repair/07-01-TRIAGE.md: FOUND
- .planning/phases/07-e2e-test-suite-repair/07-01-SUMMARY.md: FOUND
- Commit 5810215be (Task 1): FOUND
- Commit 439aa61d3 (Task 2): FOUND

---
*Phase: 07-e2e-test-suite-repair*
*Completed: 2026-03-27*
