/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for events/search skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/events
 * Phase 2: CLI direct skill command (openmates apps events search --json)
 * Phase 3: CLI chat send triggers skill (openmates chats new "..." --json)
 * Phase 4: Web UI chat preserves embed refs from streaming through the final grouped view
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
const { verifyEmbedPreviewPage } = require('./helpers/embed-test-helpers');
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
	'Berlin Philharmonic',
	'GPN24',
	'39C3',
	'38C3',
	'37C3'
];

const EVENT_SEARCH_CARD_ICON_PROVIDERS = [
	'Meetup',
	'Luma',
	'Eventbrite',
	'Google Events',
	'Resident Advisor',
	'Siegessäule',
	'Berlin Philharmonic'
];

const EVENT_SEARCH_CARD_SELECTOR = '[data-testid="embed-preview"][data-app-id="events"][data-skill-id="search"]';
const EVENT_SEARCH_FIRST_RANGE = 'Jun 20, 2026 - Jun 21, 2026';
const EVENT_SEARCH_SECOND_RANGE = 'Jun 27, 2026 - Jun 28, 2026';

test.describe('App: Events / Skill: search', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 0: Apps metadata and UI expose event providers with loaded icons', async ({ page }: { page: any }) => {
		test.setTimeout(120_000);

		const events = appsMetadata.events;
		expect(events, 'events app should appear in Apps metadata').toBeTruthy();
		const searchSkill = (events.skills || []).find((skill: { id: string }) => skill.id === 'search');
		expect(searchSkill, 'events search skill should appear in Apps metadata').toBeTruthy();
		expect(searchSkill.providers).toEqual(EVENT_SEARCH_PROVIDERS);

		await page.setViewportSize({ width: 1600, height: 900 });
		await page.goto(getE2EDebugUrl('/#settings/apps/events'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		const settingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="apps/events"]');
		await expect(settingsMenu).toBeVisible({ timeout: 15_000 });

		const searchSkillCard = settingsMenu.getByTestId('app-store-card').filter({ hasText: 'Search' }).first();
		await expectSkillCardProviderIcons(searchSkillCard, EVENT_SEARCH_CARD_ICON_PROVIDERS);

		await page.goto(getE2EDebugUrl('/#settings/apps/events/skill/search'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		const skillSettingsMenu = page.locator('[data-testid="settings-menu"][data-active-view="apps/events/skill/search"]');
		await expect(skillSettingsMenu).toBeVisible({ timeout: 15_000 });
		await expectSettingsProviderIcons(skillSettingsMenu, EVENT_SEARCH_CARD_ICON_PROVIDERS);
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
			'Use events.search to make two separate searches for tech events in Berlin. First search: start_date 2026-06-20T00:00:00+02:00 and end_date 2026-06-21T23:59:59+02:00. Second search: start_date 2026-06-27T00:00:00+02:00 and end_date 2026-06-28T23:59:59+02:00. Show both event search cards before answering.',
			'events_search_web'
		);
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'events-search');

		logCheckpoint('Waiting for events search embeds to appear during streaming...');
		const streamingEmbeds = page.locator(EVENT_SEARCH_CARD_SELECTOR);
		const rangedEmbeds = streamingEmbeds.filter({ has: page.getByTestId('events-search-range') });
		await expect(streamingEmbeds.first()).toBeVisible({ timeout: 60_000 });
		await expect(rangedEmbeds.first()).toBeVisible({ timeout: 60_000 });
		await expect(page.getByTestId('events-search-range').filter({ hasText: EVENT_SEARCH_FIRST_RANGE })).toBeVisible({ timeout: 60_000 });
		await expect(page.getByTestId('events-search-range').filter({ hasText: EVENT_SEARCH_SECOND_RANGE })).toBeVisible({ timeout: 60_000 });
		const embed = rangedEmbeds
			.filter({ has: page.getByTestId('events-search-range').filter({ hasText: EVENT_SEARCH_SECOND_RANGE }) })
			.last();
		await expect(embed).toBeVisible({ timeout: 60_000 });
		const streamingMessageContent = page
			.getByTestId('message-content')
			.filter({ has: embed });
		await expect(streamingMessageContent).toHaveAttribute('data-streaming', 'true');
		await takeStepScreenshot(page, 'events-search-embeds-during-streaming');

		const finalGroupedView = page.getByTestId('embeds-map-view').last();
		await expect(finalGroupedView).toBeVisible({ timeout: 60_000 });
		const finalGroupedCards = finalGroupedView.getByTestId('embeds-map-view-card');
		const finalGroupedCardCount = await finalGroupedCards.count();
		expect(finalGroupedCardCount).toBeGreaterThan(0);
		await expect(page.getByText('Loading preview...', { exact: true })).toHaveCount(0);
		logCheckpoint(`Resolved non-streaming final grouped view contains ${finalGroupedCardCount} event embeds.`);

		const stabilityProbe = await page.evaluate(() => {
			const value = crypto.randomUUID();
			(window as any).__reportIssueStabilityProbe = value;
			return value;
		});
		await page.locator('#settings-menu-toggle').click();
		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		await expect(settingsMenu).toBeVisible({ timeout: 10_000 });
		await settingsMenu
			.getByRole('menuitem', { name: /report.*issue|issue.*report|problem.*melden/i })
			.first()
			.click();
		await expect(page.getByTestId('report-issue-form')).toBeVisible({ timeout: 15_000 });

		expect(await page.evaluate(() => (window as any).__reportIssueStabilityProbe)).toBe(stabilityProbe);
		await expect(finalGroupedView).toBeVisible();
		await expect(
			page.getByTestId('message-content').filter({ has: finalGroupedView })
		).toHaveAttribute('data-streaming', 'false');
		expect(await finalGroupedCards.count()).toBe(finalGroupedCardCount);
		await expect(page.getByText('Loading preview...', { exact: true })).toHaveCount(0);
		logCheckpoint('Report Issue opened without reloading the page or changing final grouped embeds.');

		const closeSettings = page.getByTestId('icon-button-close');
		if (await closeSettings.isVisible().catch(() => false)) {
			await closeSettings.click();
		}

		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'events-search');
	});
});
