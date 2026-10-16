import { afterEach, describe, expect, it, vi } from 'vitest';
// Vitest externalizes dependencies to Node; select the same browser transport
// that Vite chooses through the exporter's browser package mapping.
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http/build/src/platform/browser/OTLPTraceExporter';

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

function response(status: number, retryAfter: string | null = null) {
	return { status, headers: { get: (name: string) => name === 'Retry-After' ? retryAfter : null } };
}

function exportBatch(exporter: OTLPTraceExporter) {
	return new Promise<{ code: number }>((resolve) => exporter.export([], resolve));
}

describe('browser OTLP quota backoff', () => {
	// contract-test: supporting surface=gui.web assertions=ai-request-observability.no-behavior-change
	it('uses Retry-After to avoid retries inside a closed quota window', async () => {
		vi.useFakeTimers();
		const fetch = vi.fn().mockResolvedValue(response(429, '60'));
		vi.stubGlobal('fetch', fetch);
		const exporter = new OTLPTraceExporter({
			url: 'https://api.example.test/v1/telemetry/traces', timeoutMillis: 30_000
		});
		const result = await exportBatch(exporter);
		expect(result.code).toBe(1);
		await vi.advanceTimersByTimeAsync(30_000);
		expect(fetch).toHaveBeenCalledTimes(1);
		await exporter.shutdown();
	});

	// contract-test: supporting surface=gui.web assertions=ai-request-observability.no-behavior-change
	it('still retries a transient quota response when its window reopens in time', async () => {
		vi.useFakeTimers();
		const fetch = vi.fn().mockResolvedValueOnce(response(429, '2')).mockResolvedValue(response(200));
		vi.stubGlobal('fetch', fetch);
		const exporter = new OTLPTraceExporter({ url: 'https://api.example.test/v1/telemetry/traces' });
		const pending = exportBatch(exporter);
		await vi.advanceTimersByTimeAsync(1_999);
		expect(fetch).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(1);
		expect((await pending).code).toBe(0);
		expect(fetch).toHaveBeenCalledTimes(2);
		expect(fetch.mock.calls[1][1].body).toEqual(fetch.mock.calls[0][1].body);
		await exporter.shutdown();
	});

	// contract-test: supporting surface=gui.web assertions=ai-request-observability.no-behavior-change
	it.each([200, 202, 403])('preserves accepted or nonretryable status %s', async (status) => {
		vi.useFakeTimers();
		const fetch = vi.fn().mockResolvedValue(response(status));
		vi.stubGlobal('fetch', fetch);
		const exporter = new OTLPTraceExporter({ url: 'https://api.example.test/v1/telemetry/traces' });
		expect((await exportBatch(exporter)).code).toBe(status < 300 ? 0 : 1);
		await vi.advanceTimersByTimeAsync(30_000);
		expect(fetch).toHaveBeenCalledTimes(1);
		await exporter.shutdown();
	});
});
