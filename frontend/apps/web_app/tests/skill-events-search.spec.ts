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
const {
	verifyEmbedPreviewPage,
	dismissVisibleNotifications
} = require('./helpers/embed-test-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');
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
const EVENT_SEARCH_MAX_DURATION_MS = 10_000;
const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const SHOULD_CAPTURE_MOBILE_RELOAD = !IS_PROOF_CAPTURE || PROOF_VIDEO_WIDTH === 390;
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const PROOF_CLEAN_CHROME_STYLE = `
html[data-events-proof-clean='true'] .top-buttons,
html[data-events-proof-clean='true'] [data-testid='message-input-wrapper'] {
	display: none !important;
}
html[data-events-proof-clean='true'] [data-testid='active-chat-container'] {
	padding-bottom: 0 !important;
}
`;
const EVENTS_SEARCH_PROOF_CONTRACT = defineVideoProof({
	id: 'events-search-map-response',
	title: 'Events search map response proof',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'request-visible',
			text: 'OpenMates starts a new chat with a request to search Berlin tech events across two weekends.',
			checkpoint: 'request-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'events-embed-visible',
			text: 'The assistant runs the Events search skill, streams event cards, and continues updating results until the response finishes.',
			checkpoint: 'events-embed-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'map-view-populated',
			text: 'The populated map view is visible.',
			checkpoint: 'map-view-populated',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'request-visible',
			checkpoint: 'request-visible',
			visual: 'The user request for two Berlin event searches is visible and contains no raw test marker.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'events-embed-visible',
			checkpoint: 'events-embed-visible',
			visual: 'At least one Events search embed card appears in the assistant response.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'map-view-populated',
			checkpoint: 'map-view-populated',
			visual: 'The final assistant response contains a populated map view with result cards and no Loading preview text.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'phone-layout-visible',
			checkpoint: 'phone-layout-visible',
			visual: 'The phone layout still shows the same populated result section.',
			devices: ['web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

test.describe('App: Events / Skill: search', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	// contract-test: supporting surface=gui.web assertions=events-search.providers.explicit,events-search.surface-parity
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
	// contract-test: supporting surface=gui.web assertions=events-search.surface-parity
	test('Phase 1: embed preview renders at /dev/preview/embeds/events', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'events', log);
	});

	// ── Phase 2: CLI direct skill command ──────────────────────────────────
	// contract-test: direct surface=cli assertions=events-search.request.validated,events-search.results.actionable,events-search.performance.bounded,events-search.surface-parity
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
			EVENT_SEARCH_MAX_DURATION_MS,
			{ record: false }
		);

		expectCliSuccess(result);
		expect(result.durationMs, `events/search took ${Math.round(result.durationMs)}ms`).toBeLessThanOrEqual(EVENT_SEARCH_MAX_DURATION_MS);
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
	// contract-test: supporting surface=cli assertions=events-search.surface-parity
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
	// contract-test: direct surface=gui.web assertions=events-search.surface-parity
	test('Phase 4: Web chat triggers events search with embed', async ({ page }: { page: any }, testInfo: any) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-events-search');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);
		const proof = IS_PROOF_CAPTURE
			? createVideoProofRuntime(EVENTS_SEARCH_PROOF_CONTRACT, {
				device: PROOF_DEVICE,
				attach: testInfo.attach.bind(testInfo),
				captureFrame: () => page.screenshot({ type: 'png' })
			})
			: null;
		const applyProofCleanChrome = async () => {
			if (!proof) return;
			await page.addStyleTag({ content: PROOF_CLEAN_CHROME_STYLE });
			await page.evaluate(() => {
				document.documentElement.dataset.eventsProofClean = 'true';
			});
		};

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);
		await dismissVisibleNotifications(page);

		const message = 'I am planning two Berlin weekends: June 20-21, 2026 and June 27-28, 2026. Find tech events for each weekend and compare the options with event cards and a map.';
		const testMockMarker = withLiveMockMarker('', 'events_search_web').trim();
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'events-search', { testMockMarker });
		await applyProofCleanChrome();
		await dismissVisibleNotifications(page);
		if (proof) {
			await proof.assert('request-visible', async () => {
				const userMessage = page.getByTestId('message-user').last();
				await expect(userMessage).toContainText('I am planning two Berlin weekends');
				await expect(userMessage).not.toContainText('TEST_LIVE_RECORD');
			});
			await proof.checkpoint('request-visible');
		}

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
		if (proof) {
			await proof.assert('events-embed-visible', async () => {
				await expect(embed).toBeVisible();
			});
			await proof.checkpoint('events-embed-visible');
		}

		const finalGroupedView = page.getByTestId('embeds-map-view').last();
		const expectHydratedMap = async (view: any) => {
			const map = view.getByTestId('embeds-map-view-map');
			await expect(map).toBeVisible({ timeout: 30_000 });
			await expect(map).toHaveAttribute('data-map-hydrated', 'true', { timeout: 30_000 });
			await expect(map.getByTestId('embed-leaflet-map')).toHaveAttribute('data-tiles-loaded', 'true', { timeout: 30_000 });
			await expect(map.getByText('Map loading when visible...', { exact: true })).toHaveCount(0);
		};
		await expect(finalGroupedView).toBeVisible({ timeout: 60_000 });
		const finalGroupedCards = finalGroupedView.getByTestId('embeds-map-view-card');
		await expect(finalGroupedCards.first()).toBeVisible({ timeout: 60_000 });
		const finalGroupedCardCount = await finalGroupedCards.count();
		expect(finalGroupedCardCount).toBeGreaterThan(0);
		await expect(finalGroupedView.getByText('Loading preview...', { exact: true })).toHaveCount(0);
		await expect(page.getByText('The AI service encountered an error while processing your request.')).toHaveCount(0);
		await expect(finalGroupedView.getByText('Waiting for source results')).toHaveCount(0);
		await expect(finalGroupedView.getByText('Referenced embeds do not expose coordinates yet.')).toHaveCount(0);
		logCheckpoint(`Resolved final grouped view contains ${finalGroupedCardCount} event embeds.`);
		await expect(
			page.getByTestId('message-content').filter({ has: finalGroupedView })
		).toHaveAttribute('data-streaming', 'false', { timeout: 60_000 });
		await expect(finalGroupedView).toBeVisible();
		await expect(page.getByText('Loading preview...', { exact: true })).toHaveCount(0);
		if (proof) {
			await finalGroupedView.evaluate((element: HTMLElement) => {
				element.scrollIntoView({ block: 'center' });
			});
			await expectHydratedMap(finalGroupedView);
			await proof.assert('map-view-populated', async () => {
				await expect(finalGroupedView).toBeVisible();
				await expect(finalGroupedCards.first()).toBeVisible();
				await expectHydratedMap(finalGroupedView);
				await expect(finalGroupedView.getByText('Loading preview...', { exact: true })).toHaveCount(0);
			});
			await proof.checkpoint('map-view-populated');
			if (PROOF_DEVICE === 'web-phone') {
				await finalGroupedView.evaluate((element: HTMLElement) => {
					element.scrollIntoView({ block: 'start' });
				});
				await proof.assert('phone-layout-visible', async () => {
					await expect(finalGroupedView).toBeVisible();
					await expect(finalGroupedCards.first()).toBeVisible();
				});
				await proof.checkpoint('phone-layout-visible');
			}
		}

		if (!IS_PROOF_CAPTURE) {
			const stabilityProbe = await page.evaluate(() => {
				const value = crypto.randomUUID();
				(window as any).__reportIssueStabilityProbe = value;
				return value;
			});
			await dismissVisibleNotifications(page);
			const directReportIssue = page.getByRole('button', { name: /^Report Issue$/i }).first();
			if (await directReportIssue.isVisible().catch(() => false)) {
				await directReportIssue.click();
			} else {
				await page.locator('#settings-menu-toggle').click();
				const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
				await expect(settingsMenu).toBeVisible({ timeout: 10_000 });
				await settingsMenu
					.getByRole('menuitem', { name: /report.*issue|issue.*report|problem.*melden/i })
					.first()
					.click();
			}
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
		}

		const reloadAndAwaitResults = async () => {
			await page.reload({ waitUntil: 'domcontentloaded' });
			await applyProofCleanChrome();
			const view = page.getByTestId('embeds-map-view').last();
			await expect(view).toBeVisible({ timeout: 60_000 });
			await expect(view.getByTestId('embeds-map-view-card').first()).toBeVisible({
				timeout: 60_000
			});
			return view;
		};
		if (proof) {
			await proof.attach();
			return;
		}

		const reloadedGroupedView = await reloadAndAwaitResults();
		await expect(page.getByText('Loading preview...', { exact: true })).toHaveCount(0);
		await takeStepScreenshot(page, 'events-search-embeds-after-reload');
		if (proof) {
			await reloadedGroupedView.evaluate((element: HTMLElement) => {
				element.scrollIntoView({ block: 'center' });
			});
			await expectHydratedMap(reloadedGroupedView);
		}
		if (SHOULD_CAPTURE_MOBILE_RELOAD) {
			await page.setViewportSize({ width: 390, height: 844 });
			await expect(reloadedGroupedView).toBeVisible();
			await expect(reloadedGroupedView.getByTestId('embeds-map-view-card').first()).toBeVisible();
			await reloadedGroupedView.evaluate((element: HTMLElement) => {
				element.scrollIntoView({ block: 'start' });
			});
			await takeStepScreenshot(page, 'events-search-embeds-after-reload-mobile');
			if (proof) {
				await proof.assert('phone-layout-visible', async () => {
					await expect(reloadedGroupedView).toBeVisible();
					await expect(reloadedGroupedView.getByTestId('embeds-map-view-card').first()).toBeVisible();
				});
				await proof.checkpoint('phone-layout-visible');
			}
		}
		if (!IS_PROOF_CAPTURE) {
			await page.setViewportSize({ width: 1280, height: 720 });
		}
		logCheckpoint('Completed app-skill group retained populated cards after reload.');

		if (!IS_PROOF_CAPTURE) {
			await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'events-search');
		}
	});
});
