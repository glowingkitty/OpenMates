/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for videos/get_transcript skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/videos
 * Phase 2: CLI direct skill command (openmates apps videos get_transcript --json)
 * Phase 3: CLI chat send triggers skill
 * Phase 4: Web UI chat triggers skill with embed rendering
 *
 * Bug history this test suite guards against:
 * - 8bc5253: URL prop not passed from AppSkillUseRenderer to VideoTranscriptEmbedPreview,
 *   causing missing video metadata (thumbnail, title, channel) during processing state.
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
const { deriveApiUrl, runCli, parseCliJson } = require('./helpers/cli-test-helpers');
const {
	verifyEmbedPreviewPage,
	waitForEmbedFinished,
	openFullscreen,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

/** Short, stable YouTube video used across all phases. */
const TEST_VIDEO_URL = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';

test.describe('App: Videos / Skill: get_transcript', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('Phase 1: embed preview renders at /dev/preview/embeds/videos', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'videos', log);
	});

	test('Phase 2: CLI apps videos get_transcript returns real transcript', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const result = await runCli(
			apiUrl,
			[
				'apps', 'videos', 'get_transcript',
				'--input', JSON.stringify({
					requests: [{ url: TEST_VIDEO_URL }]
				}),
				'--json'
			],
			45_000
		);

		expect(result.code).toBe(0);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);
		expect(parsed.data).toBeTruthy();

		// Verify the response contains actual transcript content.
		// parsed.data is the TranscriptResponse: { results: [{ id, results: [...] }], provider, ... }
		const responseData = parsed.data;
		expect(responseData.results).toBeTruthy();
		expect(responseData.results.length).toBeGreaterThanOrEqual(1);

		// The first group should contain at least one transcript result
		const firstGroup = responseData.results[0];
		expect(firstGroup.results).toBeTruthy();
		expect(firstGroup.results.length).toBeGreaterThanOrEqual(1);

		const transcript = firstGroup.results[0];
		// URL must be present (this was the OPE-158 bug — url missing from embed)
		expect(transcript.url).toBeTruthy();
		expect(transcript.url).toContain('youtube.com');
		// Transcript text must be non-empty
		expect(transcript.transcript).toBeTruthy();
		expect(transcript.transcript.length).toBeGreaterThan(100);
		// Word count must be a positive number
		expect(transcript.word_count).toBeGreaterThan(0);

		console.log(
			`[P2] videos/get_transcript returned transcript: ` +
			`url=${transcript.url}, words=${transcript.word_count}, ` +
			`chars=${transcript.transcript.length}`
		);
	});

	test('Phase 3: CLI chats new triggers real transcript extraction', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'API key required.');

		const message = withLiveMockMarker(
			`Get the transcript of this video: ${TEST_VIDEO_URL}`,
			'videos_transcript_cli'
		);
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 60_000);
		expect(result.code).toBe(0);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();

		// The AI response should reference the transcript or the video
		const stdout = result.stdout.toLowerCase();
		const mentionsTranscript = stdout.includes('transcript') || stdout.includes('word');
		expect(mentionsTranscript).toBe(true);
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	test('Phase 4: Web chat triggers transcript with embed and URL', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-videos-transcript');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(
			page,
			withLiveMockMarker(
				`Get the transcript of this video: ${TEST_VIDEO_URL}`,
				'videos_transcript_web'
			),
			logCheckpoint, takeStepScreenshot, 'videos-transcript'
		);

		// Wait for the transcript embed to finish
		const embed = await waitForEmbedFinished(page, 'videos', 'get_transcript');
		logCheckpoint('Videos transcript embed finished.');
		await takeStepScreenshot(page, 'embed-finished');

		// Verify the embed preview shows a real video title (not just the fallback "YouTube Video").
		// The title comes from YouTube metadata fetched via the url prop (OPE-158 fix).
		const titleEl = embed.getByTestId('transcript-title');
		await expect(titleEl).toBeVisible({ timeout: 15_000 });
		const titleText = await titleEl.textContent();
		logCheckpoint(`Embed preview title: "${titleText}"`);
		// Title should be a real YouTube title, not the empty fallback
		expect(titleText).toBeTruthy();
		expect(titleText!.length).toBeGreaterThan(3);

		// Verify the subtitle shows word count (e.g. "via YouTube:\n42 words")
		const subtitleEl = embed.getByTestId('transcript-subtitle');
		await expect(subtitleEl).toBeVisible({ timeout: 5_000 });
		const subtitleText = await subtitleEl.textContent();
		logCheckpoint(`Embed subtitle: "${subtitleText}"`);
		expect(subtitleText).toContain('words');

		// Open fullscreen and verify transcript content
		const fullscreenOverlay = await openFullscreen(page, embed);
		logCheckpoint('Fullscreen opened.');
		await takeStepScreenshot(page, 'fullscreen-opened');

		// Verify word count header is visible
		const wordCountEl = fullscreenOverlay.getByTestId('transcript-word-count');
		await expect(wordCountEl).toBeVisible({ timeout: 10_000 });
		const wordCountText = await wordCountEl.textContent();
		logCheckpoint(`Fullscreen word count: "${wordCountText}"`);
		expect(wordCountText).toContain('words');

		// Verify transcript box has real content (not empty)
		const transcriptBox = fullscreenOverlay.getByTestId('transcript-box');
		await expect(transcriptBox).toBeVisible({ timeout: 10_000 });
		const transcriptContent = await transcriptBox.textContent();
		logCheckpoint(`Fullscreen transcript length: ${transcriptContent?.length || 0} chars`);
		expect(transcriptContent).toBeTruthy();
		expect(transcriptContent!.length).toBeGreaterThan(100);

		await closeFullscreen(page, fullscreenOverlay);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'videos-transcript');
	});
});
