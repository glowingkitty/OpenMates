/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Plans V1 acceptance check workflow coverage.
 *
 * Verifies encrypted plan details can add acceptance criteria, attach required
 * checks, and persist check evidence inside the plan surface.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { createProjectPlanForTest } = require('./helpers/create-project-plan');

test.describe('Plans V1 acceptance checks flow', () => {
	// contract-test: direct surface=gui.web assertions=plans.execution.gates-evidence
	test('covers an acceptance criterion with a check and evidence', async ({ page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);

		const projectName = `E2E checks project ${Date.now()}`;
		const criterionText = 'The implementation has a green focused backend test';
		const checkTitle = 'Run focused backend pytest';
		const evidenceText = 'pytest returned 1 passed';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		await createProjectPlanForTest(page, projectName);

		await expect(page.getByTestId('plan-detail-page')).toBeVisible({ timeout: 30000 });
		await page.getByTestId('plan-criterion-input').fill(criterionText);
		await page.getByTestId('plan-criterion-add-button').click();

		const criterionItem = page.getByTestId('plan-criterion-item').filter({ hasText: criterionText }).first();
		await expect(criterionItem).toBeVisible({ timeout: 30000 });
		await expect(criterionItem).toHaveAttribute('data-plan-coverage-status', 'uncovered');
		await expect(page.getByTestId('plan-criteria-summary')).toContainText('1');

		await page.getByTestId('plan-check-title-input').fill(checkTitle);
		await page.getByTestId('plan-check-command-input').fill('python3 -m pytest backend/tests/test_plan_acceptance_criteria_coverage.py');
		await page.getByTestId('plan-check-add-button').click();

		const checkItem = page.getByTestId('plan-check-item').filter({ hasText: checkTitle }).first();
		await expect(checkItem).toBeVisible({ timeout: 30000 });
		await expect(criterionItem).toHaveAttribute('data-plan-coverage-status', 'covered', { timeout: 30000 });
		await expect(page.getByTestId('plan-criteria-summary')).toContainText('0');

		await page.getByTestId('plan-evidence-summary-input').fill(evidenceText);
		await page.getByTestId('plan-evidence-add-button').click();
		await expect(checkItem).toHaveAttribute('data-plan-check-status', 'passed', { timeout: 30000 });
		await expect(checkItem).toContainText(evidenceText);
	});
});
