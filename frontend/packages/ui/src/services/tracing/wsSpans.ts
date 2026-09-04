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

import { context, propagation, SpanStatusCode, type Span } from '@opentelemetry/api';
import { getTracer } from './setup';

// ---------------------------------------------------------------------------
// Recent trace ID ring buffer — attached to issue reports so admins can
// correlate reported issues with OTel traces in OpenObserve.
// ---------------------------------------------------------------------------

/** Maximum number of trace IDs to retain in the ring buffer. */
const MAX_RECENT_TRACE_IDS = 20;

/** Ring buffer of the last N request trace IDs. */
const _recentTraceIds: string[] = [];

function recordTraceId(span: Span): void {
	const traceId = span.spanContext()?.traceId;
	if (!traceId) return;
	if (_recentTraceIds.length >= MAX_RECENT_TRACE_IDS) {
		_recentTraceIds.shift();
	}
	if (_recentTraceIds[_recentTraceIds.length - 1] !== traceId) {
		_recentTraceIds.push(traceId);
	}
}

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
	recordTraceId(span);

	return span;
}

/** Run one WebSocket send while its span is the active propagation context. */
export function withActiveWsSpan<T>(name: string, send: () => T | Promise<T>): Promise<T> {
	return getTracer().startActiveSpan(`ws.${name}`, async (span) => {
		recordTraceId(span);
		try {
			return await send();
		} catch (error) {
			span.setStatus({ code: SpanStatusCode.ERROR });
			throw error;
		} finally {
			span.end();
		}
	});
}
