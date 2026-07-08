/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Plans V1 web flow coverage.
 *
 * Verifies the deployed web app can create encrypted durable plans from the
 * Tasks surface, display linked plan cards, and activate a plan before work
 * tasks begin.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

test.describe('Plans V1 flow', () => {
	test('creates and activates an encrypted plan from the Tasks surface', async ({ page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);

		const planTitle = `E2E plan ${Date.now()}`;
		const planSummary = 'Created by the Plans V1 Playwright flow';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('linked-plans-section')).toBeVisible({ timeout: 30000 });

		await page.getByTestId('plan-title-input').fill(planTitle);
		await page.getByTestId('plan-summary-input').fill(planSummary);
		await page.getByTestId('plan-create-button').click();

		const planCard = page.getByTestId('linked-plan-card').filter({ hasText: planTitle }).first();
		await expect(planCard).toBeVisible({ timeout: 30000 });
		await expect(planCard).toContainText(planSummary);
		await expect(planCard).toHaveAttribute('data-plan-status', 'draft');

		await planCard.getByTestId('plan-activate-button').click();
		await expect(planCard).toHaveAttribute('data-plan-status', 'active', { timeout: 30000 });
	});
});
