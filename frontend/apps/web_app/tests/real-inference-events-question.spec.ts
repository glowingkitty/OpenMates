/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and attached screenshots cover each checkpoint)
/**
 * Conference questions are answered through the Events app (real-inference proof, TASK-2134).
 *
 * Runs in the `real_inference` CI group (isolated per-run stack with real Gemini, Mistral, Brave
 * and Jev keys) and still manually against dev through
 * scripts/events_question_web_real_test.py:
 *   1. @Gemini-3.8-Flash is asked for the largest open source conference in
 *      Europe and when it happens. The Events app search skill must run first
 *      (its app icon in the answer's activity line), never plain web search only.
 *   2. When Events found events, its card opens fullscreen. When it found no
 *      dated edition, the answer falls back to a web search card instead of
 *      answering from memory (specialised skill first, web search as fallback).
 *   3. A chat header image bubble, when the header shows one, opens fullscreen
 *      without the "Embed not found" server error.
 * The chat is deleted afterwards.
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
const { closeFullscreen, openFullscreen } = require('./helpers/embed-test-helpers');
const { requireRealInference } = require('./helpers/real-inference-guard');
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const QUESTION = ' What is the largest open source software conference in Europe and when does it happen?';
const ANSWER_TIMEOUT_MS = 300_000;
const EMBED_NOT_FOUND = /Embed not found/i;

/** The turn is over when the stop button and typing indicator stay hidden for 5 s. */
async function waitForIdle(page: Page): Promise<void> {
	const busy = page.locator('[data-testid="stop-processing-button"]:visible, [data-testid="typing-indicator"]:visible');
	let idleSince = 0;
	await expect
		.poll(async () => {
			if ((await busy.count()) > 0) {
				idleSince = 0;
				return false;
			}
			idleSince ||= Date.now();
			return Date.now() - idleSince >= 5_000;
		}, { timeout: ANSWER_TIMEOUT_MS, intervals: [1_000] })
		.toBe(true);
}

async function askWithGemini(page: Page, log: any): Promise<void> {
	const editor = page.getByTestId('message-editor');
	await focusMessageEditor(editor);
	await page.keyboard.insertText('@Gemini-3.8-Flash');
	const dropdown = page.getByTestId('mention-dropdown');
	await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: /Gemini 3\.8 Flash/i }).first()).toBeVisible({ timeout: 10_000 });
	await page.keyboard.press('Tab');
	await expect(dropdown).toBeHidden({ timeout: 5_000 });
	await page.keyboard.type(QUESTION);
	await page.locator('[data-action="send-message"]').click();
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 20_000 });
	log('Sent the largest open source conference question with @Gemini-3.8-Flash.');
}

// contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.conditional-context
test('the largest open source conference question is answered through the Events app, with web search only as fallback', async ({ page }: { page: Page }, testInfo: any) => {
	test.setTimeout(900_000);
	requireRealInference('Events question', BASE_URL);
	test.skip(!getTestAccount().email, 'Test account credentials required.');
	await page.setViewportSize({ width: 1280, height: 900 });
	const log = createSignupLogger('EVENTS_QUESTION');
	const screenshot = createStepScreenshotter(log);
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await loginToTestAccount(page, log, screenshot);
	await setChatSidebarOpen(page, false, log);
	await startNewChat(page, log);

	try {
		await askWithGemini(page, log);
		const answer = page.getByTestId('message-assistant').last();
		await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
		await waitForIdle(page);
		await expect(answer.getByTestId('generated-by')).toContainText(/Gemini 3\.8 Flash/i, { timeout: 60_000 });

		// The Events app search skill ran first: its app icon and its search card are in the answer.
		const eventsActivity = answer.locator('[data-testid="assistant-skill-app-icon"][data-app-id="events"]').first();
		await expect(eventsActivity, 'the Events app ran for this answer').toBeAttached({ timeout: 60_000 });
		const eventsCard = page.locator('[data-testid="embed-preview"][data-app-id="events"][data-skill-id="search"]').first();
		// Collapsed activity lines show only answer cards; open the line when the card sits inside it.
		if (!(await eventsCard.waitFor({ state: 'visible', timeout: 20_000 }).then(() => true, () => false))) {
			await answer.getByTestId('assistant-activity-toggle').first().click();
		}
		await expect(eventsCard, 'the Events app search card is in the answer').toBeVisible({ timeout: 60_000 });
		await expect(eventsCard).toHaveAttribute('data-status', 'finished', { timeout: 120_000 });
		await eventsCard.evaluate(element => element.scrollIntoView({ block: 'center' }));
		await testInfo.attach('answer-with-events-card', { body: await page.screenshot(), contentType: 'image/png' });

		const overlay = await openFullscreen(page, eventsCard);
		await expect(overlay).not.toContainText(EMBED_NOT_FOUND);
		await page.waitForTimeout(1_500);
		const eventsFoundNothing = await overlay.getByTestId('search-no-results-message').isVisible();
		await testInfo.attach('events-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
		await closeFullscreen(page, overlay);

		if (eventsFoundNothing) {
			// Events found no dated edition: the answer must fall back to web search, never to memory.
			log('Events found no dated edition; expecting the web search fallback.');
			const webSearchCard = answer.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]').first();
			await expect(webSearchCard, 'web search ran as the fallback after an empty Events result').toBeVisible({ timeout: 60_000 });
			await expect(webSearchCard).toHaveAttribute('data-status', 'finished', { timeout: 120_000 });
			await webSearchCard.evaluate(element => element.scrollIntoView({ block: 'center' }));
			await testInfo.attach('answer-with-web-search-fallback', { body: await page.screenshot(), contentType: 'image/png' });
			const webOverlay = await openFullscreen(page, webSearchCard);
			await expect(webOverlay).not.toContainText(EMBED_NOT_FOUND);
			await page.waitForTimeout(1_500);
			await testInfo.attach('web-search-fallback-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
			await closeFullscreen(page, webOverlay);
		} else {
			log('Events found events: the Events search card lists them.');
		}

		// A header image bubble opens fullscreen without "Embed not found".
		await page.evaluate(() => window.scrollTo(0, 0));
		const bubble = page.locator('[data-testid="chat-header-image-bubble-left"], [data-testid="chat-header-image-bubble-right"]').first();
		if (await bubble.isVisible().catch(() => false)) {
			const bubbleOverlay = await openFullscreen(page, bubble);
			await page.waitForTimeout(2_000);
			await expect(page.getByText(EMBED_NOT_FOUND)).toHaveCount(0);
			await testInfo.attach('header-bubble-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
			await closeFullscreen(page, bubbleOverlay);
		} else {
			log('The chat header shows no image bubble for this answer.');
		}
		await expect(page.getByText(EMBED_NOT_FOUND)).toHaveCount(0);
	} finally {
		await deleteActiveChat(page, log, screenshot);
	}
});
