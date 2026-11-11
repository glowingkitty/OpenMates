// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers expose CommonJS exports. */
export {};
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const { expect, test } = require('../helpers/cookie-audit');

test.describe('Workflow memory mention picker preview', () => {
	// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.ask-ai
	test('keeps many memory chips in one horizontally scrollable row', async ({ page }: { page: Page }, testInfo: { attach: (name: string, options: { body: Buffer; contentType: string }) => Promise<void> }) => {
		test.setTimeout(90_000);
		await page.setViewportSize({ width: 390, height: 600 });
		const params = new URLSearchParams({ theme: 'light', width: '390', chrome: '0' });
		await page.goto(`/dev/preview/workflows/WorkflowMemoryPicker?${params}`, { waitUntil: 'domcontentloaded' });
		await waitForComponentPreview(page, 60_000);
		await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);

		const picker = page.getByTestId('workflow-memory-picker');
		const chips = picker.locator('.chip');
		await expect(chips).toHaveCount(12);
		const tops = await chips.evaluateAll((nodes: HTMLElement[]) => nodes.map(node => Math.round(node.getBoundingClientRect().top)));
		expect(new Set(tops).size).toBe(1);

		const scroll = page.getByTestId('workflow-memory-chip-scroll');
		const metrics = await scroll.evaluate((node: HTMLElement) => ({ scrollWidth: node.scrollWidth, clientWidth: node.clientWidth }));
		expect(metrics.scrollWidth).toBeGreaterThan(metrics.clientWidth);
		await scroll.evaluate((node: HTMLElement) => { node.scrollLeft = node.scrollWidth; });
		expect(await scroll.evaluate((node: HTMLElement) => node.scrollLeft)).toBeGreaterThan(0);
		await scroll.evaluate((node: HTMLElement) => { node.scrollLeft = 0; });

		// Memories 1, 4, 7, 10 carry save times (newest first); the rest follow in reversed stored order.
		const ids = await chips.evaluateAll((nodes: HTMLElement[]) => nodes.map(node => node.getAttribute('data-memory-id')));
		expect(ids).toEqual(['memory-10', 'memory-7', 'memory-4', 'memory-1', 'memory-12', 'memory-11', 'memory-9', 'memory-8', 'memory-6', 'memory-5', 'memory-3', 'memory-2']);
		const longChip = picker.locator('[data-memory-id="memory-3"]');
		const longWidth = (await longChip.boundingBox())!.width;
		expect(longWidth).toBeLessThanOrEqual(14 * 16 + 1);

		await testInfo.attach('memory-picker-single-row', { body: await picker.screenshot(), contentType: 'image/png' });
	});
});
