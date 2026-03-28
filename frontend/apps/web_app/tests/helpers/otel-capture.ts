/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * frontend/apps/web_app/tests/helpers/otel-capture.ts
 *
 * Playwright helper that intercepts OTLP trace export requests from the
 * browser OTel SDK and captures span data for test artifacts.
 *
 * Usage:
 *   const { setupOtelCapture, getOtelTimeline, saveOtelTimeline } = require('./helpers/otel-capture');
 *
 *   // In test setup (after page.goto):
 *   await setupOtelCapture(page);
 *
 *   // After sending a message:
 *   const timeline = getOtelTimeline();
 *   saveOtelTimeline(timeline, chatId, 'after-send');
 *
 * The captured data includes span names, durations, start/end timestamps,
 * attributes, and parent-child relationships. This enables profiling the
 * message send pipeline without needing access to OpenObserve.
 */
export {};

const fs = require('fs');
const path = require('path');

/** Raw span data extracted from OTLP JSON payloads. */
interface CapturedSpan {
	traceId: string;
	spanId: string;
	parentSpanId: string | null;
	name: string;
	startTimeUnixNano: string;
	endTimeUnixNano: string;
	durationMs: number;
	status: string;
	attributes: Record<string, any>;
}

/** Accumulated spans from all OTLP exports during the test. */
let capturedSpans: CapturedSpan[] = [];

/**
 * Set up OTLP request interception on a Playwright page.
 *
 * Intercepts POST requests to /v1/telemetry/traces, parses the OTLP JSON
 * payload, extracts span data, and forwards the request to the server
 * (so OpenObserve still receives the traces).
 *
 * Call once per page, after page.goto() but before any traced operations.
 */
async function setupOtelCapture(page: any): Promise<void> {
	capturedSpans = [];

	await page.route('**/v1/telemetry/traces', async (route: any) => {
		const request = route.request();

		try {
			const postData = request.postData();
			if (postData) {
				const payload = JSON.parse(postData);
				extractSpansFromPayload(payload);
			}
		} catch (err) {
			// JSON parse failure — payload might be protobuf. Skip extraction.
			console.warn('[OTel Capture] Failed to parse OTLP payload:', err);
		}

		// Forward the request to the actual endpoint so traces still reach OpenObserve
		await route.continue();
	});
}

/**
 * Extract span data from an OTLP JSON payload.
 *
 * OTLP JSON structure:
 *   { resourceSpans: [{ scopeSpans: [{ spans: [...] }] }] }
 *
 * Each span has: traceId, spanId, parentSpanId, name, startTimeUnixNano,
 * endTimeUnixNano, status, attributes.
 */
function extractSpansFromPayload(payload: any): void {
	const resourceSpans = payload?.resourceSpans || [];

	for (const rs of resourceSpans) {
		const scopeSpans = rs?.scopeSpans || [];
		for (const ss of scopeSpans) {
			const spans = ss?.spans || [];
			for (const span of spans) {
				const startNano = BigInt(span.startTimeUnixNano || '0');
				const endNano = BigInt(span.endTimeUnixNano || '0');
				const durationMs = Number((endNano - startNano) / BigInt(1_000_000));

				capturedSpans.push({
					traceId: span.traceId || '',
					spanId: span.spanId || '',
					parentSpanId: span.parentSpanId || null,
					name: span.name || 'unknown',
					startTimeUnixNano: span.startTimeUnixNano || '0',
					endTimeUnixNano: span.endTimeUnixNano || '0',
					durationMs,
					status: span.status?.code === 2 ? 'ERROR' : 'OK',
					attributes: extractAttributes(span.attributes || [])
				});
			}
		}
	}
}

/**
 * Convert OTLP attribute array to a flat key-value object.
 * OTLP attributes: [{ key: "foo", value: { stringValue: "bar" } }, ...]
 */
function extractAttributes(attrs: any[]): Record<string, any> {
	const result: Record<string, any> = {};
	for (const attr of attrs) {
		const key = attr.key;
		const val = attr.value;
		if (val?.stringValue !== undefined) result[key] = val.stringValue;
		else if (val?.intValue !== undefined) result[key] = Number(val.intValue);
		else if (val?.doubleValue !== undefined) result[key] = val.doubleValue;
		else if (val?.boolValue !== undefined) result[key] = val.boolValue;
	}
	return result;
}

/**
 * Get the captured OTel timeline, filtered to message.send.* spans.
 *
 * Returns spans sorted by start time, with a tree structure showing
 * parent-child relationships and a summary of the pipeline stages.
 */
function getOtelTimeline(filterPrefix: string = 'message.send'): {
	spans: CapturedSpan[];
	totalCount: number;
	filteredCount: number;
	pipelineSummary: { name: string; durationMs: number; status: string }[];
} {
	const filtered = capturedSpans
		.filter((s) => s.name.startsWith(filterPrefix))
		.sort((a, b) => {
			const aStart = BigInt(a.startTimeUnixNano);
			const bStart = BigInt(b.startTimeUnixNano);
			return aStart < bStart ? -1 : aStart > bStart ? 1 : 0;
		});

	const pipelineSummary = filtered.map((s) => ({
		name: s.name,
		durationMs: s.durationMs,
		status: s.status
	}));

	return {
		spans: filtered,
		totalCount: capturedSpans.length,
		filteredCount: filtered.length,
		pipelineSummary
	};
}

/**
 * Save the OTel timeline to an artifacts file for the test report.
 *
 * Creates a markdown file with a formatted timeline table showing
 * per-stage latency breakdown. This file is uploaded as a GHA artifact
 * and can be included in test result MD reports.
 */
function saveOtelTimeline(
	chatId: string,
	phase: string = 'message-send',
	filterPrefix: string = 'message.send'
): string {
	const timeline = getOtelTimeline(filterPrefix);
	const artifactsDir = path.resolve(process.cwd(), 'artifacts');
	fs.mkdirSync(artifactsDir, { recursive: true });

	const filePath = path.join(artifactsDir, `otel-timeline-${chatId}.md`);

	const lines: string[] = [
		`# OTel Timeline: ${phase}`,
		'',
		`**Chat ID:** ${chatId}`,
		`**Captured:** ${new Date().toISOString()}`,
		`**Total spans:** ${timeline.totalCount}`,
		`**Pipeline spans:** ${timeline.filteredCount}`,
		'',
		'## Pipeline Stage Latency',
		'',
		'| Stage | Duration (ms) | Status |',
		'|-------|--------------|--------|'
	];

	for (const stage of timeline.pipelineSummary) {
		const indent = stage.name.includes('.') && stage.name.split('.').length > 3 ? '  ' : '';
		lines.push(
			`| ${indent}${stage.name} | ${stage.durationMs} | ${stage.status} |`
		);
	}

	lines.push('');

	// Add the raw span data as JSON for programmatic analysis
	lines.push('## Raw Span Data');
	lines.push('');
	lines.push('```json');
	lines.push(JSON.stringify(timeline.spans, null, 2));
	lines.push('```');
	lines.push('');

	fs.writeFileSync(filePath, lines.join('\n'), 'utf8');
	console.log(`[OTel Capture] Saved timeline to ${filePath}`);

	// Also save as JSON for programmatic consumption
	const jsonPath = path.join(artifactsDir, `otel-timeline-${chatId}.json`);
	fs.writeFileSync(
		jsonPath,
		JSON.stringify(
			{
				chat_id: chatId,
				phase,
				captured_at: new Date().toISOString(),
				total_spans: timeline.totalCount,
				pipeline_spans: timeline.filteredCount,
				stages: timeline.pipelineSummary,
				spans: timeline.spans
			},
			null,
			2
		),
		'utf8'
	);

	return filePath;
}

/**
 * Clear all captured spans (call between test cases if needed).
 */
function clearOtelCapture(): void {
	capturedSpans = [];
}

/**
 * Get the total number of captured spans (for assertions).
 */
function getCapturedSpanCount(): number {
	return capturedSpans.length;
}

module.exports = {
	setupOtelCapture,
	getOtelTimeline,
	saveOtelTimeline,
	clearOtelCapture,
	getCapturedSpanCount
};
