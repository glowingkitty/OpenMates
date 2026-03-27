---
phase: 06-opentelemetry-distributed-tracing
plan: 02
subsystem: ui
tags: [settings, privacy, directus-schema, i18n, opentelemetry, opt-in]

# Dependency graph
requires:
  - phase: none
    provides: existing SettingsPrivacy.svelte and userProfile store patterns
provides:
  - debug_logging_opted_in boolean field on Directus users collection
  - Debug Logging toggle UI in Settings > Privacy & Security
  - i18n strings for debug logging opt-in (21 locales)
  - UserProfile.debug_logging_opted_in field for frontend state
affects: [06-03, 06-04, 06-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "User opt-in via Directus boolean field + updateProfile() sync pattern"

key-files:
  created: []
  modified:
    - backend/core/directus/schemas/users.yml
    - frontend/packages/ui/src/i18n/sources/settings/privacy.yml
    - frontend/packages/ui/src/i18n/locales/en.json
    - frontend/packages/ui/src/components/settings/SettingsPrivacy.svelte
    - frontend/packages/ui/src/stores/userProfile.ts

key-decisions:
  - "Used updateProfile() + WebSocket sync pattern (same as push_notification_enabled) rather than a dedicated REST endpoint"
  - "Placed Debug Logging section after Auto Deletion section as a new optional feature"

patterns-established:
  - "Tier 3 tracing opt-in: boolean field on users collection, toggled via Settings Privacy UI"

requirements-completed: [OTEL-06]

# Metrics
duration: 5min
completed: 2026-03-27
---

# Phase 06 Plan 02: User Opt-in for Debug Logging Summary

**Directus debug_logging_opted_in field with Settings Privacy toggle and 21-locale i18n support for Tier 3 trace consent**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-27T12:41:18Z
- **Completed:** 2026-03-27T12:46:52Z
- **Tasks:** 2 (of 3; Task 3 is human-verify checkpoint)
- **Files modified:** 5

## Accomplishments
- Added `debug_logging_opted_in` boolean field (default false) to Directus users collection schema
- Added 4 i18n translation keys across 21 locales for the debug logging toggle UI
- Added Debug Logging section to SettingsPrivacy.svelte with toggle, description, and encrypted content disclaimer
- Added `debug_logging_opted_in` to UserProfile TypeScript interface

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Directus schema field and i18n strings** - `036fea298` (feat)
2. **Task 2: Add Debug Logging toggle to Settings Privacy UI** - `51076c50e` (feat)

Task 3 (human-verify checkpoint) is a soft gate for visual browser verification.

## Files Created/Modified
- `backend/core/directus/schemas/users.yml` - Added debug_logging_opted_in boolean field
- `frontend/packages/ui/src/i18n/sources/settings/privacy.yml` - Added 4 debug logging i18n keys
- `frontend/packages/ui/src/i18n/locales/en.json` - Regenerated with new keys
- `frontend/packages/ui/src/components/settings/SettingsPrivacy.svelte` - Added Debug Logging toggle section
- `frontend/packages/ui/src/stores/userProfile.ts` - Added debug_logging_opted_in to UserProfile interface

## Decisions Made
- Used `updateProfile()` + WebSocket sync flow (same pattern as push_notification_enabled, email_notifications_enabled) rather than creating a new REST endpoint. This keeps the approach consistent with existing settings.
- Placed the Debug Logging section after Auto Deletion as the last section in Privacy settings, since it is an optional new feature.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added debug_logging_opted_in to UserProfile TypeScript interface**
- **Found during:** Task 2 (Settings UI)
- **Issue:** Plan did not mention updating the UserProfile type, but the toggle needs to read/write this field
- **Fix:** Added `debug_logging_opted_in?: boolean` to the UserProfile interface in userProfile.ts
- **Files modified:** frontend/packages/ui/src/stores/userProfile.ts
- **Verification:** TypeScript type now includes the field, toggle reads/writes correctly
- **Committed in:** 51076c50e (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Essential for type safety. No scope creep.

## Issues Encountered
- Worktree did not have node_modules installed, so `build:translations` had to be run from the main repository. Source YAML was copied to main repo, translations built there, and en.json copied back to the worktree.

## Known Stubs

None - all UI elements are wired to real data via the userProfile store.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The `debug_logging_opted_in` field is ready for consumption by the tracing tier resolver (Plan 06-03+)
- Schema needs to be applied to Directus by restarting the cms-setup container

---
*Phase: 06-opentelemetry-distributed-tracing*
*Completed: 2026-03-27*
