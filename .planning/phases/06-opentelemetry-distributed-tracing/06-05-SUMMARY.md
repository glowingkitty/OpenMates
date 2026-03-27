---
phase: 06-opentelemetry-distributed-tracing
plan: 05
subsystem: infra
tags: [opentelemetry, tracing, correlation, issue-reporting, debugging]

requires:
  - phase: 06-03
    provides: "WS trace context and frontend OTel SDK with wsSpans.ts"
  - phase: 06-04
    provides: "debug_trace.py CLI for querying OTel traces from OpenObserve"

provides:
  - OTel-aware request_id generation (trace_id replaces UUID4 when OTel is active)
  - Trace_id in request.state and exception logs for OTel correlation
  - Celery manual request_id propagation replaced by OTel auto-instrumentation
  - Ring buffer of recent trace IDs in wsSpans.ts for issue reports
  - Trace IDs in issue report payload (frontend + backend)
  - OTel trace span merging in debug.py issue --timeline

affects: [logging, issue-reporting, debugging, celery]

tech-stack:
  added: []
  patterns: [otel-trace-id-as-request-id, trace-id-ring-buffer, trace-timeline-merge]

key-files:
  created: []
  modified:
    - backend/core/api/app/utils/request_context.py
    - backend/core/api/app/middleware/logging_middleware.py
    - backend/core/api/app/tasks/celery_config.py
    - frontend/packages/ui/src/services/tracing/wsSpans.ts
    - frontend/packages/ui/src/components/settings/SettingsReportIssue.svelte
    - backend/core/api/app/routes/settings.py
    - backend/scripts/debug_issue.py

key-decisions:
  - "Used OTel trace_id as request_id (not alongside it) so existing log queries work unchanged"
  - "Kept RequestIdLogFilter for backwards compatibility with existing dashboards and log queries"
  - "Commented out manual Celery request_id injection (not deleted) for rollback safety"
  - "Used importlib.util to load debug_trace.py as sibling module (not sys.path manipulation)"

patterns-established:
  - "OTel-aware request_id: generate_request_id() derives from OTel trace_id when active, UUID4 fallback"
  - "Trace ring buffer: wsSpans.ts maintains last 20 trace IDs for issue correlation"
  - "Trace timeline merge: debug_issue.py queries OpenObserve for trace spans and merges into log timeline"

requirements-completed: [OTEL-08]

duration: 6min
completed: 2026-03-27
---

# Phase 06 Plan 05: Request Correlation + Issue Trace Integration Summary

**OTel trace_id replaces UUID request_id for unified log correlation, with trace IDs flowing into issue reports and debug timeline**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-27T13:10:06Z
- **Completed:** 2026-03-27T13:16:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Migrated generate_request_id() to prefer OTel trace_id when active (UUID4 fallback)
- Added trace_id to request.state and exception error logs in LoggingMiddleware
- Commented out manual Celery request_id signal handlers (replaced by OTel auto-instrumentation)
- Added ring buffer of last 20 trace IDs to wsSpans.ts with getRecentTraceIds() export
- SettingsReportIssue.svelte now collects and sends trace_ids in issue report payload
- Backend settings.py accepts trace_ids field and saves to Directus + passes to email task
- debug_issue.py fetch_issue_timeline_local() now merges OTel trace spans into --timeline output

## Task Commits

| Task | Description | Commit | Key Files |
|------|-------------|--------|-----------|
| 1 | Migrate LoggingMiddleware and request_context to OTel trace context | 20c284be3 | request_context.py, logging_middleware.py, celery_config.py |
| 2 | Add trace IDs to issue reports and merge traces into debug timeline | 5a99676c6 | wsSpans.ts, SettingsReportIssue.svelte, settings.py, debug_issue.py |

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None -- all functionality is fully wired and functional.

## Self-Check: PASSED

- All 7 modified files exist on disk
- Both commit hashes (20c284be3, 5a99676c6) found in git log
