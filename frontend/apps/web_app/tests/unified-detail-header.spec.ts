/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Red interaction contract for editable fields in the shared detail header.
 *
 * The spec owns one Task record and deletes that exact record. It verifies
 * title and description editing semantics without sharing mutable fixtures with
 * another Playwright spec or depending on concurrent test execution.
 */

import type { Locator } from '@playwright/test';

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

interface ClientRectSnapshot {
	left: number;
	right: number;
	top: number;
	bottom: number;
	width: number;
	height: number;
}

async function getClientRect(locator: Locator): Promise<ClientRectSnapshot> {
	return locator.evaluate((element) => {
		const rect = element.getBoundingClientRect();
		return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height };
	});
}

async function getTextRects(locator: Locator): Promise<ClientRectSnapshot[]> {
	return locator.evaluate((element) => {
		const textNode = Array.from(element.childNodes).find((node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim());
		if (!textNode) return [];

		const range = document.createRange();
		range.selectNodeContents(textNode);
		const rects = Array.from(range.getClientRects())
			.map((rect) => ({ left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height }))
			.filter((rect) => rect.width > 0 && rect.height > 0);
		range.detach();
		return rects;
	});
}

function rectsOverlap(a: ClientRectSnapshot, b: ClientRectSnapshot): boolean {
	return Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) > 0 && Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)) > 0;
}

test.describe('Unified detail header editing', () => {
	test('Task title and description expose hints, save, and undo semantics', async ({ page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks']);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const suffix = `${Date.now()}-${test.info().workerIndex}`;
		const originalTitle = `Unified header task ${suffix}`;
		const originalDescription = `Persisted description ${suffix}`;
		let taskId = '';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		try {
			await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });
			await page.getByTestId('task-title-input').fill(originalTitle);
			await page.getByTestId('task-description-input').fill(originalDescription);
			const created = page.waitForResponse(
				(response) => response.request().method() === 'POST' && response.url().endsWith('/v1/user-tasks') && response.ok()
			);
			await page.getByTestId('task-create-button').click();
			taskId = (await (await created).json()).task.task_id;

			await page.goto(getE2EDebugUrl(`/tasks/${taskId}`), { waitUntil: 'domcontentloaded' });
			const header = page.getByTestId('workspace-detail-header');
			await expect(header).toBeVisible({ timeout: 30000 });
			await expect(header).toHaveAttribute('data-header-system', 'workspace-detail');

			const titleField = header.getByTestId('workspace-detail-title-field');
			await titleField.hover();
			const titleEditButton = titleField.getByTestId('workspace-detail-title-edit');
			await expect(titleEditButton).toBeVisible();
			const titleTextRects = await getTextRects(header.getByTestId('workspace-detail-title'));
			const titleEditRect = await getClientRect(titleEditButton);
			expect(titleEditRect.width).toBeLessThanOrEqual(40);
			expect(titleEditRect.height).toBeLessThanOrEqual(40);
			expect(
				titleTextRects.some((rect) => rectsOverlap(rect, titleEditRect)),
				'Title edit hover button must not overlap the rendered title text.'
			).toBe(false);
			await titleEditButton.focus();
			await titleEditButton.press('Enter');

			const titleInput = titleField.getByTestId('workspace-detail-title-input');
			await expect(titleInput).toBeVisible();
			await expect(titleField.getByTestId('workspace-detail-title-hint')).toBeVisible();
			await titleInput.fill(`Unsaved title ${suffix}`);
			await expect(titleField.getByTestId('workspace-detail-title-save')).toBeVisible();
			await expect(titleField.getByTestId('workspace-detail-title-undo')).toBeVisible();
			await titleField.getByTestId('workspace-detail-title-undo').click();
			await expect(header.getByTestId('workspace-detail-title')).toHaveText(originalTitle);

			await header.getByTestId('workspace-detail-title').click();
			await titleField.getByTestId('workspace-detail-title-input').fill(`Saved title ${suffix}`);
			const titleSave = page.waitForResponse(
				(response) => response.request().method() === 'PATCH' && response.url().endsWith(`/v1/user-tasks/${taskId}`) && response.ok()
			);
			await titleField.getByTestId('workspace-detail-title-input').press('Enter');
			await titleSave;
			await expect(header.getByTestId('workspace-detail-title')).toHaveText(`Saved title ${suffix}`);

			const descriptionField = header.getByTestId('workspace-detail-description-field');
			await descriptionField.getByTestId('workspace-detail-description').click();
			const descriptionInput = descriptionField.getByTestId('workspace-detail-description-input');
			await expect(descriptionInput).toBeVisible();
			await expect(descriptionField.getByTestId('workspace-detail-description-hint')).toBeVisible();
			await descriptionInput.fill(`Saved description ${suffix}`);
			await expect(descriptionField.getByTestId('workspace-detail-description-save')).toBeVisible();
			await expect(descriptionField.getByTestId('workspace-detail-description-undo')).toBeVisible();
			const descriptionSave = page.waitForResponse(
				(response) => response.request().method() === 'PATCH' && response.url().endsWith(`/v1/user-tasks/${taskId}`) && response.ok()
			);
			await descriptionField.getByTestId('workspace-detail-description-save').click();
			await descriptionSave;
			await expect(descriptionField.getByTestId('workspace-detail-description')).toHaveText(`Saved description ${suffix}`);

			await descriptionField.getByTestId('workspace-detail-description').click();
			await descriptionField.getByTestId('workspace-detail-description-input').fill(`Keyboard description ${suffix}`);
			const keyboardSave = page.waitForResponse(
				(response) => response.request().method() === 'PATCH' && response.url().endsWith(`/v1/user-tasks/${taskId}`) && response.ok()
			);
			await descriptionField.getByTestId('workspace-detail-description-input').press('Control+Enter');
			await keyboardSave;
			await expect(descriptionField.getByTestId('workspace-detail-description')).toHaveText(`Keyboard description ${suffix}`);
		} finally {
			if (taskId) {
				await page.request.delete(`${apiUrl}/v1/user-tasks/${encodeURIComponent(taskId)}`).catch(() => null);
			}
		}
	});
});
