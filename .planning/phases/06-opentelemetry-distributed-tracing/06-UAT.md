---
status: testing
phase: 06-opentelemetry-distributed-tracing
source: [06-01-SUMMARY.md, 06-02-SUMMARY.md, 06-03-SUMMARY.md, 06-04-SUMMARY.md, 06-05-SUMMARY.md]
started: 2026-03-27T13:15:00Z
updated: 2026-03-27T13:40:00Z
---

## Current Test

number: 5
name: Traces appear in OpenObserve
expected: |
  OTLP ingestion accepted (200 OK), but OpenObserve trace stream shows 0 docs.
  Likely WAL flush delay or OpenObserve trace stream config issue.
awaiting: investigation — OpenObserve trace WAL flush configuration

## Tests

### 1. API container starts with OTel tracing enabled
expected: API container boots without errors after deploy. Logs show tracing initialization.
result: PASS — Fixed instrumentor API (instance-level .instrument()). Logs show "Initializing OpenTelemetry tracing for service 'api'" and "OpenTelemetry tracing initialized: service=api, endpoint=http://openobserve:5080/api/default/v1/traces"

### 2. Settings > Privacy shows Debug Logging toggle
expected: A "Debug Logging" toggle appears in Settings > Privacy & Security with description text.
result: [needs browser check — user]

### 3. Debug Logging toggle saves state
expected: Toggle Debug Logging ON, reload the page. Toggle persists as ON.
result: [needs browser check — user]

### 4. debug.py trace CLI responds
expected: `debug.py trace errors --last 1h` returns results or "No traces found" — not an error.
result: PASS — Returns "No trace data found." (no crash, correct behavior when no traces yet)

### 5. Traces appear in OpenObserve
expected: After requests, traces appear in OpenObserve trace stream.
result: PARTIAL — OTLP endpoint accepts payloads (200 OK, partialSuccess: null), but trace stream shows doc_num: 0. BatchSpanProcessor in uvicorn process sends spans, but OpenObserve WAL hasn't flushed to queryable state. Need to investigate OO trace retention/flush config.

### 6. Issue report includes trace IDs
expected: Issue report YAML contains trace_ids field.
result: [blocked by test 5 — needs traces flowing first]

### 7. debug.py issue --timeline shows trace spans
expected: Merged timeline with log events + trace spans.
result: [blocked by test 5 — needs traces flowing first]

## Summary

total: 7
passed: 2
issues: 1
pending: 2
skipped: 0
blocked: 2

## Gaps

### GAP-1: OpenObserve trace stream not returning data
severity: medium
status: investigating
description: OTLP ingestion succeeds (HTTP 200), but the trace stream shows 0 docs. Spans sent with current timestamps are accepted without rejection. Likely an OpenObserve WAL/compaction configuration issue — trace data may be buffered but not yet flushed to the queryable index. Need to check OpenObserve trace retention settings, WAL flush interval, and whether the `default` trace stream needs explicit configuration.
debug_session: none
