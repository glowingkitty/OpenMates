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
// Keep caption reading time inside the real source recording, without synthetic holds.
const PROOF_READING_HOLD_MS = 7_000;
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
		text: 'A logged-out visitor starts the reviewed welcome response using the voice player.',
		checkpoint: 'logged-out-public-playback',
		devices: ['web-laptop', 'web-phone']
	}],
	assertions: [{
		id: 'logged-out-public-playback',
		checkpoint: 'logged-out-public-playback',
		visual: 'The voice response player shows its playback control and current chapter for the logged-out welcome example.',
		devices: ['web-laptop', 'web-phone']
	}],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: PROOF_READING_HOLD_MS }
});

test.describe('Public example assistant speech', () => {
	test.setTimeout(90_000);

	// contract-test: direct surface=gui.web assertions=assistant-speech.public-example.reviewed-fixture-playback,public-example-chats.speech.reviewed-public-playback
	test('plays reviewed immutable fixtures while logged out', async ({ page, context }: { page: any; context: any }, testInfo: any) => {
		await context.clearCookies();
		// The queue creates detached Audio elements, so a DOM locator cannot prove
		// playback. Observe the real media instances without replacing their audio,
		// network requests, playback promise, or browser autoplay policy.
		await page.addInitScript(() => {
			const observedMedia: HTMLMediaElement[] = [];
			(window as any).__exampleSpeechObservedMedia = observedMedia;
			const originalPlay = HTMLMediaElement.prototype.play;
			HTMLMediaElement.prototype.play = function () {
				if (!observedMedia.includes(this)) observedMedia.push(this);
				return originalPlay.call(this);
			};
		});
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
		await expect(player.getByTestId('assistant-speech-waveform-region')).toHaveCount(2);
		await expect.poll(() => audioResponses.length, { timeout: 30_000 }).toBeGreaterThan(0);
		for (const response of audioResponses) expect(response.ok()).toBe(true);
		await expect.poll(() => page.evaluate((audioHost: string) => {
			const observedMedia = (window as any).__exampleSpeechObservedMedia as HTMLMediaElement[];
			return observedMedia.some((media) => {
				if (!media.currentSrc) return false;
				const url = new URL(media.currentSrc);
				return url.hostname === audioHost
					&& url.pathname.startsWith('/assistant-speech/sha256-')
					&& media.error === null
					&& media.currentTime > 0.25;
			});
		}, EXPECTED_PUBLIC_AUDIO_HOST), {
			message: 'Public speech must decode and advance its playback clock, not merely download',
			timeout: 30_000,
		}).toBe(true);
		// Retain concrete media-clock evidence with the CI report, not only a pass.
		await testInfo.attach('public-speech-playback-state', {
			body: JSON.stringify(await page.evaluate(() => {
				const media = (window as any).__exampleSpeechObservedMedia as HTMLMediaElement[];
				return media.map((item) => ({
					currentTime: item.currentTime,
					duration: item.duration,
					paused: item.paused,
					readyState: item.readyState,
					errorCode: item.error?.code ?? null,
				}));
			}), null, 2),
			contentType: 'application/json',
		});
		expect(sentWebSocketFrames.some((frame) => frame.includes('"type":"assistant_speech"'))).toBe(false);

		if (proof) {
			await proof.assert('logged-out-public-playback', async () => {
				await expect(player).toBeVisible();
				await expect(player.getByTestId('assistant-speech-waveform-region')).toHaveCount(2);
			});
			await proof.checkpoint('logged-out-public-playback');
			await page.waitForTimeout(PROOF_READING_HOLD_MS);
			await proof.attach();
		}
	});
});
