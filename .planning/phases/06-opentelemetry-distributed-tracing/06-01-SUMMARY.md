---
phase: 06-opentelemetry-distributed-tracing
plan: 01
subsystem: infra
tags: [opentelemetry, tracing, privacy, observability, openobserve]

# Dependency graph
requires: []
provides:
  - "setup_tracing() entry point for OTel SDK initialization"
  - "TracePrivacyFilter wrapping SpanExporter with 3-tier attribute filtering"
  - "determine_user_tier() for privacy tier resolution from span attributes"
  - "Auto-instrumentation for FastAPI, httpx, Celery, Redis, logging"
affects: [06-02, 06-03, 06-04, 06-05]

# Tech tracking
tech-stack:
  added: [opentelemetry-sdk 1.40.0, opentelemetry-api 1.40.0, opentelemetry-exporter-otlp-proto-http 1.40.0, opentelemetry-instrumentation-fastapi 0.61b0, opentelemetry-instrumentation-httpx 0.61b0, opentelemetry-instrumentation-celery 0.61b0, opentelemetry-instrumentation-redis 0.61b0, opentelemetry-instrumentation-logging 0.61b0]
  patterns: [wrapping SpanExporter for attribute filtering, daily-salted SHA256 pseudonymization, env-var gated SDK initialization]

key-files:
  created:
    - backend/shared/python_utils/tracing/__init__.py
    - backend/shared/python_utils/tracing/config.py
    - backend/shared/python_utils/tracing/privacy_filter.py
    - backend/shared/python_utils/tracing/user_tier.py
    - backend/tests/test_tracing/__init__.py
    - backend/tests/test_tracing/conftest.py
    - backend/tests/test_tracing/test_setup.py
    - backend/tests/test_tracing/test_privacy_filter.py
  modified:
    - backend/core/api/requirements.txt
    - backend/core/api/main.py
    - backend/apps/base_main.py

key-decisions:
  - "Used OTel instrumentation 0.61b0 (not 0.51b0) for SDK 1.40.0 compatibility"
  - "Implemented privacy filter as wrapping SpanExporter (not SpanProcessor) because ReadableSpan is immutable"
  - "Dev server bypasses all privacy filtering for maximum debugging visibility"

patterns-established:
  - "Wrapping SpanExporter pattern: TracePrivacyFilter wraps the real OTLP exporter, creating filtered span copies during export()"
  - "3-tier privacy model: Tier 1 (minimal), Tier 2 (operational), Tier 3 (full) with attribute visibility rules"
  - "Daily-salted SHA256 pseudonymization for user IDs at Tier 1"

requirements-completed: [OTEL-01, OTEL-02]

# Metrics
duration: 8min
completed: 2026-03-27
---

# Phase 06 Plan 01: OTel Tracing Foundation Summary

**OTel SDK 1.40.0 with auto-instrumentation for FastAPI/httpx/Celery/Redis and 3-tier TracePrivacyFilter exporting to OpenObserve**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-27T12:41:16Z
- **Completed:** 2026-03-27T12:49:50Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- Created `backend/shared/python_utils/tracing/` module with 4 files providing centralized OTel SDK initialization
- TracePrivacyFilter implements 3-tier privacy model as a wrapping SpanExporter with daily-salted user ID pseudonymization
- Both entry points (main.py and base_main.py) call setup_tracing() before FastAPI instance creation
- 15 unit tests covering all privacy tiers, pseudonymization, and SDK initialization

## Task Commits

Each task was committed atomically:

1. **Task 1: Create tracing module with SDK config, privacy filter, and unit tests** - `41eaab260` (test: RED phase) + `78d1ee966` (feat: GREEN phase)
2. **Task 2: Integrate setup_tracing() into main.py and base_main.py** - `0280a97bb` (feat)

_Note: Task 1 followed TDD with RED then GREEN commits_

## Files Created/Modified
- `backend/shared/python_utils/tracing/__init__.py` - Module entry point, exports setup_tracing()
- `backend/shared/python_utils/tracing/config.py` - TracerProvider setup, OTLP exporter, auto-instrumentor registration
- `backend/shared/python_utils/tracing/privacy_filter.py` - TracePrivacyFilter SpanExporter with 3-tier attribute filtering
- `backend/shared/python_utils/tracing/user_tier.py` - determine_user_tier() for privacy tier resolution
- `backend/core/api/requirements.txt` - Added 8 OTel packages
- `backend/core/api/main.py` - Added setup_tracing() call after logging, before FastAPI imports
- `backend/apps/base_main.py` - Added setup_tracing() with ImportError fallback for missing packages
- `backend/tests/test_tracing/conftest.py` - Shared fixtures with sample span attributes per tier
- `backend/tests/test_tracing/test_setup.py` - 3 tests for setup_tracing() function
- `backend/tests/test_tracing/test_privacy_filter.py` - 12 tests for privacy filter and user tier

## Decisions Made
- Used OTel instrumentation version 0.61b0 instead of plan-specified 0.51b0 due to SDK 1.40.0 compatibility requirements
- Implemented _FilteredSpan proxy class to work around ReadableSpan immutability rather than modifying spans in-place
- Added TIER_1_STRIP_ATTRS (db.statement, rpc.request.body) as a separate category not in the plan's original tier lists

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated OTel instrumentation versions from 0.51b0 to 0.61b0**
- **Found during:** Task 1 (dependency installation)
- **Issue:** Plan specified opentelemetry-instrumentation-*==0.51b0 which is incompatible with opentelemetry-sdk==1.40.0
- **Fix:** Used 0.61b0 which is the correct matching instrumentation version for SDK 1.40.0
- **Files modified:** backend/core/api/requirements.txt
- **Verification:** pip install succeeded, all tests pass
- **Committed in:** 78d1ee966 (Task 1 commit)

**2. [Rule 3 - Blocking] Fixed InMemorySpanExporter import path for SDK 1.40.0**
- **Found during:** Task 1 (test infrastructure setup)
- **Issue:** `from opentelemetry.sdk.trace.export import InMemorySpanExporter` raises ImportError in SDK 1.40.0
- **Fix:** Used `from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter`
- **Files modified:** backend/tests/test_tracing/conftest.py
- **Verification:** Tests import and run correctly
- **Committed in:** 78d1ee966 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both auto-fixes necessary due to API changes in OTel SDK 1.40.0. No scope creep.

## Issues Encountered
None beyond the version compatibility issues documented as deviations.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Tracing foundation complete, ready for Plan 02 (custom span creation and context propagation)
- Plans 03-05 can build on the auto-instrumentation and privacy filter established here
- App microservices need OTel packages in their own requirements.txt files (currently only in core API)

## Self-Check: PASSED

All 11 files verified present. All 3 commits verified (41eaab260, 78d1ee966, 0280a97bb). 15/15 tests pass.

---
*Phase: 06-opentelemetry-distributed-tracing*
*Completed: 2026-03-27*
