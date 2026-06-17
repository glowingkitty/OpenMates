/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * frontend/apps/web_app/tests/source-quote-verification.spec.ts
 *
 * Verifies that false source quotes emitted by the assistant are stripped before
 * they render in the chat UI. The mocked AI fixture still runs through the real
 * chat, encryption, embed recreation, and source-quote verification path.
 *
 * Architecture: docs/architecture/source-quotes.md
 */
export {};

const { test, expect } = require('./console-monitor');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	waitForAssistantMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');

const FALSE_QUOTE =
	'The tower was known as Burj Dubai until its official opening in January 2010. ' +
	'It was renamed in honour of the ruler of Abu Dhabi, Khalifa bin Zayed Al Nahyan; ' +
	'Abu Dhabi and the federal government of UAE lent Dubai tens of billions of US ' +
	'dollars so that Dubai could pay its debts.';

const SHARED_CHAT_WITH_WEBSITE_QUOTE = 'https://app.dev.openmates.org/s/aUc6RjnR#bIiNzh';
const WEBSITE_SOURCE_QUOTE =
	'xHain is a hack+makespace in the heart of Berlin, Germany. You can drop in on our Open Monday night from 18h until late at night.';

const SHARED_CHAT_WITH_VIDEO_QUOTE = 'https://app.dev.openmates.org/s/Is8cygIa#fBhhCJ';
const VIDEO_SOURCE_QUOTE =
	'LLMs can get you 80% there, but the other 20%, man, if you’re not an expert, you are gonna have a hard time.';

test.describe('Source quote verification', () => {
	test.setTimeout(240_000);

	test('auto-removes false source quotes before rendering assistant message', async ({ page }: { page: any }) => {
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const log = createSignupLogger('source-quote-verification');
		await archiveExistingScreenshots(log);
		const screenshot = createStepScreenshotter(log);

		await loginToTestAccount(page, log, screenshot, { waitForEditor: true });
		await startNewChat(page, log);

		await sendMessage(
			page,
			'<<<TEST_MOCK:false_source_quote_stripped>>> Simulate a false source quote from the LLM.',
			log,
			screenshot,
			'false-source-quote'
		);

		const assistantMessage = await waitForAssistantMessage(page, {
			which: 'last',
			contains: 'This sentence should remain after the invalid quote is removed.',
			timeout: 120_000,
			logCheckpoint: log
		});

		await expect(assistantMessage).toContainText('The source says the Burj Khalifa had a previous name.');
		await expect(assistantMessage).not.toContainText(FALSE_QUOTE);
		await expect(assistantMessage).not.toContainText('embed:en.wikipedia.org-gDS');
		await expect(assistantMessage.locator('[data-testid="source-quote-block"]')).toHaveCount(0);

		const embed = page.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]').first();
		await expect(embed).toBeVisible({ timeout: 30_000 });
		await screenshot(page, 'false-source-quote-stripped');

		await deleteActiveChat(page, log, screenshot, 'false-source-quote');
	});

	test('clicking a website source quote highlights matching fullscreen text', async ({ page }: { page: any }) => {
		test.setTimeout(120_000);

		const response = await page.goto(SHARED_CHAT_WITH_WEBSITE_QUOTE, { waitUntil: 'networkidle' });
		expect(response?.status()).toBe(200);

		const sourceQuote = page.getByTestId('source-quote-block').filter({ hasText: WEBSITE_SOURCE_QUOTE }).first();
		await expect(sourceQuote).toBeVisible({ timeout: 30_000 });
		await sourceQuote.click();

		// A source quote from a web search child result opens the parent search fullscreen
		// and then the focused website child overlay, so scope assertions to the topmost
		// fullscreen instead of the hidden parent shell.
		const overlay = page.getByTestId('embed-fullscreen-overlay').last();
		await expect(overlay).toBeVisible({ timeout: 30_000 });

		const highlight = overlay.getByTestId('embed-source-text-highlight').first();
		await expect(highlight).toBeVisible({ timeout: 10_000 });
		await expect(highlight).toContainText('xHain is a hack+makespace in the heart of Berlin');

		const styles = await highlight.evaluate((el: HTMLElement) => {
			const computed = window.getComputedStyle(el);
			return {
				backgroundColor: computed.backgroundColor,
				boxShadow: computed.boxShadow,
			};
		});
		expect(styles.backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
		expect(styles.boxShadow).not.toBe('none');
	});

	test('clicking a video source quote opens transcript fullscreen', async ({ page }: { page: any }) => {
		test.setTimeout(120_000);

		const response = await page.goto(SHARED_CHAT_WITH_VIDEO_QUOTE, { waitUntil: 'networkidle' });
		expect(response?.status()).toBe(200);

		const sourceQuote = page.getByTestId('source-quote-block').filter({ hasText: VIDEO_SOURCE_QUOTE }).first();
		await expect(sourceQuote).toBeVisible({ timeout: 30_000 });
		await expect(sourceQuote).toContainText('YouTube Video Transcript');
		await expect(sourceQuote).not.toContainText('vS-gfLhxYDg');

		await sourceQuote.click();

		const overlay = page.getByTestId('embed-fullscreen-overlay').last();
		await expect(overlay).toBeVisible({ timeout: 30_000 });
		await expect(overlay).toContainText('YouTube Video', { timeout: 10_000 });

		const highlights = overlay.getByTestId('embed-source-text-highlight');
		await expect(highlights.first()).toBeVisible({ timeout: 10_000 });
		const highlightedText = await highlights.evaluateAll((elements: HTMLElement[]) =>
			elements
				.map((element) => element.textContent || '')
				.join(' ')
				.replace(/\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b/g, ' ')
				.replace(/\s+/g, ' ')
				.trim()
		);
		expect(highlightedText).toContain('LLMs can get you 80% there');
	});

});
