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
 * Usage: call injectTraceparent(payload) before sending any WS message.
 */

import { context, propagation, type Span } from '@opentelemetry/api';
import { getTracer } from './setup';

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
 * @param name  - Span name suffix (prefixed with "ws." automatically).
 * @param attributes - Optional span attributes.
 * @returns The started Span instance.
 */
export function createWsSpan(
	name: string,
	attributes?: Record<string, string>
): Span {
	const tracer = getTracer();
	return tracer.startSpan(`ws.${name}`, { attributes });
}
