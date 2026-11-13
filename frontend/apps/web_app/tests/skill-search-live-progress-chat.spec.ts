/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and step screenshots cover each checkpoint)

/**
 * Search skills in chat (real inference, dev server only): while an event
 * discovery or a product search runs across its sources, the processing card
 * shows the live status line (sources done, results so far) and then the
 * finished results. On a server with installed providers the searches also
 * answer from public web pages; "early next year" conferences in Europe must
 * include FOSDEM as an event card built from such a page.
 *
 * Run through scripts/skill_search_progress_web_real_test.py (personal dev test
 * account, leases, installed Chromium, output outside the repository).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const { test, expect, attachConsoleListeners, attachNetworkListeners } = require('./console-monitor');

const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');

const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat,
	focusMessageEditor
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);

const MODEL_QUERY = 'gemini-3.8-flash';
const MODEL_NAME = /Gemini 3\.8 Flash/i;
const ANSWER_TIMEOUT = 300_000;
const CASES: Array<{ name: string; app: string; prompt: string; expectEventTitle?: RegExp }> = [
	{
		name: 'event discovery',
		app: 'events',
		prompt: 'Any upcoming open source conferences in Europe?'
	},
	{
		// The structured FOSDEM event card is built from public web pages, not from a provider feed.
		name: 'event discovery early next year',
		app: 'events',
		prompt: 'Open source conferences in Europe early next year?',
		expectEventTitle: /FOSDEM/i
	},
	{
		name: 'product search',
		app: 'shopping',
		prompt:
			'Search shops in Germany for one of these new mask microphones that cover the mouth, so I can talk to an AI agent in public without annoying people around me.'
	},
	{
		name: 'bus connection search',
		app: 'travel',
		prompt: 'Which long-distance buses go from Munich to Vienna next Wednesday, and what do they cost?'
	}
];

/** Insert the Gemini 3.8 Flash mention through the dropdown, then send the prompt after it. */
async function sendWithGemini(page: any, prompt: string, log: any, screenshot: any, label: string) {
	const editor = page.getByTestId('message-field').last().getByTestId('message-editor');
	await expect(editor).toBeVisible();
	await focusMessageEditor(editor);
	await page.keyboard.insertText(`@${MODEL_QUERY}`);
	const dropdown = page.getByTestId('mention-dropdown');
	await expect(dropdown).toBeVisible({ timeout: 10_000 });
	await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: MODEL_NAME }).first())
		.toBeVisible({ timeout: 10_000 });
	await page.keyboard.press('Tab');
	await expect(dropdown).not.toBeVisible({ timeout: 3000 });
	await sendMessage(page, ` ${prompt}`, log, screenshot, label, { preserveExistingContent: true });
}

for (const searchCase of CASES) {
	// contract-test: direct surface=gui.web assertions=app-skills.progress.live-status
	test(`${searchCase.name} shows live source progress and then its results`, async ({ page }) => {
		test.setTimeout(600_000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		const log = createSignupLogger('skill-search-live-progress');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: `skill-search-progress-${searchCase.app}` });
		attachConsoleListeners(page);
		attachNetworkListeners(page);

		await loginToTestAccount(page, log, screenshot);
		await startNewChat(page, log);
		try {
			await sendWithGemini(page, searchCase.prompt, log, screenshot, searchCase.app);
			const card = `[data-testid="embed-preview"][data-app-id="${searchCase.app}"]`;

			const progress = page.locator(`${card} [data-testid="embed-progress"]`).first();
			await expect(progress).toBeVisible({ timeout: ANSWER_TIMEOUT });
			const total = Number(await progress.getAttribute('data-sources-total'));
			expect(total).toBeGreaterThan(0);
			log(`first status line: ${(await progress.textContent())?.trim()} (sources ${total})`);
			await screenshot(page, 'progress-first', { fullPage: false });

			if (total > 1) {
				// A later frame: at least one source finished while the card is still processing.
				const later = page.locator(`${card} [data-testid="embed-progress"]:not([data-sources-done="0"])`).first();
				await expect(later).toBeVisible({ timeout: 120_000 });
				log(`later status line: ${(await later.textContent())?.trim()}`);
				await screenshot(page, 'progress-later', { fullPage: false });
			}

			const finished = page.locator(`${card}[data-status="finished"]`).first();
			// Once the answer is written the used-apps group collapses; open it to see the card.
			const toggle = page.getByTestId('message-assistant').last().getByTestId('assistant-activity-toggle').first();
			await expect(async () => {
				if ((await toggle.count()) && (await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
				await expect(finished).toBeVisible({ timeout: 3000 });
			}).toPass({ timeout: ANSWER_TIMEOUT });
			await expect(page.locator(`${card} [data-testid="embed-progress"]`)).toHaveCount(0);
			await expect(page.getByTestId('typing-indicator')).not.toBeVisible({ timeout: ANSWER_TIMEOUT });
			const generatedBy = page.getByTestId('message-assistant').last().getByTestId('generated-by');
			await expect(generatedBy).toContainText(MODEL_NAME, { timeout: 120_000 });
			await finished.scrollIntoViewIfNeeded();
			await screenshot(page, 'results', { fullPage: false });
			if (searchCase.expectEventTitle) {
				const named = page
					.getByTestId('message-assistant')
					.last()
					.locator(card)
					.filter({ hasText: searchCase.expectEventTitle })
					.first();
				await expect(named).toBeAttached({ timeout: 30_000 });
				await named.scrollIntoViewIfNeeded();
				log(`event card: ${(await named.textContent())?.replace(/\s+/g, ' ').trim().slice(0, 200)}`);
				await screenshot(page, 'named-event', { fullPage: false });
			}
			await page.getByTestId('message-assistant').last().scrollIntoViewIfNeeded();
			await screenshot(page, 'answer', { fullPage: false });
		} catch (error) {
			// The chat is deleted below; keep what it looked like when the check failed.
			await screenshot(page, 'failure-state', { fullPage: false });
			throw error;
		} finally {
			if (process.env.KEEP_SEARCH_PROGRESS_CHAT !== '1') await deleteActiveChat(page, log);
		}
	});
}
