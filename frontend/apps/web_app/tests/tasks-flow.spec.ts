/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Tasks V1 web flow coverage.
 *
 * Verifies the deployed /tasks workspace can create encrypted user-facing tasks,
 * render them on the shared Kanban board, move them through touch-safe controls,
 * edit title and description through the real API, and preserve state after reload.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { createRunnerCodexEligibility } = require('./helpers/task-creator-e2e-helpers');

test.describe('Tasks V1 flow', () => {
	// contract-test: direct surface=gui.web assertions=tasks.content.client-encrypted,tasks.assignment.identity-separated,tasks.lifecycle.visible,tasks.surface.semantic-parity
	test('persists title and description edits and a Kanban status move', async ({ page }) => {
		test.setTimeout(120000);
		expect(getTestAccount().email, 'Runner test account credentials are required').toBeTruthy();
		await skipIfFeaturesDisabled(test, page, ['platform:tasks']);

		const taskTitle = `E2E task ${Date.now()}`;
		const taskDescription = 'Created by the Tasks V1 Playwright flow';
		const codexPrompt = `Create a new task ${taskTitle} Codex follow-up and assign it to Codex`;

        // Pairing performs the single real browser login before creating a receipt.
        // Logging in here first would make pairing wait for an already-hidden Login button.
        // A browser-created Task or copied shared-dev receipt cannot unlock it.
        await createRunnerCodexEligibility(page);
        const eligibilityResponse = page.waitForResponse((response) =>
            response.request().method() === 'GET' && response.url().includes('/v1/user-tasks?limit=1') && response.ok()
        );
		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
        expect((await (await eligibilityResponse).json()).eligible_external_ai,
            'Run the approved real CLI creator gate for this account before web proof').toContain('codex');
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });

		await page.getByTestId('task-title-input').fill(taskTitle);
		await page.getByTestId('task-description-input').fill(taskDescription);
		await page.getByTestId('task-create-button').click();

		const todoColumn = page.getByTestId('task-column-todo');
		const initialCard = todoColumn.getByTestId('task-card').filter({ hasText: taskTitle });
		await expect(initialCard).toBeVisible({ timeout: 30000 });
		await expect(initialCard).toContainText(taskDescription);
		const taskId = await initialCard.getAttribute('data-task-id');
		expect(taskId).toBeTruthy();
		// Keep the identity stable when the edited title changes the card text.
		const createdCard = todoColumn.locator(`[data-testid="task-card"][data-task-id="${taskId}"]`);
		const editedTitle = `${taskTitle} edited`;
		const editedDescription = 'Edited task description persisted through the real API';
		await createdCard.getByTestId('task-card-open').click();
		const detail = page.getByTestId('task-detail-fullscreen');
		await expect(detail).toBeVisible();

		// Cancelling either editor must restore its persisted value.
		for (const [field, original, displayId] of [
			['title', taskTitle, 'task-detail-title'],
			['description', taskDescription, 'workspace-detail-description'],
		]) {
			await detail.getByTestId(displayId).click();
			await detail.getByTestId(`workspace-detail-${field}-input`).fill('Discard this draft');
			await detail.getByTestId(`workspace-detail-${field}-undo`).click();
			await expect(detail.getByTestId(displayId)).toHaveText(original);
		}
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(createdCard).toBeVisible({ timeout: 30000 });
		await createdCard.getByTestId('task-card-open').click();
		await expect(detail.getByTestId('task-detail-title')).toHaveText(taskTitle);
		await expect(detail.getByTestId('workspace-detail-description')).toHaveText(taskDescription);

		for (const [field, value, displayId] of [
			['title', editedTitle, 'task-detail-title'],
			['description', editedDescription, 'workspace-detail-description'],
		]) {
			await detail.getByTestId(displayId).click();
			await detail.getByTestId(`workspace-detail-${field}-input`).fill(value);
			const [saved] = await Promise.all([
				page.waitForResponse((response) => response.request().method() === 'PATCH' &&
					new URL(response.url()).pathname === `/v1/user-tasks/${taskId}`),
				detail.getByTestId(`workspace-detail-${field}-save`).click(),
			]);
			expect(saved.status()).toBe(200);
			const patch = saved.request().postDataJSON();
			expect(patch[`encrypted_${field}`]).toEqual(expect.any(String));
			expect(patch[`encrypted_${field}`].length).toBeGreaterThan(0);
			expect(JSON.stringify(patch)).not.toContain(value);
			expect((await saved.json()).task.task_id).toBe(taskId);
			await expect(detail.getByTestId(displayId)).toHaveText(value);
		}

		// A full reload discards the detail's local state. Reopen the same Task
		// from the authenticated board and assert both decrypted saved values.
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(createdCard).toBeVisible({ timeout: 30000 });
		await expect(createdCard).toContainText(editedTitle);
		await expect(createdCard).toContainText(editedDescription);
		await createdCard.getByTestId('task-card-open').click();
		await expect(detail.getByTestId('task-detail-title')).toHaveText(editedTitle);
		await expect(detail.getByTestId('workspace-detail-description')).toHaveText(editedDescription);
		// Make a real competing edit in another authenticated page, leaving this
		// fullscreen on its older version. Do not mock the API conflict response.
		const concurrentTitle = `${editedTitle} from another page`;
		const staleDraft = `${editedTitle} stale draft`;
		const otherPage = await page.context().newPage();
		try {
			await otherPage.goto(getE2EDebugUrl(`/tasks/${taskId}`), { waitUntil: 'domcontentloaded' });
			await expect(otherPage.getByTestId('task-detail-title')).toHaveText(editedTitle);
			await otherPage.getByTestId('task-detail-title').click();
			await otherPage.getByTestId('workspace-detail-title-input').fill(concurrentTitle);
			const [competingSave] = await Promise.all([
				otherPage.waitForResponse((response) => response.request().method() === 'PATCH' &&
					new URL(response.url()).pathname === `/v1/user-tasks/${taskId}`),
				otherPage.getByTestId('workspace-detail-title-save').click(),
			]);
			expect(competingSave.status()).toBe(200);
			await expect(otherPage.getByTestId('task-detail-title')).toHaveText(concurrentTitle);
			await detail.getByTestId('task-detail-title').click();
			await detail.getByTestId('workspace-detail-title-input').fill(staleDraft);
			const [conflict] = await Promise.all([
				page.waitForResponse((response) => response.request().method() === 'PATCH' &&
					new URL(response.url()).pathname === `/v1/user-tasks/${taskId}`),
				detail.getByTestId('workspace-detail-title-save').click(),
			]);
			expect(conflict.status()).toBe(409);
			await expect(detail.getByTestId('workspace-detail-title-error')).toBeVisible();
			await expect(detail.getByTestId('workspace-detail-title-input')).toHaveValue(staleDraft);
		} finally {
			await otherPage.close();
		}
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(createdCard).toBeVisible({ timeout: 30000 });
		await createdCard.getByTestId('task-card-open').click();
		await expect(detail.getByTestId('task-detail-title')).toHaveText(concurrentTitle);
		await expect(detail.getByTestId('workspace-detail-description')).toHaveText(editedDescription);

		// Exercise the human/unassigned selector without launching an AI worker.
		for (const assignment of ['unassigned', 'user']) {
			const [assigned] = await Promise.all([
				page.waitForResponse((response) => response.request().method() === 'PATCH' &&
					new URL(response.url()).pathname === `/v1/user-tasks/${taskId}`),
				detail.getByTestId('task-detail-assignee-select').selectOption(assignment),
			]);
			expect(assigned.status()).toBe(200);
			expect((await assigned.json()).task.assignee_type).toBe(assignment);
			await expect(detail.getByTestId('task-detail-assignee-select')).toHaveValue(assignment);
		}
		for (const status of ['in_progress', 'todo']) {
			const [moved] = await Promise.all([
				page.waitForResponse((response) => response.request().method() === 'POST' &&
					new URL(response.url()).pathname === '/v1/user-tasks/reorder'),
				detail.getByTestId('task-detail-status-select').selectOption(status),
			]);
			expect(moved.status()).toBe(200);
			expect((await moved.json()).tasks.find((task: { task_id: string }) => task.task_id === taskId).status).toBe(status);
			await expect(detail.getByTestId('task-detail-status-select')).toHaveValue(status);
		}
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(createdCard).toBeVisible({ timeout: 30000 });
		await createdCard.getByTestId('task-card-open').click();
		await expect(detail.getByTestId('task-detail-title')).toHaveText(concurrentTitle);
		await expect(detail.getByTestId('workspace-detail-description')).toHaveText(editedDescription);
		await expect(detail.getByTestId('task-detail-assignee-select')).toHaveValue('user');
		await expect(detail.getByTestId('task-detail-status-select')).toHaveValue('todo');
		await detail.getByTestId('task-detail-minimize').click();
		await expect(detail).not.toBeVisible();

		const codexCreateResponsePromise = page.waitForResponse((response) =>
			response.request().method() === 'POST' &&
			response.url().endsWith('/v1/user-tasks') &&
			response.ok()
		);
		await page.getByTestId('task-workspace-input').fill(codexPrompt);
		await page.getByTestId('task-workspace-submit').click();
		const codexCreateResponse = await codexCreateResponsePromise;
		const codexCreateBody = JSON.parse(codexCreateResponse.request().postData() ?? '{}');
		expect(codexCreateBody.assignee_type).toBe('external_ai');
		expect(codexCreateBody.assignee_identity).toBe('codex');
		expect(JSON.stringify(codexCreateBody)).not.toContain(codexPrompt);
		const codexCard = todoColumn.getByTestId('task-card').filter({ hasText: codexPrompt });
		await expect(codexCard).toBeVisible({ timeout: 30000 });
		await expect(codexCard).toContainText('Codex');

		await Promise.all([
			page.waitForResponse((response) =>
				response.request().method() === 'POST' &&
				response.url().includes('/v1/user-tasks/') &&
				response.url().endsWith('/complete') &&
				response.ok()
			),
			createdCard.getByTestId('task-move-done').click(),
		]);

		const doneColumn = page.getByTestId('task-column-done');
		await expect(doneColumn.getByTestId('task-card').filter({ hasText: editedTitle })).toBeVisible({ timeout: 30000 });

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('task-column-done').getByTestId('task-card').filter({ hasText: editedTitle })).toBeVisible({ timeout: 30000 });
	});
});
