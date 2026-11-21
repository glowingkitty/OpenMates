// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page, TestInfo } from '@playwright/test';

const { expect, test } = require('../helpers/cookie-audit');

const VIEWPORTS = [
	{ name: 'phone', width: 390, height: 844 },
	{ name: 'tablet', width: 820, height: 1180 },
	{ name: 'desktop', width: 1280, height: 800 }
] as const;

const previewUrl = (component: string, variant: string, width: number) =>
	`/dev/preview/workflows/${component}?${new URLSearchParams({ theme: 'light', background: '#dbeafe', width: String(Math.min(width, 900)), chrome: '0', variant })}`;

async function open(page: Page, component: string, variant: string, width: number, height: number) {
	await page.setViewportSize({ width, height });
	await page.goto(previewUrl(component, variant, width), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30_000 });
}

async function shot(page: Page, testInfo: TestInfo, name: string, target = page.getByTestId('workspace-detail-header')) {
	await testInfo.attach(name, { body: await target.screenshot(), contentType: 'image/png' });
}

test.describe('Workflow detail description clamp and node label clamp', () => {
	for (const vp of VIEWPORTS) {
		// contract-test: direct surface=gui.web assertions=workflows-ui.detail-header.description-clamp
		test(`clamps a long description to 3 lines and toggles the full text (${vp.name})`, async ({ page }: { page: Page }, testInfo: TestInfo) => {
			await open(page, 'WorkflowDetailPage', 'longDescription', vp.width, vp.height);
			const header = page.getByTestId('workspace-detail-header');
			const description = page.getByTestId('workspace-detail-description');
			const toggle = page.getByTestId('workflow-description-toggle');
			const fixedHeight = (await header.boundingBox())!.height;
			const lineHeight = await description.evaluate((el: HTMLElement) => parseFloat(getComputedStyle(el).lineHeight));

			await expect(toggle).toBeVisible();
			await expect(toggle).toHaveAttribute('aria-expanded', 'false');
			await expect(toggle).toHaveAttribute('aria-label', 'Show full description');
			expect((await description.boundingBox())!.height).toBeLessThanOrEqual(lineHeight * 3 + 1);
			expect(await description.evaluate((el: HTMLElement) => el.scrollHeight > el.clientHeight)).toBe(true);
			// Nothing in the fixed-height header overlaps: the triangle sits below the text and every
			// header part stays inside the header.
			const descriptionBox = (await description.boundingBox())!;
			const toggleBox = (await toggle.boundingBox())!;
			expect(toggleBox.y).toBeGreaterThanOrEqual(descriptionBox.y + descriptionBox.height - 1);
			const headerBox = (await header.boundingBox())!;
			for (const part of [page.getByTestId('toggle-workflow'), toggle, page.getByTestId('workflow-detail-metadata')]) {
				const box = (await part.boundingBox())!;
				expect(box.y).toBeGreaterThanOrEqual(headerBox.y);
				expect(box.y + box.height).toBeLessThanOrEqual(headerBox.y + headerBox.height + 1);
			}
			await shot(page, testInfo, `description-collapsed-${vp.name}`);

			await toggle.click();
			await expect(toggle).toHaveAttribute('aria-expanded', 'true');
			await expect(toggle).toHaveAttribute('aria-label', 'Show less of the description');
			expect((await description.boundingBox())!.height).toBeGreaterThan(lineHeight * 3 + 1);
			expect((await header.boundingBox())!.height).toBeCloseTo(fixedHeight, 0);
			await expect(toggle.locator('svg')).toHaveCSS('transform', /matrix\(-1, .*\)/);
			await shot(page, testInfo, `description-expanded-${vp.name}`);

			await toggle.click();
			await expect(toggle).toHaveAttribute('aria-expanded', 'false');
			expect((await description.boundingBox())!.height).toBeLessThanOrEqual(lineHeight * 3 + 1);
			expect((await header.boundingBox())!.height).toBeCloseTo(fixedHeight, 0);
			await shot(page, testInfo, `description-collapsed-again-${vp.name}`);
		});

		// contract-test: direct surface=gui.web assertions=workflows-ui.detail-header.description-clamp
		test(`shows no triangle for a short description (${vp.name})`, async ({ page }: { page: Page }, testInfo: TestInfo) => {
			await open(page, 'WorkflowDetailPage', 'default', vp.width, vp.height);
			await expect(page.getByTestId('workspace-detail-description')).toBeVisible();
			await expect(page.getByTestId('workflow-description-toggle')).toHaveCount(0);
			await shot(page, testInfo, `description-short-${vp.name}`);
		});

		// contract-test: direct surface=gui.web assertions=workflows-ui.canvas.node-label-clamp
		test(`clamps a long node label to 2 lines with the full text in the title (${vp.name})`, async ({ page }: { page: Page }, testInfo: TestInfo) => {
			await open(page, 'WorkflowGraphRenderer', 'websiteTemplate', vp.width, vp.height);
			const labels = page.getByTestId('workflow-node-title-label');
			await expect(labels.first()).toBeVisible();
			const metrics = await labels.evaluateAll((els: HTMLElement[]) => els.map(el => ({
				height: el.getBoundingClientRect().height,
				lineHeight: parseFloat(getComputedStyle(el).lineHeight),
				clipped: el.scrollHeight > el.clientHeight,
				title: el.getAttribute('title') ?? '',
				text: el.textContent ?? ''
			})));
			for (const m of metrics) {
				expect(m.height).toBeLessThanOrEqual(m.lineHeight * 2 + 1);
				expect(m.title).toBe(m.text);
			}
			expect(metrics.some(m => m.clipped && m.text.includes('Chaos Communication Congress'))).toBe(true);
			await shot(page, testInfo, `node-label-clamped-${vp.name}`, page.getByTestId('workflow-node-stack'));
		});
	}
});
