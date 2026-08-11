/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Plans V1 assumption workflow coverage.
 *
 * Verifies encrypted plan details can create and resolve required assumptions
 * before implementation proceeds.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

test.describe('Plans V1 assumptions flow', () => {
	// contract-test: direct surface=gui.web assertions=plans.execution.gates-evidence
	test('creates and confirms an encrypted plan assumption', async ({ page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);

		const planTitle = `E2E assumption plan ${Date.now()}`;
		const assumptionText = 'Production API quota is already approved';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		await page.goto(getE2EDebugUrl('/plans'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('plans-page')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('plans-workspace-home')).toBeVisible({ timeout: 30000 });

		await page.getByTestId('plan-workspace-input').fill(planTitle);
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/v1/user-plans') && response.ok()),
			page.getByTestId('plan-workspace-submit').click(),
		]);
		const planCard = page.getByTestId('plan-card').filter({ hasText: planTitle }).first();
		await expect(planCard).toBeVisible({ timeout: 30000 });
		await planCard.getByTestId('plan-detail-link').click();

		await expect(page.getByTestId('plan-detail-page')).toBeVisible({ timeout: 30000 });
		await page.getByTestId('plan-assumption-input').fill(assumptionText);
		await page.getByTestId('plan-assumption-add-button').click();

		const assumptionItem = page.getByTestId('plan-assumption-item').filter({ hasText: assumptionText }).first();
		await expect(assumptionItem).toBeVisible({ timeout: 30000 });
		await expect(assumptionItem).toHaveAttribute('data-plan-assumption-status', 'unchecked');
		await expect(page.getByTestId('plan-assumption-summary')).toContainText('1');

		await assumptionItem.getByTestId('plan-assumption-confirm-button').click();
		await expect(assumptionItem).toHaveAttribute('data-plan-assumption-status', 'confirmed', { timeout: 30000 });
		await expect(page.getByTestId('plan-assumption-summary')).toContainText('0');
	});
});
