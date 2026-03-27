---
phase: 09-otel-tracing-fix
plan: 02
subsystem: api
tags: [opentelemetry, websocket, tracing, observability]

# Dependency graph
requires:
  - phase: 09-01
    provides: ws_span_helper module and user_otel_attrs extraction in websockets.py
provides:
  - All 37 WS handlers instrumented with OTel spans via ws_span_helper
  - Audit test preventing uninstrumented handler regression
affects: [09-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ws_span_helper try/finally pattern for all WS handlers"
    - "Parametrized file-system audit test for handler instrumentation"

key-files:
  created:
    - backend/tests/test_tracing/test_handler_instrumentation.py
  modified:
    - backend/core/api/app/routes/websockets.py
    - backend/core/api/app/routes/handlers/websocket_handlers/*.py (all 37 files)

key-decisions:
  - "Wrap handler body in try/finally rather than decorator to preserve existing error handling"
  - "Use lazy import of ws_span_helper inside try/except for zero-cost when OTel unavailable"
  - "Pass payload=None for initial_sync (no _traceparent in its payload format)"

patterns-established:
  - "Handler OTel pattern: _otel_span/_otel_token init -> start_ws_handler_span in try/except -> body in try -> end_ws_handler_span in finally"

requirements-completed: [OTEL-05]

# Metrics
duration: 14min
completed: 2026-03-27
---

# Phase 09 Plan 02: WS Handler OTel Instrumentation Summary

**All 37 WebSocket handlers instrumented with OTel spans via ws_span_helper, with 149-test audit suite preventing regression**

## Performance

- **Duration:** 14 min
- **Started:** 2026-03-27T18:39:28Z
- **Completed:** 2026-03-27T18:53:14Z
- **Tasks:** 2
- **Files modified:** 38

## Accomplishments
- All 37 WS handler files now create OTel spans with user privacy attributes (enduser.is_admin, enduser.debug_opted_in)
- websockets.py passes user_otel_attrs to all 38 handler calls (some handlers called from multiple dispatch points)
- initial_sync_handler and message_received_handler migrated from inline OTel to ws_span_helper
- key_received_handler specifically instrumented (OTEL-05 gap closure)
- 149-test audit suite ensures future handlers cannot be added without OTel instrumentation

## Task Commits

Each task was committed atomically:

1. **Task 1: Instrument all 37 WS handlers + update websockets.py dispatch** - `56fe87879` (feat)
2. **Task 2: Handler instrumentation audit test** - `c1234c2c6` (test)

## Files Created/Modified
- `backend/core/api/app/routes/websockets.py` - Added user_otel_attrs kwarg to all 38 handler calls, removed noqa comment
- `backend/core/api/app/routes/handlers/websocket_handlers/*.py` (37 files) - Added ws_span_helper instrumentation pattern
- `backend/tests/test_tracing/test_handler_instrumentation.py` - Parametrized audit test (4 checks x 37 files + 1 discovery)

## Decisions Made
- Wrapped handler bodies in try/finally rather than using a decorator, to preserve each handler's existing error handling patterns
- Used lazy import of ws_span_helper inside each handler's try/except block for zero runtime cost when OTel is not installed
- Passed payload=None for initial_sync_handler since its payload format differs from the standard WS dispatch (no _traceparent field)
- Preserved handler-specific span attributes (ws.client_chat_count, ws.result_status) in migrated handlers

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed broken migration of initial_sync_handler and message_received_handler**
- **Found during:** Task 1 (automated script run)
- **Issue:** The instrumentation script's regex-based migration created duplicate except clauses (valid Python but semantically broken - second except unreachable)
- **Fix:** Restored both files from git and applied migration manually with targeted edits
- **Files modified:** initial_sync_handler.py, message_received_handler.py
- **Verification:** Python syntax check passes, handler structure preserved
- **Committed in:** 56fe87879 (Task 1 commit)

**2. [Rule 1 - Bug] Fixed syntax error in offline_sync_handler.py**
- **Found during:** Task 1 (syntax validation)
- **Issue:** Script placed trailing comma incorrectly when the last param had an inline comment containing braces
- **Fix:** Manually fixed the parameter line formatting
- **Files modified:** offline_sync_handler.py
- **Verification:** ast.parse() passes for all 37 files
- **Committed in:** 56fe87879 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 bugs from instrumentation script)
**Impact on plan:** Both bugs were in the automated instrumentation script output, caught and fixed before commit. No scope creep.

## Issues Encountered
- The automated regex-based migration for initial_sync_handler and message_received_handler produced broken code due to the complex existing try/except/finally structure. Resolved by restoring from git and applying targeted manual edits instead.
- handle_initial_sync is defined but never called from websockets.py (possibly legacy or called from another path). Still instrumented with default user_otel_attrs=None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 37 WS handlers are now visible in OTel distributed traces
- Plan 03 (if any remaining) can build on complete handler coverage
- Audit test will catch any new uninstrumented handlers in CI

---
*Phase: 09-otel-tracing-fix*
*Completed: 2026-03-27*
