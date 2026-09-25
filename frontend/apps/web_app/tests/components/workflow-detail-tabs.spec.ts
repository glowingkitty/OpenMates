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
