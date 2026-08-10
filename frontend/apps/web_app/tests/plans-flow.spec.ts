/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Plans V1 web flow coverage.
 *
 * Verifies the deployed web app can create encrypted durable plans from the
 * central Plans workspace, display plan board cards, and archive with explicit
 * confirmation plus undo.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

test.describe('Plans V1 flow', () => {
	test('creates and archives an encrypted plan from the Plans workspace', async ({ page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);

		const planTitle = `E2E plan ${Date.now()}`;
		const renamedPlanTitle = `${planTitle} renamed`;
		let createRequestPayload = '';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		await page.goto(getE2EDebugUrl('/plans'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('plans-page')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('plans-workspace-home')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('plan-greeting')).toContainText(/what is your next plan\?/i, { timeout: 15000 });
		await expect(page.getByTestId('plan-board')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('task-create-form')).toHaveCount(0);

		const createResponse = page.waitForResponse((response) => {
			if (!response.url().includes('/v1/user-plans') || response.request().method() !== 'POST') return false;
			createRequestPayload = response.request().postData() ?? '';
			return response.ok();
		});
		await page.getByTestId('plan-workspace-input').fill(planTitle);
		await page.getByTestId('plan-workspace-submit').click();
		await createResponse;
		expect(createRequestPayload).not.toContain(planTitle);

		const planCard = page.getByTestId('plan-card').filter({ hasText: planTitle }).first();
		await expect(planCard).toBeVisible({ timeout: 30000 });
		await expect(planCard).toHaveAttribute('data-plan-status', 'draft');
		await expect(page.getByTestId('plan-column-backlog')).toContainText(planTitle);

		await page.getByTestId('plan-workspace-input').fill(`rename ${planTitle} to ${renamedPlanTitle}`);
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'PATCH' && response.url().includes('/v1/user-plans/') && response.ok()),
			page.getByTestId('plan-workspace-submit').click(),
		]);
		const renamedCard = page.getByTestId('plan-card').filter({ hasText: renamedPlanTitle }).first();
		await expect(renamedCard).toBeVisible({ timeout: 30000 });

		await page.getByTestId('plan-workspace-input').fill(`delete ${renamedPlanTitle}`);
		await page.getByTestId('plan-workspace-submit').click();
		await expect(page.getByTestId('plan-archive-confirmation')).toBeVisible({ timeout: 15000 });
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'PATCH' && response.url().includes('/v1/user-plans/') && response.ok()),
			page.getByTestId('plan-archive-confirm').click(),
		]);
		await expect(page.getByTestId('plan-board')).not.toContainText(renamedPlanTitle, { timeout: 30000 });
		await expect(page.getByTestId('plan-archive-undo')).toBeVisible({ timeout: 15000 });
	});
});
