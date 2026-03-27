---
phase: 06-opentelemetry-distributed-tracing
plan: 03
subsystem: infra
tags: [opentelemetry, tracing, websocket, otlp, distributed-tracing]

requires:
  - phase: 06-01
    provides: OTel SDK setup with TracerProvider and privacy-filtered export

provides:
  - WS trace context extraction/injection module (ws_trace_context.py)
  - OTLP proxy endpoint for frontend browser traces (/v1/telemetry/traces)
  - Server-side spans on message_received and initial_sync WS handlers
  - Browser OTel SDK with fetch auto-instrumentation
  - Frontend WS traceparent injection on all outgoing messages

affects: [06-04, 06-05]

tech-stack:
  added: ["@opentelemetry/api", "@opentelemetry/sdk-trace-web", "@opentelemetry/instrumentation-fetch", "@opentelemetry/exporter-trace-otlp-http", "@opentelemetry/context-zone", "@opentelemetry/instrumentation"]
  patterns: [ws-traceparent-propagation, otlp-proxy, importerror-guard-tracing]

key-files:
  created:
    - backend/shared/python_utils/tracing/ws_trace_context.py
    - backend/core/api/app/routes/telemetry.py
    - frontend/packages/ui/src/services/tracing/config.ts
    - frontend/packages/ui/src/services/tracing/setup.ts
    - frontend/packages/ui/src/services/tracing/wsSpans.ts
    - backend/tests/test_tracing/test_ws_trace_context.py
  modified:
    - backend/core/api/main.py
    - backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py
    - backend/core/api/app/routes/handlers/websocket_handlers/initial_sync_handler.py
    - frontend/packages/ui/src/services/websocketService.ts
    - frontend/packages/ui/src/services/chatSyncServiceSenders.ts
    - frontend/packages/ui/src/app.ts
    - frontend/packages/ui/package.json

key-decisions:
  - "Used opentelemetry.propagate.extract/inject instead of TraceContextTextMapPropagator directly (API changed in OTel SDK 1.40)"
  - "Centralized traceparent injection in websocketService.sendMessage() rather than per-sender function in chatSyncServiceSenders.ts for single injection point"
  - "Guarded all OTel imports with ImportError try/catch so handlers work without OTel installed"

patterns-established:
  - "ImportError guard pattern: all OTel usage in WS handlers wrapped in try/except ImportError for graceful degradation"
  - "WS traceparent propagation: frontend injects _traceparent into payload, backend pops it before processing"
  - "OTLP proxy pattern: authenticated endpoint forwards browser OTLP payloads to OpenObserve with server-side credentials"

requirements-completed: [OTEL-03, OTEL-04, OTEL-05]

duration: 11min
completed: 2026-03-27
---

# Phase 06 Plan 03: WS Instrumentation + Frontend SDK Summary

**Custom WebSocket span instrumentation with _traceparent propagation and browser OTel SDK exporting through authenticated OTLP proxy**

## Performance

- **Duration:** 11 min
- **Started:** 2026-03-27T12:54:40Z
- **Completed:** 2026-03-27T13:06:29Z
- **Tasks:** 2 (Task 1 TDD: RED + GREEN)
- **Files modified:** 13

## Accomplishments

- Backend WS trace context module extracts/injects W3C traceparent from WS message payloads
- OTLP proxy endpoint at /v1/telemetry/traces forwards browser traces to OpenObserve with JWT auth and rate limiting
- message_received_handler and initial_sync_handler create server-side spans correlated with frontend traces
- Browser OTel SDK auto-instruments fetch() calls and injects traceparent into all outgoing WS messages
- 6 unit tests pass for WS trace context extraction/injection

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED):** test(06-03): add failing tests - `7cbe5a1af`
2. **Task 1 (GREEN):** feat(06-03): backend WS trace context + OTLP proxy + handler spans - `ef615b954`
3. **Task 2:** feat(06-03): frontend OTel SDK setup + WS traceparent injection - `89ae7fce7`

## Files Created/Modified

- `backend/shared/python_utils/tracing/ws_trace_context.py` - Extract/inject W3C traceparent from WS payloads
- `backend/core/api/app/routes/telemetry.py` - OTLP proxy endpoint forwarding browser traces to OpenObserve
- `backend/core/api/main.py` - Register telemetry router
- `backend/core/api/app/routes/handlers/websocket_handlers/message_received_handler.py` - Add ws.message_received span with trace context
- `backend/core/api/app/routes/handlers/websocket_handlers/initial_sync_handler.py` - Add ws.initial_sync span
- `frontend/packages/ui/src/services/tracing/config.ts` - Tracing constants (service name, OTLP path, ignore URLs)
- `frontend/packages/ui/src/services/tracing/setup.ts` - initTracing() browser SDK initialization
- `frontend/packages/ui/src/services/tracing/wsSpans.ts` - injectTraceparent() and createWsSpan()
- `frontend/packages/ui/src/services/websocketService.ts` - Inject traceparent into all outgoing WS messages
- `frontend/packages/ui/src/services/chatSyncServiceSenders.ts` - Documentation reference to tracing integration
- `frontend/packages/ui/src/app.ts` - Initialize OTel tracing after auth
- `frontend/packages/ui/package.json` - Added 6 @opentelemetry packages
- `backend/tests/test_tracing/test_ws_trace_context.py` - 6 unit tests for WS trace context

## Decisions Made

1. **opentelemetry.propagate API over TraceContextTextMapPropagator** - OTel SDK 1.40 moved the propagator; using the top-level `propagate.extract/inject` API is more portable across versions
2. **Centralized traceparent injection in websocketService.sendMessage()** - Rather than modifying 15+ sender functions in chatSyncServiceSenders.ts, injecting in the single send bottleneck ensures ALL WS messages get traceparent with zero maintenance burden
3. **ImportError guard pattern** - All OTel usage in WS handlers is wrapped in try/except ImportError so the handlers continue to work even if OTel packages are not installed (e.g., in test environments or lightweight deployments)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] OTel SDK 1.40 API differences**
- **Found during:** Task 1 (ws_trace_context.py implementation)
- **Issue:** `opentelemetry.propagation` module doesn't exist in OTel SDK 1.40; it's `opentelemetry.propagate`. Similarly `TraceContextTextMapPropagator` is not importable from the expected path.
- **Fix:** Used `from opentelemetry.propagate import extract, inject` instead
- **Files modified:** backend/shared/python_utils/tracing/ws_trace_context.py
- **Verification:** All 6 unit tests pass

**2. [Rule 2 - Missing Critical] Traceparent injection point**
- **Found during:** Task 2 (chatSyncServiceSenders.ts integration)
- **Issue:** Plan suggested modifying chatSyncServiceSenders.ts sender functions individually, but there are 15+ call sites. This would be fragile and miss any new sender functions added later.
- **Fix:** Added traceparent injection centrally in websocketService.sendMessage() instead, ensuring all WS messages get traceparent automatically
- **Files modified:** frontend/packages/ui/src/services/websocketService.ts
- **Verification:** grep confirms injectTraceparent is called before ws.send()

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing critical)
**Impact on plan:** Both auto-fixes improve robustness and maintainability. No scope creep.

## Issues Encountered

- OTel Python SDK v1.40 has different import paths than documented in older tutorials. Resolved by testing imports interactively and using the `opentelemetry.propagate` module.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- WS tracing infrastructure is complete; Plans 04 and 05 can build on this for Celery task spans and dashboard configuration
- The `_traceparent` field propagation pattern is established and can be extended to additional WS handlers

---
*Phase: 06-opentelemetry-distributed-tracing*
*Completed: 2026-03-27*

## Self-Check: PASSED

All 7 created files exist. All 3 commits verified in git log.
