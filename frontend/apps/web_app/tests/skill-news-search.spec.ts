/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for news/search skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/news
 * Phase 2: CLI direct skill command (openmates apps news search --json)
 * Phase 3: CLI chat send triggers skill
 * Phase 4: Web UI chat triggers skill with embed rendering + fullscreen grid
 *
 * Architecture context: docs/architecture/embeds.md
 */
export {};

const { test, expect } = require('./console-monitor');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	withLiveMockMarker,
	installE2EServerContentOverrideGate
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { deriveApiUrl, runCli, parseCliJson } = require('./helpers/cli-test-helpers');
const {
	verifyEmbedPreviewPage,
	waitForEmbedFinished,
	openFullscreen,
	verifySearchGrid,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

const NEWS_SEARCH_FIXTURE_QUERY = 'openmates_e2e_news_fixture_ai';

test.describe('App: News / Skill: search', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	// contract-test: supporting surface=gui.web assertions=web-search.surface-parity
	test('Phase 1: embed preview renders at /dev/preview/embeds/news', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'news', log);
	});

	// contract-test: supporting surface=cli assertions=web-search.surface-parity
	test('Phase 2: CLI apps news search returns results', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const result = await runCli(
			apiUrl,
			[
				'apps', 'news', 'search',
				'--input', JSON.stringify({ requests: [{ query: NEWS_SEARCH_FIXTURE_QUERY, freshness: 'pw' }] }),
				'--json'
			],
			30_000
		);

		expect(result.code).toBe(0);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);

		const results = parsed.data?.results?.[0]?.results || [];
		expect(results.length).toBeGreaterThan(0);
		expect(results[0].title || results[0].name).toBeTruthy();
		expect(results[0].url).toBeTruthy();
		console.log(`[P2] news/search found ${results.length} article(s)`);
	});

	// contract-test: supporting surface=cli assertions=web-search.surface-parity
	test('Phase 3: CLI chats new triggers news search', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const message = withLiveMockMarker(`Search news for ${NEWS_SEARCH_FIXTURE_QUERY}`, 'news_search_cli');
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 60_000);
		expect(result.code).toBe(0);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	// contract-test: direct surface=gui.web assertions=web-search.surface-parity
	test('Phase 4: Web chat and short follow-up each execute news search with embeds', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-news-search');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await installE2EServerContentOverrideGate(page, 'news-search-mock-marker');
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker(`Search news for ${NEWS_SEARCH_FIXTURE_QUERY}`, 'news_search_web'),
			logCheckpoint, takeStepScreenshot, 'news-search'
		);

		const embed = await waitForEmbedFinished(page, 'news', 'search');
		logCheckpoint('News search embed finished.');
		await expect(embed, 'Finished news search card must keep the visible query.').toContainText(NEWS_SEARCH_FIXTURE_QUERY);
		const assistantMessage = page.getByTestId('message-assistant').last();
		await expect(assistantMessage).not.toContainText('app_skill_use');
		await expect(assistantMessage).not.toContainText('embed_ref');

		const fullscreenOverlay = await openFullscreen(page, embed);
		const resultCards = await verifySearchGrid(fullscreenOverlay);
		logCheckpoint(`Found ${await resultCards.count()} news result(s).`);

		await closeFullscreen(page, fullscreenOverlay);

		await page.reload({ waitUntil: 'networkidle' });
		const reloadedEmbed = await waitForEmbedFinished(page, 'news', 'search');
		await expect(reloadedEmbed, 'Reloaded news search card must keep the visible query.').toContainText(NEWS_SEARCH_FIXTURE_QUERY);
		const reloadedAssistantMessage = page.getByTestId('message-assistant').last();
		await expect(reloadedAssistantMessage).not.toContainText('app_skill_use');
		await expect(reloadedAssistantMessage).not.toContainText('embed_ref');
		logCheckpoint('Reload preserved finished news search card without raw protocol text.');

		// JDPC5: an implicit same-intent follow-up used to emit a TOON code
		// embed without executing news.search. Scope to the NEW assistant turn
		// so the first turn's successful search cannot satisfy this assertion.
		const originalEmbedId = await reloadedEmbed.getAttribute('data-embed-id');
		const assistantCount = await page.getByTestId('message-assistant').count();
		await sendMessage(
			page,
			withLiveMockMarker('und OpenAI?', 'news_search_web_followup'),
			logCheckpoint, takeStepScreenshot, 'news-search-followup'
		);
		await expect(page.getByTestId('message-assistant')).toHaveCount(assistantCount + 1, { timeout: 90_000 });
		const followup = page.getByTestId('message-assistant').last();
		const followupEmbed = followup.locator(
			'[data-testid="embed-preview"][data-app-id="news"][data-skill-id="search"][data-status="finished"]'
		).first();
		await expect(followupEmbed).toBeVisible({ timeout: 90_000 });
		expect(await followupEmbed.getAttribute('data-embed-id')).not.toBe(originalEmbedId);
		await expect(followupEmbed).toContainText(/OpenAI/i);
		await expect(followup).not.toContainText(/app_id:|skill_id:|app_skill_use|embed_ref|```toon/);
		await expect(followup.locator('[data-testid="embed-preview"][data-app-id="code"]')).toHaveCount(0);
		const followupOverlay = await openFullscreen(page, followupEmbed);
		await verifySearchGrid(followupOverlay);
		await closeFullscreen(page, followupOverlay);

		await page.reload({ waitUntil: 'networkidle' });
		const persistedFollowup = page.getByTestId('message-assistant').last();
		await expect(persistedFollowup.locator(
			'[data-testid="embed-preview"][data-app-id="news"][data-skill-id="search"][data-status="finished"]'
		).first()).toContainText(/OpenAI/i, { timeout: 90_000 });
		await expect(persistedFollowup).not.toContainText(/app_id:|skill_id:|app_skill_use|embed_ref|```toon/);
		logCheckpoint('Short follow-up executed a distinct news search and survived reload without protocol leakage.');
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'news-search');
	});
});
