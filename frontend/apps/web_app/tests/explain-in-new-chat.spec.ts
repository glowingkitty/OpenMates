/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Explain in new chat E2E coverage.
 *
 * Verifies the selected-assistant-text workflow: selecting text exposes the
 * Explain in new chat option in the existing highlight context menu, starts a
 * forked background chat, shows an open action notification, and auto-sends the
 * explanation prompt in the new chat without appending it to the source transcript.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	waitForAssistantMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const SELECTORS = {
	userMessageContent: '[data-testid="user-message-content"]',
	mateMessageContent: '[data-testid="mate-message-content"]',
	selectionToolbar: '[data-testid="message-selection-toolbar"]',
	selectionToolbarExplain: '[data-testid="message-selection-explain-new-chat"]',
	contextMenuExplain: '[data-testid="chat-context-explain-new-chat"]',
	notification: '[data-testid="notification"]',
	notificationAction: '[data-testid="notification-action"]',
	messageWrapper: '[data-testid="message-wrapper"]'
};

async function selectInsideMessage(
	page: any,
	messageSelector: string,
	needle: string
): Promise<{ selected: boolean; rect: { x: number; y: number; width: number; height: number } | null }> {
	return page.evaluate(
		({ sel, n }: { sel: string; n: string }) => {
			const container = document.querySelector(sel) as HTMLElement | null;
			if (!container) return { selected: false, rect: null };
			container.scrollIntoView({ block: 'center', inline: 'nearest' });

			const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
			let node: Node | null = walker.nextNode();
			while (node) {
				const textNode = node as Text;
				const idx = (textNode.nodeValue ?? '').indexOf(n);
				if (idx !== -1) {
					const range = document.createRange();
					range.setStart(textNode, idx);
					range.setEnd(textNode, idx + n.length);
					const selection = window.getSelection();
					if (!selection) return { selected: false, rect: null };
					selection.removeAllRanges();
					selection.addRange(range);
					const r = range.getBoundingClientRect();
					return { selected: true, rect: { x: r.x, y: r.y, width: r.width, height: r.height } };
				}
				node = walker.nextNode();
			}
			return { selected: false, rect: null };
		},
		{ sel: messageSelector, n: needle }
	);
}

test('explains selected assistant text in a background new chat', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(300_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('EXPLAIN_NEW_CHAT');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'explain-new-chat' });
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const seedPrompt = withMockMarker(
		'Reply in one short sentence that includes the exact phrase: vector database.',
		'explain_in_new_chat_seed'
	);
	await sendMessage(page, seedPrompt, log, screenshot, 'seed');
	await waitForAssistantMessage(page, {
		which: 'last',
		contains: 'vector database',
		timeout: 90_000,
		logCheckpoint: log
	});

	const sourceUrl = page.url();
	const sourceChatTextBefore = await page.getByTestId('message-wrapper').allTextContents();
	expect(sourceChatTextBefore.join('\n')).toContain('vector database');

	log('Verifying user-message selections do not expose Explain in new chat.');
	const userSelection = await selectInsideMessage(page, SELECTORS.userMessageContent, 'vector database');
	expect(userSelection.selected).toBe(true);
	expect(userSelection.rect).not.toBeNull();
	await page.mouse.click(
		userSelection.rect!.x + userSelection.rect!.width / 2,
		userSelection.rect!.y + userSelection.rect!.height / 2,
		{ button: 'right' }
	);
	await expect(page.locator(SELECTORS.contextMenuExplain)).toHaveCount(0);
	await page.mouse.click(10, 10);

	log('Selecting assistant phrase and clicking Explain in new chat from the highlight menu.');
	const assistantSelection = await selectInsideMessage(page, SELECTORS.mateMessageContent, 'vector database');
	expect(assistantSelection.selected).toBe(true);
	expect(assistantSelection.rect).not.toBeNull();
	await page.mouse.click(
		assistantSelection.rect!.x + assistantSelection.rect!.width / 2,
		assistantSelection.rect!.y + assistantSelection.rect!.height / 2,
		{ button: 'right' }
	);
	const explainButton = page.locator(SELECTORS.contextMenuExplain);
	await expect(explainButton).toBeVisible({ timeout: 5000 });
	await screenshot(page, 'explain-action-visible');
	await explainButton.click();

	await expect(page).toHaveURL(sourceUrl, { timeout: 5000 });
	await expect(page.locator(SELECTORS.notification).filter({ hasText: /background/i })).toBeVisible({ timeout: 20_000 });
	const sourceChatTextAfter = await page.getByTestId('message-wrapper').allTextContents();
	expect(sourceChatTextAfter.join('\n')).not.toContain('Tell me more about: vector database');

	log('Opening background explanation chat from notification action.');
	const openAction = page.locator(SELECTORS.notificationAction).filter({ hasText: /open/i }).first();
	await expect(openAction).toBeVisible({ timeout: 10_000 });
	await openAction.click();
	await expect(page).not.toHaveURL(sourceUrl, { timeout: 15_000 });

	const promptText = 'Tell me more about: vector database';
	await expect(page.locator(SELECTORS.messageWrapper).filter({ hasText: promptText })).toBeVisible({ timeout: 30_000 });
	await waitForAssistantMessage(page, { timeout: 120_000, logCheckpoint: log });
	await screenshot(page, 'background-explanation-chat-opened');

	await deleteActiveChat(page, log, screenshot, 'cleanup-explanation-chat');
	await page.goto(sourceUrl);
	await page.waitForTimeout(1500);
	await deleteActiveChat(page, log, screenshot, 'cleanup-source-chat');
});
