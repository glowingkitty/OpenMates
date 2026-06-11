/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Live E2E coverage for videos.create Remotion embeds.
 *
 * This spec verifies the real chat-to-render path: natural-language routing,
 * Remotion source extraction, E2B render completion, UI preview refresh, and
 * fullscreen playback/source inspection. It also guards the parser boundary so
 * generic TSX code fences remain code-code embeds.
 */
export {};

const { test, expect } = require('./console-monitor');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const {
	deleteActiveChat,
	loginToTestAccount,
	sendMessage,
	startNewChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const {
	closeFullscreen,
	openFullscreen,
	waitForEmbedFinished
} = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(4);

const REMOTION_TIMEOUT_MS = 600_000;
const API_POLL_TIMEOUT_MS = 90_000;
const VIDEO_PROMPT = [
	'Create a short deterministic Remotion video.',
	'Use an explicit remotion fence named OpenMatesProof.tsx.',
	'The video should contain the exact text "OpenMates Remotion Proof" and be about 3 seconds long.',
	'Do not use external assets, stock footage, or generative video providers.'
].join(' ');

function logFailureDiagnostics(prefix: string, page: any): Promise<void> {
	return page
		.locator('body')
		.innerText({ timeout: 2000 })
		.then((bodyText: string) => {
			console.log(`[${prefix}] Body text tail:\n${bodyText.slice(-2000)}`);
		})
		.catch((error: unknown) => {
			console.log(`[${prefix}] Failed to capture body text: ${String(error)}`);
		});
}

async function readRemotionStatus(page: any, embedId: string): Promise<Record<string, unknown>> {
	return await page.evaluate(async (id: string) => {
		const response = await fetch(`/v1/videos/remotion/${id}`, { credentials: 'include' });
		const text = await response.text();
		let parsed: Record<string, unknown> = {};
		try {
			parsed = JSON.parse(text) as Record<string, unknown>;
		} catch {
			parsed = { raw: text };
		}
		return { ok: response.ok, statusCode: response.status, ...parsed };
	}, embedId);
}

test.describe('videos.create Remotion embeds', () => {
	test.afterEach(async ({ page }: { page: any }, testInfo: any) => {
		if (testInfo.status !== 'passed' && page) {
			await logFailureDiagnostics('REMOTION_VIDEO_CREATE', page);
		}
		if (page) {
			const noop = () => undefined;
			const noopScreenshot = async () => undefined;
			await deleteActiveChat(page, noop, noopScreenshot, 'remotion-video-cleanup').catch(noop);
		}
	});

	test('natural-language request creates and renders a Remotion video embed', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(720_000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const logCheckpoint = createSignupLogger('REMOTION_VIDEO_CREATE');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'remotion-video-create'
		});

		await archiveExistingScreenshots(logCheckpoint);
		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		await sendMessage(page, VIDEO_PROMPT, logCheckpoint, takeStepScreenshot, 'remotion-create');
		await waitForAssistantMessage(page, { which: 'first', timeout: 180_000, logCheckpoint });

		const processingEmbed = page.locator(
			'[data-testid="embed-preview"][data-app-id="videos"][data-skill-id="create"]'
		);
		await expect(processingEmbed.first()).toBeVisible({ timeout: 180_000 });
		await expect(processingEmbed.first().getByTestId('video-create-preview')).toBeVisible({ timeout: 20_000 });
		logCheckpoint('Remotion videos.create preview appeared.');

		const finishedEmbed = await waitForEmbedFinished(page, 'videos', 'create', REMOTION_TIMEOUT_MS);
		const embedId = await finishedEmbed.getAttribute('data-embed-id');
		expect(embedId, 'videos.create embed should expose data-embed-id').toBeTruthy();
		logCheckpoint(`Remotion videos.create embed finished: ${embedId}`);

		await expect(async () => {
			const apiPayload = await readRemotionStatus(page, embedId as string);
			expect(apiPayload.ok, `Remotion API payload: ${JSON.stringify(apiPayload)}`).toBe(true);
			expect(apiPayload.status, `Remotion API payload: ${JSON.stringify(apiPayload)}`).toBe('finished');
			expect(apiPayload.filename, `Remotion API payload: ${JSON.stringify(apiPayload)}`).toContain('.tsx');
			expect(apiPayload.remotion_source, `Remotion API payload: ${JSON.stringify(apiPayload)}`).toContain('OpenMates Remotion Proof');
		}).toPass({ timeout: API_POLL_TIMEOUT_MS, intervals: [2000, 5000, 10000] });

		await expect(finishedEmbed.getByTestId('video-create-preview')).toBeVisible({ timeout: 20_000 });
		await expect(finishedEmbed).toContainText(/\d+s\s*·\s*\d+x\d+/, { timeout: 30_000 });
		await takeStepScreenshot(page, 'remotion-video-preview-finished');

		const fullscreenOverlay = await openFullscreen(page, finishedEmbed);
		const fullscreen = fullscreenOverlay.getByTestId('video-create-fullscreen');
		await expect(fullscreen).toBeVisible({ timeout: 30_000 });
		await expect(fullscreen.getByRole('button', { name: 'Video' })).toBeVisible();
		await expect(fullscreen.getByRole('button', { name: 'Timeline' })).toBeVisible();
		await expect(fullscreen.getByRole('button', { name: 'Code' })).toBeVisible();
		await expect(fullscreen.locator('video')).toBeVisible({ timeout: 60_000 });

		await fullscreen.getByRole('button', { name: 'Timeline' }).click();
		await expect(fullscreen).toContainText(/0s/);

		await fullscreen.getByRole('button', { name: 'Code' }).click();
		await expect(fullscreen).toContainText('OpenMates Remotion Proof', { timeout: 10_000 });
		await expect(fullscreen).toContainText(/from ['"]remotion['"]/);
		await takeStepScreenshot(page, 'remotion-video-fullscreen-code');

		await closeFullscreen(page, fullscreenOverlay);
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'remotion-video-create');
	});

	test('generic tsx fences remain code-code embeds instead of videos.create embeds', async ({ page }: { page: any }) => {
		test.setTimeout(180_000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const logCheckpoint = createSignupLogger('REMOTION_TSX_GUARD');
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
			filenamePrefix: 'remotion-tsx-guard'
		});

		await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
		await startNewChat(page, logCheckpoint);

		const message = [
			'Please keep this as a normal TSX code sample and do not create a video:',
			'```tsx',
			'export function PlainCard() {',
			'  return <section>Generic TSX should stay code-code</section>;',
			'}',
			'```'
		].join('\n');
		await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'generic-tsx');

		const userMessage = page.getByTestId('message-user').last();
		await expect(userMessage).toBeVisible({ timeout: 30_000 });
		await expect(
			userMessage.locator('[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]')
		).toBeVisible({ timeout: 30_000 });
		await expect(userMessage).toContainText('Generic TSX should stay code-code', { timeout: 30_000 });
		await expect(userMessage.locator('[data-testid="embed-preview"][data-app-id="videos"][data-skill-id="create"]'))
			.toHaveCount(0);

		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'generic-tsx-guard');
	});
});
