/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * frontend/apps/web_app/tests/helpers/otel-capture.ts
 *
 * Playwright helper that captures OTel span data from the browser for
 * profiling the message send pipeline in E2E tests.
 *
 * Strategy: Injects a custom SpanProcessor into the browser's OTel SDK
 * that stores completed span data in window.__otelCapturedSpans. This is
 * more reliable than intercepting OTLP network exports (which may use
 * protobuf encoding that can't be parsed in Node).
 *
 * Usage:
 *   const { injectOtelCapture, collectOtelSpans, saveOtelTimeline } = require('./helpers/otel-capture');
 *
 *   // After page loads and OTel is initialized (after login):
 *   await injectOtelCapture(page);
 *
 *   // After sending a message (wait for spans to complete):
 *   const spans = await collectOtelSpans(page);
 *   saveOtelTimeline(spans, chatId, 'message-send');
 */
export {};

const fs = require('fs');
const path = require('path');

/** Span data shape returned from the browser. */
interface CapturedSpan {
	traceId: string;
	spanId: string;
	parentSpanId: string;
	name: string;
	startMs: number;
	endMs: number;
	durationMs: number;
	status: string;
	attributes: Record<string, any>;
}

/**
 * Inject a capturing SpanProcessor into the browser's OTel SDK.
 *
 * Must be called AFTER the page has loaded and initTracing() has run.
 * The injected processor records all completed spans to window.__otelCapturedSpans.
 * Existing processors (BatchSpanProcessor for OpenObserve export) are preserved.
 *
 * @param page - Playwright page object
 */
async function injectOtelCapture(page: any): Promise<boolean> {
	return await page.evaluate(() => {
		try {
			(window as any).__otelCapturedSpans = [];

			// Access the global OTel trace API to get the registered provider.
			// The provider is registered by setup.ts initTracing().
			const otelApi = (window as any).__OTEL_API__ ||
				// The OTel API stores the global provider in a symbol-keyed property.
				// We can access it via the trace API's getTracerProvider().
				null;

			// Monkey-patch the tracer's startSpan to wrap spans with onEnd recording.
			// This is more reliable than accessing the provider's internal processor list.
			const originalGetTracer = (window as any).__otelOriginalGetTracer;
			if (originalGetTracer) {
				// Already injected
				return true;
			}

			// Alternative approach: use PerformanceObserver to capture span timing
			// via performance.mark() calls that OTel SDK adds internally.
			// This doesn't require accessing OTel internals.

			// Simplest reliable approach: add performance marks in the pipeline code
			// and capture them here. But since we already have OTel spans, we need
			// to capture them.

			// Most reliable approach for capturing: wrap console.debug to detect
			// span-related logging, OR simply use PerformanceObserver for resource
			// timing on the OTLP export requests.

			// Use a MutationObserver-style approach: poll for a custom data attribute
			// that we'll add to the pipeline code.

			// Actually — simplest: override the OTLP exporter's export method.
			// The WebTracerProvider stores processors, each processor has an exporter.
			// But this requires accessing private fields.

			// PRAGMATIC APPROACH: Wrap fetch() to intercept OTLP exports.
			// This works because:
			// 1. OTLPTraceExporter uses fetch() (not sendBeacon)
			// 2. We can parse the JSON body before it's sent
			// 3. Wrapping fetch is a standard testing pattern
			const originalFetch = window.fetch;
			window.fetch = async function (...args: any[]) {
				const [url, options] = args;
				const urlStr = typeof url === 'string' ? url : (url as Request)?.url || '';

				if (urlStr.includes('/v1/telemetry/traces') && options?.method === 'POST') {
					try {
						let body = options.body;
						// OTLPTraceExporter sends JSON with content-type application/json
						if (typeof body === 'string') {
							const payload = JSON.parse(body);
							const spans = (window as any).__otelCapturedSpans;
							for (const rs of (payload.resourceSpans || [])) {
								for (const ss of (rs.scopeSpans || [])) {
									for (const span of (ss.spans || [])) {
										const startNano = Number(BigInt(span.startTimeUnixNano || '0') / BigInt(1_000_000));
										const endNano = Number(BigInt(span.endTimeUnixNano || '0') / BigInt(1_000_000));
										spans.push({
											traceId: span.traceId || '',
											spanId: span.spanId || '',
											parentSpanId: span.parentSpanId || '',
											name: span.name || 'unknown',
											startMs: startNano,
											endMs: endNano,
											durationMs: endNano - startNano,
											status: span.status?.code === 2 ? 'ERROR' : 'OK',
											attributes: (span.attributes || []).reduce((acc: any, attr: any) => {
												const v = attr.value;
												acc[attr.key] = v?.stringValue ?? v?.intValue ?? v?.doubleValue ?? v?.boolValue ?? null;
												return acc;
											}, {})
										});
									}
								}
							}
						}
					} catch {
						// Parse failed — body might be ArrayBuffer (protobuf). Skip.
					}
				}

				return originalFetch.apply(window, args);
			};

			return true;
		} catch (err: any) {
			console.error('[OTel Capture] Injection failed:', err);
			return false;
		}
	});
}

/**
 * Collect captured OTel spans from the browser context.
 *
 * Forces the BatchSpanProcessor to flush, waits briefly, then reads
 * all spans accumulated in window.__otelCapturedSpans.
 *
 * @param page - Playwright page object
 * @param filterPrefix - Only return spans whose name starts with this prefix
 */
async function collectOtelSpans(
	page: any,
	filterPrefix: string = 'message.send'
): Promise<CapturedSpan[]> {
	// Force-flush the OTel provider to export pending spans
	await page.evaluate(async () => {
		try {
			// The OTel SDK registers the provider globally. Access it via the
			// internal registry. The trace API module caches the provider.
			// We need to call forceFlush() on the WebTracerProvider.
			// The simplest way: the provider is stored by the OTel API's
			// setGlobalTracerProvider, accessible via the API's internal state.
			// Since we can't import modules in page.evaluate, we access the
			// global OTel proxy object that the API creates.
			const globalThis = window as any;
			// OTel API stores providers in a global symbol
			const symbols = Object.getOwnPropertySymbols(globalThis);
			for (const sym of symbols) {
				const val = globalThis[sym];
				if (val && typeof val === 'object') {
					// Look for the trace provider delegate
					const delegate = val?.['trace']?._delegate || val?.['trace'];
					if (delegate && typeof delegate.forceFlush === 'function') {
						await delegate.forceFlush();
						return;
					}
				}
			}
			// Fallback: try the global OpenTelemetry object pattern
			if (globalThis.OpenTelemetry?.trace?.getTracerProvider) {
				const provider = globalThis.OpenTelemetry.trace.getTracerProvider();
				if (typeof provider.forceFlush === 'function') {
					await provider.forceFlush();
				}
			}
		} catch {
			// Force flush failed — spans may still arrive via batch timer
		}
	});

	// Wait for the flush + export to complete
	await page.waitForTimeout(2000);

	// Read captured spans from the browser
	const allSpans: CapturedSpan[] = await page.evaluate(() => {
		return (window as any).__otelCapturedSpans || [];
	});

	// Filter to requested prefix
	return allSpans
		.filter((s: CapturedSpan) => s.name.startsWith(filterPrefix))
		.sort((a: CapturedSpan, b: CapturedSpan) => a.startMs - b.startMs);
}

/**
 * Save the OTel timeline to artifacts for the test report.
 *
 * Creates both a markdown file (human-readable) and a JSON file
 * (programmatic) with the pipeline stage latency breakdown.
 *
 * @param spans - Captured spans from collectOtelSpans()
 * @param chatId - Chat ID for the test message
 * @param phase - Label for this capture point
 * @returns Path to the saved markdown file
 */
function saveOtelTimeline(
	spans: CapturedSpan[],
	chatId: string,
	phase: string = 'message-send'
): string {
	const artifactsDir = path.resolve(process.cwd(), 'artifacts');
	fs.mkdirSync(artifactsDir, { recursive: true });

	const filePath = path.join(artifactsDir, `otel-timeline-${chatId}.md`);

	const pipelineSummary = spans.map((s: CapturedSpan) => ({
		name: s.name,
		durationMs: s.durationMs,
		status: s.status
	}));

	const totalDuration = spans.length > 0
		? spans[spans.length - 1].endMs - spans[0].startMs
		: 0;

	const lines: string[] = [
		`# OTel Timeline: ${phase}`,
		'',
		`**Chat ID:** ${chatId}`,
		`**Captured:** ${new Date().toISOString()}`,
		`**Pipeline spans:** ${spans.length}`,
		`**Total pipeline duration:** ${totalDuration}ms`,
		'',
		'## Pipeline Stage Latency',
		'',
		'| # | Stage | Duration (ms) | % of Total | Status |',
		'|---|-------|--------------|------------|--------|'
	];

	spans.forEach((s: CapturedSpan, i: number) => {
		const pct = totalDuration > 0 ? ((s.durationMs / totalDuration) * 100).toFixed(1) : '0';
		const depth = s.name.split('.').length;
		const indent = depth > 3 ? '\u00A0\u00A0' : '';
		lines.push(
			`| ${i + 1} | ${indent}${s.name} | ${s.durationMs} | ${pct}% | ${s.status} |`
		);
	});

	if (spans.length === 0) {
		lines.push('| - | No spans captured | - | - | - |');
		lines.push('');
		lines.push('> **Note:** No message.send.* spans were captured. This could mean:');
		lines.push('> - The OTel SDK was not initialized (check console for "[Tracing] Browser OTel SDK initialized")');
		lines.push('> - The BatchSpanProcessor did not flush before capture');
		lines.push('> - The fetch() wrapper was not injected (call injectOtelCapture after page load)');
	}

	lines.push('');
	lines.push('## Raw Span Data');
	lines.push('');
	lines.push('```json');
	lines.push(JSON.stringify(spans, null, 2));
	lines.push('```');
	lines.push('');

	fs.writeFileSync(filePath, lines.join('\n'), 'utf8');
	console.log(`[OTel Capture] Saved timeline (${spans.length} spans) to ${filePath}`);

	// Also save as JSON for programmatic consumption
	const jsonPath = path.join(artifactsDir, `otel-timeline-${chatId}.json`);
	fs.writeFileSync(
		jsonPath,
		JSON.stringify(
			{
				chat_id: chatId,
				phase,
				captured_at: new Date().toISOString(),
				pipeline_spans: spans.length,
				total_duration_ms: totalDuration,
				stages: pipelineSummary,
				spans
			},
			null,
			2
		),
		'utf8'
	);

	return filePath;
}

module.exports = {
	injectOtelCapture,
	collectOtelSpans,
	saveOtelTimeline
};
