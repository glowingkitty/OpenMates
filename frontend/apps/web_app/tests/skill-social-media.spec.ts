/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * E2E coverage for Social Media get-posts and search skills.
 *
 * These tests verify the user-facing async embed flow: chat skill invocation,
 * processing parent embed completion, child post embed rendering, fullscreen
 * open/close, and the follow-up assistant interpretation after async results.
 *
 * Architecture context: docs/architecture/apps/social-media.md
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
const {
	waitForEmbedFinished,
	openFullscreen,
	closeFullscreen,
	verifySearchGrid
} = require('./helpers/embed-test-helpers');

async function openFirstSocialPostFullscreen(page: any, parentFullscreen: any): Promise<any> {
	const resultCards = await verifySearchGrid(parentFullscreen, 1, 90_000);
	const child = resultCards.first();
	await expect(child).toBeVisible({ timeout: 10_000 });
	await child.click();

	const overlays = page.getByTestId('embed-fullscreen-overlay');
	await expect(async () => {
		const count = await overlays.count();
		expect(count).toBeGreaterThanOrEqual(2);
	}).toPass({ timeout: 10_000 });

	return overlays.last();
}

async function expectAssistantInterpretation(page: any): Promise<void> {
	const assistantMessages = page.getByTestId('message-assistant');
	await expect(async () => {
		const count = await assistantMessages.count();
		expect(count).toBeGreaterThanOrEqual(2);
	}).toPass({ timeout: 120_000 });

	const latestText = ((await assistantMessages.last().textContent()) || '').trim();
	expect(latestText.length).toBeGreaterThan(20);
	expect(latestText).not.toContain('The requested async skill has started');
}

test.describe('App: Social Media / Skills: get-posts and search', () => {
	test.setTimeout(360_000);

	test('Web chat triggers social media search with post embeds', async ({ page }: { page: any }) => {
		test.slow();
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-social-media-search');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		const message = withLiveMockMarker(
			'Search social media on Reddit for privacy. Use the Social Media Search skill and summarize what you find.',
			'social_media_search_web'
		);
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'social-media-search');

		const embed = await waitForEmbedFinished(page, 'social_media', 'search', 120_000);
		logCheckpoint('Social Media search embed finished.');
		await takeStepScreenshot(page, 'social-media-search-embed-finished');

		const parentFullscreen = await openFullscreen(page, embed);
		logCheckpoint('Social Media search fullscreen opened.');
		const childFullscreen = await openFirstSocialPostFullscreen(page, parentFullscreen);
		logCheckpoint('Social post fullscreen opened.');
		await closeFullscreen(page, childFullscreen);
		await closeFullscreen(page, parentFullscreen);

		await expectAssistantInterpretation(page);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'social-media-search');
	});

	test('Web chat triggers social media get-posts with post embeds', async ({ page }: { page: any }) => {
		test.slow();
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-social-media-get-posts');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		const message = withLiveMockMarker(
			'Get the latest Bluesky posts from the bsky.app profile using Social Media Get posts, then summarize the posts.',
			'social_media_get_posts_web'
		);
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'social-media-get-posts');

		const embed = await waitForEmbedFinished(page, 'social_media', 'get-posts', 120_000);
		logCheckpoint('Social Media get-posts embed finished.');
		await takeStepScreenshot(page, 'social-media-get-posts-embed-finished');

		const parentFullscreen = await openFullscreen(page, embed);
		logCheckpoint('Social Media get-posts fullscreen opened.');
		const childFullscreen = await openFirstSocialPostFullscreen(page, parentFullscreen);
		logCheckpoint('Social post fullscreen opened.');
		await closeFullscreen(page, childFullscreen);
		await closeFullscreen(page, parentFullscreen);

		await expectAssistantInterpretation(page);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'social-media-get-posts');
	});
});
