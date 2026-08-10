/* @ts-nocheck */
/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Plans V1 assumption workflow coverage.
 *
 * Verifies encrypted plan details can create and resolve required assumptions
 * before implementation proceeds.
 */

const planAssumptionsAudit = require('./helpers/cookie-audit');
const planAssumptionsHelpers = require('./helpers/chat-test-helpers');
const planAssumptionsEnv = require('./helpers/env-guard');
const planAssumptionsSignup = require('./signup-flow-helpers');

const planAssumptionsExpect = planAssumptionsAudit.expect;
const planAssumptionsTest = planAssumptionsAudit.test;

planAssumptionsTest.describe('Plans V1 assumptions flow', () => {
	planAssumptionsTest('creates and confirms an encrypted plan assumption', async ({ page }) => {
		planAssumptionsTest.setTimeout(120000);
		planAssumptionsTest.skip(!planAssumptionsSignup.getTestAccount().email, 'Test account credentials required.');
		await planAssumptionsEnv.skipIfFeaturesDisabled(planAssumptionsTest, page, ['platform:tasks', 'platform:plans']);

		const planTitle = `E2E assumption plan ${Date.now()}`;
		const assumptionText = 'Production API quota is already approved';

		await page.goto(planAssumptionsSignup.getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await planAssumptionsHelpers.loginToTestAccount(page);
		await page.goto(planAssumptionsSignup.getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
		await planAssumptionsExpect(page.getByTestId('linked-plans-section')).toBeVisible({ timeout: 30000 });

		await page.getByTestId('plan-title-input').fill(planTitle);
		await page.getByTestId('plan-create-button').click();
		const planCard = page.getByTestId('linked-plan-card').filter({ hasText: planTitle }).first();
		await planAssumptionsExpect(planCard).toBeVisible({ timeout: 30000 });
		await planCard.getByTestId('plan-detail-link').click();

		await planAssumptionsExpect(page.getByTestId('plan-detail-page')).toBeVisible({ timeout: 30000 });
		await page.getByTestId('plan-assumption-input').fill(assumptionText);
		await page.getByTestId('plan-assumption-add-button').click();

		const assumptionItem = page.getByTestId('plan-assumption-item').filter({ hasText: assumptionText }).first();
		await planAssumptionsExpect(assumptionItem).toBeVisible({ timeout: 30000 });
		await planAssumptionsExpect(assumptionItem).toHaveAttribute('data-plan-assumption-status', 'unchecked');
		await planAssumptionsExpect(page.getByTestId('plan-assumption-summary')).toContainText('1');

		await assumptionItem.getByTestId('plan-assumption-confirm-button').click();
		await planAssumptionsExpect(assumptionItem).toHaveAttribute('data-plan-assumption-status', 'confirmed', { timeout: 30000 });
		await planAssumptionsExpect(page.getByTestId('plan-assumption-summary')).toContainText('0');
	});
});
