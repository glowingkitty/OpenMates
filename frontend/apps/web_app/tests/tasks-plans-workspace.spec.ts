/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};

/**
 * Tasks and Plans shared workspace coverage.
 *
 * Verifies /tasks and /plans render as sibling shared-workspace surfaces with
 * route-specific composers, boards, and two-axis board scrolling.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { loginToTestAccount, waitForChatReady } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const TASK_COLUMNS = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];
const PLAN_COLUMNS = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];
const PROOF_RECORDING_DIR = 'test-results/proof-video-source/tasks-plans-workspace';
const LAPTOP_PROOF_VIEWPORT = { name: 'web-laptop', width: 1440, height: 900 };
const PHONE_PROOF_VIEWPORT = { name: 'web-phone', width: 390, height: 844 };
const PROOF_STATE_SETTLE_MS = 2500;
const PROOF_SCROLL_STEP_SETTLE_MS = 900;
const PROOF_SCROLL_SETTLE_MS = 2200;
const PROOF_READY_TRIM_LEAD_SECONDS = 0.15;
const TOP_LEVEL_WORKSPACES = [
	{
		path: '/projects',
		navTestId: 'projects-nav-link',
		containerTestId: 'projects-page',
		shellTestId: 'projects-start-screen',
		backgroundIconTestId: 'projects-workspace-background-icon',
		composerTestId: 'project-input-composer',
		inputTestId: 'project-input-textarea'
	},
	{
		path: '/workflows',
		navTestId: 'workflows-nav-link',
		containerTestId: 'workflows-page',
		shellTestId: 'workflows-start-screen',
		backgroundIconTestId: 'workflows-workspace-background-icon',
		composerTestId: 'workflow-input-composer',
		inputTestId: 'workflow-input-textarea'
	},
	{
		path: '/tasks',
		navTestId: 'tasks-nav-link',
		containerTestId: 'tasks-figma-workspace',
		shellTestId: 'tasks-workspace-home',
		backgroundIconTestId: 'tasks-workspace-background-icon',
		composerTestId: 'task-workspace-composer',
		inputTestId: 'task-workspace-input'
	},
	{
		path: '/plans',
		navTestId: 'plans-nav-link',
		containerTestId: 'plans-page',
		shellTestId: 'plans-workspace-home',
		backgroundIconTestId: 'plans-workspace-background-icon',
		composerTestId: 'plan-workspace-composer',
		inputTestId: 'plan-workspace-input'
	}
];

type VisualMetrics = {
	container: { left: number; top: number; right: number; bottom: number; background: string; borderRadius: string };
	dailyInspiration: { left: number; top: number; width: number; height: number };
	reportIssue: { width: number; height: number };
	composer: { left: number; bottom: number; width: number; height: number; background: string; borderRadius: string };
};

async function visualMetrics(page: any, selectors: {
	containerTestId: string;
	dailyInspirationTestId: string;
	reportIssueShellTestId: string;
	composerFieldTestId: string;
}): Promise<VisualMetrics> {
	return page.evaluate((ids: typeof selectors) => {
		const element = (testId: string): HTMLElement => {
			const match = document.querySelector(`[data-testid="${testId}"]`);
			if (!(match instanceof HTMLElement)) throw new Error(`Missing visual parity element: ${testId}`);
			return match;
		};
		const rect = (target: HTMLElement) => target.getBoundingClientRect();
		const container = element(ids.containerTestId);
		const daily = element(ids.dailyInspirationTestId);
		const report = element(ids.reportIssueShellTestId);
		const composer = element(ids.composerFieldTestId);
		const containerBox = rect(container);
		const dailyBox = rect(daily);
		const reportBox = rect(report);
		const composerBox = rect(composer);
		const containerStyle = getComputedStyle(container);
		const composerStyle = getComputedStyle(composer);
		return {
			container: {
				left: containerBox.left,
				top: containerBox.top,
				right: containerBox.right,
				bottom: containerBox.bottom,
				background: containerStyle.backgroundColor,
				borderRadius: containerStyle.borderRadius
			},
			dailyInspiration: { left: dailyBox.left, top: dailyBox.top, width: dailyBox.width, height: dailyBox.height },
			reportIssue: { width: reportBox.width, height: reportBox.height },
			composer: {
				left: composerBox.left,
				bottom: composerBox.bottom,
				width: composerBox.width,
				height: composerBox.height,
				background: composerStyle.backgroundColor,
				borderRadius: composerStyle.borderRadius
			}
		};
	}, selectors);
}

function expectNear(actual: number, expected: number, message: string, tolerance = 3): void {
	expect(Math.abs(actual - expected), message).toBeLessThanOrEqual(tolerance);
}

function expectVisualParity(actual: VisualMetrics, chats: VisualMetrics, workspace: string): void {
	expect(actual.container.background, `${workspace} container background`).toBe(chats.container.background);
	expect(actual.container.borderRadius, `${workspace} container radius`).toBe(chats.container.borderRadius);
	expectNear(actual.container.left, chats.container.left, `${workspace} container left`);
	expectNear(actual.container.top, chats.container.top, `${workspace} container top`);
	expectNear(actual.container.right, chats.container.right, `${workspace} container right`);
	expectNear(actual.container.bottom, chats.container.bottom, `${workspace} container bottom`);
	expectNear(actual.dailyInspiration.left, chats.dailyInspiration.left, `${workspace} inspiration left`);
	expectNear(actual.dailyInspiration.top, chats.dailyInspiration.top, `${workspace} inspiration top`);
	expectNear(actual.dailyInspiration.width, chats.dailyInspiration.width, `${workspace} inspiration width`);
	expectNear(actual.dailyInspiration.height, chats.dailyInspiration.height, `${workspace} inspiration height`);
	expect(actual.reportIssue, `${workspace} report issue control`).toEqual(chats.reportIssue);
	expectNear(actual.composer.left, chats.composer.left, `${workspace} composer left`);
	expectNear(actual.composer.bottom, chats.composer.bottom, `${workspace} composer bottom`);
	expectNear(actual.composer.width, chats.composer.width, `${workspace} composer width`);
	expectNear(actual.composer.height, chats.composer.height, `${workspace} composer height`);
	expect(actual.composer.background, `${workspace} composer background`).toBe(chats.composer.background);
	expect(actual.composer.borderRadius, `${workspace} composer radius`).toBe(chats.composer.borderRadius);
}

async function expectFigmaBoardControls(page: any, surface: 'tasks' | 'plans', mobile: boolean): Promise<void> {
	const prefix = surface === 'tasks' ? 'task' : 'plan';
	await expect(page.getByRole('heading', { name: surface === 'tasks' ? 'Task board' : 'Plan board' })).toHaveCount(0);
	await expect(page.getByTestId(`${prefix}-filter-button`)).toBeVisible();
	await expect(page.getByTestId(`${prefix}-search-input`)).toHaveCount(0);
	if (mobile || surface === 'plans') {
		await expect(page.getByTestId(`${prefix}-search-link`)).toHaveCount(0);
		await expect(page.getByTestId(`${prefix}-filter-tags`)).toHaveCount(0);
		return;
	}
	const search = page.getByTestId('task-search-link');
	const tags = page.getByTestId('task-filter-tags');
	const filter = page.getByTestId('task-filter-button');
	await expect(search).toBeVisible();
	await expect(tags).toBeVisible();
	const [searchBox, tagsBox, filterBox, boardBox] = await Promise.all([
		search.boundingBox(),
		tags.boundingBox(),
		filter.boundingBox(),
		page.getByTestId('task-board').boundingBox()
	]);
	expect(searchBox && tagsBox && filterBox && boardBox, 'Figma task controls must be measurable').toBeTruthy();
	expect(searchBox!.x + searchBox!.width).toBeLessThanOrEqual(filterBox!.x + 3);
	expect(tagsBox!.x + tagsBox!.width).toBeLessThanOrEqual(filterBox!.x + 3);
	expect(tagsBox!.y).toBeGreaterThan(searchBox!.y);
	expect(tagsBox!.y + tagsBox!.height).toBeLessThanOrEqual(boardBox!.y + 8);
}

async function expectHorizontalBoardScroll(board: any): Promise<void> {
	await expect.poll(async () => board.evaluate((element: HTMLElement) => element.scrollWidth > element.clientWidth)).toBe(true);
}

async function moveBoardHorizontalScroll(page: any, board: any): Promise<void> {
	await expectHorizontalBoardScroll(board);
	await board.evaluate((element: HTMLElement) => {
		element.scrollLeft = 0;
	});
	await page.waitForTimeout(PROOF_SCROLL_STEP_SETTLE_MS);
	await board.evaluate((element: HTMLElement) => {
		element.scrollLeft = Math.min(element.scrollWidth - element.clientWidth, 260);
	});
	await page.waitForTimeout(PROOF_SCROLL_STEP_SETTLE_MS);
	await board.evaluate((element: HTMLElement) => {
		element.scrollLeft = Math.min(element.scrollWidth - element.clientWidth, 520);
	});
	await expect.poll(async () => board.evaluate((element: HTMLElement) => element.scrollLeft > 0)).toBe(true);
}

async function expectTaskBoardReady(page: any): Promise<void> {
	await expect(page.getByTestId('tasks-loading')).toHaveCount(0, { timeout: 30000 });
	await expect(page.getByTestId('task-board')).toBeVisible({ timeout: 30000 });
	for (const column of TASK_COLUMNS) {
		await expect(page.getByTestId(`task-column-${column}`)).toBeVisible({ timeout: 15000 });
	}
}

async function expectPlanBoardReady(page: any): Promise<void> {
	await expect(page.getByTestId('plans-loading')).toHaveCount(0, { timeout: 30000 });
	await expect(page.getByTestId('plan-board')).toBeVisible({ timeout: 30000 });
	for (const column of PLAN_COLUMNS) {
		await expect(page.getByTestId(`plan-column-${column}`)).toBeVisible({ timeout: 15000 });
	}
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

function proofVideoPath(testInfo: any, viewport: { name: string; width: number; height: number }): string {
	const safeTitle = String(testInfo.title || 'proof')
		.replace(/[^A-Za-z0-9._-]+/g, '-')
		.replace(/^-+|-+$/g, '')
		.slice(0, 96);
	return path.resolve(PROOF_RECORDING_DIR, `${viewport.name}-${safeTitle || 'proof'}.webm`);
}

function trimProofVideoToReadyMarker(rawPath: string, outputPath: string, readyTimestampMs: number): void {
	const trimStartSeconds = Math.max(0, readyTimestampMs / 1000 - PROOF_READY_TRIM_LEAD_SECONDS);
	const result = spawnSync('ffmpeg', [
		'-y',
		'-ss', trimStartSeconds.toFixed(3),
		'-i', rawPath,
		'-map', '0:v:0',
		'-c:v', 'libvpx-vp9',
		'-deadline', 'realtime',
		'-cpu-used', '4',
		'-b:v', '0',
		'-crf', '32',
		'-an',
		outputPath
	], { encoding: 'utf8' });
	if (result.error || result.status !== 0 || !fs.existsSync(outputPath)) {
		const detail = result.error?.message || result.stderr || result.stdout || 'unknown ffmpeg failure';
		throw new Error(`Proof video trim failed: ${String(detail).slice(-1000)}`);
	}
	fs.rmSync(rawPath, { force: true });
}

async function createAuthenticatedStorageState(browser: any, baseURL: string): Promise<Record<string, unknown>> {
	const context = await browser.newContext({ baseURL });
	const page = await context.newPage();
	try {
		await loginToTestAccount(page);
		await waitForChatReady(page, () => undefined, 30000);
		return await context.storageState({ indexedDB: true });
	} finally {
		await context.close();
	}
}

async function runWithProofPage(
	browser: any,
	baseURL: string,
	testInfo: any,
	viewport: { name: string; width: number; height: number },
	callback: (page: any, markReady: () => void) => Promise<void>
): Promise<void> {
	fs.mkdirSync(PROOF_RECORDING_DIR, { recursive: true });
	const outputPath = proofVideoPath(testInfo, viewport);
	const rawOutputPath = `${outputPath}.raw.webm`;
	fs.rmSync(outputPath, { force: true });
	fs.rmSync(rawOutputPath, { force: true });
	const storageState = await createAuthenticatedStorageState(browser, baseURL);

	const context = await browser.newContext({
		baseURL,
		recordVideo: {
			dir: PROOF_RECORDING_DIR,
			size: { width: viewport.width, height: viewport.height }
		},
		storageState,
		viewport: { width: viewport.width, height: viewport.height }
	});
	const page = await context.newPage();
	const video = page.video();
	const recordingStartedAt = Date.now();
	let readyTimestampMs: number | null = null;
	let thrown: unknown;
	const markReady = () => {
		if (readyTimestampMs === null) readyTimestampMs = Date.now() - recordingStartedAt;
	};

	try {
		await callback(page, markReady);
	} catch (error) {
		thrown = error;
	} finally {
		await page.waitForTimeout(500).catch(() => undefined);
		await context.close();
	}

	if (video) {
		const generatedPath = await video.path();
		await video.saveAs(rawOutputPath);
		if (path.resolve(generatedPath) !== path.resolve(rawOutputPath)) {
			fs.rmSync(generatedPath, { force: true });
		}
		if (readyTimestampMs === null && !thrown) {
			throw new Error(`Proof video for ${viewport.name} did not record a loaded ready marker`);
		}
		if (readyTimestampMs !== null && !thrown) {
			trimProofVideoToReadyMarker(rawOutputPath, outputPath, readyTimestampMs);
		} else {
			fs.renameSync(rawOutputPath, outputPath);
		}
		const stats = fs.statSync(outputPath);
		if (stats.size <= 0) {
			throw new Error(`Proof video for ${viewport.name} was empty`);
		}
		await testInfo.attach(`${viewport.name}-proof-video`, {
			path: outputPath,
			contentType: 'video/webm'
		});
	} else if (!thrown) {
		throw new Error(`Playwright did not create a proof video for ${viewport.name}`);
	}

	if (thrown) {
		throw thrown;
	}
}

test.describe('Tasks and Plans workspace transition', () => {
	test.describe('proof laptop viewport', () => {
		// contract-test: direct surface=gui.web assertions=workspace-shell.start.shared-affordances,workspace-shell.kanban.scroll-containment
		test('renders route-specific shared workspace shells', async ({ browser, baseURL }: { browser: any; baseURL: string }, testInfo: any) => {
			test.setTimeout(240000);
			test.skip(!getTestAccount().email, 'Test account credentials required.');
			await runWithProofPage(browser, baseURL, testInfo, LAPTOP_PROOF_VIEWPORT, async (page, markReady) => {
				await skipIfFeaturesDisabled(test, page, ['platform:projects', 'platform:tasks', 'platform:plans', 'platform:workflows']);

				await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
				await expect(page.getByTestId('tasks-workspace-home')).toBeVisible({ timeout: 30000 });
				await expect(page.getByTestId('tasks-daily-inspiration-area')).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId('tasks-workspace-background-icon')).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId('task-greeting')).toContainText(/what task is next\?/i, { timeout: 15000 });
				await expect(page.getByTestId('task-workspace-composer')).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId('tasks-board-workspace')).toBeVisible({ timeout: 15000 });
				await expectFigmaBoardControls(page, 'tasks', false);
				await expectBoardScrollsUnderFixedComposer(page, 'tasks-workspace-home', 'tasks-board-scroll-content', 'task-workspace-composer');
				await expectTaskBoardReady(page);
				markReady();
				await page.waitForTimeout(PROOF_STATE_SETTLE_MS);

				await page.goto(getE2EDebugUrl('/plans'), { waitUntil: 'domcontentloaded' });
				await expect(page.getByTestId('plans-workspace-home')).toBeVisible({ timeout: 30000 });
				await expect(page.getByTestId('plans-daily-inspiration-area')).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId('plans-workspace-background-icon')).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId('plan-greeting')).toContainText(/what is your next plan\?/i, { timeout: 15000 });
				await expect(page.getByTestId('plan-workspace-composer')).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId('plans-board-workspace')).toBeVisible({ timeout: 15000 });
				await expectFigmaBoardControls(page, 'plans', false);
				await expectBoardScrollsUnderFixedComposer(page, 'plans-workspace-home', 'plans-board-scroll-content', 'plan-workspace-composer');
				await expect(page.getByTestId('task-create-form')).toHaveCount(0);
				await expect(page.getByTestId('task-extract-card')).toHaveCount(0);
				await expectPlanBoardReady(page);
				await page.waitForTimeout(PROOF_STATE_SETTLE_MS);
			});
		});

		// contract-test: direct surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible,workspace-shell.start.shared-affordances,workspace-shell.start.chat-visual-parity
		test('keeps top-level workspace tabs and composers aligned with the chat shell', async ({ browser, baseURL }: { browser: any; baseURL: string }, testInfo: any) => {
			test.setTimeout(240000);
			test.skip(!getTestAccount().email, 'Test account credentials required.');
			await runWithProofPage(browser, baseURL, testInfo, LAPTOP_PROOF_VIEWPORT, async (page, markReady) => {
				await skipIfFeaturesDisabled(test, page, ['platform:projects', 'platform:tasks', 'platform:plans', 'platform:workflows']);
				await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
				await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 30000 });
				await expect(page.getByTestId('daily-inspiration-area')).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId('report-issue-button-shell')).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId('message-input-field')).toBeVisible({ timeout: 15000 });
				const chatsMetrics = await visualMetrics(page, {
					containerTestId: 'active-chat-container',
					dailyInspirationTestId: 'daily-inspiration-area',
					reportIssueShellTestId: 'report-issue-button-shell',
					composerFieldTestId: 'message-input-field'
				});
				markReady();
				await page.waitForTimeout(PROOF_STATE_SETTLE_MS);

				for (const workspace of TOP_LEVEL_WORKSPACES) {
					await page.goto(getE2EDebugUrl(workspace.path), { waitUntil: 'domcontentloaded' });
					await expect(page.getByTestId(workspace.navTestId)).toBeVisible({ timeout: 30000 });
				}

				for (const workspace of TOP_LEVEL_WORKSPACES) {
					await page.goto(getE2EDebugUrl(workspace.path), { waitUntil: 'domcontentloaded' });
					await expect(page.getByTestId(workspace.shellTestId)).toBeVisible({ timeout: 30000 });
					await expect(page.getByTestId(workspace.backgroundIconTestId)).toBeVisible({ timeout: 15000 });
					await expect(page.getByTestId(workspace.composerTestId)).toBeVisible({ timeout: 15000 });
					await expect(page.getByTestId(workspace.inputTestId)).toHaveCSS('text-align', 'center');
					await expectComposerAnchoredOverShell(page, workspace.shellTestId, workspace.composerTestId);
					await expect(page.getByTestId('report-issue-button-shell')).toBeVisible({ timeout: 15000 });
					const workspaceMetrics = await visualMetrics(page, {
						containerTestId: workspace.containerTestId,
						dailyInspirationTestId: `${workspace.path.slice(1)}-daily-inspiration-area`,
						reportIssueShellTestId: 'report-issue-button-shell',
						composerFieldTestId: workspace.composerTestId
					});
					expectVisualParity(workspaceMetrics, chatsMetrics, workspace.path);
					if (workspace.path === '/tasks') await expectTaskBoardReady(page);
					if (workspace.path === '/plans') await expectPlanBoardReady(page);
					await page.waitForTimeout(PROOF_STATE_SETTLE_MS);
				}
			});
		});
	});

	test.describe('proof phone viewport', () => {
		// contract-test: direct surface=gui.web assertions=workspace-shell.start.chat-visual-parity,workspace-shell.kanban.figma-controls,workspace-shell.kanban.scroll-containment
		test('keeps boards horizontally scrollable on mobile', async ({ browser, baseURL }: { browser: any; baseURL: string }, testInfo: any) => {
			test.setTimeout(240000);
			test.skip(!getTestAccount().email, 'Test account credentials required.');
			await runWithProofPage(browser, baseURL, testInfo, PHONE_PROOF_VIEWPORT, async (page, markReady) => {
				await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);
				await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
				await expect(page.getByTestId('active-chat-container')).toBeVisible({ timeout: 30000 });
				await expect(page.getByTestId('daily-inspiration-area')).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId('report-issue-button-shell')).toBeVisible({ timeout: 15000 });
				await expect(page.getByTestId('message-input-field')).toBeVisible({ timeout: 15000 });
				const chatsMetrics = await visualMetrics(page, {
					containerTestId: 'active-chat-container',
					dailyInspirationTestId: 'daily-inspiration-area',
					reportIssueShellTestId: 'report-issue-button-shell',
					composerFieldTestId: 'message-input-field'
				});
				markReady();
				await page.waitForTimeout(PROOF_STATE_SETTLE_MS);

				for (const workspace of TOP_LEVEL_WORKSPACES) {
					await page.goto(getE2EDebugUrl(workspace.path), { waitUntil: 'domcontentloaded' });
					await expect(page.getByTestId(workspace.shellTestId)).toBeVisible({ timeout: 30000 });
					await expect(page.getByTestId(workspace.composerTestId)).toBeVisible({ timeout: 15000 });
					await expect(page.getByTestId('report-issue-button-shell')).toBeVisible({ timeout: 15000 });
					const workspaceMetrics = await visualMetrics(page, {
						containerTestId: workspace.containerTestId,
						dailyInspirationTestId: `${workspace.path.slice(1)}-daily-inspiration-area`,
						reportIssueShellTestId: 'report-issue-button-shell',
						composerFieldTestId: workspace.composerTestId
					});
					expectVisualParity(workspaceMetrics, chatsMetrics, `${workspace.path} mobile`);
					await page.waitForTimeout(PROOF_STATE_SETTLE_MS);
				}

				await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
				await expectTaskBoardReady(page);
				await expect(page.getByTestId('task-workspace-composer')).toBeVisible({ timeout: 15000 });
				await expectFigmaBoardControls(page, 'tasks', true);
				for (const column of TASK_COLUMNS.slice(0, 2)) {
					await expect(page.getByTestId(`task-column-${column}`)).toBeVisible({ timeout: 15000 });
				}
				await page.waitForTimeout(PROOF_STATE_SETTLE_MS);
				await moveBoardHorizontalScroll(page, page.getByTestId('task-board'));
				await page.waitForTimeout(PROOF_SCROLL_SETTLE_MS);

				await page.goto(getE2EDebugUrl('/plans'), { waitUntil: 'domcontentloaded' });
				await expectPlanBoardReady(page);
				await expect(page.getByTestId('plan-workspace-composer')).toBeVisible({ timeout: 15000 });
				await expectFigmaBoardControls(page, 'plans', true);
				for (const column of PLAN_COLUMNS.slice(0, 2)) {
					await expect(page.getByTestId(`plan-column-${column}`)).toBeVisible({ timeout: 15000 });
				}
				await page.waitForTimeout(PROOF_STATE_SETTLE_MS);
				await moveBoardHorizontalScroll(page, page.getByTestId('plan-board'));
				await page.waitForTimeout(PROOF_SCROLL_SETTLE_MS);
			});
		});
	});
});
