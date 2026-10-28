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
	'audio-generate-openmates-success-chime',
	'audio-speak-welcome-message'
];


const GENERATED_AUDIO_EXAMPLE_CASES = [
	{
		chatId: 'example-community-garden-volunteer-chime',
		slug: 'community-garden-volunteer-chime',
		skillId: 'generate',
		promptSnippet: 'Create a short, warm notification sound for a community garden app',
		embedPromptSnippet: 'Warm and gentle two-note acoustic chime'
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

for (const [slug, expected] of [
	['browse-example-domain', 'example.com'],
	['browse-heading-json', 'Herman Melville - Moby-Dick']
]) {
	for (const width of [1280, 390]) {
		// contract-test: direct surface=gui.web assertions=web-browse.delivery-and-evidence,web-browse.private-storage-and-api,web-browse.structured-data,public-example-chats.transcript.safe-rendering
		test(`public Browse example ${slug} is read-only with saved JSON at ${width}px`, async ({ page }: { page: any }) => {
			const ownerRequests: string[] = [];
			page.on('request', (request: any) => {
				if (/\/v1\/apps\/web\/browse\//.test(request.url())) ownerRequests.push(request.method());
			});
			await page.setViewportSize({ width, height: width < 600 ? 844 : 1000 });
			await page.goto(getE2EDebugUrl(`/#chat-id=example-${slug}`), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });
			const activity = page.getByTestId('assistant-activity-toggle').first();
			if (await activity.getAttribute('aria-expanded') === 'false') await activity.click();
			const card = page.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="browse"]');
			await expect(card).toContainText('Completed');
			await expect(card.locator('img')).toBeVisible();
			await card.click();
			await expect(page.getByTestId('browse-fullscreen')).toBeVisible();
			await expect(page.getByTestId('browse-session-viewer')).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Take control', exact: true })).toHaveCount(0);
			await page.getByText('Structured data', { exact: true }).click();
			await expect(page.getByTestId('browse-json')).toContainText(expected);
			await page.reload();
			await expect(page.getByTestId('example-chat-badge')).toBeVisible();
			expect(ownerRequests, 'Public examples must never contact owner-only browser APIs').toEqual([]);
		});
	}
}

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

async function expectGuestWelcome(page: any) {
	await expect(page.getByTestId('welcome-content')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
	await expect(page.getByTestId('guest-show-all-examples')).toBeVisible({ timeout: 10000 });
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
		await expectGuestWelcome(page);
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
			.toHaveAttribute('data-slide-index', previousSlideId ?? '0');

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
  test('retained web search replacement shows its real natural request', async ({ page }: { page: any }) => {
    await page.goto(getE2EDebugUrl('/#chat-id=example-gigantic-airplanes'), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('user-message-content').filter({ hasText: 'rocket' })).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('sub-chats-carousel')).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText('"type":"focus_mode_activation"');
  });

	// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test('chat edge fade stays shallow and fullscreen results restore the hidden chat', async ({ page }: { page: any }) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto(getE2EDebugUrl('/#chat-id=example-gigantic-airplanes'), { waitUntil: 'domcontentloaded' });
		const history = page.getByTestId('chat-history-container');
		await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });
		for (const width of [900, 1440]) {
			await page.setViewportSize({ width, height: 900 });
			await history.evaluate((element: HTMLElement) => { element.scrollTop = 150; });
			await expect.poll(() => history.evaluate((element: HTMLElement) => element.scrollTop)).toBeGreaterThan(0);
			await expect.poll(() => history.evaluate((element: HTMLElement) => getComputedStyle(element).maskImage)).toMatch(/rgba\(0, 0, 0, 0\) 0%, rgb\(0, 0, 0\) 30px/);
		}

		await page.getByTestId('assistant-activity-toggle').first().click();
		const preview = page.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]').first();
		const parent = await openFullscreen(page, preview);
		const chatClose = page.getByTestId('chat-close-button');
		await chatClose.click();
		await expect(parent.getByTestId('embed-show-chat-button')).toBeVisible();
		await expect.poll(() => history.evaluate((element: HTMLElement) => !!element.closest('[inert]'))).toBe(true);
		await parent.getByTestId('embed-show-chat-button').click();
		await expect.poll(() => history.evaluate((element: HTMLElement) => !!element.closest('[inert]'))).toBe(false);

		// Drill down to a child result: it must inherit the same restoration control.
		const child = await openFullscreen(page, parent.getByTestId('search-template-grid').getByTestId('embed-preview').first());
		await chatClose.click();
		await expect(child.getByTestId('embed-show-chat-button')).toBeVisible();
		await child.getByTestId('embed-show-chat-button').click();
		await expect.poll(() => history.evaluate((element: HTMLElement) => !!element.closest('[inert]'))).toBe(false);
		await expect(chatClose).toBeVisible();
		await expect(child).toBeVisible();
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.navigation.static-public-link,public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity,chat-share-settings.generated-link-controls,chat-share-settings.shell-navigation
	test('guest example chat exposes share and chat settings with a static public link', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		const exampleChatId = 'example-gigantic-airplanes';

		await page.goto(getE2EDebugUrl(`/#chat-id=${exampleChatId}`), {
			waitUntil: 'domcontentloaded'
		});

		await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });

		await page.getByTestId('assistant-activity-toggle').first().click();
		const appSkillGroup = page.getByTestId('app-skill-embed-group').first();
		await expect(appSkillGroup).toBeVisible({ timeout: 15000 });
		await expect(appSkillGroup.getByText('4 app skills used:', { exact: true })).toBeVisible();
		await expect(appSkillGroup.locator('[data-embed-type="app-skill-use"][data-embed-item-id]')).toHaveCount(4);
		await expect(appSkillGroup.locator('[data-testid="embed-preview"][data-status="finished"]')).toHaveCount(4);
		await expect(appSkillGroup.locator('[data-testid="embed-preview"][data-app-id="images"][data-skill-id="search"]')).toHaveCount(3);
		const webPreview = appSkillGroup.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]');
		await expect(webPreview).toHaveCount(1);
		await expect.poll(async () => {
      const remaining = Number((await webPreview.getByTestId('search-preview-remaining-count').innerText()).match(/\d+/)?.[0]);
      return remaining + await webPreview.locator('img.favicon').count();
    }).toBe(6);
		await expect(webPreview).not.toContainText('Open to view results');

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

	// contract-test: direct surface=gui.web assertions=public-example-chats.catalog.discoverable
	test('memory settings keep sample entries without retired public memory chats', async ({
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
		const memoryCategory = settingsMenu.getByTestId('app-settings-memories-category');
		await expect(memoryCategory).toHaveAttribute('data-app-id', 'books');
		await expect(memoryCategory).toHaveAttribute('data-category-id', 'currently_reading');
		await expect(memoryCategory.getByTestId('app-store-memory-example-chats')).toHaveCount(0);
		const sampleEntries = memoryCategory.locator('.examples-list');
		await expect(sampleEntries).toBeVisible({ timeout: 15000 });
		await expect(sampleEntries.locator('.settings-item')).toHaveCount(2);
		await sampleEntries.locator('.settings-item').first().click();
		await expect(settingsMenu).toHaveAttribute(
			'data-active-view',
			'apps/books/settings_memories/currently_reading/entry/example_0',
			{ timeout: 10000 }
		);
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.history.explicit-forgotten-reveal,public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
	test('internal compression fixture hides compressed history behind forgotten messages', async ({
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

		await page.goto(getE2EDebugUrl('/#chat-id=example-vegetarian-recipes-from-fridge'), {
			waitUntil: 'domcontentloaded'
		});

		await expect(page.getByTestId('user-message-content').filter({
			hasText: 'Recommendations for vegetarian recipes? I still have spinach, carrots, bell peppers and chickpeas in the fridge.'
		})).toBeVisible({ timeout: 15000 });

		const activityToggle = page.getByTestId('assistant-activity-toggle').first();
		await expect(activityToggle).toBeVisible({ timeout: 15000 });
		if ((await activityToggle.getAttribute('aria-expanded')) !== 'true') await activityToggle.click();
		await expect(activityToggle).toHaveAttribute('aria-expanded', 'true');

		const nutritionSearchCardSelector = '[data-testid="embed-preview"][data-app-id="nutrition"][data-skill-id="search_recipes"][data-status="finished"]';
		const assistantMessageWithNutritionCard = page
			.getByTestId('message-assistant')
			.filter({ hasText: 'Here are three distinct culinary directions' })
			.filter({ has: page.locator(nutritionSearchCardSelector) })
			.first();
		await expect(assistantMessageWithNutritionCard).toBeVisible({ timeout: 15000 });

		const nutritionSearchCard = assistantMessageWithNutritionCard.locator(nutritionSearchCardSelector);
		await expect(nutritionSearchCard).toBeVisible({ timeout: 15000 });
		await expect(nutritionSearchCard).toContainText('spinach chickpea bell pepper carrot');
		await expect(nutritionSearchCard).toContainText('Edamam');
		await expect(assistantMessageWithNutritionCard).not.toContainText('"type":"app_skill_use"');
		expect(
			await assistantMessageWithNutritionCard.evaluate((message, selector) => {
				const card = message.querySelector(selector);
				const walker = document.createTreeWalker(message, NodeFilter.SHOW_TEXT);
				let answerTextNode: Node | null = null;
				while (walker.nextNode()) {
					if (walker.currentNode.textContent?.includes('Here are three distinct culinary directions')) {
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
		const resultCards = await verifySearchGrid(fullscreenOverlay, 4, 30000);
		await expect(resultCards).toHaveCount(4);
		await expect(resultCards.first().getByTestId('nutrition-recipe-preview-image')).toBeVisible({ timeout: 15000 });

		const selectedRecipeCard = fullscreenOverlay.locator('[data-testid="embed-preview"][data-embed-id="9c8b68fa-8220-4a7c-be8a-e18350135861"]');
		await expect(selectedRecipeCard.getByTestId('nutrition-recipe-preview-image')).toBeVisible({ timeout: 15000 });
		await selectedRecipeCard.click();
		await expect(page.getByTestId('nutrition-recipe-image')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('result-facts')).toContainText('4 servings');
		await page.getByTestId('nutrition-recipe-tags').getByRole('button').click();
		await expect(page.getByRole('tooltip')).toContainText('Vegetarian');
		await page.keyboard.press('Escape');
		await page.getByTestId('nutrition-recipe-categories').getByRole('button').click();
		await expect(page.getByRole('tooltip')).toContainText('american');
		await page.keyboard.press('Escape');
		// Reviewed selected result: 81.44995g total protein / 4 servings.
		await expect(page.locator('body')).toContainText('20.4g');
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.catalog.discoverable,public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity,audio-generate.output.playable-audio,audio-generate.surface-parity
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
				exampleCase.embedPromptSnippet,
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

	// contract-test: direct surface=gui.web assertions=audio-generate.output.playable-audio,public-example-chats.transcript.safe-rendering
	test('generated audio chime example renders mobile playback controls', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(90000);
		await page.setViewportSize({ width: 390, height: 844 });
		const exampleCase = GENERATED_AUDIO_EXAMPLE_CASES[0];
		expect(exampleCase.skillId, 'audio.generate example case should exist').toBe('generate');

		await page.goto(getE2EDebugUrl(`/#chat-id=${exampleCase.chatId}`), {
			waitUntil: 'domcontentloaded'
		});
		await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });

		const preview = page
			.locator('[data-testid="embed-preview"][data-app-id="audio"][data-skill-id="generate"][data-status="finished"]')
			.first();
		await expect(preview, 'mobile audio.generate example should render a finished generated-audio preview').toBeVisible({
			timeout: 15000
		});
		await preview.scrollIntoViewIfNeeded();
		await expect(preview.getByTestId('audio-generate-preview-play-button')).toBeVisible({ timeout: 15000 });
		const previewAudio = preview.getByTestId('audio-generate-audio');
		await expect(previewAudio).toBeAttached({ timeout: 15000 });
		await expectAudioCanPlay(previewAudio, 'mobile audio.generate preview audio');

		const fullscreenOverlay = await openFullscreen(page, preview);
		await expect(fullscreenOverlay.getByTestId('audio-generate-fullscreen')).toBeVisible({ timeout: 15000 });
		await expect(fullscreenOverlay.getByTestId('audio-generate-fullscreen-play-button')).toBeVisible({ timeout: 15000 });
		const fullscreenAudio = fullscreenOverlay.getByTestId('audio-generate-fullscreen-audio');
		await expect(fullscreenAudio).toBeAttached({ timeout: 15000 });
		await expectAudioCanPlay(fullscreenAudio, 'mobile audio.generate fullscreen audio');
	});

	// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity,chat-processing-feedback.completed-processing-summary
	test('historical transport results retain route geometry and child drilldown without a public example', async ({ page }: { page: any }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto('/dev/preview/embeds/travel/TravelSearchEmbedFullscreen?chrome=0&variant=routeOverview&width=390');
		const map = page.getByTestId('search-results-map');
		await expect(map).toHaveAttribute('data-route-count', '2');
		await expect(map.getByTestId('search-result-route-path')).toHaveCount(2);
		const cards = page.locator('.search-result-card');
		await expect(cards).toHaveCount(2);
		await expect(cards.first()).toContainText('Hamburg Central Station');
		await expect(cards.last()).toContainText('Leipzig Central Station');
		for (const card of await cards.all()) {
			const details = card.getByTestId('connection-preview-details');
			await expect(details).toBeVisible();
			await expectNoPreviewOverflow(details, 'historical transport card details');
		}
		await page.getByTestId('search-template-filter-button').click();
		const filter = page.getByTestId('search-template-filter');
		await filter.fill('Hamburg');
		await expect(cards).toHaveCount(1);
		await expect(map).toHaveAttribute('data-route-count', '1');
		await filter.clear();
		await expect(cards).toHaveCount(2);
		await expect(map).toHaveAttribute('data-route-count', '2');
		await cards.first().click();
		await expect(page.locator('.child-embed-overlay').getByTestId('flight-details-card')).toContainText('Hamburg Central Station');
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
