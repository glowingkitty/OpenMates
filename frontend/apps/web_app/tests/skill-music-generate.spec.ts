/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified E2E coverage for music/generate.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/music.
 * Phase 2: CLI direct skill command dispatches music generation.
 * Phase 3: CLI chat send triggers music generation.
 * Phase 4: Web UI chat triggers music generation with preview + fullscreen audio.
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

const RUN_REAL_MUSIC_GENERATION = process.env.OPENMATES_RUN_MUSIC_GENERATION_TESTS === 'true';

test.describe('App: Music / Skill: generate', () => {
	test.setTimeout(420_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 1: embed preview renders at /dev/preview/embeds/music', async ({ page }: { page: any }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'music', log);
	});

	test('Phase 2: CLI apps music generate dispatches a task', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'OPENMATES_TEST_ACCOUNT_API_KEY required.');
		test.skip(!RUN_REAL_MUSIC_GENERATION, 'Set OPENMATES_RUN_MUSIC_GENERATION_TESTS=true to run Lyria generation.');

		const result = await runCli(
			apiUrl,
			[
				'apps', 'music', 'generate',
				'--input', JSON.stringify({
					requests: [
						{
							prompt: 'A 30 second upbeat electronic test jingle with warm synth pads',
							mode: 'jingle',
							duration_seconds: 30,
							model: 'lyria-3-clip-preview'
						}
					]
				}),
				'--json'
			],
			90_000
		);

		expectCliSuccess(result, 'music/generate CLI');
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);
		expect(parsed.data?.task_id || parsed.data?.task_ids?.[0]).toBeTruthy();
	});

	test('Phase 3: CLI chats new triggers music generation', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'OPENMATES_TEST_ACCOUNT_API_KEY required.');
		test.skip(!RUN_REAL_MUSIC_GENERATION, 'Set OPENMATES_RUN_MUSIC_GENERATION_TESTS=true to run Lyria generation.');

		const message = withLiveMockMarker(
			'Generate a 30 second calm lo-fi background music loop with soft piano and vinyl texture',
			'music_generate_cli'
		);
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 120_000);
		expectCliSuccess(result, 'CLI chat music generation');

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	test('Phase 4: Web chat renders generated music preview and fullscreen player', async ({ page }: { page: any }) => {
		test.slow();
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		test.skip(!RUN_REAL_MUSIC_GENERATION, 'Set OPENMATES_RUN_MUSIC_GENERATION_TESTS=true to run Lyria generation.');

		const logCheckpoint = createSignupLogger('skill-music-generate');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		const message = withLiveMockMarker(
			'Generate a 30 second cinematic ambient background music cue with gentle strings and no drums',
			'music_generate_web'
		);
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'music-generate');

		const embed = await waitForEmbedFinished(page, 'music', 'generate', 240_000);
		await expect(embed.getByTestId('music-generate-preview')).toBeVisible({ timeout: 15_000 });
		await expect(embed.getByTestId('music-generate-audio')).toBeVisible({ timeout: 60_000 });
		await takeStepScreenshot(page, 'music-generate-preview-finished');

		const fullscreen = await openFullscreen(page, embed);
		await expect(fullscreen.getByTestId('music-generate-fullscreen')).toBeVisible({ timeout: 15_000 });
		await expect(fullscreen.getByTestId('music-generate-fullscreen-audio')).toBeVisible({ timeout: 60_000 });
		await closeFullscreen(page, fullscreen);

		await deleteActiveChat(page, logCheckpoint);
	});
});
