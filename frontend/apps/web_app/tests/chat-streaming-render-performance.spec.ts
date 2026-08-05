/**
 * Deterministic browser contract for bounded assistant-message rendering work.
 * Production exposes only sanitized counters and performance measures; this test
 * never reads or logs private message text, embed refs, or decrypted embed data.
 * Spec: docs/specs/streaming-message-render-convergence/spec.yml
 */

import { expect, test } from './helpers/cookie-audit';

type StreamingRenderMetrics = {
	chunks: number;
	flushes: number;
	fullReplacements: number;
	nodeViewMounts: number;
	mapHydrations: number;
};

type PerformanceSample = {
	metrics: StreamingRenderMetrics;
	compileDurations: number[];
	applyDurations: number[];
};

function percentile95(values: number[]): number {
	const sorted = [...values].sort((left, right) => left - right);
	return sorted[Math.max(0, Math.ceil(sorted.length * 0.95) - 1)] ?? 0;
}

test.describe('Streaming render performance metrics', () => {
	test('exposes bounded sanitized metrics and named pipeline measures', async ({ page }) => {
		await page.addInitScript(() => {
			(window as typeof window & { __streamingHarnessIdbWrites?: number }).__streamingHarnessIdbWrites = 0;
			for (const method of ['add', 'put', 'delete', 'clear'] as const) {
				const original = IDBObjectStore.prototype[method];
				IDBObjectStore.prototype[method] = function (...args: Parameters<typeof original>) {
					(window as typeof window & { __streamingHarnessIdbWrites: number }).__streamingHarnessIdbWrites += 1;
					return original.apply(this, args);
				} as typeof original;
			}
		});
		const runtimeRequests: string[] = [];
		page.on('request', (request) => {
			if (['fetch', 'xhr'].includes(request.resourceType()) && !request.url().includes('/e2e/client-logs')) {
				runtimeRequests.push(request.url());
			}
		});

		const samples: PerformanceSample[] = [];
		for (let run = 0; run < 4; run += 1) {
			await page.goto('/dev/preview/StreamingMessageRenderHarness', { waitUntil: 'domcontentloaded' });
			const harness = page.getByTestId('streaming-render-harness');
			await expect(harness).toHaveAttribute('data-phase', 'complete', { timeout: 15_000 });
			await expect(page.getByTestId('message-assistant')).toHaveAttribute('data-streaming', 'false');
			await expect(page.getByTestId('message-content')).toContainText('Bounded canonical rendering remains responsive.');
			const sample = await page.evaluate(() => ({
				metrics: (window as typeof window & {
					__openmatesStreamingRenderMetrics: StreamingRenderMetrics;
				}).__openmatesStreamingRenderMetrics,
				compileDurations: performance.getEntriesByName('openmates.streaming.compile').map((entry) => entry.duration),
				applyDurations: performance.getEntriesByName('openmates.streaming.apply').map((entry) => entry.duration),
			}));
			if (run > 0) samples.push(sample);
		}

		const result = samples[1];
		expect(result.metrics).toEqual(expect.objectContaining({
			chunks: expect.any(Number),
			flushes: expect.any(Number),
			fullReplacements: expect.any(Number),
			nodeViewMounts: expect.any(Number),
			mapHydrations: expect.any(Number),
		}));
		expect(result.metrics.chunks).toBeGreaterThan(30);
		expect(result.metrics.flushes).toBeLessThanOrEqual(21);
		expect(result.metrics.nodeViewMounts).toBeLessThanOrEqual(2);
		expect(result.metrics.mapHydrations).toBeLessThanOrEqual(1);
		expect(result.compileDurations.length).toBeGreaterThan(0);
		expect(result.applyDurations.length).toBeGreaterThan(0);

		const sampleP95s = samples.map((sample) => percentile95([
			...sample.compileDurations,
			...sample.applyDurations,
		]));
		const medianP95 = [...sampleP95s].sort((left, right) => left - right)[1];
		expect(medianP95).toBeLessThan(32);
		expect(Math.max(...samples.flatMap((sample) => [
			...sample.compileDurations,
			...sample.applyDurations,
		]))).toBeLessThan(50);
		expect(runtimeRequests).toEqual([]);
		expect(await page.evaluate(() => (
			window as typeof window & { __streamingHarnessIdbWrites?: number }
		).__streamingHarnessIdbWrites)).toBe(0);
	});
});
