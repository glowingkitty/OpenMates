/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for web/read skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/web
 * Phase 2: CLI direct skill command (openmates apps web read --json)
 * Phase 3: CLI chat send triggers skill (openmates chats new "..." --json)
 * Phase 4: Web UI chat triggers skill with embed rendering
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

test.describe('App: Web / Skill: read', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	// ── Phase 1: Embed preview renders ─────────────────────────────────────
	test('Phase 1: embed preview renders at /dev/preview/embeds/web', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'web', log);
	});

	// ── Phase 2: CLI direct skill command ──────────────────────────────────
	test('Phase 2: CLI apps web read returns structured JSON', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const result = await runCli(
			apiUrl,
			[
				'apps', 'web', 'read',
				'--input', JSON.stringify({ requests: [{ url: 'https://example.com' }] }),
				'--json'
			],
			30_000
		);

		expect(result.code).toBe(0);
		const parsed = parseCliJson(result);
		expect(parsed.success).toBe(true);
		expect(parsed.data).toBeTruthy();

		const skillData = parsed.data;
		expect(Array.isArray(skillData.results)).toBe(true);
		expect(skillData.results.length).toBeGreaterThan(0);

		const resultGroup = skillData.results[0];
		expect(Array.isArray(resultGroup.results)).toBe(true);
		const page = resultGroup.results[0];
		expect(page.url).toContain('example.com');
		expect(page.title).toBeTruthy();
		expect(typeof page.markdown).toBe('string');
		expect(page.markdown.length).toBeGreaterThan(20);

		console.log(`[P2] web/read title="${page.title}", markdown=${page.markdown.length} chars`);
	});

	// ── Phase 3: CLI chat send triggers skill ──────────────────────────────
	test('Phase 3: CLI chats new triggers web read', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const message = withLiveMockMarker(
			'Read this page and summarize it: https://example.com',
			'web_read_cli'
		);
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 60_000);
		expect(result.code).toBe(0);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	// ── Phase 4: Web UI chat triggers skill ────────────────────────────────
	test('Phase 4: Web chat triggers web read with embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const { logCheckpoint } = createSignupLogger('skill-web-read');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		const message = withLiveMockMarker(
			'Read this page and summarize it: https://example.com',
			'web_read_web'
		);
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'web-read');

		logCheckpoint('Waiting for web read embed to finish...');
		const embed = await waitForEmbedFinished(page, 'web', 'read');
		logCheckpoint('Web read embed finished.');
		await takeStepScreenshot(page, 'web-read-embed-finished');

		const fullscreenOverlay = await openFullscreen(page, embed);
		logCheckpoint('Fullscreen opened.');

		await closeFullscreen(page, fullscreenOverlay);
		logCheckpoint('Fullscreen closed.');

		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'web-read');
	});
});
