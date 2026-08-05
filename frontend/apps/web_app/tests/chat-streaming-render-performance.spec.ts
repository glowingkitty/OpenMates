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

test.describe('Streaming render performance metrics', () => {
	test('exposes bounded sanitized metrics and named pipeline measures', async ({ page }) => {
		await page.goto('/dev/preview/embeds/EmbedsMapView', { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('embeds-map-view')).toBeVisible();

		const result = await page.evaluate(() => {
			const metrics = (window as typeof window & {
				__openmatesStreamingRenderMetrics?: StreamingRenderMetrics;
			}).__openmatesStreamingRenderMetrics;
			return {
				metrics,
				compileMeasures: performance.getEntriesByName('openmates.streaming.compile').length,
				applyMeasures: performance.getEntriesByName('openmates.streaming.apply').length,
			};
		});

		expect(result.metrics).toBeTruthy();
		expect(result.metrics).toEqual(expect.objectContaining({
			chunks: expect.any(Number),
			flushes: expect.any(Number),
			fullReplacements: expect.any(Number),
			nodeViewMounts: expect.any(Number),
			mapHydrations: expect.any(Number),
		}));
		expect(result.compileMeasures).toBeGreaterThan(0);
		expect(result.applyMeasures).toBeGreaterThan(0);
	});
});
