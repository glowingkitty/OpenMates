/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for events/search skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/events
 * Phase 2: CLI direct skill command (openmates apps events search --json)
 * Phase 3: CLI chat send triggers skill (openmates chats new "..." --json)
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
	getE2EDebugUrl,
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
const {
	saveCurrentFullscreenEmbed,
	verifySavedMemoryEntry
} = require('./helpers/saved-memory-test-helpers');
const {
	expectSettingsProviderIcons,
	expectSkillCardProviderIcons
} = require('./helpers/provider-icon-helpers');
const { appsMetadata } = require('../../../packages/ui/src/data/appsMetadata');

const EVENT_SEARCH_PROVIDERS = [
	'Meetup',
	'Luma',
	'Eventbrite',
	'Google Events',
	'Resident Advisor',
	'Siegessäule',
	'Berlin Philharmonic'
];

async function expectCalendarDownload(page: any, logCheckpoint: (message: string) => void): Promise<void> {
	const dismissButtons = page.getByTestId('notification-dismiss');
	const dismissCount = await dismissButtons.count();
	for (let i = 0; i < dismissCount; i += 1) {
		await dismissButtons.nth(i).click().catch(() => undefined);
	}
	if (dismissCount > 0) {
		logCheckpoint(`Dismissed ${dismissCount} notification(s) before calendar download.`);
	}

	const calendarButton = page.getByTestId('embed-calendar-button');
	await expect(calendarButton).toBeVisible({ timeout: 5000 });

	const downloadPromise = page.waitForEvent('download', { timeout: 15000 });
	await calendarButton.click();
	const download = await downloadPromise;
	const suggestedFilename = download.suggestedFilename();
	expect(suggestedFilename).toMatch(/\.ics$/);
	expect(await download.failure()).toBeNull();
	logCheckpoint(`Calendar download started: ${suggestedFilename}`);
}

test.describe('App: Events / Skill: search', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 0: app store metadata and UI expose event providers with loaded icons', async ({ page }: { page: any }) => {
		test.setTimeout(120_000);

		const events = appsMetadata.events;
		expect(events, 'events app should appear in app store metadata').toBeTruthy();
		const searchSkill = (events.skills || []).find((skill: { id: string }) => skill.id === 'search');
		expect(searchSkill, 'events search skill should appear in app store metadata').toBeTruthy();
		expect(searchSkill.providers).toEqual(EVENT_SEARCH_PROVIDERS);

		await page.setViewportSize({ width: 1600, height: 900 });
		await page.goto(getE2EDebugUrl('/#settings/app_store/events'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		const settingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="app_store/events"]');
		await expect(settingsMenu).toBeVisible({ timeout: 15_000 });

		const searchSkillCard = settingsMenu.getByTestId('app-store-card').filter({ hasText: /^Search\b/ }).first();
		await expectSkillCardProviderIcons(searchSkillCard, EVENT_SEARCH_PROVIDERS);

		await page.goto(getE2EDebugUrl('/#settings/app_store/events/skill/search'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		const skillSettingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="app_store/events/skill/search"]');
		await expect(skillSettingsMenu).toBeVisible({ timeout: 15_000 });
		await expectSettingsProviderIcons(skillSettingsMenu, EVENT_SEARCH_PROVIDERS);
	});

	// ── Phase 1: Embed preview renders ─────────────────────────────────────
	test('Phase 1: embed preview renders at /dev/preview/embeds/events', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'events', log);
	});

	// ── Phase 2: CLI direct skill command ──────────────────────────────────
	test('Phase 2: CLI apps events search returns results', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const result = await runCli(
			apiUrl,
			[
				'apps', 'events', 'search',
				'--input', JSON.stringify({
					requests: [{ query: 'technology meetup', location: 'Berlin', provider: 'auto' }]
				}),
				'--json'
			],
			45_000
		);

		expectCliSuccess(result);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);

		const skillData = parsed.data;
		expect(Array.isArray(skillData.results)).toBe(true);
		expect(skillData.results.length).toBeGreaterThan(0);

		const events = skillData.results[0].results || [];
		expect(events.length).toBeGreaterThan(0);

		const ev = events[0];
		expect(ev.name || ev.title).toBeTruthy();
		expect(ev.url).toBeTruthy();
		console.log(`[P2] events/search found ${events.length} event(s). First: "${ev.name || ev.title}"`);
	});

	// ── Phase 3: CLI chat send triggers skill ──────────────────────────────
	test('Phase 3: CLI chats new triggers events search', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const message = withLiveMockMarker('Find tech events in Berlin this week', 'events_search_cli');
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 60_000);
		expectCliSuccess(result);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	// ── Phase 4: Web UI chat triggers skill ────────────────────────────────
	test('Phase 4: Web chat triggers events search with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-events-search');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		const message = withLiveMockMarker(
			'Find tech events in Berlin this week',
			'events_search_web'
		);
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'events-search');

		logCheckpoint('Waiting for events search embed to finish...');
		const embed = await waitForEmbedFinished(page, 'events', 'search');
		logCheckpoint('Events search embed finished.');
		await takeStepScreenshot(page, 'events-search-embed-finished');

		const fullscreenOverlay = await openFullscreen(page, embed);
		logCheckpoint('Fullscreen opened.');

		const resultCards = await verifySearchGrid(fullscreenOverlay);
		const count = await resultCards.count();
		logCheckpoint(`Found ${count} event result(s) in fullscreen grid.`);

		await resultCards.first().click();
		await expectCalendarDownload(page, logCheckpoint);
		const savedTitle = await saveCurrentFullscreenEmbed(page, logCheckpoint, undefined, { expectReminder: true });

		await closeFullscreen(page, fullscreenOverlay);
		logCheckpoint('Fullscreen closed.');
		await verifySavedMemoryEntry(page, 'events', 'saved_events', savedTitle, logCheckpoint);

		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'events-search');
	});
});
