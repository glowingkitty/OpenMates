---
phase: 06-opentelemetry-distributed-tracing
plan: 04
subsystem: infra
tags: [opentelemetry, openobserve, cli, tracing, debugging]

requires:
  - phase: 06-01
    provides: "OpenTelemetry SDK setup and OTLP export config"
provides:
  - "debug.py trace CLI with 6 subcommands for querying OTLP traces from OpenObserve"
  - "Indented span timeline formatter for trace inspection"
  - "Duration parser and trace ID utilities"
affects: [debugging, observability]

tech-stack:
  added: []
  patterns: ["OpenObserve SQL search for OTLP traces via httpx", "argparse subparser dispatch for trace CLI"]

key-files:
  created:
    - backend/scripts/debug_trace.py
    - backend/tests/test_tracing/test_debug_trace.py
  modified:
    - backend/scripts/debug.py

key-decisions:
  - "Used httpx sync client (not aiohttp) since debug_trace.py is a CLI tool, not an async service"
  - "Used 'default' as initial OTLP trace stream name with comment noting runtime discovery may be needed"

patterns-established:
  - "Trace CLI pattern: argparse subparsers with --json/--production flags on every subcommand"
  - "Timeline formatter: parent-child hierarchy via span_id/parent_span_id with depth-based indentation"

requirements-completed: [OTEL-07]

duration: 5min
completed: 2026-03-27
---

# Phase 06 Plan 04: Trace CLI Summary

**debug.py trace CLI with 6 subcommands (request/errors/task/session/slow/login) querying OTLP traces from OpenObserve with indented span timeline output**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-27T12:54:39Z
- **Completed:** 2026-03-27T12:59:51Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created debug_trace.py with 6 trace subcommands and OpenObserve SQL query builders
- Indented span timeline formatter that builds parent-child hierarchy from span_id/parent_span_id
- 21 unit tests covering argument parsing, duration parsing, trace ID utilities, and timeline formatting
- Registered trace subcommand in debug.py dispatch table

## Task Commits

Each task was committed atomically:

1. **Task 1: Create debug_trace.py CLI module with all subcommands** - `ca8dca665` (feat)
2. **Task 2: Register trace subcommand in debug.py** - `99ded6d58` (feat)

_Note: Task 1 used TDD flow (RED: import fails -> GREEN: implementation passes 21 tests)_

## Files Created/Modified
- `backend/scripts/debug_trace.py` - Trace CLI module with 6 subcommands, OpenObserve query builders, timeline formatter
- `backend/tests/test_tracing/test_debug_trace.py` - 21 unit tests for parsing and formatting
- `backend/scripts/debug.py` - Added trace to COMMANDS dict, docstring, and dispatch logic

## Decisions Made
- Used httpx sync client instead of aiohttp since this is a CLI tool run outside the async event loop
- Set TRACE_STREAM to "default" with a comment noting the exact OTLP stream name may need runtime discovery per RESEARCH.md Open Question 2
- Used parse_args function that returns Namespace (testable without argparse side effects)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- The test_tracing conftest.py imports opentelemetry SDK which is not installed on the host; used --noconftest flag to run tests successfully. This is expected since OTEL runs inside Docker containers.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Trace CLI is ready for use inside Docker containers via `docker exec api python /app/backend/scripts/debug.py trace <subcommand>`
- Stream name discovery may need adjustment once OTLP traces are flowing to OpenObserve

---
*Phase: 06-opentelemetry-distributed-tracing*
*Completed: 2026-03-27*

## Self-Check: PASSED
