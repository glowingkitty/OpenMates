/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

test.afterEach(async ({ page: _page }: { page: any }, testInfo: any) => {
	void _page;
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');

const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

/**
 * Message highlights E2E — covers the full annotation lifecycle for the
 * yellow-highlight + comment feature (OPE-xxx):
 *
 *   1. Send a user message (no AI call required for highlighting — we only
 *      need a message in the chat to select text inside).
 *   2. Select some text inside the user message, open the context menu, click
 *      "Highlight" → verify the yellow box renders and ChatHeader pill shows
 *      "1 highlight".
 *   3. Use "Highlight & comment" on a different selection → popover opens in
 *      edit mode → save a comment → pill updates to "N highlights, 1 comment".
 *   4. Click the existing highlight → popover shows the saved comment +
 *      author + Edit/Delete actions (we're the author).
 *   5. Delete the highlight via the popover → count decrements.
 *
 * Uses no AI inference — purely UI + client-encrypted round-trip through the
 * WebSocket + Directus persistence layer.
 *
 * REQUIRED ENV VARS (same as other chat specs):
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const SELECTORS = {
	userMessageContent: '[data-testid="user-message-content"]',
	mateMessageContent: '[data-testid="mate-message-content"]',
	messageContextHighlight: '[data-testid="chat-context-highlight"]',
	messageContextHighlightAndComment: '[data-testid="chat-context-highlight-and-comment"]',
	highlightBox: '[data-testid="message-highlight-box"]',
	headerHighlightCount: '[data-testid="chat-header-highlight-count"]',
	commentPopover: '[data-testid="highlight-comment-popover"]',
	commentInput: '[data-testid="highlight-comment-input"]',
	commentSave: '[data-testid="highlight-comment-save"]',
	commentDelete: '[data-testid="highlight-comment-delete"]',
	commentEdit: '[data-testid="highlight-comment-edit"]',
	commentText: '[data-testid="highlight-comment-text"]'
};

function setupPageListeners(page: any): void {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});
}

/**
 * Select text inside a rendered message AND atomically dispatch a contextmenu
 * event on the message element, all from within a single page.evaluate call so
 * the selection is still live when the event fires. Returns { selected, rect }
 * where `selected` is true when the substring was found.
 *
 * This is more reliable than the physical-mouse approach because we're not
 * racing against layout shifts from streaming AI responses.
 */
async function selectAndOpenContextMenu(
	page: any,
	messageSelector: string,
	textToSelect: string
): Promise<{ selected: boolean; rect: { x: number; y: number; width: number; height: number } | null }> {
	return page.evaluate(
		({ sel, needle }: { sel: string; needle: string }) => {
			const container = document.querySelector(sel) as HTMLElement | null;
			if (!container) return { selected: false, rect: null };

			const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
			let node: Node | null = walker.nextNode();
			while (node) {
				const t = node as Text;
				const nodeText = t.nodeValue ?? '';
				const idx = nodeText.indexOf(needle);
				if (idx !== -1) {
					const range = document.createRange();
					range.setStart(t, idx);
					range.setEnd(t, idx + needle.length);
					const selection = window.getSelection();
					if (!selection) return { selected: false, rect: null };
					selection.removeAllRanges();
					selection.addRange(range);
					const r = range.getBoundingClientRect();
					// Immediately dispatch contextmenu — the selection is still live.
					const ev = new MouseEvent('contextmenu', {
						bubbles: true,
						cancelable: true,
						view: window,
						clientX: Math.max(0, r.x + r.width / 2),
						clientY: Math.max(0, r.y + r.height / 2),
						button: 2
					});
					container.dispatchEvent(ev);
					return {
						selected: true,
						rect: { x: r.x, y: r.y, width: r.width, height: r.height }
					};
				}
				node = walker.nextNode();
			}
			return { selected: false, rect: null };
		},
		{ sel: messageSelector, needle: textToSelect }
	);
}


test('message highlights: add, comment, navigate, delete', async ({ page }: { page: any }) => {
	setupPageListeners(page);

	// No AI call needed — purely UI + WS round-trip.
	test.setTimeout(120000);

	const logCheckpoint = createSignupLogger('HIGHLIGHTS');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'msg-highlights'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting message-highlights E2E test.');

	// ───────────────────────────────────────────────────────────
	// STEP 1 — Login + start fresh chat + send a seed message
	// ───────────────────────────────────────────────────────────
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	const seedText = 'The quick brown fox jumps over the lazy dog near the old bridge today.';
	await sendMessage(page, seedText, logCheckpoint, takeStepScreenshot, 'seed');

	// Wait for the user message to render
	const userMsg = page.locator(SELECTORS.userMessageContent).first();
	await expect(userMsg).toBeVisible({ timeout: 15000 });
	await expect(userMsg).toContainText('quick brown fox');
	await takeStepScreenshot(page, 'seed-rendered');
	logCheckpoint('User message rendered.');

	// ───────────────────────────────────────────────────────────
	// STEP 2 — First highlight (no comment) via "Highlight"
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Scrolling user message into view + selecting "quick brown fox"...');
	await userMsg.scrollIntoViewIfNeeded();
	// Atomic select + contextmenu dispatch (single page.evaluate) so the
	// browser has no chance to clear the selection between the two steps.
	const sel1 = await selectAndOpenContextMenu(
		page,
		SELECTORS.userMessageContent,
		'quick brown fox'
	);
	expect(sel1.selected).toBe(true);
	await takeStepScreenshot(page, 'selection-1');
	const highlightBtn = page.locator(SELECTORS.messageContextHighlight);
	await expect(highlightBtn).toBeVisible({ timeout: 5000 });
	await highlightBtn.click();
	logCheckpoint('Clicked "Highlight".');
	await takeStepScreenshot(page, 'highlight-clicked');

	// Highlight box appears.
	const highlightBox = page.locator(SELECTORS.highlightBox);
	await expect(highlightBox).toHaveCount(1, { timeout: 10000 });
	logCheckpoint('First highlight box rendered.');

	// ChatHeader pill updates to "1 highlight"-ish (locale-dependent — just check it's visible).
	const pill = page.locator(SELECTORS.headerHighlightCount);
	await expect(pill).toBeVisible({ timeout: 10000 });
	const pillText1 = (await pill.textContent())?.trim() ?? '';
	logCheckpoint(`ChatHeader pill text after first highlight: "${pillText1}"`);
	expect(pillText1).toMatch(/1\b|^\s*1/);
	await takeStepScreenshot(page, 'pill-1-highlight');

	// ───────────────────────────────────────────────────────────
	// STEP 3 — Second highlight WITH comment via "Highlight & comment"
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Selecting "old bridge" for commented highlight...');
	await userMsg.scrollIntoViewIfNeeded();
	const sel2 = await selectAndOpenContextMenu(
		page,
		SELECTORS.userMessageContent,
		'old bridge'
	);
	expect(sel2.selected).toBe(true);

	const commentBtn = page.locator(SELECTORS.messageContextHighlightAndComment);
	await expect(commentBtn).toBeVisible({ timeout: 5000 });
	await commentBtn.click();
	logCheckpoint('Clicked "Highlight & comment".');
	await takeStepScreenshot(page, 'highlight-comment-clicked');

	// Popover opens in edit mode.
	const popover = page.locator(SELECTORS.commentPopover);
	await expect(popover).toBeVisible({ timeout: 10000 });
	const input = page.locator(SELECTORS.commentInput);
	await expect(input).toBeVisible({ timeout: 5000 });

	const COMMENT_TEXT = 'I was here last summer — the bridge is oak, not stone.';
	await input.fill(COMMENT_TEXT);
	await takeStepScreenshot(page, 'comment-typed');

	const saveBtn = page.locator(SELECTORS.commentSave);
	await saveBtn.click();
	logCheckpoint('Saved comment.');

	// Popover returns to view mode showing the comment text.
	const commentView = page.locator(SELECTORS.commentText);
	await expect(commentView).toBeVisible({ timeout: 10000 });
	await expect(commentView).toHaveText(COMMENT_TEXT, { timeout: 5000 });
	await takeStepScreenshot(page, 'comment-saved-view');

	// Two highlight boxes now.
	await expect(highlightBox).toHaveCount(2, { timeout: 10000 });
	// Pill now reads "2 highlights, 1 comment" (locale-dependent — check substrings).
	const pillText2 = (await pill.textContent())?.trim() ?? '';
	logCheckpoint(`ChatHeader pill text after second highlight: "${pillText2}"`);
	expect(pillText2).toMatch(/2/);
	expect(pillText2).toMatch(/1/);
	await takeStepScreenshot(page, 'pill-2-highlights');

	// Close popover by clicking outside.
	await page.mouse.click(5, 5);
	await expect(popover).not.toBeVisible({ timeout: 5000 });

	// ───────────────────────────────────────────────────────────
	// STEP 4 — Click the commented highlight → view popover
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Clicking the commented highlight box to open the view popover...');
	// Find the highlight box that has the speech-bubble badge (the commented one).
	// Both boxes are visible — the second one (old-bridge) has the comment badge.
	const commentedBox = highlightBox.nth(1);
	await commentedBox.click({ force: true });
	await expect(popover).toBeVisible({ timeout: 5000 });
	await expect(commentView).toHaveText(COMMENT_TEXT);
	// Author-only Edit / Delete buttons are present.
	await expect(page.locator(SELECTORS.commentEdit)).toBeVisible();
	await expect(page.locator(SELECTORS.commentDelete)).toBeVisible();
	await takeStepScreenshot(page, 'view-popover-author');

	// ───────────────────────────────────────────────────────────
	// STEP 5 — Delete the commented highlight
	// ───────────────────────────────────────────────────────────
	logCheckpoint('Deleting the commented highlight...');
	await page.locator(SELECTORS.commentDelete).click();
	// Popover closes, only 1 highlight box remains.
	await expect(popover).not.toBeVisible({ timeout: 5000 });
	await expect(highlightBox).toHaveCount(1, { timeout: 10000 });
	const pillText3 = (await pill.textContent())?.trim() ?? '';
	logCheckpoint(`ChatHeader pill after delete: "${pillText3}"`);
	expect(pillText3).toMatch(/1/);
	await takeStepScreenshot(page, 'after-delete');

	// Cleanup
	logCheckpoint('Cleaning up the test chat.');
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'cleanup');
	logCheckpoint('message-highlights test completed successfully.');
});
