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
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function activateWikipediaSearch(page: any, query: string): Promise<any> {
	const editor = page.getByTestId('message-editor').last();
	await editor.click();
	await page.keyboard.insertText('@');
	const source = page.getByTestId('wikipedia-source-result');
	await expect(source).toBeVisible({ timeout: 5000 });
	await source.click();
	await expect(editor).toContainText('@wiki:');
	await page.keyboard.insertText(query);
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

	const editor = page.getByTestId('message-editor').last();
	await editor.click();
	await page.keyboard.insertText('@');
	await expect(page.getByTestId('wikipedia-source-result')).toBeVisible({ timeout: 5000 });
	expect(wikipediaRequests).toHaveLength(0);
	await screenshot(page, 'wiki-static-discovery');

	await page.getByTestId('wikipedia-source-result').click();
	await page.keyboard.insertText('AlbertEin');
	const result = page.getByTestId('wikipedia-result').filter({ hasText: 'Albert Einstein' }).first();
	await expect(result).toBeVisible({ timeout: 15000 });
	await expect(result.getByTestId('wikipedia-description')).not.toBeEmpty();
	await expect(result.getByTestId('wikipedia-thumbnail')).toHaveAttribute('src', /\/api\/v1\/image\?/);
	await screenshot(page, 'wiki-preview-results');

	await result.click();
	const mention = editor.locator('[data-mention-type="wikipedia"]');
	await expect(mention).toBeVisible();
	await expect(mention).toHaveAttribute('data-mention-syntax', '@wikipedia:en:Albert_Einstein');
	await page.keyboard.insertText(' Summarize his most important contribution and identify Wikipedia as the source.');
	await screenshot(page, 'wiki-selected-mention');

	await page.locator('[data-action="send-message"]').last().click();
	const assistant = page.getByTestId('message-assistant').last();
	await expect(assistant).toBeVisible({ timeout: 120000 });
	await expect(assistant).toContainText(/Wikipedia/i, { timeout: 120000 });
	await screenshot(page, 'wiki-source-aware-response');

	await page.reload();
	await expect(page.getByTestId('message-assistant').last()).toContainText(/Wikipedia/i, { timeout: 30000 });
	await expect(page.getByTestId('message-user').last()).not.toContainText('@wikipedia:en:Albert_Einstein');
	await deleteActiveChat(page, log);
});

// contract-test: direct surface=gui.web assertions=wikipedia-mentions.resolution.disambiguation-visible,wikipedia-mentions.safety.fail-closed
test('Wiki disambiguation and provider failures stay visible before inference', async ({ page }: { page: any }) => {
	test.setTimeout(120000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('WIKIPEDIA_MENTION_FAILURES');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'wikipedia-mention-failures' });
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const editor = await activateWikipediaSearch(page, 'Mercury');
	const disambiguation = page.getByTestId('wikipedia-result').filter({ hasText: /^Mercury/ }).first();
	await expect(disambiguation).toHaveAttribute('data-disambiguation', 'true', { timeout: 15000 });
	await disambiguation.click();
	await expect(page.getByTestId('wikipedia-disambiguation-message')).toBeVisible();
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
});
