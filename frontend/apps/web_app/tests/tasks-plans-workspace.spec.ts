/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};

/**
 * Plans projected into the global Tasks workspace.
 *
 * Plans remain encrypted Plan records with canonical detail routes, while the
 * global Tasks board presents them in the same five status lanes as Tasks and
 * Workflow runs. New Plans are created from their owning Project context.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const TASK_COLUMNS = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];

function deriveApiUrl(baseUrl: string): string {
	const url = new URL(baseUrl || 'https://app.dev.openmates.org');
	if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
	if (url.hostname === 'localhost') return 'http://localhost:8000';
	return 'https://api.openmates.org';
}

function projectHashUrlPattern(projectId: string): RegExp {
	return new RegExp(`/#(?:[^#]*&)?project-id=${projectId}(?:&|$)`);
}

async function columnCount(page: any, status: string): Promise<number> {
	const text = await page.getByTestId(`task-column-count-${status}`).textContent();
	const match = text?.match(/\d+/);
	if (!match) throw new Error(`Missing numeric ${status} column count`);
	return Number(match[0]);
}

async function expectTaskBoardReady(page: any): Promise<void> {
	await expect(page.getByTestId('tasks-loading')).toHaveCount(0, { timeout: 30000 });
	await expect(page.getByTestId('task-board')).toBeVisible({ timeout: 30000 });
	for (const column of TASK_COLUMNS) {
		await expect(page.getByTestId(`task-column-${column}`)).toBeVisible({ timeout: 15000 });
	}
}

async function createProjectPlan(page: any, projectName: string): Promise<{ projectId: string; planId: string }> {
	await page.goto(getE2EDebugUrl('/projects'), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });

	const projectCreated = page.waitForResponse(
		(response: any) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok()
	);
	await page.getByTestId('project-input-textarea').fill(projectName);
	await page.getByTestId('project-input-submit').click();
	await page.getByTestId('project-write-policy-apply-and-show').check();
	await page.getByTestId('project-write-policy-confirm').click();
	const projectId = (await (await projectCreated).json()).project.project_id;
	await expect(page).toHaveURL(projectHashUrlPattern(projectId));

	const planCreated = page.waitForResponse(
		(response: any) => response.request().method() === 'POST' && response.url().endsWith('/v1/user-plans') && response.ok()
	);
	await page.getByTestId('project-readme-create').click();
	await expect(page.getByTestId('project-create-menu')).toBeVisible();
	await page.getByTestId('project-create-plan').click();
	const planId = (await (await planCreated).json()).plan.plan_id;
	await expect(page).toHaveURL(new RegExp(`/#plan-id=${planId}(?:&|$)`));
	await expect(page.getByTestId('plan-detail-page')).toBeVisible({ timeout: 30000 });

	return { projectId, planId };
}

async function dragPlanToColumn(page: any, planCard: any, status: string): Promise<void> {
	await planCard.evaluate((element: HTMLElement) => {
		const dataTransfer = new DataTransfer();
		const planId = element.dataset.planId || '';
		dataTransfer.setData('application/x-openmates-plan-id', planId);
		dataTransfer.setData('text/plain', planId);
		(window as unknown as { planBoardDataTransfer: DataTransfer }).planBoardDataTransfer = dataTransfer;
		element.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer }));
	});
	await page.getByTestId(`task-column-${status}`).evaluate((element: HTMLElement) => {
		const dataTransfer = (window as unknown as { planBoardDataTransfer: DataTransfer }).planBoardDataTransfer;
		element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer }));
	});
	await planCard.evaluate((element: HTMLElement) => element.dispatchEvent(new DragEvent('dragend', { bubbles: true })));
}

test.describe('Plans on the global Tasks board', () => {
	// contract-test: direct surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible,tasks.surface.semantic-parity,plans.lifecycle.visible,plans.content.client-encrypted,plans.ui.edit-approve-resume
	test('shows project-owned Plans as movable cards in the shared five-column board', async ({ page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:projects', 'platform:tasks', 'platform:plans']);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const suffix = `${Date.now()}-${test.info().workerIndex}`;
		const projectName = `Global Plan Board Project ${suffix}`;
		let projectId = '';
		let planId = '';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		try {
			await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
			await expectTaskBoardReady(page);
			await expect(page.getByTestId('plans-nav-link')).toBeVisible();
			await expect(page.getByTestId('plan-create-form')).toHaveCount(0);

			await page.goto(getE2EDebugUrl('/plans'), { waitUntil: 'domcontentloaded' });
			await expect(page).toHaveURL(/\/#plans(?:&|$)/);
			await expect(page.getByTestId('plans-page')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('plans-nav-link')).toBeVisible();

			({ projectId, planId } = await createProjectPlan(page, projectName));

			await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
			await expectTaskBoardReady(page);
			const planCard = page.locator(`[data-testid="task-board-plan-card"][data-plan-id="${planId}"]`);
			await expect(planCard).toBeVisible({ timeout: 30000 });
			await expect(planCard).toContainText('Untitled plan');
			await expect(planCard).toHaveAttribute('data-plan-status', 'draft');
			await expect(planCard).toHaveAttribute('data-plan-column', 'backlog');
			await expect(page.getByTestId('task-column-backlog').locator(`[data-plan-id="${planId}"]`)).toHaveCount(1);
			await expect(planCard.getByTestId('task-board-plan-actions')).toBeVisible();
			await expect(planCard.getByTestId('task-board-plan-move-todo')).toBeAttached();

			const backlogBefore = await columnCount(page, 'backlog');
			const todoBefore = await columnCount(page, 'todo');
			const moved = page.waitForResponse(
				(response: any) => response.request().method() === 'PATCH'
					&& new URL(response.url()).pathname.endsWith(`/v1/user-plans/${planId}`)
					&& response.ok()
			);
			await dragPlanToColumn(page, planCard, 'todo');
			await moved;
			await expect(planCard).toHaveAttribute('data-plan-status', 'awaiting_confirmation', { timeout: 30000 });
			await expect(planCard).toHaveAttribute('data-plan-column', 'todo');
			await expect(page.getByTestId('task-column-todo').locator(`[data-plan-id="${planId}"]`)).toHaveCount(1);
			await expect.poll(() => columnCount(page, 'backlog')).toBe(backlogBefore - 1);
			await expect.poll(() => columnCount(page, 'todo')).toBe(todoBefore + 1);

			await planCard.getByTestId('task-board-plan-open').click();
			await expect(page).toHaveURL(new RegExp(`/#plan-id=${planId}(?:&|$)`));
			await expect(page.getByTestId('plan-detail-page')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('plans-nav-link')).toBeVisible();
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
