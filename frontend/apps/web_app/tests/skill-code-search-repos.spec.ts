/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified E2E test for code/search_repos skill.
 *
 * Verifies preview rendering, direct CLI execution, CLI chat routing, and web UI
 * rendering of repository search embeds with child GitHub repo cards.
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
	closeFullscreen
} = require('./helpers/embed-test-helpers');

test.describe('App: Code / Skill: search_repos', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 1: embed preview renders at /dev/preview/embeds/code', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'code', log);
	});

	test('Phase 2: CLI apps code search_repos returns repositories', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const result = await runCli(
			apiUrl,
			[
				'apps', 'code', 'search_repos',
				'--input', JSON.stringify({ requests: [{ query: 'svelte markdown editor', count: 3 }] }),
				'--json'
			],
			45_000
		);

		expectCliSuccess(result);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);
		expect(parsed.data?.results?.length).toBeGreaterThan(0);
		const firstGroup = parsed.data.results[0];
		expect(firstGroup.results.length).toBeGreaterThan(0);
		expect(firstGroup.results[0].url).toContain('github.com/');
		console.log(`[P2] code/search_repos returned ${firstGroup.results.length} repository result(s)`);
	});

	test('Phase 3: CLI chats new triggers repo search', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const message = withLiveMockMarker(
			'Use the Code Search repos skill to find GitHub repositories for svelte markdown editor libraries',
			'code_search_repos_cli'
		);
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 75_000);
		expectCliSuccess(result);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	test('Phase 4: Web chat triggers repo search with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-code-search-repos');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker('Use the Code Search repos skill to find GitHub repositories for svelte markdown editor libraries', 'code_search_repos_web'),
			logCheckpoint,
			takeStepScreenshot,
			'code-search-repos'
		);

		const rejectMemoriesButton = page.getByRole('button', { name: /reject all/i });
		if (await rejectMemoriesButton.isVisible({ timeout: 5000 }).catch(() => false)) {
			await rejectMemoriesButton.click();
			logCheckpoint('Rejected optional memory permissions prompt.');
		}

		const embed = await waitForEmbedFinished(page, 'code', 'search_repos');
		logCheckpoint('Code repo search embed finished.');
		await takeStepScreenshot(page, 'repo-search-embed-finished');

		const fullscreenOverlay = await openFullscreen(page, embed);
		logCheckpoint('Fullscreen opened.');
		await expect(fullscreenOverlay.getByText(/GitHub|repos|hashmd|carta/i).first()).toBeVisible({ timeout: 10_000 });

		await closeFullscreen(page, fullscreenOverlay);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'code-search-repos');
	});
});
