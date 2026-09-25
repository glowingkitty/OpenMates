/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */

export {};

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

test.describe('Root hash workspace routing', () => {
	test.beforeEach(async ({ page }: { page: any }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		await skipIfFeaturesDisabled(test, page, [
			'platform:projects',
			'platform:plans',
			'platform:tasks',
			'platform:workflows'
		]);
	});

	// contract-test: direct surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
	test('uses canonical root hashes and restores workspace history', async ({
		page
	}: {
		page: any;
	}) => {
		const projectsTab = page.getByTestId('projects-nav-link');
		const plansTab = page.getByTestId('plans-nav-link');
		const tasksTab = page.getByTestId('tasks-nav-link');
		const workflowsTab = page.getByTestId('workflows-nav-link');

		await expect(projectsTab).toHaveAttribute('href', '/#projects');
		await expect(plansTab).toHaveAttribute('href', '/#plans');
		await expect(tasksTab).toHaveAttribute('href', '/#tasks');
		await expect(workflowsTab).toHaveAttribute('href', '/#workflows');

		await projectsTab.click();
		await expect(page).toHaveURL(/\/#projects$/);
		await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('projects-nav-link')).toHaveAttribute('aria-current', 'page');

		await page.getByTestId('tasks-nav-link').click();
		await expect(page).toHaveURL(/\/#tasks$/);
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });

		await page.getByTestId('plans-nav-link').click();
		await expect(page).toHaveURL(/\/#plans$/);
		await expect(page.getByTestId('plans-page')).toBeVisible({ timeout: 30000 });

		await page.getByTestId('workflows-nav-link').click();
		await expect(page).toHaveURL(/\/#workflows$/);
		await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30000 });

		await page.goBack();
		await expect(page).toHaveURL(/\/#plans$/);
		await expect(page.getByTestId('plans-page')).toBeVisible({ timeout: 30000 });

		await page.goForward();
		await expect(page).toHaveURL(/\/#workflows$/);
		await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30000 });
	});

	// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
	test('keeps direct root workspace hashes through shell initialization', async ({
		page
	}: {
		page: any;
	}) => {
		for (const [workspace, testId] of [
			['projects', 'projects-page'],
			['plans', 'plans-page'],
			['tasks', 'tasks-page'],
			['workflows', 'workflows-page']
		] as const) {
			await page.goto(getE2EDebugUrl(`/#${workspace}`), { waitUntil: 'domcontentloaded' });
			await expect(page).toHaveURL(new RegExp(`/#${workspace}$`));
			await expect(page.getByTestId(testId)).toBeVisible({ timeout: 30000 });
		}
	});

	// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
	test('redirects legacy workspace paths to their canonical root hashes', async ({
		page
	}: {
		page: any;
	}) => {
		for (const workspace of ['projects', 'plans', 'tasks', 'workflows']) {
			await page.goto(`/${workspace}`, { waitUntil: 'domcontentloaded' });
			await expect(page).toHaveURL(new RegExp(`/#${workspace}$`));
		}
	});
});
