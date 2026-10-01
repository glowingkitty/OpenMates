/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Tasks web app parity coverage.
 *
 * Proves the browser Tasks workspace follows the existing CLI/API contract:
 * encrypted task creation, the shared daily inspiration header, fixed Kanban
 * columns, status/action parity, and touch-safe explicit controls.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { seedLegacyTaskLink } = require('./helpers/legacy-user-task-fixture');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const TASK_STATUSES = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];

function taskCardIn(column: any, title: string): any {
	return column.getByTestId('task-card').filter({ hasText: title }).first();
}

test.describe('Tasks web app parity', () => {
	// contract-test: direct surface=gui.web assertions=tasks.lifecycle.visible,tasks.external-chat.encrypted-context,tasks.surface.semantic-parity
	test('persists a drag to Done for a historical external-chat task without changing its encrypted link', async ({ page }) => {
		test.setTimeout(150_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks']);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, () => {}, async () => {});
		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
		const title = `Historical task drag ${Date.now()}`;
		await page.getByTestId('task-workspace-input').fill(title);
		const [created] = await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/v1/user-tasks')),
			page.getByTestId('task-workspace-submit').click(),
		]);
		expect(created.ok()).toBe(true);
		const { task: newTask } = await created.json();
		const tasksUrl = new URL('/v1/user-tasks', created.url()).toString();
		const taskUrl = `${tasksUrl}/${newTask.task_id}`;
		const readTask = async () => {
			const response = await page.request.get(taskUrl);
			expect(response.ok()).toBe(true);
			return (await response.json()).task;
		};
		try {
			seedLegacyTaskLink(newTask.task_id);
			const legacyTask = await readTask();
			const legacyLink = {
				external_chat_provider: 'opencode',
				external_chat_lookup_hash: 'c'.repeat(64),
				encrypted_external_chat_id: newTask.encrypted_title,
				encrypted_external_chat_title: newTask.encrypted_title,
			};
			expect(legacyTask).toMatchObject(legacyLink);
			// Verify the reported failing REST action before exercising browser drag.
			const completed = await page.request.post(`${taskUrl}/complete`, { data: { version: legacyTask.version } });
			expect(completed.ok()).toBe(true);
			const completedTask = await readTask();
			expect(completedTask).toMatchObject({ ...legacyLink, status: 'done' });
			const reset = await page.request.post(`${tasksUrl}/reorder`, {
				data: { moves: [{ task_id: newTask.task_id, version: completedTask.version, status: 'todo', position: 0 }] },
			});
			expect(reset.ok()).toBe(true);
			await page.reload({ waitUntil: 'domcontentloaded' });
			const card = taskCardIn(page.getByTestId('task-column-todo'), title);
			await expect(card).toBeVisible({ timeout: 30_000 });
			const [completeResponse, reorderResponse] = await Promise.all([
				page.waitForResponse((response) => response.request().method() === 'POST' && response.url() === `${taskUrl}/complete`),
				page.waitForResponse((response) => response.request().method() === 'POST' && response.url() === `${tasksUrl}/reorder`),
				card.getByTestId('task-card-open').dragTo(page.getByTestId('task-column-done'), { targetPosition: { x: 80, y: 20 } }),
			]);
			expect(completeResponse.ok()).toBe(true);
			expect(reorderResponse.ok()).toBe(true);
			await expect(taskCardIn(page.getByTestId('task-column-done'), title)).toBeVisible();
			await expect(page.getByText('Failed to update task', { exact: true })).toHaveCount(0);
			expect(await readTask()).toMatchObject({ ...legacyLink, status: 'done', encrypted_title: newTask.encrypted_title });
			await page.reload({ waitUntil: 'domcontentloaded' });
			await expect(taskCardIn(page.getByTestId('task-column-done'), title)).toBeVisible({ timeout: 30_000 });
		} finally {
			const task = await readTask();
			expect((await page.request.delete(`${taskUrl}?version=${task.version}`)).ok()).toBe(true);
		}
	});

	// contract-test: supporting surface=gui.web assertions=tasks.content.client-encrypted,tasks.surface.semantic-parity,workspace-shell.start.chat-visual-parity
	test('preserves a multiline workspace draft through collapse, expansion and encrypted submission', async ({ page }) => {
		test.setTimeout(120_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks']);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, () => {}, async () => {});
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
		const composer = page.getByTestId('task-workspace-composer');
		const input = page.getByTestId('task-workspace-input');
		await expect(composer).toBeVisible({ timeout: 30_000 });
		const restingHeight = (await composer.boundingBox())!.height;
		const headline = `Multiline workspace draft ${Date.now()}`;
		const draft = `${headline}\nInclude the weekly notes and follow up with the team.\nKeep these instructions together.`;
		let taskId: string | null = null;
		let tasksUrl = '';
		try {
			await input.fill(draft);
			await input.press('Escape');
			await expect(page.getByTestId('task-workspace-input-preview')).toHaveText(`${headline}…`);
			await expect(input).toHaveValue(draft);
			await expect.poll(async () => (await composer.boundingBox())!.height).toBe(restingHeight);
			await input.click();
			await page.getByTestId('task-workspace-input-expand').click();
			await expect(page.getByTestId('task-workspace-input-expand')).toHaveAttribute('aria-expanded', 'true');
			await expect(input).toHaveValue(draft);
			await input.press('Escape');
			const [response] = await Promise.all([
				page.waitForResponse((candidate) => candidate.request().method() === 'POST' && candidate.url().endsWith('/v1/user-tasks')),
				page.getByTestId('task-workspace-submit').click(),
			]);
			expect(response.ok()).toBe(true);
			tasksUrl = new URL('/v1/user-tasks', response.url()).toString();
			const payload = response.request().postDataJSON();
			expect(payload.encrypted_title).toEqual(expect.any(String));
			expect(JSON.stringify(payload)).not.toContain(headline);
			const card = taskCardIn(page.getByTestId('task-column-todo'), headline);
			await expect(card).toBeVisible({ timeout: 30_000 });
			taskId = await card.getAttribute('data-task-id');
			expect(taskId).toBeTruthy();
			await expect(input).toHaveValue('');
			await page.reload({ waitUntil: 'domcontentloaded' });
			await expect(card).toBeVisible({ timeout: 30_000 });
			await card.getByTestId('task-card-open').click();
			await expect(page.getByTestId('task-detail-title')).toHaveText(draft);
			await expect(page.getByTestId('workspace-detail-description')).toHaveText(draft);
		} finally {
			if (taskId) {
				const current = await page.request.get(`${tasksUrl}/${taskId}`);
				expect(current.ok()).toBe(true);
				const { task } = await current.json();
				expect((await page.request.delete(`${tasksUrl}/${taskId}?version=${task.version}`)).ok()).toBe(true);
			}
		}
	});

	// contract-test: supporting surface=gui.web assertions=tasks.content.client-encrypted,tasks.project-links.encrypted,tasks.surface.semantic-parity
	test('creates project-scoped tasks from the compact Figma composer', async ({ page }) => {
		test.setTimeout(150_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:projects', 'platform:tasks']);

		const log = createSignupLogger('PROJECT_TASK_COMPOSER');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'project-task-composer' });
		const projectName = `Task board project ${Date.now()}`;
		const taskTitle = `Project-scoped task ${Date.now()}`;

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);
		await page.goto(getE2EDebugUrl('/projects'), { waitUntil: 'domcontentloaded' });
		const projectResponse = page.waitForResponse(
			(response) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok()
		);
		await page.getByTestId('project-input-textarea').fill(projectName);
		await page.getByTestId('project-input-submit').click();
		await page.getByTestId('project-write-policy-apply-and-show').check();
		await page.getByTestId('project-write-policy-confirm').click();
		const projectId = (await (await projectResponse).json()).project.project_id;

		await page.getByTestId('project-tab-tasks').click();
		await expect(page.getByTestId('project-task-workspace-composer')).toBeVisible({ timeout: 30_000 });
		await expect(page.getByTestId('task-create-form')).toHaveCount(0);
		await expect(page.getByTestId('task-extract-card')).toHaveCount(0);
		const createResponse = page.waitForResponse(
			(response) => response.request().method() === 'POST' && response.url().endsWith('/v1/user-tasks') && response.ok()
		);
		await page.getByTestId('project-task-workspace-input').fill(taskTitle);
		await page.getByTestId('project-task-workspace-submit').click();
		const requestBody = JSON.parse((await createResponse).request().postData() ?? '{}');
		expect(requestBody.linked_project_ids).toEqual([projectId]);
		expect(JSON.stringify(requestBody)).not.toContain(taskTitle);
		await expect(page.getByTestId('task-board')).toContainText(taskTitle, { timeout: 30_000 });
	});

	// contract-test: direct surface=gui.web assertions=tasks.content.client-encrypted,tasks.lifecycle.visible,tasks.detail.embed-responsive,tasks.surface.semantic-parity
	test('renders daily task tips and manages encrypted tasks through Kanban actions', async ({ page }) => {
		test.slow();
		test.setTimeout(180_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks']);

		const log = createSignupLogger('TASKS_WEB_PARITY');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'tasks-web-parity' });
		const suffix = Date.now();
		const taskTitle = `Web parity task ${suffix}`;

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);
		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });

		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30_000 });
		const dailySuggestion = page.getByTestId('tasks-daily-inspiration-area');
		await expect(dailySuggestion).toBeVisible({ timeout: 15_000 });
		await expect(dailySuggestion.getByTestId('daily-inspiration-label')).toHaveText(/daily inspiration/i);
		await expect(dailySuggestion.getByTestId('daily-inspiration-phrase')).toContainText(/next action|tasks that matter|done looks like/i);
		await expect(page.getByTestId('tasks-figma-workspace')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('task-greeting')).toContainText(/hey .*!/i, { timeout: 15_000 });
		await expect(page.getByTestId('task-greeting')).toContainText(/what task is next\?/i);
		await expect(page.getByTestId('linked-plans-section')).toHaveCount(0);
		await expect(page.getByTestId('task-workspace-composer')).toBeVisible({ timeout: 15_000 });
		const suggestionText = (await dailySuggestion.getByTestId('daily-inspiration-phrase').textContent())?.trim();
		expect(suggestionText).toBeTruthy();
		await dailySuggestion.getByTestId('daily-inspiration-banner').click();
		await expect(page.getByTestId('task-workspace-input')).toHaveValue(suggestionText!);

		const suggestionBox = await dailySuggestion.boundingBox();
		const greetingBox = await page.getByTestId('task-greeting').boundingBox();
		const boardBox = await page.getByTestId('task-board').boundingBox();
		expect(suggestionBox, 'daily suggestion should be measurable').not.toBeNull();
		expect(greetingBox, 'task greeting should be measurable').not.toBeNull();
		expect(boardBox, 'task board should be measurable').not.toBeNull();
		expect(suggestionBox!.y + suggestionBox!.height).toBeLessThanOrEqual(greetingBox!.y + 8);
		expect(greetingBox!.y + greetingBox!.height).toBeLessThanOrEqual(boardBox!.y + 80);

		for (const status of TASK_STATUSES) {
			await expect(page.getByTestId(`task-column-${status}`)).toBeVisible({ timeout: 15_000 });
		}

		let createRequestPayload = '';
		const createResponse = page.waitForResponse((response) => {
			if (!response.url().includes('/v1/user-tasks') || response.request().method() !== 'POST') return false;
			createRequestPayload = response.request().postData() ?? '';
			return response.ok();
		});
		await page.getByTestId('task-workspace-input').fill(taskTitle);
		await page.getByTestId('task-workspace-submit').click();
		const createdResponse = await createResponse;

		expect(createRequestPayload).not.toContain(taskTitle);

		const todoCard = taskCardIn(page.getByTestId('task-column-todo'), taskTitle);
		await expect(todoCard).toBeVisible({ timeout: 30_000 });
		const createdTaskId = await todoCard.getAttribute('data-task-id');
		expect(createdTaskId, 'created task id should be available for reorder verification').toBeTruthy();
		const openTarget = todoCard.getByTestId('task-card-open');
		await openTarget.click();
		await expect(page.getByTestId('task-detail-fullscreen')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('task-detail-panel')).toBeVisible();
		await expect(page.getByTestId('task-board')).toBeVisible();
		const [workspaceBounds, detailBounds, composerBounds] = await Promise.all([
			page.getByTestId('tasks-figma-workspace').boundingBox(),
			page.getByTestId('task-detail-panel').boundingBox(),
			page.getByTestId('task-workspace-composer').boundingBox(),
		]);
		expect(workspaceBounds && detailBounds && composerBounds).toBeTruthy();
		expect(workspaceBounds!.x + workspaceBounds!.width).toBeLessThanOrEqual(detailBounds!.x + 2);
		expect(Math.abs(workspaceBounds!.y - detailBounds!.y)).toBeLessThanOrEqual(2);
		expect(detailBounds!.height).toBeGreaterThanOrEqual(workspaceBounds!.height - 2);
		expect(composerBounds!.x).toBeGreaterThanOrEqual(workspaceBounds!.x - 1);
		expect(composerBounds!.x + composerBounds!.width).toBeLessThanOrEqual(workspaceBounds!.x + workspaceBounds!.width + 1);
		await expect(page.getByTestId('embed-header-title')).toContainText(taskTitle);
		await page.getByTestId('task-detail-minimize').click();
		await expect(page.getByTestId('task-detail-fullscreen')).toHaveCount(0, { timeout: 2_000 });

		await openTarget.focus();
		await page.keyboard.press('Enter');
		await expect(page.getByTestId('task-detail-fullscreen')).toBeVisible({ timeout: 15_000 });
		await page.keyboard.press('Escape');
		await expect(page.getByTestId('task-detail-fullscreen')).toHaveCount(0, { timeout: 2_000 });
		await openTarget.focus();
		await page.keyboard.press('Space');
		await expect(page.getByTestId('task-detail-fullscreen')).toBeVisible({ timeout: 15_000 });
		await page.getByTestId('task-detail-minimize').click();
		await expect(page.getByTestId('task-detail-fullscreen')).toHaveCount(0, { timeout: 2_000 });
		const tasksApiUrl = new URL('/v1/user-tasks', createdResponse.url()).toString();
		const currentTasks = await page.request.get(tasksApiUrl);
		expect(currentTasks.ok()).toBe(true);
		const currentTask = (await currentTasks.json()).tasks.find((task: { task_id: string }) => task.task_id === createdTaskId);
		expect(currentTask).toBeTruthy();
		const concurrentMove = await page.request.post(`${tasksApiUrl}/reorder`, {
			data: { moves: [{ task_id: createdTaskId, version: currentTask.version, status: 'todo', position: currentTask.position }] },
		});
		expect(concurrentMove.ok()).toBe(true);

		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/v1/user-tasks/reorder') && response.status() === 409),
			page.waitForResponse((response) => {
				if (response.request().method() !== 'POST' || !response.url().includes('/v1/user-tasks/reorder') || !response.ok()) return false;
				const body = JSON.parse(response.request().postData() ?? '{}');
				return Array.isArray(body.moves) && body.moves.some((move) => move.task_id === createdTaskId && move.status === 'in_progress');
			}),
			todoCard.getByTestId('task-card-open').dragTo(page.getByTestId('task-column-in_progress'), {
				targetPosition: { x: 80, y: 20 },
			}),
		]);
		await expect(page.getByTestId('task-detail-fullscreen')).toHaveCount(0);
		const inProgressCard = taskCardIn(page.getByTestId('task-column-in_progress'), taskTitle);
		await expect(inProgressCard).toBeVisible({ timeout: 30_000 });
		await expect(page.getByTestId('task-column-in_progress').getByTestId('task-card').first()).toHaveAttribute('data-task-id', createdTaskId!);
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/block') && response.ok()),
			inProgressCard.getByTestId('task-card-open').dragTo(page.getByTestId('task-column-blocked'), {
				targetPosition: { x: 80, y: 20 },
			}),
		]);
		const blockedCard = taskCardIn(page.getByTestId('task-column-blocked'), taskTitle);
		await expect(blockedCard).toBeVisible({ timeout: 30_000 });

		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/unblock') && response.ok()),
			blockedCard.getByTestId('task-card-open').dragTo(page.getByTestId('task-column-todo'), {
				targetPosition: { x: 80, y: 20 },
			}),
		]);
		await expect(taskCardIn(page.getByTestId('task-column-todo'), taskTitle)).toBeVisible({ timeout: 30_000 });

		const reboundTodoCard = taskCardIn(page.getByTestId('task-column-todo'), taskTitle);
		await reboundTodoCard.getByTestId('task-actions-more').click();
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/complete') && response.ok()),
			reboundTodoCard.getByTestId('task-move-done').click(),
		]);
		const doneCard = taskCardIn(page.getByTestId('task-column-done'), taskTitle);
		await expect(doneCard).toBeVisible({ timeout: 30_000 });

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30_000 });
		const persistedDoneCard = taskCardIn(page.getByTestId('task-column-done'), taskTitle);
		await expect(persistedDoneCard).toBeVisible({ timeout: 30_000 });
		const taskId = await persistedDoneCard.getAttribute('data-task-id');
		expect(taskId, 'created task id should be available for direct-route verification').toBeTruthy();
		const secondTaskTitle = `Web parity route B ${suffix}`;
		const secondCreated = page.waitForResponse((response) =>
			response.request().method() === 'POST' && response.url().endsWith('/v1/user-tasks') && response.ok()
		);
		await page.getByTestId('task-workspace-input').fill(secondTaskTitle);
		await page.getByTestId('task-workspace-submit').click();
		const secondTaskId = (await (await secondCreated).json()).task.task_id as string;
		await expect(taskCardIn(page.getByTestId('task-column-todo'), secondTaskTitle)).toBeVisible({ timeout: 30_000 });
		await page.goto(getE2EDebugUrl('/#tasks'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30_000 });
		const boardToDetailListReads: string[] = [];
		const recordBoardToDetailListRead = (request: { method: () => string; url: () => string }) => {
			if (request.method() !== 'GET') return;
			const path = new URL(request.url()).pathname;
			if (path === '/v1/user-tasks' || path === '/v1/user-plans' || path === '/v1/projects') boardToDetailListReads.push(path);
		};
		page.on('request', recordBoardToDetailListRead);
		await page.evaluate((selectedTaskId: string) => {
			(window as typeof window & { taskDetailDocumentMarker?: string }).taskDetailDocumentMarker = 'board-to-task';
			window.location.hash = `task-id=${encodeURIComponent(selectedTaskId)}`;
		}, taskId!);
		await expect(page.getByTestId('task-detail-page')).toBeVisible({ timeout: 30_000 });
		await expect(page.getByTestId('task-detail-title')).toContainText(taskTitle);
		expect(await page.evaluate(() =>
			(window as typeof window & { taskDetailDocumentMarker?: string }).taskDetailDocumentMarker
		), 'the board must open Task A without reloading the document').toBe('board-to-task');
		page.off('request', recordBoardToDetailListRead);
		expect(boardToDetailListReads, 'board-to-detail navigation does not load full workspace lists').toEqual([]);
		await page.evaluate(() => { window.location.hash = 'tasks'; });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30_000 });
		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30_000 });
		const coldDetailReads: string[] = [];
		const recordColdDetailRead = (request: { method: () => string; url: () => string }) => {
			if (request.method() !== 'GET') return;
			const path = new URL(request.url()).pathname;
			if (path === '/v1/user-tasks' || path === '/v1/user-tasks/assignment-eligibility' ||
				path === `/v1/user-tasks/${taskId}` || path === `/v1/user-tasks/${secondTaskId}` ||
				path === '/v1/user-plans' || path === '/v1/projects') coldDetailReads.push(path);
		};
		page.on('request', recordColdDetailRead);
		await page.evaluate(() => {
			(window as typeof window & { taskDetailDocumentMarker?: string }).taskDetailDocumentMarker = 'before-cold-detail';
		});
		await page.goto(getE2EDebugUrl(`/?e2e-task-detail-cold=1#task-id=${encodeURIComponent(taskId!)}`), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('task-detail-page')).toBeVisible({ timeout: 30_000 });
		await expect(page.getByTestId('task-detail-content')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('task-detail-title')).toContainText(taskTitle);
		expect(await page.evaluate(() =>
			(window as typeof window & { taskDetailDocumentMarker?: string }).taskDetailDocumentMarker
		), 'cold Task A must load in a new document').toBeUndefined();
		await page.evaluate((nextTaskId: string) => {
			(window as typeof window & { taskDetailDocumentMarker?: string }).taskDetailDocumentMarker = 'same-document';
			window.location.hash = `task-id=${encodeURIComponent(nextTaskId)}`;
		}, secondTaskId);
		await expect(page).toHaveURL((url) => url.pathname === '/' &&
			new URLSearchParams(url.hash.slice(1)).get('task-id') === secondTaskId);
		await expect(page.getByTestId('task-detail-title')).toContainText(secondTaskTitle, { timeout: 30_000 });
		await expect(page.getByTestId('task-detail-title')).not.toContainText(taskTitle);
		expect(await page.evaluate(() =>
			(window as typeof window & { taskDetailDocumentMarker?: string }).taskDetailDocumentMarker
		), 'Task B must open by client navigation without reloading the document').toBe('same-document');
		page.off('request', recordColdDetailRead);
		expect(coldDetailReads.filter((path) => path === `/v1/user-tasks/${taskId}`), 'cold Task A reads its selected record once').toHaveLength(1);
		expect(coldDetailReads.filter((path) => path === `/v1/user-tasks/${secondTaskId}`), 'Task B reads its selected record once after the hash switch').toHaveLength(1);
		expect(coldDetailReads.filter((path) => path !== `/v1/user-tasks/${taskId}` && path !== `/v1/user-tasks/${secondTaskId}`), 'detail navigation does not load full task, Plan or Project lists').toEqual([]);
		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30_000 });
		const cardToDelete = taskCardIn(page.getByTestId('task-column-done'), taskTitle);
		await expect(cardToDelete).toBeVisible({ timeout: 30_000 });
		await cardToDelete.getByTestId('task-actions-more').click();

		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'DELETE' && response.url().includes('/v1/user-tasks/') && response.ok()),
			cardToDelete.getByTestId('task-delete-button').click(),
		]);
		await expect(page.getByTestId('task-board')).not.toContainText(taskTitle, { timeout: 30_000 });
		await page.getByTestId('chats-nav-link').click();
		await page.getByTestId('tasks-nav-link').click();
		await expect(page.getByTestId('task-board')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('task-board')).not.toContainText(taskTitle);
		const secondCardToDelete = taskCardIn(page.getByTestId('task-column-todo'), secondTaskTitle);
		await expect(secondCardToDelete).toBeVisible();
		await secondCardToDelete.getByTestId('task-actions-more').click();
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'DELETE' &&
				new URL(response.url()).pathname === `/v1/user-tasks/${secondTaskId}` && response.ok()),
			secondCardToDelete.getByTestId('task-delete-button').click(),
		]);
		await expect(page.getByTestId('task-board')).not.toContainText(secondTaskTitle);
	});

	// contract-test: supporting surface=gui.web assertions=tasks.lifecycle.visible,tasks.detail.embed-responsive,tasks.surface.semantic-parity
	test('keeps task actions reachable on a mobile viewport', async ({ page }) => {
		test.slow();
		test.setTimeout(150_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks']);

		const log = createSignupLogger('TASKS_WEB_MOBILE_PARITY');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'tasks-web-mobile-parity' });
		const taskTitle = `Mobile task ${Date.now()}`;

		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);
		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });

		await expect(page.getByTestId('tasks-daily-inspiration-area')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('tasks-daily-inspiration-area').getByTestId('daily-inspiration-cta-text')).toContainText('create task');
		await expect(page.getByTestId('task-board')).toBeVisible({ timeout: 30_000 });
		await page.getByTestId('task-workspace-input').fill(taskTitle);
		await page.getByTestId('task-workspace-submit').click();

		const todoCard = taskCardIn(page.getByTestId('task-column-todo'), taskTitle);
		await expect(todoCard).toBeVisible({ timeout: 30_000 });
		await todoCard.getByTestId('task-actions-more').click();
		await expect(todoCard.getByTestId('task-move-done')).toBeVisible({ timeout: 10_000 });
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/complete') && response.ok()),
			todoCard.getByTestId('task-move-done').click(),
		]);
		await expect(taskCardIn(page.getByTestId('task-column-done'), taskTitle)).toBeVisible({ timeout: 30_000 });
	});
});
