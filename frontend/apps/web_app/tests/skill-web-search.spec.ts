/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for web/search skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/web
 * Phase 2: CLI direct skill command (openmates apps web search --json)
 * Phase 3: CLI chat send triggers skill (openmates chats new "..." --json)
 * Phase 4: Web UI chat triggers skill with embed rendering + fullscreen
 *
 * All chat phases use withLiveMockMarker — the full pipeline always runs,
 * only external API calls (LLM + HTTP) are cached.
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
	withLiveMockMarker
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');
const {
	verifyEmbedPreviewPage,
	waitForEmbedFinished,
	openFullscreen,
	verifySearchGrid,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

test.describe('App: Web / Skill: search', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	// ── Phase 1: Embed preview renders ─────────────────────────────────────
	test('Phase 1: embed preview renders at /dev/preview/embeds/web', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'web', log);
	});

	// ── Phase 2: CLI direct skill command ──────────────────────────────────
	test('Phase 2: CLI apps web search returns results', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const result = await runCli(apiUrl, ['apps', 'web', 'search', 'OpenMates AI assistant']);
		expectCliSuccess(result);
		expect(result.stdout.length).toBeGreaterThan(10);
		expect(result.stderr).not.toMatch(/error|failed|exception/i);
		console.log(`[P2] web/search returned ${result.stdout.length} chars`);
	});

	// ── Phase 3: CLI chat send triggers skill ──────────────────────────────
	test('Phase 3: CLI chats new triggers web search', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const message = withLiveMockMarker('Search the web for OpenMates AI assistant', 'web_search_cli');
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 60_000);
		expectCliSuccess(result);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		// Cleanup: extract chat ID and delete
		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	// ── Phase 5: Zero-hit query must NOT show "App skill processing error" ──
	// Regression guard for Linear OPE-405 / prod issue 0d73ab38.
	// When one sub-query in a parallel multi-search legitimately returns 0 Brave
	// results, the assistant answer must still render cleanly without the red
	// embed-error banner, and the zero-hit embed must finalize to status=finished
	// (not status=error). Fix is in backend/apps/ai/processing/main_processor.py.
	test('Phase 5: Zero-result query does not show error banner', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-web-search-zero-results');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		// Deterministically zero-hit query: the impossible-exact-phrase combined with
		// an unusual language fragment never matches anything on Brave. Verified
		// directly against the Brave API as part of OPE-405.
		const message = withLiveMockMarker(
			'Search the web for "xyznonexistentproduct123456" lokale API MQTT — just try to find results',
			'web_search_zero_results'
		);
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'web-search-zero');

		// The embed must finalize to status=finished (NOT status=error).
		logCheckpoint('Waiting for web search embed to finalize (finished or error)...');
		const anyEmbed = page.locator(
			'[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]'
		).first();
		await expect(anyEmbed).toBeVisible({ timeout: 90_000 });

		// Poll until status is no longer "processing"
		await expect(async () => {
			const status = await anyEmbed.getAttribute('data-status');
			expect(['finished', 'error']).toContain(status);
		}).toPass({ timeout: 90_000 });

		const finalStatus = await anyEmbed.getAttribute('data-status');
		logCheckpoint(`Zero-result embed final status: ${finalStatus}`);
		await takeStepScreenshot(page, 'zero-results-embed-final');

		// PRIMARY ASSERTIONS (the bug)
		expect(
			finalStatus,
			`Zero-result web search embed must finalize to "finished", not "error". ` +
			`Got: ${finalStatus}. This is the OPE-405 regression — backend is mis-classifying ` +
			`empty Brave results as a skill failure.`
		).toBe('finished');

		// The red error banner must NOT appear on the assistant message.
		const errorBanner = page.getByTestId('embed-error-banner');
		await expect(
			errorBanner,
			'Red "App skill processing error" banner must not appear when the only ' +
			'failure is a legitimate zero-hit search.'
		).not.toBeVisible();

		// Assistant response text must be non-empty — the LLM answer should render
		// regardless of the zero-hit sub-query.
		const assistantMessage = page.getByTestId('message-assistant').last();
		await expect(assistantMessage).toBeVisible({ timeout: 30_000 });

		// Zero-result embed must render a clear "No results found for '<query>'"
		// message (not a generic empty state). This is the UX follow-up to the
		// OPE-405 backend fix. The testid is added by WebSearchEmbedPreview and
		// SearchResultsTemplate components.
		const noResultsPreviewMessage = anyEmbed.getByTestId('search-no-results-message');
		await expect(
			noResultsPreviewMessage,
			'Zero-result web search embed must show a "No results found" message in the preview.'
		).toBeVisible({ timeout: 15_000 });
		const previewText = (await noResultsPreviewMessage.textContent()) || '';
		expect(
			previewText.toLowerCase(),
			`No-results preview text must mention "no results" (got: "${previewText}")`
		).toContain('no results');
		// If the query was wired through, the message should contain part of it.
		expect(
			previewText,
			`No-results preview should include the query string "xyznonexistentproduct123456" ` +
			`to prove the query placeholder substitution works (got: "${previewText}")`
		).toContain('xyznonexistentproduct123456');
		logCheckpoint(`Preview no-results message: "${previewText}"`);

		// Open the fullscreen and verify the same message renders there too.
		const fullscreenOverlay = await openFullscreen(page, anyEmbed);
		logCheckpoint('Fullscreen opened for zero-result embed.');
		const fullscreenNoResults = fullscreenOverlay.getByTestId('search-no-results-message');
		await expect(
			fullscreenNoResults,
			'Fullscreen must also render the no-results message when the search returned 0 hits.'
		).toBeVisible({ timeout: 10_000 });
		const fullscreenText = (await fullscreenNoResults.textContent()) || '';
		expect(fullscreenText).toContain('xyznonexistentproduct123456');
		await takeStepScreenshot(page, 'zero-results-fullscreen');
		await closeFullscreen(page, fullscreenOverlay);
		logCheckpoint('Fullscreen closed.');

		logCheckpoint('Phase 5 passed: zero-hit query rendered without error banner.');
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'web-search-zero');
	});

	// ── Phase 4: Web UI chat triggers skill ────────────────────────────────
	test('Phase 4: Web chat triggers web search with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-web-search');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		const message = withLiveMockMarker(
			'Search the web for OpenMates AI assistant',
			'web_search_web'
		);
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'web-search');

		logCheckpoint('Waiting for web search embed to finish...');
		const embed = await waitForEmbedFinished(page, 'web', 'search');
		logCheckpoint('Web search embed finished.');
		await takeStepScreenshot(page, 'web-search-embed-finished');

		const fullscreenOverlay = await openFullscreen(page, embed);
		logCheckpoint('Fullscreen opened.');

		const resultCards = await verifySearchGrid(fullscreenOverlay);
		const count = await resultCards.count();
		logCheckpoint(`Found ${count} search result(s) in fullscreen grid.`);

		await closeFullscreen(page, fullscreenOverlay);
		logCheckpoint('Fullscreen closed.');

		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'web-search');
	});
});
