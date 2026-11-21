/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (the raw Playwright video and attached screenshots show the notice)
/**
 * Background chat notice shows the summary headline (dev-only real-inference proof, TASK-390 follow-up).
 *
 * Runs without mocks against the deployed dev stack through
 * scripts/chat_notice_headline_web_real_test.py. A code-heavy request in a new chat,
 * answered by @Gemini-3.8-Flash while another new chat is open, used to produce a notice
 * reading only "New AI response ready" with no mate image. Now:
 *   1. The in-app notice of the background chat appears for that chat.
 *   2. Its body becomes the summary headline: starts with ✅, ❓ or ℹ️, never the generic text.
 *   3. The header shows the chat title and the mate profile image is shown.
 * The chat is deleted afterwards. Never run in CI: it needs real providers.
 */
import type { Page } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const {
	deleteActiveChat,
	focusMessageEditor,
	loginToTestAccount,
	setChatSidebarOpen,
	startNewChat
} = require('./helpers/chat-test-helpers');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const PROMPT =
	'Write a simple single-file recipe web app in HTML, CSS and JavaScript: add recipes, list them, delete them. Reply with the code only.';
const GENERIC_TEXT = 'New AI response ready';

// contract-test: direct surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
test('a background chat notice shows the summary headline, the chat title and the mate image', async ({ page }: { page: Page }, testInfo: any) => {
	test.setTimeout(600_000);
	test.skip(Boolean(process.env.E2E_USE_MOCKS), 'Real dev inference only.');
	test.skip(!getTestAccount().email, 'Test account credentials required.');
	await page.setViewportSize({ width: 390, height: 844 });
	const log = createSignupLogger('CHAT_NOTICE_HEADLINE');
	const screenshot = createStepScreenshotter(log);
	// Notice diagnostics from the app's own console lines (ids and sources only, never content).
	page.on('console', (message) => {
		const text = message.text();
		if (/\[Notifications\]|Showing notification for background chat|notification_headline|post_processing_completed/.test(text)) log(`console: ${text.slice(0, 200)}`);
	});
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await loginToTestAccount(page, log, screenshot);
	await setChatSidebarOpen(page, false, log);
	await startNewChat(page, log);

	let chatId: string | null = null;
	try {
		const editor = page.getByTestId('message-editor');
		await focusMessageEditor(editor);
		await page.keyboard.insertText('@Gemini-3.8-Flash');
		const dropdown = page.getByTestId('mention-dropdown');
		await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: /Gemini 3\.8 Flash/i }).first()).toBeVisible({ timeout: 10_000 });
		await page.keyboard.press('Tab');
		await expect(dropdown).toBeHidden({ timeout: 5_000 });
		await page.keyboard.insertText(` ${PROMPT}`);
		await page.keyboard.press('Escape');
		await page.locator('[data-action="send-message"]').click();
		await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 20_000 });
		chatId = page.url().match(/chat-id=([^&# ]+)/)?.[1] ?? null;
		expect(chatId).toBeTruthy();
		const sent = page.getByTestId('message-user').last();
		await expect(sent.getByText('Sending...')).not.toBeVisible({ timeout: 30_000 });
		log(`Chat ${chatId} sent; opening a new chat so it runs in the background.`);

		await page.waitForTimeout(1500);
		await startNewChat(page, log);

		const notice = page.locator(`[data-testid="chat-notification"][data-chat-id="${chatId}"]`).first();
		await expect(notice).toBeVisible({ timeout: 240_000 });
		// The notice is still sliding in (not "stable") and lives 10 s: hover without the stability wait to pause its dismissal.
		await notice.hover({ force: true });
		// The headline arrives after post-processing and replaces the excerpt in place.
		const message = notice.getByTestId('notification-message');
		await expect(message).toHaveText(/^(✅|❓|ℹ️) \S/, { timeout: 60_000 });
		const text = ((await message.textContent()) ?? '').trim();
		log(`Notice headline: "${text}"`);
		expect(text).not.toContain(GENERIC_TEXT);
		expect([...text].length).toBeLessThanOrEqual(110);
		await expect(notice.getByTestId('notification-title')).not.toHaveText('');
		await expect(notice.getByTestId('notification-mate-profile')).toBeVisible();
		await testInfo.attach('01-notice-headline', { body: await page.screenshot(), contentType: 'image/png' });
		await testInfo.attach('02-notice-element', { body: await notice.screenshot(), contentType: 'image/png' });
	} finally {
		if (chatId) {
			await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`), { waitUntil: 'domcontentloaded' }).catch(() => undefined);
			await deleteActiveChat(page, log).catch((error: unknown) => log(`Cleanup could not delete the chat: ${String(error)}`));
		}
	}
});
