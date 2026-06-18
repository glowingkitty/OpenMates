/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Browser E2E test for code/get_docs skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/code
 * Phase 2: Web UI chat triggers skill with embed rendering
 *
 * CLI coverage lives in frontend/packages/openmates-cli/tests/code-docs.integration.mjs
 * and runs through scripts/run_tests.py --suite cli.
 *
 * Note: code/get_docs does NOT use the requests[] array pattern —
 * it takes {library, question} directly.
 *
 * Architecture context: docs/architecture/embeds.md
 */
export {};

const { test } = require('./console-monitor');
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
	verifyEmbedPreviewPage,
	waitForEmbedFinished,
	openFullscreen,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

test.describe('App: Code / Skill: get_docs', () => {
	test.setTimeout(120_000);

	test('Phase 1: embed preview renders at /dev/preview/embeds/code', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'code', log);
	});

	test('Phase 2: Web chat triggers code docs with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-code-docs');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker('Show me React useState documentation', 'code_docs_web'),
			logCheckpoint, takeStepScreenshot, 'code-docs'
		);

		const embed = await waitForEmbedFinished(page, 'code', 'get_docs');
		logCheckpoint('Code docs embed finished.');

		const fullscreenOverlay = await openFullscreen(page, embed);
		logCheckpoint('Fullscreen opened.');

		await closeFullscreen(page, fullscreenOverlay);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'code-docs');
	});
});
