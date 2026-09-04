/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
// contract-test-file: tooling
/**
 * Shared Playwright helpers for selecting composer mentions.
 *
 * Keeps mention entry deterministic when late chat notifications interrupt
 * editor focus during authenticated end-to-end flows.
 */
export {};

const { expect } = require('@playwright/test');
const { dismissVisibleNotifications } = require('./embed-test-helpers');

export async function openMentionDropdown(page: any, query = ''): Promise<{ editor: any; dropdown: any }> {
	const editor = page.getByTestId('message-field').last().getByTestId('message-editor');
	const dropdown = page.getByTestId('mention-dropdown');
	const mentionQuery = `@${query}`;

	await expect(async () => {
		await dismissVisibleNotifications(page);
		await editor.click();
		await page.keyboard.press('Control+A');
		await page.keyboard.press('Backspace');
		await page.keyboard.type(mentionQuery, { delay: 50 });
		await expect(editor).toContainText(mentionQuery, { timeout: 2_000 });
		await expect(dropdown).toBeVisible({ timeout: 2_000 });
	}).toPass({ timeout: 15_000 });

	return { editor, dropdown };
}

export async function selectMentionResult(page: any, query: string, resultText: string): Promise<void> {
	const { dropdown } = await openMentionDropdown(page, query);

	const result = dropdown.getByTestId('mention-result').filter({ hasText: resultText }).first();
	await expect(result).toBeVisible({ timeout: 10_000 });
	await result.click();
	await expect(dropdown).not.toBeVisible({ timeout: 5_000 });
}
