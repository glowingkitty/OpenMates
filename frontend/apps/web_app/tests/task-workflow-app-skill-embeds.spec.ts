/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Web coverage for Tasks and Workflows app-skill parent/child embeds.
 *
 * The spec uses the unauthenticated embed preview route so it verifies renderer
 * registration, parent fullscreen grids, child fullscreen drilldown, and
 * responsive layout without depending on live AI generation or test-account OTP.
 * Product contract: docs/specs/tasks-workflows-app-skill-embeds/spec.yml
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { verifySearchGrid } = require('./helpers/embed-test-helpers');

async function waitForPreviewApp(page: any, app: string) {
	const response = await page.goto(`/dev/preview/embeds/${app}`, { waitUntil: 'networkidle' });
	expect(response?.status()).toBe(200);
	await expect(page.getByTestId('unknown-app')).not.toBeVisible({ timeout: 15_000 });
	await expect(page.getByTestId('app-title')).toContainText(app, { timeout: 15_000 });
	await expect(async () => {
		expect(await page.getByTestId('section-loading').count()).toBe(0);
	}).toPass({ timeout: 20_000 });
	expect(await page.getByTestId('section-error').count()).toBe(0);
}

async function expectParentChildPreview(page: any, app: 'tasks' | 'workflows', skillId: string, childTestId: string, fullscreenTestId: string) {
	const parent = page.locator(`[data-testid="embed-preview"][data-app-id="${app}"][data-skill-id="${skillId}"][data-status="finished"]`).first();
	await expect(parent).toBeVisible({ timeout: 15_000 });
	await expect(parent).toContainText(/garden|packing|workflow|search|found|created/i);

	const section = page.getByTestId('skill-section').filter({ has: parent }).first();
	const fullscreenClip = section.getByTestId('fs-clip').first();
	const resultCards = await verifySearchGrid(fullscreenClip, 1, 15_000);
	const childCard = resultCards.first();
	await expect(childCard.getByTestId(childTestId)).toBeVisible({ timeout: 15_000 });

	await childCard.click();
	await expect(fullscreenClip.getByTestId(fullscreenTestId)).toBeVisible({ timeout: 15_000 });
}

test.describe('Task and workflow app-skill web embeds', () => {
	test('renders Tasks parent previews, child grid, child fullscreen, and mobile layout', async ({ page }) => {
		test.setTimeout(120_000);

		await waitForPreviewApp(page, 'tasks');
		await expectParentChildPreview(page, 'tasks', 'create', 'task-embed-card', 'task-embed-fullscreen');
		await expectParentChildPreview(page, 'tasks', 'search', 'task-embed-card', 'task-embed-fullscreen');

		await page.setViewportSize({ width: 390, height: 760 });
		await waitForPreviewApp(page, 'tasks');
		const mobileGrid = page.getByTestId('search-template-grid').first();
		await expect(mobileGrid).toBeVisible({ timeout: 15_000 });
		const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
		expect(overflow, 'Tasks embed preview should not create horizontal overflow on mobile').toBeLessThan(8);
	});

	test('renders Workflows parent previews, child grid, child fullscreen, and mobile layout', async ({ page }) => {
		test.setTimeout(120_000);

		await waitForPreviewApp(page, 'workflows');
		await expectParentChildPreview(page, 'workflows', 'create-or-modify', 'workflow-embed-card', 'workflow-embed-fullscreen');
		await expectParentChildPreview(page, 'workflows', 'search', 'workflow-embed-card', 'workflow-embed-fullscreen');

		await page.setViewportSize({ width: 390, height: 760 });
		await waitForPreviewApp(page, 'workflows');
		const mobileGrid = page.getByTestId('search-template-grid').first();
		await expect(mobileGrid).toBeVisible({ timeout: 15_000 });
		const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
		expect(overflow, 'Workflows embed preview should not create horizontal overflow on mobile').toBeLessThan(8);
	});
});
