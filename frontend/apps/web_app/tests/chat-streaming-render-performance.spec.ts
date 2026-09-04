/**
 * Deterministic browser contract for bounded assistant-message rendering work.
 * Production exposes only sanitized counters and performance measures; this test
 * never reads or logs private message text, embed refs, or decrypted embed data.
 * Spec: docs/specs/streaming-message-render-convergence/spec.yml
 */

import { expect, test } from './helpers/cookie-audit';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';

const STREAMING_PROOF_CONTRACT = defineVideoProof({
	id: 'bounded-streaming-render-convergence',
	title: 'Bounded streaming render convergence',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'open-harness',
			text: 'Open the streaming render harness to replay a long assistant response.',
			checkpoint: 'harness-open',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'bounded-updates',
			text: 'Frequent response chunks converge into bounded visual updates while the message remains responsive.',
			checkpoint: 'bounded-updates',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'finished',
			text: 'Streaming finishes with the complete response and no loading state left behind.',
			checkpoint: 'final-state',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'harness-complete',
			checkpoint: 'final-state',
			visual: 'The harness reaches its complete phase.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'streaming-finished',
			checkpoint: 'final-state',
			visual: 'The assistant message ends with streaming set to false.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'response-readable',
			checkpoint: 'final-state',
			visual: 'The complete canonical response text remains visible and readable.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'clean-final-state',
			checkpoint: 'final-state',
			visual: 'No implementation error, clipping, or stale loading indicator is visible.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

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
	// contract-test: supporting surface=gui.web assertions=chats.streaming.ordered-final
	test('exposes bounded sanitized metrics and named pipeline measures', async ({ page }, testInfo) => {
		const proof = createVideoProofRuntime(STREAMING_PROOF_CONTRACT, {
			device: PROOF_DEVICE,
			attach: testInfo.attach.bind(testInfo),
			captureFrame: () => page.screenshot({ type: 'png' })
		});
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
			if (run === 0) await proof.checkpoint('harness-open');
			if (run === 1) await proof.checkpoint('bounded-updates');
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
		const renderingTriggeredRequests = runtimeRequests.filter((requestUrl) => {
			const url = new URL(requestUrl);
			if (url.hostname === 'm.stripe.com') return false;
			return url.pathname !== '/v1/settings/server-status';
		});
		expect(renderingTriggeredRequests).toEqual([]);
		expect(await page.evaluate(() => (
			window as typeof window & { __streamingHarnessIdbWrites?: number }
		).__streamingHarnessIdbWrites)).toBe(0);
		await proof.assert('harness-complete', async () => {
			await expect(page.getByTestId('streaming-render-harness')).toHaveAttribute('data-phase', 'complete');
		});
		await proof.assert('streaming-finished', async () => {
			await expect(page.getByTestId('message-assistant')).toHaveAttribute('data-streaming', 'false');
		});
		await proof.assert('response-readable', async () => {
			await expect(page.getByTestId('message-content')).toContainText('Bounded canonical rendering remains responsive.');
		});
		await proof.assert('clean-final-state', async () => {
			await expect(page.getByText(/implementation error/i)).toHaveCount(0);
			await expect(page.getByText('Loading preview...', { exact: true })).toHaveCount(0);
		});
		await proof.checkpoint('final-state');
		await proof.attach();
	});
});
