/*
 * Deployed Wikipedia mention contract for the web composer.
 * Verifies explicit-only discovery, proxied previews, canonical selection,
 * source-aware completion, and visible pre-inference failure states.
 * The backend suite owns upstream throttling and Groq safety internals.
 */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { openMentionDropdown } = require('./helpers/mention-test-helpers');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function openWikipediaSourceMenu(page: any): Promise<{ editor: any; source: any }> {
	const { editor, dropdown } = await openMentionDropdown(page);
	const source = dropdown.getByTestId('wikipedia-source-result');
	await expect(source).toBeVisible({ timeout: 5000 });
	return { editor, source };
}

async function activateWikipediaSearch(
	page: any,
	query: string,
	opened?: { editor: any; source: any }
): Promise<any> {
	const { editor, source } = opened ?? await openWikipediaSourceMenu(page);
	await source.click();
	await expect(editor).toContainText('@wiki:', { timeout: 2_000 });
	await expect(page.getByTestId('mention-dropdown-header')).toHaveText('Enter a term to search for on Wikipedia');
	await page.keyboard.insertText(query);
	await expect(editor).toContainText(`@wiki:${query}`, { timeout: 2_000 });
	return editor;
}

// contract-test: direct surface=gui.web assertions=wikipedia-mentions.discovery.web-menu,wikipedia-mentions.surfaces.semantic-parity,wikipedia-mentions.ai.source-aware-intent
test('Wiki discovery selects a canonical article and completes with source context', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('WIKIPEDIA_MENTIONS');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'wikipedia-mentions' });
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const wikipediaRequests: string[] = [];
	page.on('request', (request: any) => {
		if (request.url().includes('/v1/wikipedia/search')) wikipediaRequests.push(request.url());
	});

	const opened = await openWikipediaSourceMenu(page);
	expect(wikipediaRequests).toHaveLength(0);
	await screenshot(page, 'wiki-static-discovery');

	const editor = await activateWikipediaSearch(page, 'AlbertEin', opened);
	const result = page.getByTestId('wikipedia-result').filter({ hasText: 'Albert Einstein' }).first();
	await expect(result).toBeVisible({ timeout: 15000 });
	await expect(result.getByTestId('wikipedia-description')).not.toBeEmpty();
	await expect(result.getByTestId('wikipedia-thumbnail')).toHaveAttribute('src', /\/api\/v1\/image\?/);
	await screenshot(page, 'wiki-preview-results');

	await result.click();
	const mention = editor.locator('[data-mention-type="wikipedia"]');
	await expect(mention).toBeVisible();
	await expect(mention).toHaveAttribute('data-mention-syntax', '@wikipedia:en:Albert_Einstein');
	await expect(mention).toHaveAttribute(
		'style',
		/--mention-color-start: var\(--color-app-study-start\); --mention-color-end: var\(--color-app-study-end\);/
	);
	await page.keyboard.insertText(' Summarize his most important contribution and identify Wikipedia as the source.');
	await screenshot(page, 'wiki-selected-mention');

	await page.locator('[data-action="send-message"]').last().click();
	const assistant = page.getByTestId('message-assistant').last();
	await expect(assistant).toBeVisible({ timeout: 120000 });
	await expect(page.getByTestId('stop-processing-button')).toHaveCount(0, { timeout: 120000 });
	await expect(assistant.getByTestId('mate-message-content')).toContainText(/Wikipedia/i, { timeout: 30000 });
	await screenshot(page, 'wiki-source-aware-response');

	await page.reload();
	await expect(page.getByTestId('message-assistant').last().getByTestId('mate-message-content')).toContainText(/Wikipedia/i, { timeout: 30000 });
	const persistedUserMessage = page.getByTestId('message-user').last();
	await expect(persistedUserMessage).not.toContainText('@wikipedia:en:Albert_Einstein');
	const persistedWikiLink = persistedUserMessage.getByTestId('wiki-inline-link');
	await expect(persistedWikiLink).toContainText('Albert Einstein');
	await persistedWikiLink.click();
	await expect(page.getByTestId('wiki-fullscreen-content')).toContainText('Albert Einstein', { timeout: 30000 });
	await page.getByTestId('embed-minimize').click();
	await deleteActiveChat(page, log);
});

// contract-test: direct surface=gui.web assertions=wikipedia-mentions.resolution.disambiguation-visible,wikipedia-mentions.safety.fail-closed
test('Wiki alternatives and provider failures stay visible before inference', async ({ page }: { page: any }) => {
	test.setTimeout(120000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('WIKIPEDIA_MENTION_FAILURES');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'wikipedia-mention-failures' });
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const editor = await activateWikipediaSearch(page, 'Mercury');
	await expect(page.getByTestId('wikipedia-result').filter({ hasText: 'Topics referred to by the same term' })).toHaveCount(0, { timeout: 15000 });
	await expect(page.getByTestId('wikipedia-result').filter({ hasText: 'Mercury (planet)' }).first()).toBeVisible();
	await expect(editor.locator('[data-mention-type="wikipedia"]')).toHaveCount(0);
	await expect(page.getByTestId('stop-processing-button')).toHaveCount(0);

	await page.keyboard.press('Control+A');
	await page.keyboard.press('Backspace');
	await page.route('**/v1/wikipedia/search**', async (route: any) => {
		await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Provider unavailable' }) });
	});
	await activateWikipediaSearch(page, 'UnavailableTopic');
	await expect(page.getByTestId('wikipedia-search-error')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('stop-processing-button')).toHaveCount(0);
	await screenshot(page, 'wiki-provider-error');
	await deleteActiveChat(page, log);
});
