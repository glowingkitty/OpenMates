---
phase: 09-otel-tracing-fix
plan: 03
subsystem: infra
tags: [opentelemetry, openobserve, cli, tracing, debug]

# Dependency graph
requires:
  - phase: 09-01
    provides: OTel tracing infrastructure and OpenObserve integration
provides:
  - Full span tree fetching via SQL _search API for all trace CLI commands
  - Unicode box-drawing hierarchy in trace timeline output
  - trace recent subcommand for viewing all recent traces
affects: [debugging, admin-tooling]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SQL _search API for full span trees instead of /traces/latest first_event"
    - "Unicode box-drawing chars for hierarchical CLI output"
    - "_collect_full_spans pattern: trace summary -> extract trace_id -> fetch all spans"

key-files:
  created: []
  modified:
    - backend/scripts/debug_trace.py
    - backend/tests/test_tracing/test_debug_trace.py

key-decisions:
  - "Use _get_full_trace_spans with SQL _search API as the single span fetching strategy for all commands"
  - "Replace timestamp-heavy span lines with service.operation (duration) status format"
  - "Renamed _search_traces_legacy to _search_traces_sql, kept legacy alias for backwards compat"

patterns-established:
  - "Trace CLI: all commands go through _collect_full_spans -> _get_full_trace_spans pipeline"
  - "Tree rendering: _render_span(sid, prefix, is_last) recursive pattern with TREE_BRANCH/TREE_LAST/TREE_PIPE/TREE_SPACE constants"

requirements-completed: [OTEL-02, OTEL-05, OTEL-06]

# Metrics
duration: 4min
completed: 2026-03-27
---

# Phase 09 Plan 03: Trace CLI Rework Summary

**Full span tree rendering with Unicode hierarchy for all trace CLI commands, replacing broken first_event-only output**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-27T18:39:29Z
- **Completed:** 2026-03-27T18:43:58Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments
- All 7 trace subcommands (request, errors, task, session, slow, login, recent) now fetch full span trees via SQL _search API
- Timeline output uses Unicode box-drawing characters with service.operation (duration) status format
- Trace headers show root span operation name (HTTP path or WS message type) instead of bare "Duration: Xms"
- New `trace recent --last 5m` subcommand shows all recent traces, not just errors
- Eliminated the broken `first_event` extraction pattern from all command dispatch code

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Failing tests** - `1ce1e7206` (test)
2. **Task 1 GREEN: Implementation** - `32cb59bf0` (feat)

_TDD task with RED/GREEN phases_

## Files Created/Modified
- `backend/scripts/debug_trace.py` - Reworked trace CLI with _get_full_trace_spans, _collect_full_spans, Unicode tree formatter, recent subcommand
- `backend/tests/test_tracing/test_debug_trace.py` - Extended from 17 to 31 tests covering Unicode tree chars, service.operation format, trace header, nesting, recent args, SQL API usage

## Decisions Made
- Used `_get_full_trace_spans` as a standalone function (not refactoring `_search_traces_legacy`) for clarity -- each function has one job
- Renamed `_search_traces_legacy` to `_search_traces_sql` with backwards-compatible alias
- Added `_collect_full_spans` helper to DRY the trace-summary-to-full-spans pipeline used by 6 commands
- Kept `_get_latest_traces` (traces/latest endpoint) for trace discovery, but all span detail goes through SQL _search

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Test for `_get_full_trace_spans` initially used `@patch("debug_trace.httpx")` which failed because httpx is imported locally inside the function. Fixed by patching `httpx.post` directly via `patch.object`.
- `tests/test_tracing/test_integration.py` has a pre-existing import failure (`ModuleNotFoundError: opentelemetry.exporter`) because OTel exporter is only installed in Docker. Not caused by this plan, out of scope.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 09 is now complete (plans 01, 02, 03 all done)
- All trace CLI commands show proper hierarchical output
- Ready for verification via `/gsd:verify-work`

## Self-Check: PASSED

- FOUND: backend/scripts/debug_trace.py
- FOUND: backend/tests/test_tracing/test_debug_trace.py
- FOUND: 1ce1e7206 (RED commit)
- FOUND: 32cb59bf0 (GREEN commit)
- All 31 tests pass
