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
 * Lifecycle:
 * - Dev: initTracing() called at app startup for all visitors.
 * - Prod: initTracing() called after login for admins / extended-debug users.
 *         stopTracing() called on logout or debug session deactivation.
 *
 * Errors are caught and logged — tracing failure must not break the application.
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

/** Cached tracer instance — created once by initTracing(). */
let _tracer: Tracer | null = null;

/** Cached provider for shutdown on logout. */
let _provider: WebTracerProvider | null = null;

/**
 * Initialize the browser OTel SDK.
 * Idempotent — calling multiple times is a no-op after the first init.
 *
 * @param apiBaseUrl - Fully qualified API gateway URL (e.g. "https://api.example.com").
 *                     The OTLP proxy path is appended to this.
 */
export function initTracing(apiBaseUrl: string): void {
	if (_tracer) {
		console.debug('[Tracing] Already initialized, skipping');
		return;
	}

	try {
		const exportUrl = `${apiBaseUrl}${OTLP_TRACES_PATH}`;

		// The OTel fetch transport does not support a credentials option, but the
		// backend requires the auth_refresh_token cookie for production auth.
		// Wrap fetch to inject credentials: 'include' for telemetry requests.
		// Pattern: same cross-origin cookie approach as clientLogForwarder.ts.
		const nativeFetch = globalThis.fetch;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		const wrappedFetch = ((...args: any[]) => {
			const [input, init] = args;
			const url =
				typeof input === 'string'
					? input
					: input instanceof URL
						? input.href
						: input.url;
			if (url.includes(OTLP_TRACES_PATH)) {
				return nativeFetch(input, { ...init, credentials: 'include' });
			}
			return nativeFetch(input, init);
		}) as typeof fetch;
		// Preserve __original so OTel's FetchTransport can bypass instrumentation
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		(wrappedFetch as any).__original = nativeFetch;
		globalThis.fetch = wrappedFetch;

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

		_provider = provider;
		_tracer = trace.getTracer(TRACING_SERVICE_NAME);

		console.info('[Tracing] Browser OTel SDK initialized — exporting to', exportUrl);
	} catch (error) {
		console.error('[Tracing] Failed to initialize browser OTel SDK:', error);
	}
}

/**
 * Stop the browser OTel SDK — flush pending spans and shut down the provider.
 * Called on logout or when a debug session is deactivated on production.
 * Safe to call when tracing is not initialized (no-op).
 */
export async function stopTracing(): Promise<void> {
	if (!_provider) return;
	try {
		await _provider.forceFlush();
		await _provider.shutdown();
		console.info('[Tracing] Browser OTel SDK stopped');
	} catch {
		// Non-critical — shutdown failure must not break the app
	} finally {
		_provider = null;
		_tracer = null;
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
