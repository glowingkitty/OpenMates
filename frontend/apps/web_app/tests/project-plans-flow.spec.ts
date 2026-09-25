/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Project-linked Plans V1 web flow coverage.
 *
 * Verifies a project can create a linked encrypted Plan and display it as a
 * first-class card in the Project Tasks board.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function projectHashUrlPattern(projectId: string): RegExp {
	return new RegExp(`/projects#(?:[^#]*&)?project-id=${projectId}(?:&|$)`);
}

function deriveApiUrl(baseUrl: string): string {
	const url = new URL(baseUrl || 'https://app.dev.openmates.org');
	if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
	if (url.hostname === 'localhost') return 'http://localhost:8000';
	return 'https://api.openmates.org';
}

async function columnCount(container: any, status: string): Promise<number> {
	const text = await container.getByTestId(`task-column-count-${status}`).textContent();
	const match = text?.match(/\d+/);
	if (!match) throw new Error(`Missing numeric ${status} column count`);
	return Number(match[0]);
}

test.describe('Project-linked Plans V1 flow', () => {
	// contract-test: direct surface=gui.web assertions=projects.workspace.contract-plan-task-check-chain,plans.project-links.encrypted
	test('creates a project-linked Plan card in the shared Tasks board', async ({ page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:projects', 'platform:tasks', 'platform:plans']);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const projectName = `E2E Plan Project ${Date.now()}`;
		let projectId = '';
		let planId = '';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		try {
			await page.goto(getE2EDebugUrl('/projects'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });

			const created = page.waitForResponse(
				(response) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok()
			);
			await page.getByTestId('project-input-textarea').fill(projectName);
			await page.getByTestId('project-input-submit').click();
			await page.getByTestId('project-write-policy-apply-and-show').check();
			await page.getByTestId('project-write-policy-confirm').click();
			projectId = (await (await created).json()).project.project_id;
			await expect(page).toHaveURL(projectHashUrlPattern(projectId));
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(projectName, { timeout: 30000 });

			const planCreated = page.waitForResponse(
				(response) => response.request().method() === 'POST' && response.url().endsWith('/v1/user-plans') && response.ok()
			);
			await page.getByTestId('project-readme-create').click();
			await expect(page.getByTestId('project-create-menu')).toBeVisible();
			await page.getByTestId('project-create-plan').click();
			planId = (await (await planCreated).json()).plan.plan_id;
			await expect(page).toHaveURL(new RegExp(`/plans/${planId}(?:[?#]|$)`));
			await expect(page.getByTestId('plan-detail-page')).toBeVisible({ timeout: 30000 });

			await page.goto(getE2EDebugUrl(`/projects#project-id=${encodeURIComponent(projectId)}`), { waitUntil: 'domcontentloaded' });
			await expect(page).toHaveURL(projectHashUrlPattern(projectId));
			await page.getByTestId('project-tab-tasks').click();
			const projectTasks = page.getByTestId('project-tasks-panel');
			await expect(projectTasks).toBeVisible({ timeout: 30000 });
			await expect(projectTasks.getByTestId('task-board')).toBeVisible({ timeout: 30000 });

			const planCard = projectTasks.locator(`[data-testid="task-board-plan-card"][data-plan-id="${planId}"]`);
			await expect(planCard).toBeVisible({ timeout: 30000 });
			await expect(planCard).toContainText('Untitled plan');
			await expect(planCard).toHaveAttribute('data-plan-status', 'draft');
			await expect(planCard).toHaveAttribute('data-plan-column', 'backlog');
			await expect(projectTasks.getByTestId('task-column-backlog').locator(`[data-plan-id="${planId}"]`)).toHaveCount(1);
			await expect.poll(() => columnCount(projectTasks, 'backlog')).toBe(1);
			await expect(planCard.getByTestId('task-board-plan-actions')).toBeVisible();
			await expect(planCard.getByTestId('task-board-plan-move-todo')).toBeAttached();

			await planCard.getByTestId('task-board-plan-open').click();
			await expect(page).toHaveURL(new RegExp(`/plans/${planId}(?:[?#]|$)`));
			await expect(page.getByTestId('plan-detail-page')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('plans-nav-link')).toHaveCount(0);
		} finally {
			if (planId) await page.request.delete(`${apiUrl}/v1/user-plans/${encodeURIComponent(planId)}`).catch(() => null);
			if (projectId) {
				await page.request.delete(
					`${apiUrl}/v1/projects/${encodeURIComponent(projectId)}?confirmation_project_id=${encodeURIComponent(projectId)}`
				).catch(() => null);
			}
		}
	});
});
