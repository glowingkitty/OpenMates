/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Deployed assistant-response speech verification and proof source.
 * A real CLI chat creates one canonical two-paragraph assistant response.
 * The browser verifies encrypted chat preference sync, voice activation,
 * on-demand generation/reuse, controls, waveform layout, and autoplay recovery.
 */
export {};

const { test, expect } = require('./console-monitor');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const SPEECH_TIMEOUT_MS = 240_000;
const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_WIDTH === 390 ? 'web-phone' : 'web-laptop';

const PROOF_CONTRACT = defineVideoProof({
	id: 'assistant-response-speech',
	title: 'Assistant response speech playback',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'voice-replies-enabled',
			text: 'Voice replies are enabled for this encrypted chat and remain enabled after reload.',
			checkpoint: 'voice-replies-enabled',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'speech-player-visible',
			text: 'Speak opens the pinned response player with paragraph regions and playback controls.',
			checkpoint: 'speech-player-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'paragraph-navigation-visible',
			text: 'The player can pause and move between response paragraphs without covering the transcript.',
			checkpoint: 'paragraph-navigation-visible',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'voice-replies-enabled',
			checkpoint: 'voice-replies-enabled',
			visual: 'The Voice control is visibly active after reload.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'speech-player-visible',
			checkpoint: 'speech-player-visible',
			visual: 'The pinned player shows at least two paragraph regions and Previous, Pause or Play, Next, and Stop controls.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'paragraph-navigation-visible',
			checkpoint: 'paragraph-navigation-visible',
			visual: 'One paragraph region is highlighted and the player does not overlap transcript content or the composer.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

test.use({
	launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
	permissions: ['microphone']
});

test.describe.serial('Assistant response speech', () => {
	test.setTimeout(900_000);

	// contract-test: direct surface=gui.web assertions=assistant-speech.preference.chat-scoped-default-off,assistant-speech.preference.voice-recording-visible-activation,assistant-speech.on-demand.generate-missing-only,assistant-speech.playback.single-queue-segment-control,assistant-speech.playback.pinned-full-response-waveform,assistant-speech.playback.autoplay-recovery-visible,message-input.actions.visibility,message-input.send.ownership
	test('plays a real assistant response with synchronized controls', async ({ page }: { page: any }, testInfo: any) => {
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		const log = createSignupLogger('assistant-response-speech');
		await archiveExistingScreenshots(log);
		const screenshot = createStepScreenshotter(log);
		const proof = IS_PROOF_CAPTURE
			? createVideoProofRuntime(PROOF_CONTRACT, {
				device: PROOF_DEVICE,
				attach: testInfo.attach.bind(testInfo),
				captureFrame: () => page.screenshot({ type: 'png' })
			})
			: null;

		await loginToTestAccount(page, log, screenshot);
		await startNewChat(page, log);
		await sendMessage(
			page,
			'Answer with exactly two short plain-text paragraphs. The first paragraph must say that assistant speech starts progressively. The second paragraph must say that paragraph controls remain available.',
			log,
			screenshot,
			'assistant-speech-source'
		);
		await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: 300_000 });
		await expect(page.getByTestId('message-assistant').last()).not.toHaveAttribute('data-streaming', 'true', { timeout: 300_000 });
		const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? '';
		expect(chatId, 'browser chat should expose a chat-id').toBeTruthy();

		const messageField = page.getByTestId('message-field').last();
		await messageField.click();
		const attachmentMenu = messageField.getByTestId('composer-attachment-menu-button');
		const modelSelector = messageField.getByTestId('composer-model-selector');
		const voiceToggle = messageField.getByTestId('assistant-speech-toggle');
		const mic = messageField.getByTestId('record-audio-button');
		await expect(attachmentMenu).toBeVisible({ timeout: 15_000 });
		await expect(modelSelector).toBeVisible({ timeout: 15_000 });
		await expect(voiceToggle).toBeVisible({ timeout: 15_000 });
		await expect(voiceToggle).toHaveAttribute('data-icon-only', 'true');
		await attachmentMenu.click();
		await expect(messageField.getByTestId('composer-attachment-camera')).toBeVisible();
		await expect(messageField.getByTestId('composer-camera-button')).toHaveCount(0);
		await attachmentMenu.click();
		const [voiceBox, micBox] = await Promise.all([voiceToggle.boundingBox(), mic.boundingBox()]);
		expect(voiceBox, 'speech control should have layout geometry').toBeTruthy();
		expect(micBox, 'microphone control should have layout geometry').toBeTruthy();
		expect(voiceBox!.x + voiceBox!.width).toBeLessThanOrEqual(micBox!.x);
		expect(micBox!.x - (voiceBox!.x + voiceBox!.width)).toBeLessThanOrEqual(32);
		const editor = messageField.getByTestId('message-editor');
		await editor.fill('Composer control verification');
		await expect(messageField.getByTestId('composer-send-button')).toBeVisible({ timeout: 10_000 });
		await editor.fill('');
		await expect(voiceToggle).toHaveAttribute('aria-pressed', 'false');
		await voiceToggle.click();
		await expect(voiceToggle).toHaveAttribute('aria-pressed', 'true');
		const speechStatus = messageField.getByTestId('assistant-speech-toggle-status');
		await expect(speechStatus).toHaveText('Speech on');
		await expect(speechStatus).not.toBeVisible({ timeout: 5_000 });

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: 60_000 });
		await page.getByTestId('message-field').last().click();
		const reloadedToggle = page.getByTestId('message-field').last().getByTestId('assistant-speech-toggle');
		await expect(reloadedToggle).toHaveAttribute('aria-pressed', 'true', { timeout: 30_000 });
		if (proof) {
			await proof.assert('voice-replies-enabled', async () => {
				await expect(reloadedToggle).toHaveAttribute('aria-pressed', 'true');
			});
			await proof.checkpoint('voice-replies-enabled');
		}

		await reloadedToggle.click();
		await expect(reloadedToggle).toHaveAttribute('aria-pressed', 'false');
		const reloadedMic = page.getByTestId('message-field').last().getByTestId('record-audio-button');
		await reloadedMic.dispatchEvent('mousedown');
		const recording = page.getByTestId('record-overlay');
		await expect(recording).toBeVisible({ timeout: 10_000 });
		await page.waitForTimeout(700);
		await recording.getByTestId('record-finish-button').click();
		await expect(reloadedToggle).toHaveAttribute('aria-pressed', 'true', { timeout: 120_000 });

		const speak = page.getByTestId('assistant-message-speak').last();
		await expect(speak).toBeVisible({ timeout: 15_000 });
		await speak.click();
		const player = page.getByTestId('assistant-speech-player');
		await expect(player).toBeVisible({ timeout: 30_000 });
		const regions = player.locator('.assistant-speech-region');
		await expect(regions).toHaveCount(2, { timeout: 30_000 });
		await expect(async () => {
			const ready = await player.locator('.assistant-speech-region.ready').count().catch(() => 0);
			const status = await player.getByTestId('assistant-speech-status').textContent();
			expect(ready > 0 || /playing|tap play/i.test(status || '')).toBeTruthy();
		}).toPass({ timeout: SPEECH_TIMEOUT_MS });

		const continueButton = player.getByTestId('assistant-speech-continue');
		if (await continueButton.isVisible().catch(() => false)) await continueButton.click();
		await expect(player.getByRole('button', { name: /pause voice response|play voice response/i })).toBeVisible({ timeout: 30_000 });
		if (proof) {
			await proof.assert('speech-player-visible', async () => {
				await expect(regions).toHaveCount(2);
				await expect(player.getByRole('button', { name: 'Previous paragraph' })).toBeVisible();
				await expect(player.getByRole('button', { name: 'Next paragraph' })).toBeVisible();
			});
			await proof.checkpoint('speech-player-visible');
		}

		await player.getByRole('button', { name: 'Next paragraph' }).click();
		await expect(regions.nth(1)).toHaveClass(/active/);
		await player.getByRole('button', { name: 'Previous paragraph' }).click();
		await expect(regions.nth(0)).toHaveClass(/active/);
		await expectNoPlayerOverlap(page, player);
		await expect(page.locator('body')).not.toContainText(/encrypted_auto_speak_response|generated_asset_id|speakable_text/);

		if (proof) {
			await proof.assert('paragraph-navigation-visible', async () => {
				await expect(regions.nth(0)).toHaveClass(/active/);
				await expectNoPlayerOverlap(page, player);
			});
			await proof.checkpoint('paragraph-navigation-visible');
			await proof.attach();
		}
		await deleteActiveChat(page, log);
	});
});

async function expectNoPlayerOverlap(page: any, player: any): Promise<void> {
	await expect.poll(async () => {
		const playerBox = await player.boundingBox();
		const composerBox = await page.getByTestId('message-field').last().boundingBox();
		const assistantBox = await page.getByTestId('message-assistant').last().boundingBox();
		if (!playerBox || !composerBox || !assistantBox) return false;
		const clearsComposer = playerBox.y + playerBox.height <= composerBox.y + 1;
		const clearsTranscript = assistantBox.y + assistantBox.height <= playerBox.y + 1;
		return clearsComposer && clearsTranscript;
	}, { timeout: 15_000 }).toBe(true);
}
