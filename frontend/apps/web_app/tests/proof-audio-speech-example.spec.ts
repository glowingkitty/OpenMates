/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Proof-video source recording for the static audio.speak example chat.
 *
 * This spec is intentionally proof-only: it opens the deployed public example
 * in exact viewport/video dimensions and records one passing source video per
 * required web proof profile. The narrated proof-video renderer consumes these
 * CI artifacts after the canonical deployed Playwright runner passes.
 */

const { test, expect } = require('@playwright/test');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const EXAMPLE_CHAT_ID = 'example-audio-speak-openmates-welcome-message';
const EXAMPLE_PATH = `/#chat-id=${EXAMPLE_CHAT_ID}`;
const PROOF_RECORDING_DIR = 'test-results/proof-video-source/audio-speech-example';

const PROOF_VIEWPORTS = [
	{ name: 'web-phone', width: 390, height: 844 },
	{ name: 'web-laptop', width: 1440, height: 900 }
] as const;

const PROOF_PHONE_CONTROL_TOP_MIN_PX = 520;
const PROOF_PHONE_CONTROL_BOTTOM_MAX_PX = 740;
const PROOF_LAPTOP_CONTROL_TOP_MIN_PX = 420;
const PROOF_LAPTOP_CONTROL_BOTTOM_MAX_PX = 820;

async function waitForPreviewAudioPlayback(audioLocator: any, label: string): Promise<void> {
	await expect(async () => {
		const state = await audioLocator.evaluate((audio: HTMLAudioElement) => ({
			currentTime: audio.currentTime,
			duration: audio.duration,
			paused: audio.paused,
			readyState: audio.readyState
		}));
		expect(state.paused, `${label} should be actively playing`).toBe(false);
		expect(state.readyState, `${label} should load audio metadata`).toBeGreaterThanOrEqual(1);
		expect(Number.isFinite(state.duration), `${label} should have finite duration`).toBe(true);
		expect(state.currentTime, `${label} should advance during playback`).toBeGreaterThan(0);
	}).toPass({ timeout: 30000 });
}

async function centerLocatorInViewport(locator: any): Promise<void> {
	await locator.evaluate((element: HTMLElement) => {
		element.scrollIntoView({ block: 'center', inline: 'nearest' });
	});
}

async function keepPlaybackControlInProofSafeArea(page: any, viewportName: string): Promise<void> {
	const minTop = viewportName === 'web-phone' ? PROOF_PHONE_CONTROL_TOP_MIN_PX : PROOF_LAPTOP_CONTROL_TOP_MIN_PX;
	const maxBottom = viewportName === 'web-phone' ? PROOF_PHONE_CONTROL_BOTTOM_MAX_PX : PROOF_LAPTOP_CONTROL_BOTTOM_MAX_PX;

	await expect(async () => {
		await page.evaluate(({ minTop, maxBottom }: { minTop: number; maxBottom: number }) => {
			const container = document.querySelector('[data-testid="chat-history-container"]') as HTMLElement | null;
			const button = document.querySelector('[data-testid="audio-speak-preview-play-button"]') as HTMLElement | null;

			if (!container || !button) {
				throw new Error('Missing audio proof scroll target');
			}

			const buttonRect = button.getBoundingClientRect();
			const safeCenterY = minTop + (maxBottom - minTop) / 2;
			container.scrollTop += buttonRect.top + buttonRect.height / 2 - safeCenterY;
		}, { minTop, maxBottom });

		await page.waitForTimeout(150);
		const box = await page.getByTestId('audio-speak-preview-play-button').boundingBox();
		expect(box, `${viewportName} playback control should have a visible bounding box`).not.toBeNull();
		expect(box!.y, `${viewportName} playback control should clear the caption area`).toBeGreaterThanOrEqual(minTop);
		expect(box!.y + box!.height, `${viewportName} playback control should clear the composer`).toBeLessThanOrEqual(maxBottom);
	}).toPass({ timeout: 5000 });
}

test.describe('Audio speech example proof video source', () => {
	for (const viewport of PROOF_VIEWPORTS) {
		// contract-test: direct surface=gui.web assertions=audio-speak.output.playable-audio,public-example-chats.transcript.safe-rendering,audio-speak.surface-parity
		test(`${viewport.name} records speech playback controls`, async ({ browser, baseURL }: { browser: any; baseURL: string }) => {
			test.setTimeout(90000);
			const context = await browser.newContext({
				baseURL,
				recordVideo: {
					dir: PROOF_RECORDING_DIR,
					size: { width: viewport.width, height: viewport.height }
				},
				viewport: { width: viewport.width, height: viewport.height }
			});
			const page = await context.newPage();

			try {
				await page.goto(getE2EDebugUrl(EXAMPLE_PATH), { waitUntil: 'domcontentloaded' });
				await expect(page.getByTestId('example-chat-badge')).toBeVisible({ timeout: 15000 });

				const preview = page
					.locator('[data-testid="embed-preview"][data-app-id="audio"][data-skill-id="speak"][data-status="finished"]')
					.first();
				await expect(preview, `${viewport.name} should show the finished audio.speak preview`).toBeVisible({
					timeout: 15000
				});
				await preview.scrollIntoViewIfNeeded();

				const prompt = preview.getByTestId('audio-speak-prompt');
				await expect(prompt).toContainText('Say this as a warm, natural welcome message', {
					timeout: 15000
				});

				const playButton = preview.getByTestId('audio-speak-preview-play-button');
				await expect(playButton).toBeVisible({ timeout: 15000 });
				await centerLocatorInViewport(playButton);
				await playButton.click();

				const previewAudio = preview.getByTestId('audio-speak-audio');
				await expect(previewAudio).toBeAttached({ timeout: 15000 });
				await waitForPreviewAudioPlayback(previewAudio, `${viewport.name} preview audio`);

				await expect(playButton).toHaveAttribute('aria-label', 'Pause', { timeout: 5000 });
				await keepPlaybackControlInProofSafeArea(page, viewport.name);
				await page.waitForTimeout(2500);
			} finally {
				await context.close();
			}
		});
	}
});
