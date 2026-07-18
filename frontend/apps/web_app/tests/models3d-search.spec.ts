/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * E2E coverage for models3d.search result rendering.
 *
 * Verifies the web phase of docs/specs/models3d-search/spec.yml: chat creates
 * the parent search embed, fullscreen renders child 3D model result cards, and
 * previews stay link-out only without downloading model files or provider JS.
 *
 * Architecture context: docs/architecture/messaging/embeds.md
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
	verifySearchGrid,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

test.describe('App: Models3D / Skill: search', () => {
	test.setTimeout(300_000);

	test('web chat renders preview-only 3D model search results', async ({ page }: { page: any }) => {
		test.slow();
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('models3d-search');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);
		const forbiddenModelFileRequests: string[] = [];
		const providerScriptRequests: string[] = [];

		page.on('request', (request: any) => {
			const url = request.url().toLowerCase();
			const isModelFile = /\.(stl|3mf|obj|step|stp|glb|gltf|zip)(?:[?#]|$)/.test(url) || url.includes('/download/');
			if (isModelFile) forbiddenModelFileRequests.push(request.url());

			const isProviderScript = request.resourceType() === 'script' && /(printables|myminifactory|thingiverse)\./.test(url);
			if (isProviderScript) providerScriptRequests.push(request.url());
		});

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker('Find 3D printable benchy models', 'models3d_search_web'),
			logCheckpoint,
			takeStepScreenshot,
			'models3d-search'
		);

		const embed = await waitForEmbedFinished(page, 'models3d', 'search', 120_000);
		await expect(embed.getByTestId('models3d-search-preview')).toBeVisible({ timeout: 30_000 });
		await expect(embed).toContainText(/result|model|Printables/i);
		logCheckpoint('Models3D search embed finished.');

		const fullscreenOverlay = await openFullscreen(page, embed);
		const resultCards = await verifySearchGrid(fullscreenOverlay, 1, 60_000);
		const firstResultCard = resultCards.first();
		await expect(firstResultCard.getByTestId('models3d-result-card')).toBeVisible({ timeout: 30_000 });
		await expect(firstResultCard.locator('img')).toHaveAttribute('src', /\/(api\/v1\/image|api\/image-proxy)\?url=/, { timeout: 30_000 });

		await firstResultCard.click();
		const childFullscreenOverlay = page.getByTestId('embed-fullscreen-overlay').last();
		await expect(childFullscreenOverlay.getByTestId('models3d-result-fullscreen')).toBeVisible({ timeout: 30_000 });

		const cta = childFullscreenOverlay.getByTestId('models3d-open-provider-cta');
		await expect(cta).toBeVisible({ timeout: 30_000 });
		await expect(cta).toContainText(/Open on /);
		const href = await cta.getAttribute('href');
		expect(href || '').toMatch(/^https:\/\/(www\.)?(printables|myminifactory|thingiverse)\./);

		expect(forbiddenModelFileRequests, 'Preview/fullscreen must not download full 3D model files').toEqual([]);
		expect(providerScriptRequests, 'Preview/fullscreen must not execute provider JavaScript').toEqual([]);

		await closeFullscreen(page, childFullscreenOverlay);
		await closeFullscreen(page, fullscreenOverlay);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'models3d-search');
	});
});
