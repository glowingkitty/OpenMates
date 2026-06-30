/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Project-linked Plans V1 web flow coverage.
 *
 * Verifies a project can create and display linked encrypted plan cards from
 * the embedded project Tasks surface before full project-plan management grows
 * richer plan filtering and navigation controls.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

test.describe('Project-linked Plans V1 flow', () => {
	test('creates a project-linked plan card', async ({ page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const projectName = `E2E Plan Project ${Date.now()}`;
		const planTitle = `E2E project plan ${Date.now()}`;

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		await page.goto(getE2EDebugUrl('/projects'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });

		await page.getByTestId('project-create-main-button').click();
		await expect(page.getByTestId('projects-sidebar')).toBeVisible({ timeout: 30000 });
		await page.getByTestId('project-name-input').fill(projectName);
		await page.getByTestId('project-create-button').click();
		await expect(page.getByTestId('project-card').filter({ hasText: projectName }).first()).toBeVisible({ timeout: 30000 });

		const projectTasks = page.getByTestId('project-tasks-section');
		await expect(projectTasks).toBeVisible({ timeout: 30000 });
		await projectTasks.getByTestId('plan-title-input').fill(planTitle);
		await projectTasks.getByTestId('plan-summary-input').fill('Project-linked plan created by E2E');
		await projectTasks.getByTestId('plan-create-button').click();

		const planCard = projectTasks.getByTestId('linked-plan-card').filter({ hasText: planTitle }).first();
		await expect(planCard).toBeVisible({ timeout: 30000 });
		await expect(planCard).toHaveAttribute('data-plan-status', 'draft');
	});
});
