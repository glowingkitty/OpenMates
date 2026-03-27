# Phase 9: OTel Tracing Fix - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix the broken OTel tracing implementation from Phase 6. Wire privacy tiers to actual user data so Tier 2/3 activate correctly. Instrument all WebSocket handlers with OTel spans. Rework `debug.py trace` CLI to show full span trees with meaningful detail. Add a new `trace recent` subcommand for viewing all requests in a time window.

This is a gap closure phase — the OTel architecture from Phase 6 is sound, but the wiring was never completed and the CLI output is practically useless.

</domain>

<decisions>
## Implementation Decisions

### Privacy Tier Wiring
- **D-01:** Inject `enduser.is_admin` and `enduser.debug_opted_in` as span attributes once during WebSocket connection authentication. All child spans inherit these attributes. One injection point covers all WS handlers.
- **D-02:** Read admin status and opt-in from the existing WS auth context — the user record is already loaded during authentication. Zero extra DB or cache calls needed.

### debug.py trace CLI Rework
- **D-03:** Default trace output shows full span trees with indented hierarchy — every span shows HTTP path/WS message type, service name, duration, and status. Example:
  ```
  Trace abc123 — GET /v1/chats (234ms) OK
    ├─ directus.get_chats (45ms) OK
    ├─ redis.get cache:chats (2ms) OK
    └─ httpx.post app-ai (180ms) OK
        └─ celery.task ask_skill (170ms) OK
  ```
- **D-04:** New `trace recent --last 5m` subcommand shows ALL traces from the time window (not just errors). Separate from `trace errors` which filters to errors only.
- **D-05:** Fix `trace errors` output to also show full span trees (same format as `trace recent`), not just bare root spans.

### WebSocket Handler Instrumentation
- **D-06:** Apply consistent OTel span instrumentation to ALL ~15 WebSocket handlers, not just `key_received_handler.py`. Creates a uniform pattern where every WS message type is visible in distributed traces.

### Claude's Discretion
- Exact span attribute names (follow OTel semantic conventions)
- How to inject attributes into the OTel context during WS auth (context propagation mechanism)
- Whether to use a decorator or inline span creation for WS handlers
- `trace recent` pagination/limit defaults
- How to query OpenObserve for recent traces (API endpoint, query syntax)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 6 Context and Implementation
- `.planning/phases/06-opentelemetry-distributed-tracing/06-CONTEXT.md` — Original OTel architecture decisions (3-tier model, performance budget, all design choices)
- `.planning/phases/06-opentelemetry-distributed-tracing/06-03-SUMMARY.md` — WS instrumentation that was done (and what was missed)
- `.planning/phases/06-opentelemetry-distributed-tracing/06-04-SUMMARY.md` — debug.py trace CLI implementation

### Milestone Audit
- `.planning/v1.0-MILESTONE-AUDIT.md` — Documents OTEL-02, OTEL-05, OTEL-06 gaps and integration breaks

### Tracing Source Files (to fix)
- `backend/shared/python_utils/tracing/user_tier.py` — Reads span attributes that are never set (the core bug)
- `backend/shared/python_utils/tracing/privacy_filter.py` — TracePrivacyFilter that calls user_tier
- `backend/shared/python_utils/tracing/config.py` — OTel SDK configuration
- `backend/shared/python_utils/tracing/ws_trace_context.py` — WS trace context extraction/injection

### WebSocket Handlers (instrumentation targets)
- `backend/core/api/app/routes/handlers/websocket_handlers/` — All WS handlers (~15 files)
- `backend/core/api/app/routes/websockets.py` — WS connection management and auth

### debug.py trace CLI (to rework)
- `backend/scripts/debug_trace.py` — Current 659-line trace CLI (output needs complete rework)
- `backend/scripts/debug.py` — Main CLI entry point

### User Settings
- `backend/core/api/app/services/directus/directus.py` — DirectusService (user record access)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `user_tier.py` — Already has the tier resolution logic, just needs span attributes populated
- `privacy_filter.py` — TracePrivacyFilter is complete and correctly calls user_tier
- `ws_trace_context.py` — Has extract/inject functions for WS trace context
- `debug_trace.py` — 659 lines, has OpenObserve query infrastructure, needs output formatting rework

### Established Patterns
- Phase 6 Plan 03 instrumented `message_received_handler.py` and `initial_sync_handler.py` — same pattern applies to remaining handlers
- WS auth already loads user record with admin status — just needs to set span attributes from it

### Integration Points
- WS connection auth in `websockets.py` — where user attributes should be injected into OTel context
- OpenObserve trace API — `debug_trace.py` already queries it, but the response parsing/formatting is broken
- `debug.py` dispatch — already routes `trace` subcommand to `debug_trace.py`

</code_context>

<specifics>
## Specific Ideas

- User explicitly reported that `debug.py trace errors --last 2h` output is "nonsense" — only shows bare root spans with no HTTP paths or child spans
- User wants to easily see "full traces of all requests from the last X min" — this is the `trace recent` use case
- The span tree format with Unicode box-drawing characters (├─ └─) is the expected output style

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 09-otel-tracing-fix*
*Context gathered: 2026-03-27*
