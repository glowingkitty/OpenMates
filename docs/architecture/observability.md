# Observability

OpenMates sends backend OpenTelemetry data to its self-hosted OpenObserve
deployment. AI request telemetry follows
`architecture.ai-request-observability`: it measures structure and timing but
must never export prompts, responses, tool payloads, URLs, filenames, raw
errors, or stable user, chat, message, task, device, or session identifiers.

## AI Request Traces

One request-scoped trace links the active client send, WebSocket handler,
Celery dispatch, `worker-app-ai` task, and final marker. AI spans use reviewed
phase names: `queue`, `prepare`, `preprocess`, `main`, `main.iteration`,
`provider`, `tool`, `finalize.billing`, `finalize.persistence`,
`finalize.validation`, `finalize.marker`, and `postprocess`.

Default exact counts are replaced by low-cardinality buckets. Aggregate phase
histograms contain only `phase` and normalized `status_class` labels. Exporters
apply the same strict attribute allowlist in development and production.

Query a known dev trace from a container that can reach OpenObserve:

```bash
docker exec api python -m backend.scripts.debug trace request --id <TRACE_ID>
```

The command renders a structural waterfall and explicitly lists missing AI
phases. Its JSON mode projects spans onto reviewed structural fields rather
than returning raw OpenObserve documents.

## Diagnostic Mode

Exact reviewed non-content metadata is disabled by default. A tier-3 operator
scope is active only when all of these variables describe an audited window of
at most 24 hours:

- `OTEL_DIAGNOSTIC_AUDIT_ID`
- `OTEL_DIAGNOSTIC_OWNER`
- `OTEL_DIAGNOSTIC_REASON`
- `OTEL_DIAGNOSTIC_STARTED_AT` as a Unix timestamp
- `OTEL_DIAGNOSTIC_EXPIRES_AT` as a Unix timestamp

Diagnostic mode never permits content, destinations, secrets, stable private
identifiers, events, links, status descriptions, or raw errors.

## Retention

The `default` trace stream inherits OpenObserve's global 14-day retention. The
AI observability contract prohibits operational trace retention above 30 days.
Verify the live dev container and stream inheritance with:

```bash
python3 scripts/verify_ai_observability.py retention --target dev
```

Dashboards and alerts are intentionally deferred until seven complete,
privacy-valid dev days are available. Thresholds must be derived from that
baseline and use sustained breach windows rather than arbitrary constants.
