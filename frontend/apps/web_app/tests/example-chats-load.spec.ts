/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Example chats loading test: verifies that hardcoded example chats render
 * for NEW USERS (clean browser context, no IndexedDB cache) in the
 * the public example-chat catalog.
 *
 * Architecture: Example chats are now static/hardcoded in exampleChatStore.ts
 * (no backend /v1/demo/chats API call). The ExampleChatsGroup component reads
 * from getAllExampleChats() and renders chat embed cards.
 *
 * Test strategy:
 *   1. Open the app with a clean browser (simulating a brand-new user)
 *   2. Verify ExampleChatsGroup renders with actual chat cards
 *   3. Verify cards have titles and are clickable
 *
 * No credentials required — this tests the non-authenticated flow.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { openFullscreen, verifySearchGrid } = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const REMOVED_GENERATED_AUDIO_EXAMPLE_SLUGS = [
	'audio-generate-confirmation-tick',
	'audio-speak-welcome-message'
];

const GENERATED_AUDIO_EXAMPLE_CASES = [
	{
		chatId: 'example-audio-generate-openmates-success-chime',
		slug: 'audio-generate-openmates-success-chime',
		skillId: 'generate',
		promptSnippet: 'Create a short, friendly success chime for an OpenMates workflow finishing'
	},
	{
		chatId: 'example-audio-speak-openmates-welcome-message',
		slug: 'audio-speak-openmates-welcome-message',
		skillId: 'speak',
		promptSnippet: 'Say this as a warm, natural welcome message'
	}
] as const;

const PUBLIC_EXAMPLE_BROKEN_MARKERS = [
	'Presigned URL request failed',
	'Network error fetching S3',
	'Transcript not available',
	'[Interactive Question - Invalid JSON]',
	'vault_wrapped_aes_key',
	'vault:v1:',
	'audio_base64',
	'aes_key',
	'aes_nonce',
	's3_base_url',
	'dev-openmates-chatfiles',
	'chatfiles/',
	's3_key:',
	'docx_s3_key:',
	'screenshot_s3_keys:',
	'app_settings_memories_request',
	'app_settings_memories_response',
	'git checkout -- .',
	'"type":"focus_mode_activation"',
	'"type": "focus_mode_activation"'
];

function countMatches(text: string, pattern: RegExp): number {
	return [...text.matchAll(pattern)].length;
}

function extractExampleSlugs(html: string): string[] {
	const matches = [...html.matchAll(/href="\/example\/([^"]+)"/g)];
	return [...new Set(matches.map((match) => match[1]))];
}

function extractJsonLd(html: string): Record<string, any> {
	const match = html.match(/<script\s+type="application\/ld\+json">([\s\S]*?)<\/script>/i);
	expect(match, 'JSON-LD script should exist').not.toBeNull();
	return JSON.parse(match[1]);
}

async function expectAudioCanPlay(audioLocator: any, label: string): Promise<void> {
	await expect(async () => {
		const state = await audioLocator.evaluate(async (audio: HTMLAudioElement) => {
			audio.muted = true;
			await audio.play();
			await new Promise((resolve) => setTimeout(resolve, 800));
			const result = {
				currentTime: audio.currentTime,
				duration: audio.duration,
				readyState: audio.readyState
			};
			audio.pause();
			return result;
		});

		expect(state.readyState, `${label} should load audio metadata`).toBeGreaterThanOrEqual(1);
		expect(Number.isFinite(state.duration), `${label} should have finite duration`).toBe(true);
		expect(state.duration, `${label} should have non-zero duration`).toBeGreaterThan(0);
		expect(state.currentTime, `${label} should advance during playback`).toBeGreaterThan(0);
	}).toPass({ timeout: 30000 });
}

async function expectGuestSlideZeroIntro(page: any) {
	await expect(page.getByTestId('welcome-content')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('landing-intro-expanded')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('daily-inspiration-banner')).toHaveAttribute(
		'data-landing-intro-phase',
		/^(expanded|expanding)$/,
		{ timeout: 10000 }
	);
}

async function expectNoPreviewOverflow(locator: any, label: string) {
	const overflow = await locator.evaluate((node: HTMLElement) => {
		const epsilon = 1;
		const nodeRect = node.getBoundingClientRect();
		const overflowingChildren = Array.from(node.querySelectorAll<HTMLElement>('[data-testid]'))
			.filter((child) => {
				const style = window.getComputedStyle(child);
				return style.display !== 'none' && style.visibility !== 'hidden' && child.offsetParent !== null;
			})
			.map((child) => ({
				testId: child.getAttribute('data-testid'),
				rect: child.getBoundingClientRect(),
				text: child.textContent?.replace(/\s+/g, ' ').trim().slice(0, 80) || ''
			}))
			.filter(({ rect }) =>
				rect.left < nodeRect.left - epsilon ||
				rect.right > nodeRect.right + epsilon ||
				rect.top < nodeRect.top - epsilon ||
				rect.bottom > nodeRect.bottom + epsilon
			)
			.map(({ testId, text }) => ({ testId, text }));

		return {
			selfOverflows:
				node.scrollWidth > node.clientWidth + epsilon ||
				node.scrollHeight > node.clientHeight + epsilon,
			overflowingChildren
		};
	});

	expect(overflow, label).toEqual({ selfOverflows: false, overflowingChildren: [] });
}

test.describe('Example chats loading for new users', () => {
	async function ensureSidebarVisible(page: any): Promise<void> {
		const history = page.getByTestId('activity-history-wrapper');
		if (await history.isVisible().catch(() => false)) {
			return;
		}

		const toggle = page.getByTestId('sidebar-toggle');
		await expect(toggle).toBeVisible({ timeout: 10000 });
		await toggle.click();
		await expect(history).toBeVisible({ timeout: 10000 });
	}

	function examplesSidebarGroup(page: any): any {
		return page.locator('[data-testid="chat-group"][data-group-key="examples"]').first();
	}

	async function sidebarExampleIds(page: any): Promise<string[]> {
		const group = examplesSidebarGroup(page);
		await expect(group).toBeVisible({ timeout: 15000 });
		return group.getByTestId('chat-item-wrapper').evaluateAll((nodes: Element[]) =>
			nodes
				.map((node) => node.getAttribute('data-chat-id') || '')
				.filter(Boolean)
		);
	}

	// contract-test: direct surface=gui.web assertions=public-example-chats.catalog.discoverable,public-example-chats.surface.semantic-parity
	test('guest show-all examples uses expanded resume cards and global search covers every example', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);
		await page.setViewportSize({ width: 390, height: 844 });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await expectGuestSlideZeroIntro(page);
		await page.getByTestId('daily-inspiration-next').click();
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0, { timeout: 5000 });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText('Actionable', { timeout: 5000 });
		const previousSlideId = await page
			.locator('[data-testid="daily-inspiration-mounted-slide"][data-current="true"]')
			.getAttribute('data-slide-index');

		const showAllExamples = page.getByTestId('guest-show-all-examples');
		await expect(showAllExamples).toBeVisible({ timeout: 10000 });
		await showAllExamples.click();

		const allExamplesView = page.getByTestId('guest-all-examples-view');
		await expect(allExamplesView).toBeVisible({ timeout: 10000 });
		await expect(allExamplesView.getByText('Explore real OpenMates chats')).toHaveCount(0);
		await expect(allExamplesView.getByText('Pick one to see how the workspace feels in practice.')).toHaveCount(0);

		const allExampleCards = allExamplesView.getByTestId('resume-chat-large-card');
		await expect.poll(async () => allExampleCards.count(), {
			message: 'Show all examples should render the full unfiltered example catalog, not the current slide subset',
			timeout: 10000
		}).toBeGreaterThan(10);
		await expect(allExamplesView.getByTestId('guest-all-example-card')).toHaveCount(0);
		await expect(allExamplesView.locator('[data-chat-id="example-screenshot-to-html-pricing"]')).toBeVisible({ timeout: 10000 });

		const backToRecent = page.getByTestId('guest-all-examples-back');
		const searchAllExamples = page.getByTestId('guest-all-examples-search');
		await expect(backToRecent).toBeVisible({ timeout: 10000 });
		await expect(searchAllExamples).toBeVisible({ timeout: 10000 });
		await expect(backToRecent).toHaveCSS('box-shadow', 'none');
		await expect(searchAllExamples).toHaveCSS('box-shadow', 'none');
		await expect(backToRecent).toHaveCSS('text-shadow', 'none');
		await expect(searchAllExamples).toHaveCSS('text-shadow', 'none');

		const firstCardTop = await allExampleCards.first().evaluate((node: HTMLElement) => node.getBoundingClientRect().top);
		expect(firstCardTop, 'All examples should start near the visible content top, without the guest intro banner reserve gap.').toBeLessThan(420);
		const expandedLayout = await page.getByTestId('guest-all-examples-grid').evaluate((grid: HTMLElement) => {
			const gridRect = grid.getBoundingClientRect();
			const composer = document.querySelector<HTMLElement>('[data-testid="message-input-wrapper"]');
			const composerRect = composer?.getBoundingClientRect();
			return {
				scrollTop: grid.scrollTop,
				bottomGap: composerRect ? composerRect.top - gridRect.bottom : Number.POSITIVE_INFINITY
			};
		});
		expect(expandedLayout.scrollTop, 'Expanded examples should open at the top of the result list.').toBe(0);
		expect(expandedLayout.bottomGap, 'Expanded examples should use the available height above the composer.').toBeLessThanOrEqual(24);

		await backToRecent.click();
		await expect(allExamplesView).toHaveCount(0);
		await expect(page.getByTestId('guest-show-all-examples')).toBeVisible({ timeout: 10000 });
		await expect(page.locator('[data-testid="daily-inspiration-mounted-slide"][data-current="true"]'))
			.toHaveAttribute('data-slide-index', previousSlideId ?? '1');

		await page.getByTestId('guest-show-all-examples').click();
		await expect(page.getByTestId('guest-all-examples-view')).toBeVisible({ timeout: 10000 });

		await expect(searchAllExamples).toBeVisible({ timeout: 10000 });
		await searchAllExamples.click();

		const searchInput = page.getByTestId('search-input');
		await expect(searchInput).toBeVisible({ timeout: 10000 });
		await searchInput.fill('screenshot');

		const searchResults = page.getByTestId('search-results');
		await expect(searchResults).toBeVisible({ timeout: 10000 });
		await expect(
			page.locator('[data-testid="search-chat-item"][data-result-id="example-screenshot-to-html-pricing"]')
		).toBeVisible({ timeout: 30000 });
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test('deep research example renders static sub-chat cards without a forced focus mention', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/#chat-id=example-us-egg-prices-deep'), {
			waitUntil: 'domcontentloaded'
		});

		const userMessage = page.getByTestId('user-message-content').filter({
			hasText: 'Why did US egg prices stay high after avian flu eased?'
		});
		await expect(userMessage).toBeVisible({ timeout: 15000 });
		await expect(
			userMessage,
			'Deep research example should demonstrate auto-selection, not @focus forcing.'
		).not.toContainText('@focus:');

		const carousel = page.getByTestId('sub-chats-carousel');
		await expect(carousel).toBeVisible({ timeout: 15000 });
		await expect(carousel.getByTestId('sub-chat-card')).toHaveCount(3);

		const focusBar = page.getByTestId('focus-mode-bar');
		await expect(focusBar).toBeVisible({ timeout: 15000 });
		await expect(focusBar.getByTestId('focus-status-label')).toContainText('Deep research');
		await expect(page.locator('body')).not.toContainText('"type":"focus_mode_activation"');
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.navigation.static-public-link,public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity,chat-share-settings.generated-link-controls,chat-share-settings.shell-navigation
	test('guest example chat exposes share and chat settings with a static public link', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		const exampleChatId = 'example-ai-workshops-meetups-berlin';

		await page.goto(getE2EDebugUrl(`/#chat-id=${exampleChatId}`), {
			waitUntil: 'domcontentloaded'
		});

		await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });

		const appSkillGroup = page.getByTestId('app-skill-embed-group').first();
		await expect(appSkillGroup, 'Berlin AI workshops example should render its grouped app-skill previews').toBeVisible({ timeout: 15000 });
		await expect(appSkillGroup.getByText('5 app skills used:', { exact: true })).toBeVisible({
			timeout: 15000
		});

		const appSkillItems = appSkillGroup.locator('[data-embed-type="app-skill-use"][data-embed-item-id]');
		await expect(appSkillItems, 'Berlin AI workshops example should keep all five parent embeds in the group').toHaveCount(5, {
			timeout: 15000
		});

		const finishedPreviews = appSkillGroup.locator('[data-testid="embed-preview"][data-status="finished"]');
		await expect(finishedPreviews, 'Berlin AI workshops example should mount all five finished app-skill previews').toHaveCount(5, {
			timeout: 15000
		});

		const eventsPreviews = appSkillGroup.locator('[data-testid="embed-preview"][data-app-id="events"][data-skill-id="search"]');
		await expect(eventsPreviews, 'Berlin AI workshops example should render three event-search previews').toHaveCount(3);
		const webPreviews = appSkillGroup.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]');
		await expect(webPreviews, 'Berlin AI workshops example should render two web-search previews').toHaveCount(2);
		for (let index = 0; index < 2; index += 1) {
			await expect(webPreviews.nth(index), `web-search preview ${index + 1} should use decoded result_count`).toContainText('+ 6 more');
			await expect(webPreviews.nth(index), `web-search preview ${index + 1} should not hide a known result count behind a generic fallback`).not.toContainText('Open to view results');
		}
		for (let index = 0; index < 3; index += 1) {
			await expect(eventsPreviews.nth(index), `event-search preview ${index + 1} should use decoded result_count`).toContainText('+ 10 more');
		}

		await expect(page.getByTestId('chat-share-button')).toBeVisible({ timeout: 10000 });
		await expect(page.getByTestId('chat-details-button')).toBeVisible({ timeout: 10000 });

		await page.getByTestId('chat-details-button').click();
		const settingsMenu = page.getByTestId('settings-menu');
		await expect(settingsMenu).toBeVisible({ timeout: 10000 });
		await expect(settingsMenu).toHaveAttribute('data-active-view', `chats/${exampleChatId}`, {
			timeout: 10000
		});
		await expect(settingsMenu.getByTestId('chat-settings-tabpanel-share')).toBeVisible({ timeout: 10000 });

		const expectedShareUrl = await page.evaluate((chatId: string) => `${window.location.origin}/#chat-id=${chatId}`, exampleChatId);
		await expect(settingsMenu.getByTestId('chat-settings-share-readonly')).toHaveCount(0);
		await expect(settingsMenu.getByTestId('share-short-link-copy')).toHaveCount(0);
		await expect(settingsMenu.getByTestId('share-short-link-url')).toHaveCount(0);
		await settingsMenu.getByTestId('chat-settings-share-show-url').click();
		const publicUrl = settingsMenu.getByTestId('chat-settings-share-url');
		await expect(publicUrl).toHaveText(expectedShareUrl, {
			timeout: 10000
		});
		await expect(publicUrl).toHaveCSS('user-select', 'text');
		await expect(settingsMenu.getByTestId('chat-settings-share-password')).toHaveCount(0);
		await expect(settingsMenu.getByTestId('chat-settings-share-community')).toHaveCount(0);
		await expect(settingsMenu.getByTestId('chat-settings-share-expire')).toHaveCount(0);
		await expect(settingsMenu.getByTestId('share-generate-link')).toHaveCount(0);
		await settingsMenu.getByTestId('banner-back-button').click();
		await expect(settingsMenu).toHaveAttribute('data-active-view', 'main', { timeout: 10000 });
		await expect(settingsMenu).not.toContainText(/\[T:settings\.chats\]/i);
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.navigation.static-public-link,public-example-chats.transcript.safe-rendering
	test('memory example cards update the reloadable chat hash on wide viewports', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);
		await page.setViewportSize({ width: 1600, height: 900 });

		await page.goto(getE2EDebugUrl('/#settings/apps/books/settings_memories/currently_reading'), {
			waitUntil: 'domcontentloaded'
		});
		await page.waitForLoadState('networkidle');

		const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
		await expect(settingsMenu).toBeVisible({ timeout: 15000 });
		const exampleCard = settingsMenu
			.locator('[data-testid="app-store-example-chat-card"][data-chat-id="example-memory-books-currently-reading"]')
			.first();
		await expect(exampleCard).toBeVisible({ timeout: 15000 });

		await exampleCard.click();
		await expect(page).toHaveURL(/[&#]chat-id=example-memory-books-currently-reading/, { timeout: 15000 });
		await expect(page.getByTestId('chat-history-container')).toBeVisible({ timeout: 15000 });

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page).toHaveURL(/[&#]chat-id=example-memory-books-currently-reading/, { timeout: 15000 });
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'spoiler-free one-week reading plan' })).toBeVisible({ timeout: 15000 });
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering
	test('reported memory examples render current text content without interactive-question errors', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);

		await page.goto(getE2EDebugUrl('/#chat-id=example-memory-books-currently-reading'), {
			waitUntil: 'domcontentloaded'
		});
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'spoiler-free one-week reading plan' })).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('app-settings-memories-summary')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('app-settings-memory-category-badge')).toBeVisible({ timeout: 15000 });
		await expect(page.locator('body')).not.toContainText('[Interactive Question - Invalid JSON]');
		await expect(page.locator('body')).not.toContainText('app_settings_memories_request');
		await expect(page.locator('body')).not.toContainText('app_settings_memories_response');
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Project Hail Mary' })).toBeVisible({ timeout: 15000 });

		await page.goto(getE2EDebugUrl('/#chat-id=example-memory-mail-writing-styles'), {
			waitUntil: 'domcontentloaded'
		});
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Friday Update - [Project Name]' })).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('app-settings-memories-summary')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('app-settings-memory-category-badge')).toBeVisible({ timeout: 15000 });
		await expect(page.locator('body')).not.toContainText('[Interactive Question - Invalid JSON]');
		await expect(page.locator('body')).not.toContainText('app_settings_memories_request');
		await expect(page.locator('body')).not.toContainText('app_settings_memories_response');
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Best, Alex' })).toBeVisible({ timeout: 15000 });
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.history.explicit-forgotten-reveal,public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test('privacy-first local AI example hides compressed history behind forgotten messages', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);

		await page.goto(getE2EDebugUrl('/#chat-id=example-privacy-first-local-ai'), {
			waitUntil: 'domcontentloaded'
		});

		await expect(page.getByTestId('chat-history-container')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('show-older-messages')).toHaveCount(0);

		const compressionSummary = page.getByTestId('message-system').filter({ hasText: 'Conversation History Summary' });
		await expect(compressionSummary).toBeVisible({ timeout: 15000 });
		await expect(compressionSummary.locator('h2, h3').filter({ hasText: 'Conversation History Summary' })).toBeVisible({ timeout: 15000 });
		await expect(compressionSummary.locator('strong').filter({ hasText: 'Compressed Messages:' })).toBeVisible({ timeout: 15000 });
		await expect(compressionSummary).not.toContainText('## Conversation History Summary');
		await expect(compressionSummary).not.toContainText('**Compressed Messages:**');

		const summaryShowMore = compressionSummary.getByTestId('compression-summary-toggle');
		await expect(summaryShowMore).toBeVisible({ timeout: 10000 });
		await expect(summaryShowMore).toHaveText(/Show full summary|Show more/);
		await expect(compressionSummary).not.toContainText('Referenced Artifacts');
		await summaryShowMore.click();
		await expect(summaryShowMore).toHaveText(/Show less/);
		await expect(compressionSummary).toContainText('Referenced Artifacts', { timeout: 15000 });

		await page.keyboard.press('End');

		const sprintBacklogPrompt = page.locator(
			'[data-testid="message-user"][data-message-id="6adc84b3-2fa5-4f2c-9e46-a35fff64d220"]'
		);
		const sprintBacklogResponse = page.locator(
			'[data-testid="message-assistant"][data-message-id="207ca93d-3959-5db1-869c-6368232737ee"]'
		);
		const latestPrompt = page.locator(
			'[data-testid="message-user"][data-message-id="f2dd7311-d9eb-4c73-87a8-5a7bc5b815c4"]'
		);
		const latestResponse = page.locator(
			'[data-testid="message-assistant"][data-message-id="5c1d9872-f3c9-59b3-9730-7bc5376e70cf"]'
		);

		await expect(sprintBacklogPrompt).toBeVisible({ timeout: 15000 });
		await expect(sprintBacklogResponse).toBeVisible({ timeout: 15000 });
		await expect(latestPrompt).toBeVisible({ timeout: 15000 });
		await expect(latestResponse).toBeVisible({ timeout: 15000 });

		const firstPrompt = page.getByTestId('user-message-content').filter({
			hasText: 'I want to build a privacy-first AI productivity company from zero'
		});
		await expect(firstPrompt).toHaveCount(0);

		const visibleMessageCount = await page.locator('[data-testid="message-user"], [data-testid="message-assistant"]').count();
		const forgottenMessagesToggle = page.getByTestId('show-forgotten-messages');
		await forgottenMessagesToggle.click();

		await expect.poll(async () => page.locator('[data-testid="message-user"], [data-testid="message-assistant"]').count(), {
			message: 'Show forgotten messages should reveal the compressed static example history',
			timeout: 10000
		}).toBeGreaterThan(visibleMessageCount);
		await expect(firstPrompt).toBeVisible({ timeout: 10000 });
		await expect(forgottenMessagesToggle).toContainText('Hide old forgotten messages', { timeout: 10000 });

		await firstPrompt.getByTestId('remember-forgotten-message').click();
		const messageEditor = page.getByTestId('message-editor');
		await expect(messageEditor).toContainText('Remember my earlier message:', { timeout: 10000 });
		await expect(messageEditor).toContainText('privacy-first AI productivity company from zero', { timeout: 10000 });

		await page.locator('[data-testid="new-chat-cta-fullwidth"], [data-testid="new-chat-button"]').first().click();
		await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
		await expect(page.getByTestId('message-editor').locator('[contenteditable="true"]').first()).toBeFocused({ timeout: 5000 });
		await expect(
			page.locator('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]').first()
		).toBeVisible({ timeout: 10000 });
		await expect(compressionSummary).toHaveCount(0);

		await page.getByTestId('profile-container').click();
		await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 8000 });
		await expect(compressionSummary).toHaveCount(0);
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test('nutrition example renders Edamam recipe search embed card', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);

		await page.goto(getE2EDebugUrl('/#chat-id=example-chickpea-spinach-protein-dinners'), {
			waitUntil: 'domcontentloaded'
		});

		await expect(page.getByTestId('user-message-content').filter({
			hasText: 'Find 3 vegetarian chickpea and spinach dinner recipes'
		})).toBeVisible({ timeout: 15000 });

		const nutritionSearchCardSelector = '[data-testid="embed-preview"][data-app-id="nutrition"][data-skill-id="search_recipes"][data-status="finished"]';
		const assistantMessageWithNutritionCard = page
			.getByTestId('message-assistant')
			.filter({ hasText: 'Here are three delicious' })
			.filter({ has: page.locator(nutritionSearchCardSelector) })
			.first();
		await expect(assistantMessageWithNutritionCard).toBeVisible({ timeout: 15000 });

		const nutritionSearchCard = assistantMessageWithNutritionCard.locator(nutritionSearchCardSelector);
		await expect(nutritionSearchCard).toBeVisible({ timeout: 15000 });
		await expect(nutritionSearchCard).toContainText('chickpea and spinach dinner');
		await expect(nutritionSearchCard).toContainText('Edamam');
		await expect(assistantMessageWithNutritionCard).not.toContainText('"type":"app_skill_use"');
		expect(
			await assistantMessageWithNutritionCard.evaluate((message, selector) => {
				const card = message.querySelector(selector);
				const walker = document.createTreeWalker(message, NodeFilter.SHOW_TEXT);
				let answerTextNode: Node | null = null;
				while (walker.nextNode()) {
					if (walker.currentNode.textContent?.includes('Here are three delicious')) {
						answerTextNode = walker.currentNode;
						break;
					}
				}
				return !!(
					card &&
					answerTextNode &&
					(card.compareDocumentPosition(answerTextNode) & Node.DOCUMENT_POSITION_FOLLOWING)
				);
			}, nutritionSearchCardSelector)
		).toBe(true);

		const fullscreenOverlay = await openFullscreen(page, nutritionSearchCard);
		const resultCards = await verifySearchGrid(fullscreenOverlay, 3, 30000);
		await expect(resultCards.first().getByTestId('nutrition-recipe-preview-image')).toBeVisible({ timeout: 15000 });

		await resultCards.first().click({ force: true });
		await expect(page.getByTestId('nutrition-recipe-image')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('nutrition-recipe-details')).toContainText('4 servings');
		await expect(page.getByTestId('nutrition-recipe-tags')).toContainText('Vegetarian');
		await expect(page.getByTestId('nutrition-recipe-categories')).toContainText('middle eastern');
		await expect(page.locator('body')).toContainText('8.7g');
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.catalog.discoverable,public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity,audio-generate.output.playable-audio,audio-speak.output.playable-audio,audio-generate.surface-parity,audio-speak.surface-parity
	test('generated audio examples use natural prompts and recording-style playback', async ({
		page,
		request
	}: {
		page: any;
		request: any;
	}) => {
		test.setTimeout(120000);

		const listingResponse = await request.get('/example');
		expect(listingResponse.status(), 'Example listing page should return 200').toBe(200);
		const listingHtml = await listingResponse.text();
		for (const slug of REMOVED_GENERATED_AUDIO_EXAMPLE_SLUGS) {
			expect(listingHtml, `removed generated-audio example /example/${slug} should not remain listed`).not.toContain(
				`/example/${slug}`
			);
		}
		for (const exampleCase of GENERATED_AUDIO_EXAMPLE_CASES) {
			expect(listingHtml, `replacement generated-audio example /example/${exampleCase.slug} should be listed`).toContain(
				`/example/${exampleCase.slug}`
			);
		}

		for (const exampleCase of GENERATED_AUDIO_EXAMPLE_CASES) {
			await page.goto(getE2EDebugUrl(`/#chat-id=${exampleCase.chatId}`), {
				waitUntil: 'domcontentloaded'
			});

			await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });
			const userMessages = await page.getByTestId('user-message-content').allInnerTexts();
			const userText = userMessages.join('\n');
			expect(userText, `${exampleCase.chatId} should show a natural user prompt`).toContain(
				exampleCase.promptSnippet
			);
			expect(userText, `${exampleCase.chatId} should not expose forced skill mentions`).not.toMatch(
				/@skill:audio/i
			);

			const preview = page
				.locator(
					`[data-testid="embed-preview"][data-app-id="audio"][data-skill-id="${exampleCase.skillId}"][data-status="finished"]`
				)
				.first();
			await expect(preview, `${exampleCase.chatId} should render a finished generated-audio preview`).toBeVisible({
				timeout: 15000
			});
			await expect(preview.getByTestId(`audio-${exampleCase.skillId}-preview`)).toBeVisible({ timeout: 15000 });
			await expect(preview.getByTestId(`audio-${exampleCase.skillId}-prompt-label`)).toBeVisible({ timeout: 15000 });
			await expect(preview.getByTestId(`audio-${exampleCase.skillId}-prompt`)).toContainText(
				exampleCase.promptSnippet,
				{ timeout: 15000 }
			);
			await expect(preview.getByTestId(`audio-${exampleCase.skillId}-preview-play-button`)).toBeVisible({ timeout: 15000 });
			await expect(
				preview.getByTestId('embed-status-value'),
				`${exampleCase.chatId} should not show a second subtitle line under the generated-audio title`
			).toHaveCount(0);

			const previewAudio = preview.getByTestId(`audio-${exampleCase.skillId}-audio`);
			await expect(previewAudio).toBeAttached({ timeout: 15000 });
			await expectAudioCanPlay(previewAudio, `${exampleCase.chatId} preview audio`);

			const fullscreenOverlay = await openFullscreen(page, preview);
			await expect(fullscreenOverlay.getByTestId(`audio-${exampleCase.skillId}-fullscreen`)).toBeVisible({ timeout: 15000 });
			await expect(fullscreenOverlay.getByTestId(`audio-${exampleCase.skillId}-fullscreen-play-button`)).toBeVisible({ timeout: 15000 });
			const fullscreenAudio = fullscreenOverlay.getByTestId(`audio-${exampleCase.skillId}-fullscreen-audio`);
			await expect(fullscreenAudio).toBeAttached({ timeout: 15000 });
			await expectAudioCanPlay(fullscreenAudio, `${exampleCase.chatId} fullscreen audio`);
		}
	});

	// contract-test: direct surface=gui.web assertions=audio-speak.output.playable-audio,public-example-chats.transcript.safe-rendering
	test('generated audio speech example renders mobile playback controls', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);
		await page.setViewportSize({ width: 390, height: 844 });
		const exampleCase = GENERATED_AUDIO_EXAMPLE_CASES[1];
		expect(exampleCase.skillId, 'audio.speak example case should exist').toBe('speak');

		await page.goto(getE2EDebugUrl(`/#chat-id=${exampleCase.chatId}`), {
			waitUntil: 'domcontentloaded'
		});
		await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });

		const preview = page
			.locator('[data-testid="embed-preview"][data-app-id="audio"][data-skill-id="speak"][data-status="finished"]')
			.first();
		await expect(preview, 'mobile audio.speak example should render a finished generated-audio preview').toBeVisible({
			timeout: 15000
		});
		await preview.scrollIntoViewIfNeeded();
		await expect(preview.getByTestId('audio-speak-preview-play-button')).toBeVisible({ timeout: 15000 });
		const previewAudio = preview.getByTestId('audio-speak-audio');
		await expect(previewAudio).toBeAttached({ timeout: 15000 });
		await expectAudioCanPlay(previewAudio, 'mobile audio.speak preview audio');

		const fullscreenOverlay = await openFullscreen(page, preview);
		await expect(fullscreenOverlay.getByTestId('audio-speak-fullscreen')).toBeVisible({ timeout: 15000 });
		await expect(fullscreenOverlay.getByTestId('audio-speak-fullscreen-play-button')).toBeVisible({ timeout: 15000 });
		const fullscreenAudio = fullscreenOverlay.getByTestId('audio-speak-fullscreen-audio');
		await expect(fullscreenAudio).toBeAttached({ timeout: 15000 });
		await expectAudioCanPlay(fullscreenAudio, 'mobile audio.speak fullscreen audio');
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test('Deutschlandticket travel example keeps preview metadata readable and shows map route lines', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(120000);
		await page.setViewportSize({ width: 390, height: 844 });

		await page.goto(getE2EDebugUrl('/#chat-id=example-deutschlandticket-train-fare-breakdown'), {
			waitUntil: 'domcontentloaded'
		});

		const assistantMessage = page
			.getByTestId('message-assistant')
			.filter({ hasText: 'Deutsche Bahn' })
			.first();
		await expect(assistantMessage).toBeVisible({ timeout: 15000 });

		const travelSearchCards = assistantMessage.locator(
			'[data-testid="embed-preview"][data-app-id="travel"][data-skill-id="search_connections"][data-status="finished"]'
		);
		await expect.poll(async () => travelSearchCards.count(), {
			message: 'Deutschlandticket example should render at least one finished travel search preview',
			timeout: 15000
		}).toBeGreaterThan(0);

		const travelSearchCount = await travelSearchCards.count();
		for (let index = 0; index < travelSearchCount; index += 1) {
			const card = travelSearchCards.nth(index);
			await expect(card, `travel search preview ${index + 1} should keep route metadata`).toContainText(
				/Bonn.*M(unich|ünchen)/i
			);
			await expect(card, `travel search preview ${index + 1} should keep date metadata`).toContainText(
				/(Aug 12|2026-08-12)/i
			);
		}

		const firstTravelSearch = travelSearchCards.first();
		await expect(firstTravelSearch, 'parent preview should use result_count/embed_ids instead of showing 0').toContainText('5 connections');

		const mapView = assistantMessage.getByTestId('embeds-map-view');
		await expect(mapView, 'Deutschlandticket example should include a grouped route map view').toBeVisible({ timeout: 15000 });
		await expect(mapView).toContainText('Bonn');
		await mapView.scrollIntoViewIfNeeded();
		await expect.poll(async () => Number(await mapView.getByTestId('embeds-map-view-map').getAttribute('data-route-count')), {
			message: 'grouped Deutschlandticket map should render all route polylines',
			timeout: 15000
		}).toBeGreaterThanOrEqual(5);
		const initialRouteCount = Number(
			await mapView.getByTestId('embeds-map-view-map').getAttribute('data-route-count')
		);
		await expect.poll(async () => mapView.getByTestId('embeds-map-view-map').getAttribute('data-map-hydrated'), {
			message: 'grouped Deutschlandticket map should lazy-hydrate once visible',
			timeout: 15000
		}).toBe('true');
		await expect(mapView.getByTestId('embed-leaflet-map')).toHaveCount(1, { timeout: 15000 });

		const filterButton = mapView.getByTestId('embeds-map-view-filter-button');
		await expect(filterButton).toBeVisible();
		await filterButton.click();
		const filterMenu = mapView.getByTestId('embeds-map-view-filter-menu');
		await expect(filterMenu).toHaveAttribute('data-layout', 'results-panel');
		await expect(filterMenu).toContainText('Departure time');
		await expect(filterMenu).toContainText('Duration');
		await expect(filterMenu).toContainText('Stops');
		await expect(filterMenu).toContainText('Train line');
		const filterMenuBox = await filterMenu.boundingBox();
		expect(filterMenuBox, 'mobile map-view filter sheet should be measurable').not.toBeNull();
		expect(filterMenuBox!.x, 'mobile map-view filter sheet should not be clipped off the left edge').toBeGreaterThanOrEqual(0);
		expect(
			filterMenuBox!.x + filterMenuBox!.width,
			'mobile map-view filter sheet should not be clipped off the right edge'
		).toBeLessThanOrEqual(390);
		expect(filterMenuBox!.height, 'mobile map-view filter panel should replace the full results body').toBeCloseTo(535, 0);
		await expect(mapView.getByTestId('embeds-map-view-option-train-line-rb26')).toBeVisible();
		await mapView.getByTestId('embeds-map-view-option-train-line-rb26').click();
		await expect(mapView.getByTestId('embeds-map-view-filter-button')).toContainText('Filter (1)');
		await filterButton.click();
		await expect(filterMenu).toBeHidden();
		await expect.poll(async () => Number(await mapView.getByTestId('embeds-map-view-map').getAttribute('data-route-count')), {
			message: 'train-line filtering should keep matching route polylines after returning to the map',
			timeout: 15000
		}).toBeGreaterThan(0);
		await expect.poll(async () => Number(await mapView.getByTestId('embeds-map-view-map').getAttribute('data-route-count')), {
			message: 'train-line filtering should reduce visible route polylines without reloading the chat',
			timeout: 15000
		}).toBeLessThan(initialRouteCount);
		await filterButton.click();
		await mapView.getByTestId('embeds-map-view-clear-filters').click();

		const fullscreenOverlay = await openFullscreen(page, firstTravelSearch);
		const resultCards = await verifySearchGrid(fullscreenOverlay, 5, 30000);
		const cardsToCheck = Math.min(3, await resultCards.count());
		for (let index = 0; index < cardsToCheck; index += 1) {
			const previewDetails = resultCards.nth(index).getByTestId('connection-preview-details');
			await expect(previewDetails).toBeVisible({ timeout: 5000 });
			await expectNoPreviewOverflow(previewDetails, `travel result card ${index + 1} should not clip visible preview details`);
		}

		await resultCards.first().click();
		await expect(page.getByTestId('flight-details-card')).toBeVisible({ timeout: 15000 });

		const routePaths = page.locator('[data-testid="travel-route-path"]');
		await expect.poll(async () => routePaths.count(), {
			message: 'travel connection fullscreen should draw visible route lines between stops',
			timeout: 15000
		}).toBeGreaterThanOrEqual(2);

		const transportTypes = await routePaths.evaluateAll((paths: SVGPathElement[]) =>
			paths.map((path) => path.getAttribute('data-transport-type')).filter(Boolean)
		);
		expect(transportTypes).toContain('regional_train');
		expect(transportTypes).not.toContain('long_distance_train');
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.catalog.discoverable,public-example-chats.surface.semantic-parity
	test('sidebar example chats show newest first and append older results after show more', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		await loginToTestAccount(page);
		await ensureSidebarVisible(page);

		const initialIds = await sidebarExampleIds(page);
		expect(initialIds.length, 'Examples group should show the initial example batch').toBeGreaterThan(0);
		expect(
			initialIds,
			'Removed Habit Garden example should not appear in the initial example batch'
		).not.toContain('example-habit-garden-vite-app');

		const showMoreExamples = page.getByTestId('show-more-example-chats');
		await expect(showMoreExamples).toBeVisible({ timeout: 10000 });
		await showMoreExamples.click();

		await expect.poll(async () => (await sidebarExampleIds(page)).length, {
			message: 'Show more should reveal more example chats after the initial batch',
			timeout: 10000
		}).toBeGreaterThan(initialIds.length);

		const expandedIds = await sidebarExampleIds(page);
		for (const id of initialIds) {
			expect(expandedIds, `Show more should keep already-visible example ${id}`).toContain(id);
		}
		expect(expandedIds, 'Removed Habit Garden example should not appear after expanding examples').not.toContain(
			'example-habit-garden-vite-app'
		);
		expect(
			new Set(expandedIds).size,
			'Show more should not duplicate example chat rows'
		).toBe(expandedIds.length);
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.seo.crawlable
	test('example chat SSR pages are accessible', async ({ request }: { request: any }) => {
		test.setTimeout(30000);

		// Verify at least one example chat has a working SSR page
		const response = await request.get('/example/gigantic-airplanes-transporting-rocket-parts');

		expect(response.status(), 'Example chat SSR page should return 200').toBe(200);

		const html = await response.text();
		expect(html).toContain('<main');
		expect(html).toContain('<article');
		expect(html).toContain('<h1>');
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.seo.crawlable,public-example-chats.transcript.safe-rendering
	test('every example chat SSR page has complete crawlable SEO HTML', async ({
		request
	}: {
		request: any;
	}) => {
		test.setTimeout(60000);

		const listingResponse = await request.get('/example');
		expect(listingResponse.status(), 'Example listing page should return 200').toBe(200);

		const listingHtml = await listingResponse.text();
		const slugs = extractExampleSlugs(listingHtml);
		expect(slugs.length, 'Example listing should link to example chat pages').toBeGreaterThan(0);

		for (const slug of slugs) {
			const response = await request.get(`/example/${slug}`);
			expect(response.status(), `/example/${slug} should return 200`).toBe(200);

			const html = await response.text();
			expect(html, `/example/${slug} should render main content without JS`).toContain('<main');
			expect(html, `/example/${slug} should render an article without JS`).toContain('<article');
			expect(html, `/example/${slug} should include user transcript text`).toContain('User:');
			expect(html, `/example/${slug} should include assistant transcript text`).toContain('OpenMates:');
			expect(html, `/example/${slug} should not leak unresolved i18n keys`).not.toContain(
				'example_chats.'
			);
			for (const marker of PUBLIC_EXAMPLE_BROKEN_MARKERS) {
				expect(html, `/example/${slug} should not contain broken public marker ${marker}`).not.toContain(
					marker
				);
			}

			expect(countMatches(html, /<title[\s>]/gi), `/example/${slug} title count`).toBe(1);
			expect(
				countMatches(html, /<meta\s+name="description"/gi),
				`/example/${slug} meta description count`
			).toBe(1);
			expect(
				countMatches(html, /<link\s+rel="canonical"/gi),
				`/example/${slug} canonical count`
			).toBe(1);
			expect(countMatches(html, /<meta\s+name="robots"/gi), `/example/${slug} robots count`).toBe(
				1
			);
			expect(countMatches(html, /<meta\s+property="og:title"/gi), `/example/${slug} OG title`).toBe(
				1
			);
			expect(
				countMatches(html, /<meta\s+property="og:description"/gi),
				`/example/${slug} OG description`
			).toBe(1);
			expect(countMatches(html, /<meta\s+property="og:image"/gi), `/example/${slug} OG image`).toBe(
				1
			);
			expect(
				countMatches(html, /<meta\s+name="twitter:title"/gi),
				`/example/${slug} Twitter title`
			).toBe(1);
			expect(
				countMatches(html, /<meta\s+name="twitter:description"/gi),
				`/example/${slug} Twitter description`
			).toBe(1);
			expect(
				countMatches(html, /<meta\s+name="twitter:image"/gi),
				`/example/${slug} Twitter image`
			).toBe(1);

			const canonicalMatch = html.match(/<link\s+rel="canonical"\s+href="([^"]+)"/i);
			expect(canonicalMatch?.[1], `/example/${slug} should have slug canonical`).toContain(
				`/example/${slug}`
			);

			const robotsMatch = html.match(/<meta\s+name="robots"\s+content="([^"]+)"/i);
			expect(robotsMatch?.[1], `/example/${slug} should have explicit robots content`).toMatch(
				/^(index, follow|noindex, nofollow)$/
			);

			const jsonLd = extractJsonLd(html);
			const qaPage = jsonLd['@graph']?.find((node: Record<string, any>) => node['@type'] === 'QAPage');
			expect(qaPage, `/example/${slug} JSON-LD QAPage`).toBeTruthy();
			expect(qaPage.name, `/example/${slug} JSON-LD name`).toBeTruthy();
			expect(qaPage.description, `/example/${slug} JSON-LD description`).toBeTruthy();
			expect(qaPage.dateModified, `/example/${slug} JSON-LD dateModified`).toBeTruthy();
			expect(qaPage.url, `/example/${slug} JSON-LD canonical`).toContain(
				`/example/${slug}`
			);
			expect(
				qaPage.mainEntity?.length,
				`/example/${slug} JSON-LD QAPage should include question/answer entries`
			).toBeGreaterThan(0);
		}
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.seo.crawlable
	test('production sitemap includes every example chat with lastmod', async ({
		request
	}: {
		request: any;
	}) => {
		test.setTimeout(30000);

		const listingResponse = await request.get('/example');
		const listingHtml = await listingResponse.text();
		const slugs = extractExampleSlugs(listingHtml);
		expect(slugs.length, 'Example listing should expose sitemap candidates').toBeGreaterThan(0);

		const sitemapResponse = await request.get('/sitemap.xml');
		expect(sitemapResponse.status(), 'Sitemap should return 200').toBe(200);

		const sitemapXml = await sitemapResponse.text();
		test.skip(
			!sitemapXml.includes(`/example/${slugs[0]}`),
			'This environment intentionally does not expose example URLs in sitemap.xml; build-time SEO audit validates production sitemap output.'
		);

		for (const slug of slugs) {
			const entryPattern = new RegExp(
				`<loc>https?://[^<]+/example/${slug}</loc>\\s*<lastmod>\\d{4}-\\d{2}-\\d{2}</lastmod>`
			);
			expect(sitemapXml, `Sitemap should include /example/${slug} with lastmod`).toMatch(
				entryPattern
			);
		}
	});
});
