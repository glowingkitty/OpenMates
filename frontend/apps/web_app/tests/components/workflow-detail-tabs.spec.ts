// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page } from '@playwright/test';

const { expect, test } = require('../helpers/cookie-audit');

const preview = (variant?: string) =>
	`/dev/preview/workflows/WorkflowDetailPage?${new URLSearchParams({
		theme: 'light',
		background: '#dbeafe',
		width: '430',
		chrome: '0',
		...(variant ? { variant } : {})
	})}`;

test.describe('Workflow detail tabs', () => {
	for (const theme of ['light', 'dark']) {
		// contract-test: direct surface=gui.web assertions=workflows-ui.responsive-accessible-reachable
		test(`keeps the gradient header title white in ${theme} mode`, async ({ page }: { page: Page }) => {
			await page.setViewportSize({ width: 430, height: 844 });
			const url = new URL(preview(), 'http://localhost');
			url.searchParams.set('theme', theme);
			await page.goto(`${url.pathname}${url.search}`, { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30_000 });
			const title = page.getByTestId('workspace-detail-title');
			await expect(title).toHaveText('Weekly AI events');
			await expect(title).toHaveCSS('color', 'rgb(255, 255, 255)');
			await title.hover();
			await expect(title).toHaveCSS('color', 'rgb(255, 255, 255)');
			await title.click();
			await page.getByRole('textbox', { name: 'Workflow name', exact: true }).fill('Updated weekly events');
			await page.getByRole('button', { name: 'Save', exact: true }).click();
			await expect(title).toHaveText('Weekly AI events');
			await expect(title).toHaveCSS('color', 'rgb(255, 255, 255)');
			await page.getByTestId('workspace-detail-header').screenshot({ path: test.info().outputPath(`workflow-header-${theme}.png`) });
		});
	}
	// contract-test: supporting surface=gui.web assertions=workflows-ui.authoring.composer-and-preview
	test('shows a provisional identity without saved-workflow actions', async ({ page }: { page: Page }) => {
		await page.goto(preview('provisional'), { waitUntil: 'networkidle' });
		await expect(page.getByTestId('workspace-detail-title')).toHaveText('Processing…');
		await expect(page.getByTestId('workspace-detail-title')).toHaveCSS('color', 'rgb(255, 255, 255)');
		await expect(page.getByTestId('workspace-detail-description')).toHaveCount(0);
		await expect(page.getByText('Click to add description')).toHaveCount(0);
		await expect(page.getByTestId('workflow-detail-metadata')).toHaveCount(0);
		await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
		await expect(page.getByTestId('workflow-view-tabs')).toHaveCount(0);
		for (const id of ['workflow-export', 'delete-workflow', 'run-workflow', 'workflow-share']) {
			await expect(page.getByTestId(id)).toHaveCount(0);
		}
		await page.getByTestId('workspace-detail-title').click();
		await expect(page.getByRole('textbox', { name: 'Workflow name' })).toHaveCount(0);
		const closed = page.evaluate(() => new Promise<void>(resolve => window.addEventListener('workflow-preview-close', () => resolve(), { once: true })));
		await page.getByTestId('workflow-detail-back').click();
		await closed;
	});
	// contract-test: supporting surface=gui.web assertions=workflows-ui.files.more-export
	test('shows export in More for a saved and a blank workflow', async ({ page }: { page: Page }) => {
		await page.goto(preview(), { waitUntil: 'networkidle' });
		await page.getByRole('button', { name: 'More', exact: true }).click();
		await expect(page.getByTestId('workflow-export')).toBeEnabled();
		const emitted = page.evaluate(() => new Promise<void>(resolve => window.addEventListener('workflow-preview-export', () => resolve(), { once: true })));
		await page.getByTestId('workflow-export').click();
		await emitted;
		await page.goto(preview('blank'), { waitUntil: 'networkidle' });
		await page.getByRole('button', { name: 'More', exact: true }).click();
		await expect(page.getByTestId('workflow-export')).toBeEnabled();
	});
	// contract-test: direct surface=gui.web assertions=workflows-ui.detail.shared-template-runs-tabs
	test('uses the shared workspace tab dimensions and gradient pill', async ({ page }: { page: Page }) => {
		await page.goto(preview(), { waitUntil: 'networkidle' });

		const tabs = page.getByTestId('workflow-view-tabs');
		const pill = page.getByTestId('workflow-view-tabs-pill');
		const tabButtons = tabs.getByRole('tab');
		await expect(tabs).toBeVisible();
		await expect(tabButtons).toHaveCount(2);
		await expect(tabButtons.first()).toHaveAttribute('aria-selected', 'true');
		await expect(tabButtons.last()).toHaveAttribute('aria-selected', 'false');
		await expect(tabButtons.first().locator('span')).toHaveCSS('background-color', 'rgb(255, 255, 255)');

		const [tabsBox, pillBox, firstTabBox, iconBox] = await Promise.all([
			tabs.boundingBox(),
			pill.boundingBox(),
			tabButtons.first().boundingBox(),
			tabButtons.first().locator('span').boundingBox()
		]);
		expect(tabsBox).not.toBeNull();
		expect(pillBox).not.toBeNull();
		expect(firstTabBox).not.toBeNull();
		expect(iconBox).not.toBeNull();
		expect(tabsBox!.width).toBeCloseTo(144, 0);
		expect(tabsBox!.height).toBeCloseTo(44.8, 0);
		expect(firstTabBox!.width).toBeCloseTo(72, 0);
		expect(firstTabBox!.height).toBeCloseTo(44.8, 0);
		expect(pillBox!.width).toBeCloseTo(72, 0);
		expect(iconBox!.width).toBe(20);
		expect(iconBox!.height).toBe(20);
		await expect(pill).toHaveCSS('background-image', /linear-gradient/);
	});
});
