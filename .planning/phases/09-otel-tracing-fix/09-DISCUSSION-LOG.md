# Phase 9: OTel Tracing Fix - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 09-otel-tracing-fix
**Areas discussed:** Privacy tier wiring, debug.py trace rework, Trace output format, Missing handler instrumentation

---

## Privacy Tier Wiring

| Option | Description | Selected |
|--------|-------------|----------|
| WebSocket middleware | Set attributes once when WS connection authenticates. All child spans inherit. | ✓ |
| Per-handler injection | Each WS handler reads user record and sets attributes on its own span. | |
| HTTP middleware + WS handler | HTTP middleware handles REST, WS auth handler covers WebSocket. | |

**User's choice:** WebSocket middleware
**Notes:** Clean single injection point.

### Data Source

| Option | Description | Selected |
|--------|-------------|----------|
| From existing WS auth context | User record already loaded during auth. Zero extra calls. | ✓ |
| Separate cache lookup | Read from Redis cache. Extra call but decoupled. | |

**User's choice:** From existing WS auth context

---

## debug.py trace rework

| Option | Description | Selected |
|--------|-------------|----------|
| Full span tree | Indented hierarchy with HTTP paths, services, durations, status. | ✓ |
| Compact one-liner per trace | One line per trace with key info. | |
| Both modes with --verbose flag | Default compact, --verbose for full tree. | |

**User's choice:** Full span tree as default

---

## Trace Output Format (Recent Command)

| Option | Description | Selected |
|--------|-------------|----------|
| New 'trace recent' subcommand | debug.py trace recent --last 5m — shows ALL traces. | ✓ |
| Fix existing commands only | Make 'trace errors' show proper trees + add --all flag. | |
| Both | New command + fix existing. | |

**User's choice:** New 'trace recent' subcommand

---

## Missing Handler Instrumentation

| Option | Description | Selected |
|--------|-------------|----------|
| All WS handlers | Instrument all ~15 handlers consistently. | ✓ |
| Only key_received_handler | Minimal fix for the audit gap. | |
| key_received + any others missing | Audit and fill gaps only. | |

**User's choice:** All WS handlers

---

## Claude's Discretion

- Span attribute naming conventions
- OTel context propagation mechanism for WS auth
- Decorator vs inline span creation
- trace recent pagination defaults
- OpenObserve query API usage

## Deferred Ideas

None
