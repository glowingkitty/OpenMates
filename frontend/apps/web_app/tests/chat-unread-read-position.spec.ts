/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Chat unread state follows the reader's position in the reply.
 *
 * A long mocked reply (fixture `unread_long_reply`, ending in a unique last-line
 * marker) is read only partially: the chat must stay unread in the sidebar row
 * and on its "Continue where you left off" card, survive reload and re-open,
 * count a follow-up reply once, and clear only once the last line is visible.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	setChatSidebarOpen,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const DEVICES = ['web-laptop'];

const UNREAD_PROOF = defineVideoProof({
	id: 'chat-unread-read-position',
	title: 'Unread until the last line is seen',
	surface: 'web',
	devices: DEVICES,
	domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'partial', text: 'Only the start of a long reply is on screen, so the open chat still shows one unread reply.', checkpoint: 'partial-read', devices: DEVICES },
		{ id: 'closed', text: 'After closing the chat, its sidebar row and its Continue card both show the unread counter.', checkpoint: 'closed-unread', devices: DEVICES },
		{ id: 'follow-up', text: 'Answering counts the earlier reply as read, so the new reply makes the counter exactly one.', checkpoint: 'follow-up-once', devices: DEVICES },
		{ id: 'read', text: 'Scrolling to the last line marks the chat read and both counters disappear.', checkpoint: 'read', devices: DEVICES }
	],
	assertions: [
		{ id: 'open-chat-unread', checkpoint: 'partial-read', visual: 'The sidebar row of the open chat shows the counter 1 while the last line is off screen.', devices: DEVICES },
		{ id: 'continue-card-unread', checkpoint: 'closed-unread', visual: 'The Continue card and sidebar row of the closed chat both show 1.', devices: DEVICES },
		{ id: 'follow-up-counts-once', checkpoint: 'follow-up-once', visual: 'After the follow-up reply the counter reads 1, not 2.', devices: DEVICES },
		{ id: 'read-clears-counters', checkpoint: 'read', visual: 'No unread counter remains on the sidebar row or the Continue card.', devices: DEVICES }
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const LONG_REPLY_FIXTURE = 'unread_long_reply';
const LONG_REPLY_LAST_LINE = 'UNREAD_LONG_REPLY_LAST_LINE';

async function sendLongReplyMessage(page: any, message: string, expectedReplies: number, log: (msg: string) => void): Promise<void> {
	await sendMessage(page, withMockMarker(message, LONG_REPLY_FIXTURE, 'instant'), log);
	await expect(page.getByTestId('message-assistant')).toHaveCount(expectedReplies, { timeout: 60000 });
	await expect(page.getByText(LONG_REPLY_LAST_LINE)).toHaveCount(expectedReplies, { timeout: 60000 });
	await expect(page.getByTestId('typing-indicator')).toHaveCount(0, { timeout: 60000 });
	await expect(page.locator('[data-action="stop-generation"]')).toHaveCount(0, { timeout: 60000 });
}

/** Scroll so only the first lines of the newest reply are on screen. */
async function showOnlyStartOfLatestReply(page: any): Promise<void> {
	const history = page.getByTestId('chat-history-container');
	await expect(history).toHaveAttribute('data-scroll-state', 'ready', { timeout: 20000 });
	await history.evaluate((container: HTMLElement) => {
		const messages = container.querySelectorAll<HTMLElement>('[data-message-id]');
		const latest = messages[messages.length - 1];
		if (!latest) throw new Error('No rendered message to scroll to');
		container.scrollTop += latest.getBoundingClientRect().top - container.getBoundingClientRect().top;
	});
	await expect(page.getByText(LONG_REPLY_LAST_LINE).last()).not.toBeInViewport();
}

function sidebarRow(page: any, chatId: string): any {
	return page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`);
}

function continueCardBadge(page: any, chatId: string): any {
	return page
		.getByTestId('recent-chats-scroll-container')
		.locator(`[data-chat-id="${chatId}"]`)
		.getByTestId('continue-card-unread-badge');
}

async function openChatsStartScreen(page: any): Promise<void> {
	await page.getByTestId('new-chat-button').click();
	await expect(page.getByTestId('recent-chats-scroll-container').first()).toBeVisible({ timeout: 20000 });
}

// contract-test: direct surface=gui.web assertions=chat-unread.reply.read-at-last-line,chat-unread.followup.implies-read,chat-unread.surfaces.sidebar-and-continue,chat-unread.persistence.cross-device
test('keeps a partially read reply unread in the sidebar and continue card until its last line is seen', async ({
	page
}: {
	page: any;
}, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const proof = createVideoProofRuntime(UNREAD_PROOF, {
		device: PROOF_DEVICE,
		attach: testInfo.attach.bind(testInfo),
		captureFrame: () => page.screenshot({ type: 'png' })
	});
	const log = createSignupLogger('CHAT_UNREAD_READ_POSITION');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);
	// Read transitions are logged by the app; keep them in the spec output.
	page.on('console', (message: any) => {
		if (message.text().includes('[ChatRead]')) log(message.text());
	});

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	await sendLongReplyMessage(page, 'Explain step by step how rainbows form.', 1, log);
	await showOnlyStartOfLatestReply(page);
	const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
	if (!chatId) throw new Error('Chat URL is missing chat-id');
	await screenshot(page, 'reply-start-only');

	// Only the first lines were seen: the open chat is still unread.
	await setChatSidebarOpen(page, true, log);
	const sidebarBadge = sidebarRow(page, chatId).getByTestId('unread-badge');
	await proof.assert('open-chat-unread', async () => {
		await expect(sidebarBadge).toHaveText('1', { timeout: 20000 });
	});
	await proof.checkpoint('partial-read');

	// Closing the chat before reading to the end keeps it unread on both surfaces.
	await openChatsStartScreen(page);
	await proof.assert('continue-card-unread', async () => {
		await expect(continueCardBadge(page, chatId)).toHaveText('1', { timeout: 20000 });
		await expect(sidebarBadge).toHaveText('1');
	});
	await proof.checkpoint('closed-unread');
	await screenshot(page, 'unread-on-continue-card-and-sidebar');

	// Persisted by the server: survives a reload.
	await page.reload();
	await setChatSidebarOpen(page, true, log);
	await expect(sidebarBadge).toHaveText('1', { timeout: 30000 });
	await expect(continueCardBadge(page, chatId)).toHaveText('1', { timeout: 30000 });

	// Re-opening alone does not mark it read.
	await sidebarRow(page, chatId).click();
	await expect(page).toHaveURL(new RegExp(`chat-id=${chatId}`), { timeout: 15000 });
	await showOnlyStartOfLatestReply(page);
	await expect(sidebarBadge).toHaveText('1');

	// Answering implies the earlier reply was read: the follow-up counts once.
	await sendLongReplyMessage(page, 'Now explain double rainbows step by step.', 2, log);
	await showOnlyStartOfLatestReply(page);
	await proof.assert('follow-up-counts-once', async () => {
		await expect(sidebarBadge).toHaveText('1', { timeout: 20000 });
	});
	await proof.checkpoint('follow-up-once');

	// Seeing the last line marks it read on both surfaces.
	const lastLine = page.getByText(LONG_REPLY_LAST_LINE).last();
	await lastLine.scrollIntoViewIfNeeded();
	await expect(lastLine).toBeInViewport();
	await proof.assert('read-clears-counters', async () => {
		await expect(sidebarBadge).toHaveCount(0, { timeout: 20000 });
		await openChatsStartScreen(page);
		await expect(continueCardBadge(page, chatId)).toHaveCount(0);
	});
	await proof.checkpoint('read');

	await assertNoMissingTranslations(page);
	await sidebarRow(page, chatId).click();
	await expect(page).toHaveURL(new RegExp(`chat-id=${chatId}`), { timeout: 15000 });
	await deleteActiveChat(page, log, screenshot, 'cleanup');
});
