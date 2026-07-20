/* @ts-nocheck */
/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Plans V1 acceptance check workflow coverage.
 *
 * Verifies encrypted plan details can add acceptance criteria, attach required
 * checks, and persist check evidence inside the plan surface.
 */

const planChecksAudit = require('./helpers/cookie-audit');
const planChecksHelpers = require('./helpers/chat-test-helpers');
const planChecksEnv = require('./helpers/env-guard');
const planChecksSignup = require('./signup-flow-helpers');

const planChecksExpect = planChecksAudit.expect;
const planChecksTest = planChecksAudit.test;

planChecksTest.describe('Plans V1 acceptance checks flow', () => {
	planChecksTest('covers an acceptance criterion with a check and evidence', async ({ page }) => {
		planChecksTest.setTimeout(120000);
		planChecksTest.skip(!planChecksSignup.getTestAccount().email, 'Test account credentials required.');
		await planChecksEnv.skipIfFeaturesDisabled(planChecksTest, page, ['platform:tasks', 'platform:plans']);

		const planTitle = `E2E checks plan ${Date.now()}`;
		const criterionText = 'The implementation has a green focused backend test';
		const checkTitle = 'Run focused backend pytest';
		const evidenceText = 'pytest returned 1 passed';

		await page.goto(planChecksSignup.getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await planChecksHelpers.loginToTestAccount(page);
		await page.goto(planChecksSignup.getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
		await planChecksExpect(page.getByTestId('linked-plans-section')).toBeVisible({ timeout: 30000 });

		await page.getByTestId('plan-title-input').fill(planTitle);
		await page.getByTestId('plan-create-button').click();
		const planCard = page.getByTestId('linked-plan-card').filter({ hasText: planTitle }).first();
		await planChecksExpect(planCard).toBeVisible({ timeout: 30000 });
		await planCard.getByTestId('plan-detail-link').click();

		await planChecksExpect(page.getByTestId('plan-detail-page')).toBeVisible({ timeout: 30000 });
		await page.getByTestId('plan-criterion-input').fill(criterionText);
		await page.getByTestId('plan-criterion-add-button').click();

		const criterionItem = page.getByTestId('plan-criterion-item').filter({ hasText: criterionText }).first();
		await planChecksExpect(criterionItem).toBeVisible({ timeout: 30000 });
		await planChecksExpect(criterionItem).toHaveAttribute('data-plan-coverage-status', 'uncovered');
		await planChecksExpect(page.getByTestId('plan-criteria-summary')).toContainText('1');

		await page.getByTestId('plan-check-title-input').fill(checkTitle);
		await page.getByTestId('plan-check-command-input').fill('python3 -m pytest backend/tests/test_plan_acceptance_criteria_coverage.py');
		await page.getByTestId('plan-check-add-button').click();

		const checkItem = page.getByTestId('plan-check-item').filter({ hasText: checkTitle }).first();
		await planChecksExpect(checkItem).toBeVisible({ timeout: 30000 });
		await planChecksExpect(criterionItem).toHaveAttribute('data-plan-coverage-status', 'covered', { timeout: 30000 });
		await planChecksExpect(page.getByTestId('plan-criteria-summary')).toContainText('0');

		await page.getByTestId('plan-evidence-summary-input').fill(evidenceText);
		await page.getByTestId('plan-evidence-add-button').click();
		await planChecksExpect(checkItem).toHaveAttribute('data-plan-check-status', 'passed', { timeout: 30000 });
		await planChecksExpect(checkItem).toContainText(evidenceText);
	});
});
