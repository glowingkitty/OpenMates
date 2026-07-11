/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Red routing contract for unified workspace detail pages.
 *
 * Every case creates a uniquely named record through its owning UI/API and
 * deletes only the resulting ID. Detail checks require canonical URLs, the
 * shared header marker, reload safety, and Report Issue access.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function deriveApiUrl(baseUrl: string): string {
	const url = new URL(baseUrl || 'https://app.dev.openmates.org');
	if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
	if (url.hostname === 'localhost') return 'http://localhost:8000';
	return 'https://api.openmates.org';
}

async function expectUnifiedDetail(page, domain: string, itemId: string): Promise<void> {
	await expect(page).toHaveURL(new RegExp(`/${domain}/${itemId}(?:[?#]|$)`));
	const header = page.getByTestId('workspace-detail-header');
	await expect(header).toBeVisible({ timeout: 30000 });
	await expect(header).toHaveAttribute('data-header-system', 'workspace-detail');
	await expect.soft(page.getByTestId('report-issue-button')).toBeVisible();
	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect(page).toHaveURL(new RegExp(`/${domain}/${itemId}(?:[?#]|$)`));
	await expect(page.getByTestId('workspace-detail-header')).toHaveAttribute('data-header-system', 'workspace-detail');
}

test.describe('Unified workspace detail pages', () => {
	test.beforeEach(async ({ page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
	});

	test('Project cards open a canonical shared-header detail page', async ({ page }) => {
		await skipIfFeaturesDisabled(test, page, ['platform:projects']);
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const title = `Unified detail project ${Date.now()}-${test.info().workerIndex}`;
		let projectId = '';

		try {
			await page.goto(getE2EDebugUrl('/projects'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
			await expect.soft(page.getByTestId('report-issue-button')).toBeVisible();
			await page.getByTestId('project-create-main-button').click();
			await page.getByTestId('project-name-input').fill(title);
			const created = page.waitForResponse(
				(response) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok()
			);
			await page.getByTestId('project-create-button').click();
			projectId = (await (await created).json()).project.project_id;
			const card = page.getByTestId('project-card').filter({ hasText: title });
			await card.getByTestId('project-detail-link').click();
			await expectUnifiedDetail(page, 'projects', projectId);
		} finally {
			if (projectId) await page.request.delete(`${apiUrl}/v1/projects/${encodeURIComponent(projectId)}`).catch(() => null);
		}
	});

	test('Task cards open a canonical shared-header detail page', async ({ page }) => {
		await skipIfFeaturesDisabled(test, page, ['platform:tasks']);
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const title = `Unified detail task ${Date.now()}-${test.info().workerIndex}`;
		let taskId = '';

		try {
			await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });
			await expect.soft(page.getByTestId('report-issue-button')).toBeVisible();
			await page.getByTestId('task-title-input').fill(title);
			const created = page.waitForResponse(
				(response) => response.request().method() === 'POST' && response.url().endsWith('/v1/user-tasks') && response.ok()
			);
			await page.getByTestId('task-create-button').click();
			taskId = (await (await created).json()).task.task_id;
			const card = page.getByTestId('task-card').filter({ hasText: title });
			await card.getByTestId('task-detail-link').click();
			await expectUnifiedDetail(page, 'tasks', taskId);
		} finally {
			if (taskId) await page.request.delete(`${apiUrl}/v1/user-tasks/${encodeURIComponent(taskId)}`).catch(() => null);
		}
	});

	test('Plan cards open a canonical shared-header detail page', async ({ page }) => {
		await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const title = `Unified detail plan ${Date.now()}-${test.info().workerIndex}`;
		let planId = '';

		try {
			await page.goto(getE2EDebugUrl('/plans'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });
			await expect.soft(page.getByTestId('report-issue-button')).toBeVisible();
			await page.getByTestId('plan-title-input').fill(title);
			const created = page.waitForResponse(
				(response) => response.request().method() === 'POST' && response.url().endsWith('/v1/user-plans') && response.ok()
			);
			await page.getByTestId('plan-create-button').click();
			planId = (await (await created).json()).plan.plan_id;
			const card = page.getByTestId('linked-plan-card').filter({ hasText: title });
			await card.getByTestId('plan-detail-link').click();
			await expectUnifiedDetail(page, 'plans', planId);
		} finally {
			if (planId) await page.request.delete(`${apiUrl}/v1/user-plans/${encodeURIComponent(planId)}`).catch(() => null);
		}
	});

	test('Workflow cards open a canonical shared-header detail page', async ({ page }) => {
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const title = `Unified detail workflow ${Date.now()}-${test.info().workerIndex}`;
		let workflowId = '';

		try {
			const response = await page.request.post(`${apiUrl}/v1/workflows`, {
				data: {
					title,
					description: 'Owned by unified-detail-pages.spec.ts',
					graph: {
						version: 1,
						trigger_node_id: 'manual',
						nodes: [{ id: 'manual', type: 'manual_trigger', title: 'Manual', config: {} }],
						edges: []
					},
					enabled: false
				}
			});
			expect(response.ok()).toBe(true);
			workflowId = (await response.json()).workflow.id;

			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30000 });
			await expect.soft(page.getByTestId('report-issue-button')).toBeVisible();
			const card = page.getByTestId('workflow-landing-card').filter({ hasText: title });
			await card.click();
			await expectUnifiedDetail(page, 'workflows', workflowId);
		} finally {
			if (workflowId) await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
		}
	});
});
