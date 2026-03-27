/**
 * frontend/packages/ui/src/services/tracing/wsSpans.ts
 *
 * WebSocket span utilities for distributed tracing.
 *
 * Since WebSocket frames don't carry HTTP headers, we inject the
 * W3C traceparent into the JSON message payload as `_traceparent`.
 * The backend's ws_trace_context.py extracts it to create
 * correlated server-side spans.
 *
 * Also maintains a ring buffer of recent trace IDs for inclusion
 * in issue reports, enabling trace-to-issue correlation.
 *
 * Usage: call injectTraceparent(payload) before sending any WS message.
 */

import { context, propagation, type Span } from '@opentelemetry/api';
import { getTracer } from './setup';

// ---------------------------------------------------------------------------
// Recent trace ID ring buffer — attached to issue reports so admins can
// correlate reported issues with OTel traces in OpenObserve.
// ---------------------------------------------------------------------------

/** Maximum number of trace IDs to retain in the ring buffer. */
const MAX_RECENT_TRACE_IDS = 20;

/** Ring buffer of the last N trace IDs created via createWsSpan(). */
const _recentTraceIds: string[] = [];

/**
 * Return a snapshot of the most recent trace IDs (newest last).
 *
 * Used by SettingsReportIssue.svelte to attach trace IDs to issue reports
 * so that debug.py issue --timeline can merge OTel trace spans.
 */
export function getRecentTraceIds(): string[] {
	return [..._recentTraceIds];
}

/**
 * Inject the current trace context into a WebSocket message payload.
 *
 * Reads the active span's W3C traceparent and sets payload._traceparent.
 * If no active span exists, the field is not added (no-op).
 *
 * @param payload - The outgoing WS message payload object. Modified in-place.
 */
export function injectTraceparent(payload: Record<string, unknown>): void {
	const carrier: Record<string, string> = {};
	propagation.inject(context.active(), carrier);

	const traceparent = carrier['traceparent'];
	if (traceparent) {
		payload._traceparent = traceparent;
	}
}

/**
 * Create and start a new span for a WebSocket operation.
 *
 * The caller is responsible for calling span.end() when the operation
 * completes. Typically used for long-running WS message flows where
 * you want to track the full lifecycle.
 *
 * Also records the span's trace ID in the ring buffer for issue reporting.
 *
 * @param name  - Span name suffix (prefixed with "ws." automatically).
 * @param attributes - Optional span attributes.
 * @returns The started Span instance.
 */
export function createWsSpan(
	name: string,
	attributes?: Record<string, string>
): Span {
	const tracer = getTracer();
	const span = tracer.startSpan(`ws.${name}`, { attributes });

	// Record trace ID in the ring buffer for issue correlation
	const spanContext = span.spanContext();
	if (spanContext && spanContext.traceId) {
		if (_recentTraceIds.length >= MAX_RECENT_TRACE_IDS) {
			_recentTraceIds.shift();
		}
		// Deduplicate: only push if different from the last entry
		if (
			_recentTraceIds.length === 0 ||
			_recentTraceIds[_recentTraceIds.length - 1] !== spanContext.traceId
		) {
			_recentTraceIds.push(spanContext.traceId);
		}
	}

	return span;
}
