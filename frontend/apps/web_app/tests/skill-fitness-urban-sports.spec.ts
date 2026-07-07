/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified E2E coverage for Fitness Urban Sports Club search skills.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/fitness
 * Phase 2: CLI direct skill commands return Urban Sports location/class groups
 * Phase 3: Web UI chat triggers Fitness search with preview and fullscreen state
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
	waitForEmbedFinished
} = require('./helpers/embed-test-helpers');

test.describe('App: Fitness / Skills: Urban Sports Club search', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 1: embed preview renders at /dev/preview/embeds/fitness', async ({ page }: { page: any }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'fitness', log);
		await expect(page.getByTestId('fitness-search-preview').first()).toBeVisible();
	});

	test('Phase 2: CLI apps fitness skills return Urban Sports results', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const locationResult = await runCli(
			apiUrl,
			[
				'apps', 'fitness', 'search_locations',
				'--input', JSON.stringify({
					requests: [{ query: 'HIIT', address: 'Sorauer Str. 12, Berlin', radius_km: 2, limit: 5 }]
				}),
				'--json'
			],
			60_000
		);
		expectCliSuccess(locationResult);
		const locationParsed = parseCliJson(locationResult);
		expect(locationParsed.success).toBe(true);
		expect(locationParsed.data?.provider).toBe('Urban Sports Club');
		expect(locationParsed.data?.results?.[0]?.results?.length).toBeGreaterThan(0);

		const classResult = await runCli(
			apiUrl,
			[
				'apps', 'fitness', 'search_classes',
				'--input', JSON.stringify({
					requests: [{ query: 'Yoga', address: 'Sorauer Str. 12, Berlin', radius_km: 3, attendance_mode: 'onsite', days: 7, limit: 5 }]
				}),
				'--json'
			],
			60_000
		);
		expectCliSuccess(classResult);
		const classParsed = parseCliJson(classResult);
		expect(classParsed.success).toBe(true);
		expect(classParsed.data?.provider).toBe('Urban Sports Club');
		expect(classParsed.data?.results?.[0]?.filters?.attendance_mode).toBe('onsite');
		expect(classParsed.data?.results?.[0]?.results?.length).toBeGreaterThan(0);
	});

	test('Phase 3: Web chat triggers Fitness class search with preview and fullscreen state', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-fitness-urban-sports');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker(
				'Use fitness.search_classes to find onsite yoga classes near Sorauer Str. 12, Berlin within 3 km. Search all Urban Sports plans and show the Fitness search card before answering.',
				'fitness_urban_sports_web'
			),
			logCheckpoint,
			takeStepScreenshot,
			'fitness-urban-sports'
		);

		const streamingEmbed = page.locator('[data-testid="embed-preview"][data-app-id="fitness"][data-skill-id="search_classes"]');
		await expect(streamingEmbed.first()).toBeVisible({ timeout: 60_000 });
		await expect(page.getByTestId('fitness-search-preview').first()).toBeVisible({ timeout: 60_000 });

		const embed = await waitForEmbedFinished(page, 'fitness', 'search_classes', 120_000);
		await expect(embed.getByText('Urban Sports Club', { exact: true })).toBeVisible({ timeout: 30_000 });
		await expect(embed.getByTestId('fitness-search-result-count')).toBeVisible({ timeout: 30_000 });

		await embed.click();
		const fullscreenOverlay = page.getByTestId('fitness-search-fullscreen');
		await expect(fullscreenOverlay).toBeVisible({ timeout: 10_000 });
		await expect(fullscreenOverlay.getByText('Search classes', { exact: true })).toBeVisible({ timeout: 10_000 });
		await expect(fullscreenOverlay.getByText('Urban Sports Club', { exact: true })).toBeVisible({ timeout: 10_000 });

		const resultsGrid = fullscreenOverlay.getByTestId('search-template-grid');
		const emptyState = fullscreenOverlay.getByTestId('fitness-search-empty');
		await expect(async () => {
			const hasGrid = await resultsGrid.isVisible().catch(() => false);
			const hasEmptyState = await emptyState.isVisible().catch(() => false);
			expect(hasGrid || hasEmptyState).toBe(true);
		}).toPass({ timeout: 30_000 });
		logCheckpoint('Fitness fullscreen opened with results or empty state.');

		await fullscreenOverlay.getByTestId('fitness-search-close').click();
		await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5_000 });
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'fitness-urban-sports');
	});
});
