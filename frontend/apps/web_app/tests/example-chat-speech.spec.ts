/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Deployed logged-out playback proof for reviewed public example speech.
 * The example must load immutable public S3 fixtures without authentication,
 * generation WebSocket requests, owner metadata, or credit-consuming work.
 * The spec is also the canonical phone/laptop proof-video contract.
 */
export {};

const { test, expect } = require('./console-monitor');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const EXAMPLE_ID = 'example-openmates-workspace-welcome';
const EXAMPLE_PATH = `/#chat-id=${EXAMPLE_ID}`;
const EXPECTED_PUBLIC_AUDIO_HOST = 'dev-openmates-public-examples.nbg1.your-objectstorage.com';
const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_DEVICE = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10) === 390 ? 'web-phone' : 'web-laptop';

const PROOF_CONTRACT = defineVideoProof({
	id: 'example-chat-speech',
	title: 'Public example response playback',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [{
		id: 'logged-out-public-playback',
		text: 'A logged-out visitor starts the reviewed welcome response and sees both paragraph tracks in the voice player.',
		checkpoint: 'logged-out-public-playback',
		devices: ['web-laptop', 'web-phone']
	}],
	assertions: [{
		id: 'logged-out-public-playback',
		checkpoint: 'logged-out-public-playback',
		visual: 'The featured welcome example remains readable while the two-region voice response player is visible.',
		devices: ['web-laptop', 'web-phone']
	}],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

test.describe('Public example assistant speech', () => {
	test.setTimeout(90_000);

	// contract-test: direct surface=gui.web assertions=assistant-speech.public-example.reviewed-fixture-playback,public-example-chats.speech.reviewed-public-playback
	test('plays reviewed immutable fixtures while logged out', async ({ page, context }: { page: any; context: any }, testInfo: any) => {
		await context.clearCookies();
		const sentWebSocketFrames: string[] = [];
		page.on('websocket', (socket: any) => socket.on('framesent', (event: { payload: string | Buffer }) => {
			sentWebSocketFrames.push(String(event.payload));
		}));
		const proof = IS_PROOF_CAPTURE
			? createVideoProofRuntime(PROOF_CONTRACT, {
				device: PROOF_DEVICE,
				attach: testInfo.attach.bind(testInfo),
				captureFrame: () => page.screenshot({ type: 'png' })
			})
			: null;

		await page.goto(getE2EDebugUrl(EXAMPLE_PATH), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15_000 });
		const speakButton = page.getByRole('button', { name: 'Speak response' }).last();
		await expect(speakButton).toBeVisible();

		const audioResponses: any[] = [];
		page.on('response', (response: any) => {
			const url = new URL(response.url());
			if (url.hostname === EXPECTED_PUBLIC_AUDIO_HOST && url.pathname.startsWith('/assistant-speech/sha256-')) {
				audioResponses.push(response);
			}
		});
		await speakButton.click();

		const player = page.getByTestId('assistant-speech-player');
		await expect(player).toBeVisible({ timeout: 15_000 });
		await expect(player.getByTestId('assistant-speech-region')).toHaveCount(2);
		await expect.poll(() => audioResponses.length, { timeout: 30_000 }).toBeGreaterThan(0);
		for (const response of audioResponses) expect(response.ok()).toBe(true);
		expect(sentWebSocketFrames.some((frame) => frame.includes('"type":"assistant_speech"'))).toBe(false);

		if (proof) {
			await proof.assert('logged-out-public-playback', async () => {
				await expect(player).toBeVisible();
				await expect(player.getByTestId('assistant-speech-region')).toHaveCount(2);
			});
			await proof.checkpoint('logged-out-public-playback');
			await page.waitForTimeout(3_000);
		}
	});
});
