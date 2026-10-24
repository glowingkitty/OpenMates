/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/** Autosave, workspace resume and clearing preserve the unsent draft lifecycle. */
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const {
	fillMessageEditor,
	focusMessageEditor,
	loginToTestAccount,
	startNewChat,
	setChatSidebarOpen,
	waitForChatReady
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
import { clearBrowserClientState, installWebSocketFrameTracker } from './helpers/cross-client-draft-sync';

const { email, password, otpKey } = getTestAccount(1);

// contract-test: direct surface=gui.web assertions=drafts.draft-only.lifecycle,drafts.sync.version-authoritative,message-input.drafts.preview-persistence,message-input.focus.workspace-suppression
test('Clearing unsent drafts twice completes chat cleanup without errors or resurrection', async ({ page }: { page: any }) => {
	test.setTimeout(240_000);
	page.on('console', (message: any) => {
		if (message.text().startsWith('[ActiveChat] Workspace reset focus:')) console.log(message.text());
	});
	skipWithoutCredentials(test, email, password, otpKey);
	await page.setViewportSize({ width: 1280, height: 900 });
	const frames = installWebSocketFrameTracker(page);
	await loginToTestAccount(page, console.log, undefined, { credentials: { email, password, otpKey } });
	await waitForChatReady(page, console.log);

	for (let cycle = 1; cycle <= 2; cycle++) {
		await startNewChat(page, console.log);
		await setChatSidebarOpen(page, false, console.log);
		const editor = page.locator('[data-testid="message-editor"]:visible').last();
		await expect(editor).toBeVisible();
		const editable = editor.locator('.ProseMirror');
		const field = page.getByTestId('message-field');
		const welcomeNode = await page.getByTestId('welcome-content').elementHandle();
		const editorNode = await editable.elementHandle();
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
		await expect(field).toHaveAttribute('data-focused', 'true');
		await expect(editable).toBeFocused();
		expect(await welcomeNode!.evaluate((node: HTMLElement) => node.isConnected)).toBe(true);
		expect(await editorNode!.evaluate((node: HTMLElement) => node.isConnected)).toBe(true);

		await page.getByTestId('input-dismiss-button').click();
		await expect(field).toHaveAttribute('data-focused', 'false');
		await expect(editable).toBeEmpty();
		await expect(page.getByTestId('welcome-content')).toBeVisible();
		const card = page.locator(`[data-testid="resume-chat-draft-card"][data-chat-id="${chatId}"]`);
		await expect(card).toContainText(draftText);
		await expect(page.getByTestId('message-user')).toHaveCount(0);
		await card.click();
		await expect(field).toHaveAttribute('data-focused', 'true');
		await expect(editable).toContainText(draftText);
		await expect(editable).toBeFocused();

		// Exercise ordinary composer editing, without replacing the draft through a test hook.
		await focusMessageEditor(editor);
		await page.keyboard.press('Control+A');
		await page.keyboard.press('Backspace');
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
		await expect(field).toHaveAttribute('data-focused', 'true');
		await expect(editable).toBeFocused();
		await expect(editable).toBeEmpty();

		if (cycle === 1) {
			await clearBrowserClientState(page, page.url());
			await loginToTestAccount(page, console.log, undefined, { credentials: { email, password, otpKey } });
		} else {
			await page.reload();
		}
		await waitForChatReady(page, console.log);
		await expect(page.locator('[data-testid="message-editor"]:visible').last()).not.toContainText(draftText);
		await setChatSidebarOpen(page, true, console.log);
		await expect(page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`)).toHaveCount(0);
		await setChatSidebarOpen(page, false, console.log);
		console.log(`Draft cleanup cycle ${cycle} completed without a deletion error or restored draft.`);
	}
});
