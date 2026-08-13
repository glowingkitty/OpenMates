/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};

/**
 * Tasks and Plans shared workspace coverage.
 *
 * Verifies /tasks and /plans render as sibling shared-workspace surfaces with
 * route-specific composers, boards, and two-axis board scrolling.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const TASK_COLUMNS = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];
const PLAN_COLUMNS = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];
const LAPTOP_PROOF_VIEWPORT = { width: 1440, height: 900 };
const PHONE_PROOF_VIEWPORT = { width: 390, height: 844 };
const TOP_LEVEL_WORKSPACES = [
	{
		path: '/projects',
		navTestId: 'projects-nav-link',
		shellTestId: 'projects-start-screen',
		backgroundIconTestId: 'projects-workspace-background-icon',
		composerTestId: 'project-input-composer',
		inputTestId: 'project-input-textarea'
	},
	{
		path: '/workflows',
		navTestId: 'workflows-nav-link',
		shellTestId: 'workflows-start-screen',
		backgroundIconTestId: 'workflows-workspace-background-icon',
		composerTestId: 'workflow-input-composer',
		inputTestId: 'workflow-input-textarea'
	},
	{
		path: '/tasks',
		navTestId: 'tasks-nav-link',
		shellTestId: 'tasks-workspace-home',
		backgroundIconTestId: 'tasks-workspace-background-icon',
		composerTestId: 'task-workspace-composer',
		inputTestId: 'task-workspace-input'
	},
	{
		path: '/plans',
		navTestId: 'plans-nav-link',
		shellTestId: 'plans-workspace-home',
		backgroundIconTestId: 'plans-workspace-background-icon',
		composerTestId: 'plan-workspace-composer',
		inputTestId: 'plan-workspace-input'
	}
];

async function expectHorizontalBoardScroll(board: any): Promise<void> {
	await expect.poll(async () => board.evaluate((element: HTMLElement) => element.scrollWidth > element.clientWidth)).toBe(true);
}

async function expectComposerAnchoredOverShell(page: any, shellTestId: string, composerTestId: string): Promise<void> {
	await expect.poll(async () => page.evaluate(({ shellTestId, composerTestId }: { shellTestId: string; composerTestId: string }) => {
		const shell = document.querySelector(`[data-testid="${shellTestId}"]`);
		const composer = document.querySelector(`[data-testid="${composerTestId}"]`);
		if (!(shell instanceof HTMLElement) || !(composer instanceof HTMLElement)) return false;
		const shellBox = shell.getBoundingClientRect();
		const composerBox = composer.getBoundingClientRect();
		return composerBox.bottom <= shellBox.bottom + 2
			&& composerBox.bottom >= shellBox.bottom - 40
			&& composerBox.left >= shellBox.left
			&& composerBox.right <= shellBox.right;
	}, { shellTestId, composerTestId })).toBe(true);
}

async function expectBoardScrollsUnderFixedComposer(page: any, shellTestId: string, boardContentTestId: string, composerTestId: string): Promise<void> {
	await expect.poll(async () => page.evaluate(({ shellTestId, boardContentTestId, composerTestId }: { shellTestId: string; boardContentTestId: string; composerTestId: string }) => {
		const shell = document.querySelector(`[data-testid="${shellTestId}"]`);
		const content = document.querySelector(`[data-testid="${boardContentTestId}"]`);
		const composer = document.querySelector(`[data-testid="${composerTestId}"]`);
		if (!(shell instanceof HTMLElement) || !(content instanceof HTMLElement) || !(composer instanceof HTMLElement)) return false;
		const scrollLayer = shell.querySelector(`[data-testid$="-workspace-scroll-layer"]`);
		if (!(scrollLayer instanceof HTMLElement)) return false;
		const shellBox = shell.getBoundingClientRect();
		const composerBoxBefore = composer.getBoundingClientRect();
		const before = scrollLayer.scrollTop;
		scrollLayer.scrollTop = before + 160;
		const after = scrollLayer.scrollTop;
		const composerBoxAfter = composer.getBoundingClientRect();
		return scrollLayer.scrollHeight > scrollLayer.clientHeight
			&& after > before
			&& composerBoxAfter.bottom <= shellBox.bottom + 2
			&& Math.abs(composerBoxAfter.bottom - composerBoxBefore.bottom) <= 2;
	}, { shellTestId, boardContentTestId, composerTestId })).toBe(true);
}

test.describe('Tasks and Plans workspace transition', () => {
	test.describe('proof laptop viewport', () => {
		test.use({
			viewport: LAPTOP_PROOF_VIEWPORT,
			video: { mode: 'on', size: LAPTOP_PROOF_VIEWPORT }
		});

		// contract-test: direct surface=gui.web assertions=workspace-shell.start.shared-affordances,workspace-shell.kanban.scroll-containment
		test('renders route-specific shared workspace shells', async ({ page }) => {
			test.setTimeout(150000);
			test.skip(!getTestAccount().email, 'Test account credentials required.');
			await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);

			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(page);

			await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('tasks-workspace-home')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('tasks-daily-inspiration-area')).toBeVisible({ timeout: 15000 });
			await expect(page.getByTestId('tasks-workspace-background-icon')).toBeVisible({ timeout: 15000 });
			await expect(page.getByTestId('task-greeting')).toContainText(/what task is next\?/i, { timeout: 15000 });
			await expect(page.getByTestId('task-workspace-composer')).toBeVisible({ timeout: 15000 });
			await expect(page.getByTestId('tasks-board-workspace')).toBeVisible({ timeout: 15000 });
			await expectBoardScrollsUnderFixedComposer(page, 'tasks-workspace-home', 'tasks-board-scroll-content', 'task-workspace-composer');
			for (const column of TASK_COLUMNS) {
				await expect(page.getByTestId(`task-column-${column}`)).toBeVisible({ timeout: 15000 });
			}

			await page.goto(getE2EDebugUrl('/plans'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('plans-workspace-home')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('plans-daily-inspiration-area')).toBeVisible({ timeout: 15000 });
			await expect(page.getByTestId('plans-workspace-background-icon')).toBeVisible({ timeout: 15000 });
			await expect(page.getByTestId('plan-greeting')).toContainText(/what is your next plan\?/i, { timeout: 15000 });
			await expect(page.getByTestId('plan-workspace-composer')).toBeVisible({ timeout: 15000 });
			await expect(page.getByTestId('plans-board-workspace')).toBeVisible({ timeout: 15000 });
			await expectBoardScrollsUnderFixedComposer(page, 'plans-workspace-home', 'plans-board-scroll-content', 'plan-workspace-composer');
			await expect(page.getByTestId('task-create-form')).toHaveCount(0);
			await expect(page.getByTestId('task-extract-card')).toHaveCount(0);
			for (const column of PLAN_COLUMNS) {
				await expect(page.getByTestId(`plan-column-${column}`)).toBeVisible({ timeout: 15000 });
			}
		});

		// contract-test: direct surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible,workspace-shell.start.shared-affordances
		test('keeps top-level workspace tabs and composers aligned with the chat shell', async ({ page }) => {
			test.setTimeout(180000);
			test.skip(!getTestAccount().email, 'Test account credentials required.');
			await skipIfFeaturesDisabled(test, page, ['platform:projects', 'platform:tasks', 'platform:plans', 'platform:workflows']);

			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(page);

			for (const workspace of TOP_LEVEL_WORKSPACES) {
				await expect(page.getByTestId(workspace.navTestId)).toBeVisible({ timeout: 30000 });
			}

			for (const workspace of TOP_LEVEL_WORKSPACES) {
				await page.goto(getE2EDebugUrl(workspace.path), { waitUntil: 'domcontentloaded' });
				await expect(page.getByTestId(workspace.shellTestId)).toBeVisible({ timeout: 30000 });
				await expect(page.getByTestId(workspace.backgroundIconTestId)).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId(workspace.composerTestId)).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId(workspace.inputTestId)).toHaveCSS('text-align', 'center');
				await expectComposerAnchoredOverShell(page, workspace.shellTestId, workspace.composerTestId);
			}
		});
	});

	test.describe('proof phone viewport', () => {
		test.use({
			viewport: PHONE_PROOF_VIEWPORT,
			video: { mode: 'on', size: PHONE_PROOF_VIEWPORT }
		});

		// contract-test: direct surface=gui.web assertions=workspace-shell.kanban.scroll-containment
		test('keeps boards horizontally scrollable on mobile', async ({ page }) => {
			test.setTimeout(150000);
			test.skip(!getTestAccount().email, 'Test account credentials required.');
			await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);

			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(page);

			await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('task-board')).toBeVisible({ timeout: 30000 });
			await expectHorizontalBoardScroll(page.getByTestId('task-board'));

			await page.goto(getE2EDebugUrl('/plans'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('plan-board')).toBeVisible({ timeout: 30000 });
			await expectHorizontalBoardScroll(page.getByTestId('plan-board'));
		});
	});
});
