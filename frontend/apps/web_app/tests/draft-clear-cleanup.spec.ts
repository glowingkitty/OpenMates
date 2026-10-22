/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Clearing unsent drafts must finish empty-chat cleanup without deletion errors. */
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const {
	fillMessageEditor,
	focusMessageEditor,
	loginToTestAccount,
	startNewChat,
	waitForChatReady
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
import { installWebSocketFrameTracker } from './helpers/cross-client-draft-sync';

const { email, password, otpKey } = getTestAccount(1);

// contract-test: direct surface=gui.web assertions=drafts.draft-only.lifecycle,drafts.sync.version-authoritative
test('Clearing unsent drafts twice completes chat cleanup without errors or resurrection', async ({ page }: { page: any }) => {
	test.setTimeout(180_000);
	skipWithoutCredentials(test, email, password, otpKey);
	const frames = installWebSocketFrameTracker(page);
	await loginToTestAccount(page, console.log, undefined, { credentials: { email, password, otpKey } });
	await waitForChatReady(page, console.log);

	for (let cycle = 1; cycle <= 2; cycle++) {
		await startNewChat(page, console.log);
		const sidebarToggle = page.getByTestId('sidebar-toggle');
		if (await sidebarToggle.getAttribute('aria-expanded') === 'true') await sidebarToggle.click();
		const editor = page.locator('[data-testid="message-editor"]:visible').last();
		await expect(editor).toBeVisible();
		const frameStart = frames.length;
		const draftText = `Unsent draft cleanup ${cycle}`;
		await fillMessageEditor(page, editor, draftText);
		await expect.poll(() => frames.slice(frameStart).find((frame) =>
			frame.direction === 'received' && frame.type === 'draft_update_receipt' && frame.chatId
		)?.chatId, { timeout: 30_000 }).toBeTruthy();
		const chatId = frames.slice(frameStart).find((frame) =>
			frame.direction === 'received' && frame.type === 'draft_update_receipt' && frame.chatId
		)!.chatId!;
		await expect(editor).toContainText(draftText);

		// Exercise ordinary composer editing, without replacing the draft through a test hook.
		await focusMessageEditor(editor);
		await page.keyboard.press('Control+A');
		await page.keyboard.press('Backspace');
		await page.keyboard.press('Tab');
		await expect.poll(() => frames.slice(frameStart).some((frame) =>
			frame.direction === 'received' && frame.type === 'draft_delete_receipt' && frame.chatId === chatId
		), { timeout: 30_000 }).toBe(true);
		await expect.poll(() => frames.slice(frameStart).some((frame) =>
			frame.direction === 'received' && frame.type === 'chat_deleted' && frame.chatId === chatId
		), { timeout: 30_000 }).toBe(true);
		expect(frames.slice(frameStart).filter((frame) =>
			frame.direction === 'received' && frame.type === 'error' && frame.chatId === chatId
		)).toEqual([]);
		await expect(page.getByTestId('notification').filter({ hasText: /failed.*delet/i })).toHaveCount(0);
		await expect.poll(() => page.url()).not.toContain(`chat-id=${chatId}`);

		await page.reload();
		await waitForChatReady(page, console.log);
		await expect(page.locator('[data-testid="message-editor"]:visible').last()).not.toContainText(draftText);
		if (await sidebarToggle.getAttribute('aria-expanded') !== 'true') await sidebarToggle.click();
		await expect(page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`)).toHaveCount(0);
		await sidebarToggle.click();
		console.log(`Draft cleanup cycle ${cycle} completed without a deletion error or restored draft.`);
	}
});
