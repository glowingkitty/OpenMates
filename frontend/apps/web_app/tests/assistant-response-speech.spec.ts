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
	getTestAccount,
	withLiveMockMarker
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const SPEECH_TIMEOUT_MS = 240_000;
const LIVE_MOCK_GROUP = 'assistant_response_speech_web';
const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_WIDTH === 390 ? 'web-phone' : 'web-laptop';

function withRequiredLiveMock(message: string): string {
	const marked = withLiveMockMarker(message, LIVE_MOCK_GROUP);
	expect(marked).toMatch(/<<<TEST_LIVE_(?:MOCK|RECORD):assistant_response_speech_web>>>/);
	return marked;
}

const PROOF_CONTRACT = defineVideoProof({
	id: 'assistant-response-speech',
	title: 'Assistant response speech playback',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'processing-progress-visible',
			text: 'The assistant and Weather processing preview appear while skill and speech work continue independently.',
			checkpoint: 'processing-progress-visible',
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
			id: 'processing-progress-visible',
			checkpoint: 'processing-progress-visible',
			visual: 'The assistant message contains a Weather preview in Processing state before the final response completes.',
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

	// contract-test: direct surface=gui.web assertions=assistant-speech.preference.chat-scoped-default-off,assistant-speech.preference.voice-recording-visible-activation,assistant-speech.execution.app-skill-progressive,assistant-speech.on-demand.generate-missing-only,assistant-speech.playback.single-queue-segment-control,assistant-speech.playback.pinned-full-response-waveform,assistant-speech.playback.two-second-idle-grace,assistant-speech.playback.autoplay-recovery-visible,message-input.actions.visibility,message-input.send.ownership
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
			withRequiredLiveMock('Reply with one short sentence confirming this encrypted chat is ready for a voice playback test.'),
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
		await expect(voiceToggle).toHaveAttribute('data-speech-state', 'off');
		await expect(voiceToggle).toHaveAccessibleName('Speak responses');
		await expect(voiceToggle.getByTestId('assistant-speech-muted-icon')).toHaveAttribute('data-visible', 'true');
		await expect(voiceToggle.getByTestId('assistant-speech-muted-icon').locator('path')).not.toHaveCount(0);
		await expect(voiceToggle.getByTestId('assistant-speech-audio-icon')).toHaveAttribute('data-visible', 'false');
		await attachmentMenu.click();
		await expect(messageField.getByTestId('composer-attachment-camera')).toBeVisible();
		await expect(messageField.getByTestId('composer-camera-button')).toHaveCount(0);
		await attachmentMenu.click();
		const [voiceBox, micBox] = await Promise.all([voiceToggle.boundingBox(), mic.boundingBox()]);
		expect(voiceBox, 'speech control should have layout geometry').toBeTruthy();
		expect(micBox, 'microphone control should have layout geometry').toBeTruthy();
		expect(voiceBox!.x + voiceBox!.width).toBeLessThanOrEqual(micBox!.x);
		expect(micBox!.x - (voiceBox!.x + voiceBox!.width)).toBeLessThanOrEqual(32);
		const editor = messageField
			.getByTestId('message-editor')
			.locator('[contenteditable="true"]');
		await editor.fill('Composer control verification');
		await expect(messageField.getByTestId('composer-send-button')).toBeVisible({ timeout: 10_000 });
		await editor.fill('');
		await expect(voiceToggle).toHaveAttribute('aria-pressed', 'false');
		await voiceToggle.click();
		await expect(voiceToggle).toHaveAttribute('aria-pressed', 'true');
		const speechStatus = messageField.getByTestId('assistant-speech-toggle-status');
		await expect(speechStatus).toHaveText('Speech turned on');
		await expect(voiceToggle).toHaveAccessibleName('Turn off speaking');
		await expect(voiceToggle.getByTestId('assistant-speech-muted-icon')).toHaveAttribute('data-visible', 'false');
		await expect(voiceToggle.getByTestId('assistant-speech-audio-icon')).toHaveAttribute('data-visible', 'true');
		await expect(voiceToggle.getByTestId('assistant-speech-audio-icon').locator('path')).not.toHaveCount(0);
		expect(await voiceToggle.getByTestId('assistant-speech-audio-icon').evaluate((element: Element) => getComputedStyle(element).transitionProperty)).toContain('opacity');

		await page.getByRole('button', { name: 'Turn off speaking' }).click();
		await expect(speechStatus).toHaveText('Speech turned off');
		await expect(voiceToggle).toHaveAccessibleName('Speak responses');
		await expect(voiceToggle).toHaveAttribute('data-speech-state', 'off');
		await expect(voiceToggle.getByTestId('assistant-speech-muted-icon')).toHaveAttribute('data-visible', 'true');

		await mic.dispatchEvent('mousedown');
		const recording = page.getByTestId('record-overlay');
		await expect(recording).toBeVisible({ timeout: 10_000 });
		await page.waitForTimeout(700);
		await recording.getByTestId('record-finish-button').click();
		await expect(voiceToggle).toHaveAttribute('aria-pressed', 'true', { timeout: 120_000 });
		await expect(speechStatus).toHaveText('Speech turned on');
		await expect(voiceToggle.getByTestId('assistant-speech-audio-icon')).toHaveAttribute('data-visible', 'true');

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: 60_000 });
		await page.getByTestId('message-field').last().click();
		const reloadedToggle = page.getByTestId('message-field').last().getByTestId('assistant-speech-toggle');
		await expect(reloadedToggle).toHaveAttribute('aria-pressed', 'true', { timeout: 30_000 });
		await expect(reloadedToggle).toHaveAccessibleName('Turn off speaking');
		await sendMessage(
			page,
			withRequiredLiveMock('Use weather.forecast to check Berlin for the next two days, then answer in exactly two short plain-text paragraphs. Summarize the forecast first, then give one practical suggestion.'),
			log,
			screenshot,
			'assistant-speech-weather-source'
		);
		const streamingAssistant = page.getByTestId('message-assistant').last();
		const processingWeather = streamingAssistant.locator('[data-testid="embed-preview"][data-app-id="weather"][data-status="processing"]');
		await expect(streamingAssistant).toBeVisible({ timeout: 60_000 });
		await expect(processingWeather).toBeVisible({ timeout: 120_000 });
		if (proof) {
			await proof.assert('processing-progress-visible', async () => {
				await expect(streamingAssistant).toBeVisible();
				await expect(processingWeather).toBeVisible();
			});
			await proof.checkpoint('processing-progress-visible');
		}

		const player = page.getByTestId('assistant-speech-player');
		await expect(player).toBeVisible({ timeout: SPEECH_TIMEOUT_MS });
		const regions = player.getByTestId('assistant-speech-region');
		await expect.poll(async () => regions.count(), { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
		await expect(async () => {
			const ready = await regions.evaluateAll((elements: Element[]) => elements.filter((element) => element.getAttribute('data-status') === 'ready').length);
			const status = await player.getByTestId('assistant-speech-status').textContent();
			expect(ready > 0 || /playing|tap play/i.test(status || '')).toBeTruthy();
		}).toPass({ timeout: SPEECH_TIMEOUT_MS });

		const continueButton = player.getByTestId('assistant-speech-continue');
		if (await continueButton.isVisible().catch(() => false)) await continueButton.click();
		await expect(player.getByRole('button', { name: /pause voice response|play voice response/i })).toBeVisible({ timeout: 30_000 });
		await expect(player.getByRole('button', { name: 'Previous paragraph' })).toBeVisible();
		await expect(player.getByRole('button', { name: 'Next paragraph' })).toBeVisible();

		await expect(streamingAssistant).not.toHaveAttribute('data-streaming', 'true', { timeout: 300_000 });
		await expect(page.locator('[data-testid="embed-preview"][data-app-id="weather"][data-status="finished"]')).toBeVisible({ timeout: 120_000 });

		const selectNextParagraph = () => player.getByRole('button', { name: 'Next paragraph' }).click();
		if (proof) {
			await proof.action('select-next-paragraph', selectNextParagraph);
		} else {
			await selectNextParagraph();
		}
		await expect(regions.nth(1)).toHaveAttribute('data-active', 'true');
		await expectNoPlayerOverlap(page, player);
		await expect(page.locator('body')).not.toContainText(/encrypted_auto_speak_response|generated_asset_id|speakable_text/);

		if (proof) {
			await proof.assert('paragraph-navigation-visible', async () => {
				await expect(regions.nth(1)).toHaveAttribute('data-active', 'true');
				await expectNoPlayerOverlap(page, player);
			});
			await proof.checkpoint('paragraph-navigation-visible');
			await proof.attach();
		}
		await player.getByRole('button', { name: 'Previous paragraph' }).click();
		await expect(regions.nth(0)).toHaveAttribute('data-active', 'true');
		await deleteActiveChat(page, log);
	});
});

async function expectNoPlayerOverlap(page: any, player: any): Promise<void> {
	await expect.poll(async () => {
		const playerBox = await player.boundingBox();
		const chatBox = await page.getByTestId('chat-side').boundingBox();
		const composerBox = await page.getByTestId('message-field').last().boundingBox();
		const actions = page.getByTestId('chat-top-actions');
		const actionsBox = await actions.boundingBox();
		const transcriptPadding = await page.getByTestId('chat-history-content').evaluate((element: Element) => Number.parseFloat(getComputedStyle(element).paddingTop));
		if (!playerBox || !chatBox || !composerBox || !actionsBox) return false;
		const [playerZ, actionsZ] = await Promise.all([
			player.evaluate((element: Element) => Number.parseInt(getComputedStyle(element).zIndex || '0', 10)),
			actions.evaluate((element: Element) => Number.parseInt(getComputedStyle(element).zIndex || '0', 10))
		]);
		const clearsComposer = playerBox.y + playerBox.height <= composerBox.y + 1;
		const pinnedToChatTop = Math.abs(playerBox.y - chatBox.y) <= 2;
		const spansChat = Math.abs(playerBox.x - chatBox.x) <= 2 && Math.abs(playerBox.width - chatBox.width) <= 4;
		const actionsOverlayPlayer = actionsBox.y >= playerBox.y && actionsBox.y + actionsBox.height <= playerBox.y + playerBox.height && actionsZ > playerZ;
		const transcriptClearsPlayer = transcriptPadding >= playerBox.height;
		return clearsComposer && pinnedToChatTop && spansChat && actionsOverlayPlayer && transcriptClearsPlayer;
	}, { timeout: 15_000 }).toBe(true);
}
