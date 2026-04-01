/**
 * frontend/packages/ui/src/services/tracing/setup.ts
 *
 * Initializes the browser OpenTelemetry SDK for distributed tracing.
 *
 * - Sets up a WebTracerProvider with a BatchSpanProcessor that exports
 *   traces to the API gateway's OTLP proxy endpoint.
 * - Registers FetchInstrumentation to auto-instrument all fetch() calls,
 *   propagating W3C traceparent headers to the backend.
 * - Uses ZoneContextManager for async context propagation in the browser.
 *
 * Call initTracing(apiBaseUrl) once at app startup, after the API base URL
 * is known. Errors are caught and logged -- tracing failure must not break
 * the application.
 */

import { trace, type Tracer } from '@opentelemetry/api';
import { WebTracerProvider } from '@opentelemetry/sdk-trace-web';
import { BatchSpanProcessor } from '@opentelemetry/sdk-trace-web';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { ZoneContextManager } from '@opentelemetry/context-zone';
import { registerInstrumentations } from '@opentelemetry/instrumentation';
import { FetchInstrumentation } from '@opentelemetry/instrumentation-fetch';
import { resourceFromAttributes } from '@opentelemetry/resources';

import {
	TRACING_SERVICE_NAME,
	OTLP_TRACES_PATH,
	TRACING_IGNORE_URLS
} from './config';

/** Cached tracer instance -- created once by initTracing(). */
let _tracer: Tracer | null = null;

/**
 * Initialize the browser OTel SDK.
 *
 * @param apiBaseUrl - Fully qualified API gateway URL (e.g. "https://api.example.com").
 *                     The OTLP proxy path is appended to this.
 */
export function initTracing(apiBaseUrl: string): void {
	try {
		const exportUrl = `${apiBaseUrl}${OTLP_TRACES_PATH}`;

		const exporter = new OTLPTraceExporter({
			url: exportUrl
		});

		const provider = new WebTracerProvider({
			resource: resourceFromAttributes({
				'service.name': TRACING_SERVICE_NAME
			}),
			spanProcessors: [new BatchSpanProcessor(exporter)]
		});

		provider.register({
			contextManager: new ZoneContextManager()
		});

		// Escape the API base URL for use in a RegExp
		const escapedBase = apiBaseUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

		registerInstrumentations({
			instrumentations: [
				new FetchInstrumentation({
					ignoreUrls: TRACING_IGNORE_URLS,
					propagateTraceHeaderCorsUrls: [new RegExp(`${escapedBase}.*`)]
				})
			]
		});

		_tracer = trace.getTracer(TRACING_SERVICE_NAME);

		console.info('[Tracing] Browser OTel SDK initialized — exporting to', exportUrl);
	} catch (error) {
		console.error('[Tracing] Failed to initialize browser OTel SDK:', error);
	}
}

/**
 * Get the application tracer instance.
 *
 * Returns a no-op tracer if initTracing() has not been called yet,
 * so callers can use it safely without null checks.
 */
export function getTracer(): Tracer {
	if (_tracer) return _tracer;
	return trace.getTracer(TRACING_SERVICE_NAME);
}
