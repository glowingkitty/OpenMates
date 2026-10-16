/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Canonical deployed voice-recording and assistant-speech journey.
 * The browser transcribes a microphone recording into editable draft text,
 * sends that text after the user explicitly enables speech, then proves segment controls,
 * durable reopen, action placement, and the five-second feedback boundary.
 */
export {};

const { test, expect } = require('./console-monitor');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount,
	installE2EServerContentOverrideGate,
	withLiveMockMarker
} = require('./signup-flow-helpers');
const { extractLiveTestMarker, loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const SPEECH_TIMEOUT_MS = 240_000;
const SERVER_RESPONSE_TIMEOUT_MS = 20_000;
const FIRST_USEFUL_SPEECH_TIMEOUT_MS = 5_000;
const PROOF_FINAL_STATE_HOLD_MS = 5_000;
const LIVE_MOCK_GROUP = 'assistant_response_speech_web';
const TRANSCRIPTION_TEXT = 'Please confirm this voice playback check.';
const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_WIDTH === 390 ? 'web-phone' : 'web-laptop';

function withRequiredLiveMock(message: string): string {
	const marked = withLiveMockMarker(message, LIVE_MOCK_GROUP);
	expect(marked).toMatch(/<<<TEST_LIVE_(?:MOCK|RECORD):assistant_response_speech_web(?::[A-Za-z0-9_-]+)?>>>/);
	return marked;
}

const PROOF_CONTRACT = defineVideoProof({
	id: 'audio-recording-and-speech',
	title: 'Voice recording and assistant speech',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'transcript-sent-as-text',
			text: 'The corrected voice transcript enters the editable composer, then the user sends its text and starts assistant speech.',
			checkpoint: 'transcript-sent-as-text',
			devices: ['web-laptop', 'web-phone']
		},
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
			id: 'transcript-sent-as-text',
			checkpoint: 'transcript-sent-as-text',
			visual: 'The sent message contains transcript text with no recording card while assistant speech feedback is visible.',
			devices: ['web-laptop', 'web-phone']
		},
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

test.describe.serial('Audio recording and assistant speech', () => {
	test.setTimeout(900_000);

	// contract-test: direct surface=gui.web assertions=assistant-speech.preference.chat-scoped-default-off,message-input.audio.editable-transcript,assistant-speech.acknowledgement.first-useful-feedback-within-five-seconds,assistant-speech.execution.app-skill-progressive,assistant-speech.on-demand.generate-missing-only,assistant-speech.playback.single-queue-segment-control,assistant-speech.playback.pinned-full-response-waveform,assistant-speech.playback.two-second-idle-grace,assistant-speech.playback.autoplay-recovery-visible,chats.local-state.precedence,chats.message.identity-idempotent,chats.persistence.client-encrypted
	test('sends corrected transcript text and controls the spoken response', async ({ page }: { page: any }, testInfo: any) => {
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		const log = createSignupLogger('audio-recording-and-speech');
		await page.addInitScript(() => {
			let nextElementId = 1;
			const elementIds = new WeakMap<HTMLMediaElement, number>();
			const originalPlay = HTMLMediaElement.prototype.play;
			(window as any).__assistantSpeechPlaybackCalls = [];
			HTMLMediaElement.prototype.play = function (...args: Parameters<HTMLMediaElement['play']>) {
				let elementId = elementIds.get(this);
				if (!elementId) {
					elementId = nextElementId++;
					elementIds.set(this, elementId);
				}
				(window as any).__assistantSpeechPlaybackCalls.push({ elementId, src: this.currentSrc || this.src });
				return originalPlay.apply(this, args);
			};
		});
        // Keep only safe sequence/status metadata from the real replay exchange.
        let requestedSpeechSequences: number[] = [];
        let acceptedSpeechSegments: Array<{ request_sequence: number; status: string }> = [];
        let manualRequestDeferred = false;
        const generationRequests: number[] = [];
        const registeredSpeechSegments = new Set<string>();
        let cancelledSpeechRequests = 0;
		const sentChatProtocolEvents: Array<{ type: string; chatId?: string }> = [];
        page.on('websocket', (socket: any) => {
            socket.on('framesent', (event: { payload: string | Buffer }) => {
                try {
                    const frame = JSON.parse(String(event.payload));
					if (frame.type === 'chat_turn_preflight' || frame.type === 'encrypted_chat_metadata') {
						sentChatProtocolEvents.push({
							type: frame.type,
							chatId: typeof frame.payload?.chat_id === 'string' ? frame.payload.chat_id : undefined
						});
					}
                    if (frame.type === 'assistant_speech' && frame.payload?.action === 'request') {
                        requestedSpeechSequences = frame.payload.segments.map((segment: { sequence: number }) => segment.sequence);
                        manualRequestDeferred = frame.payload.defer_after_first === true;
                        acceptedSpeechSegments = [];
                    }
                    if (frame.type === 'assistant_speech' && frame.payload?.action === 'generate') {
                        generationRequests.push(frame.payload.segments?.[0]?.sequence);
                    }
                    if (frame.type === 'assistant_speech' && frame.payload?.action === 'cancel') cancelledSpeechRequests += 1;
                } catch { /* Ignore non-JSON transport frames. */ }
            });
            socket.on('framereceived', (event: { payload: string | Buffer }) => {
                try {
                    const frame = JSON.parse(String(event.payload));
                    if (frame.type === 'assistant_speech_status' && frame.payload?.status === 'accepted') {
                        acceptedSpeechSegments = frame.payload.segments.map((segment: { request_sequence: number; status: string }) => ({
                            request_sequence: segment.request_sequence, status: segment.status,
                        }));
                    }
                    if (frame.type === 'assistant_speech_status' && frame.payload?.status === 'registered' && typeof frame.payload.segment_id === 'string') {
                        registeredSpeechSegments.add(frame.payload.segment_id);
                    }
                } catch { /* Ignore non-JSON transport frames. */ }
            });
        });

		await archiveExistingScreenshots(log);
		const screenshot = createStepScreenshotter(log);
		const proof = IS_PROOF_CAPTURE
			? createVideoProofRuntime(PROOF_CONTRACT, {
				device: PROOF_DEVICE,
				attach: testInfo.attach.bind(testInfo),
				captureFrame: () => page.screenshot({ type: 'png' })
			})
			: null;
		let audioUploads = 0;
		let batchTranscriptions = 0;
		page.on('request', (request: any) => {
			if (request.method() !== 'POST') return;
			if (request.url().includes('/v1/upload/file')) audioUploads++;
			if (request.url().includes('/v1/apps/audio/skills/transcribe')) batchTranscriptions++;
		});
		await page.routeWebSocket('**/v1/apps/audio/realtime-transcription*', (socket: any) => {
			socket.send(JSON.stringify({ type: 'session.ready' }));
			socket.onMessage((payload: string) => {
				if (JSON.parse(payload).type !== 'input_audio.end') return;
				socket.send(JSON.stringify({ type: 'transcription.done', transcript: TRANSCRIPTION_TEXT, model: 'test-realtime' }));
				socket.send(JSON.stringify({ type: 'correction.done', transcript: TRANSCRIPTION_TEXT, correction_model: 'test-correction' }));
			});
		});
		await installE2EServerContentOverrideGate(page, 'assistant-response-speech');

		await loginToTestAccount(page, log, screenshot);
		await startNewChat(page, log);

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
		await expect(editor).toHaveText(TRANSCRIPTION_TEXT, { timeout: 30_000 });
		await expect(voiceToggle).toHaveAttribute('aria-pressed', 'false');
		await expect(messageField.getByTestId('recording-preview')).toHaveCount(0);
		expect(audioUploads).toBe(0);
		expect(batchTranscriptions).toBe(0);
		await voiceToggle.click();
		await expect(voiceToggle).toHaveAttribute('aria-pressed', 'true');
		const firstRequest = extractLiveTestMarker(withRequiredLiveMock('Reply in exactly two short plain-text paragraphs confirming this encrypted chat is ready for a voice playback test.'));
		await editor.click();
		await page.keyboard.type(' ' + firstRequest.message);
		const sendAcceptedAt = Date.now();
		await editor.evaluate((element: HTMLElement, marker: string) => element.dispatchEvent(new CustomEvent('custom-send-message', {
			bubbles: true,
			cancelable: true,
			detail: { testMockMarker: marker }
		})), firstRequest.testMockMarker);
		const finalizedMessage = page.locator('[data-message-id]').filter({ hasText: TRANSCRIPTION_TEXT }).last();
		await expect(finalizedMessage).toBeVisible({ timeout: 30_000 });
		await expect(finalizedMessage.getByTestId('recording-preview')).toHaveCount(0);
		const pendingMessageId = await finalizedMessage.getAttribute('data-message-id');
		expect(pendingMessageId).toBeTruthy();
		const player = page.getByTestId('assistant-speech-player');
		await expect(player).toBeVisible({ timeout: FIRST_USEFUL_SPEECH_TIMEOUT_MS });
		expect(Date.now() - sendAcceptedAt).toBeLessThanOrEqual(FIRST_USEFUL_SPEECH_TIMEOUT_MS);
		if (proof) {
			await proof.assert('transcript-sent-as-text', async () => {
				await expect(finalizedMessage).toContainText(TRANSCRIPTION_TEXT);
				await expect(finalizedMessage.getByTestId('recording-preview')).toHaveCount(0);
				await expect(player).toBeVisible();
			});
			await proof.checkpoint('transcript-sent-as-text');
		}
		await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: SERVER_RESPONSE_TIMEOUT_MS });
		await expect(page.getByTestId('message-assistant').last()).not.toHaveAttribute('data-streaming', 'true', { timeout: 300_000 });
		const firstAssistantMessage = page.getByTestId('message-assistant').last();
		const identityRow = firstAssistantMessage.getByTestId('assistant-identity-row');
		await expect(identityRow.getByTestId('chat-mate-name')).toBeVisible();
		const firstSpeakAction = identityRow.getByTestId('assistant-message-speak');
		await expect(firstSpeakAction).toBeVisible();
		await expect(firstSpeakAction).toHaveAccessibleName('Speak response');
		await expect(firstAssistantMessage.getByTestId('generated-by-container').getByTestId('assistant-message-speak')).toHaveCount(0);
		const [messageBox, speakBox] = await Promise.all([firstAssistantMessage.boundingBox(), firstSpeakAction.boundingBox()]);
		expect(messageBox).toBeTruthy();
		expect(speakBox).toBeTruthy();
		expect(speakBox!.x + speakBox!.width).toBeLessThanOrEqual(messageBox!.x + messageBox!.width);
		const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? '';
		expect(chatId, 'voice-first chat should become durable after its first message').toBeTruthy();
		const voiceChatProtocolEvents = sentChatProtocolEvents.filter((event) => event.chatId === chatId);
		const preflightIndex = voiceChatProtocolEvents.findIndex((event) => event.type === 'chat_turn_preflight');
		const firstMetadataIndex = voiceChatProtocolEvents.findIndex((event) => event.type === 'encrypted_chat_metadata');
		expect(preflightIndex, JSON.stringify(voiceChatProtocolEvents)).toBeGreaterThanOrEqual(0);
		expect(firstMetadataIndex, JSON.stringify(voiceChatProtocolEvents)).toBeGreaterThan(preflightIndex);
		const initialHeaderTitle = page.getByTestId('chat-header-title');
		await expect(initialHeaderTitle).toBeVisible({ timeout: 30_000 });
		await expect(initialHeaderTitle).not.toContainText(/untitled|creating new chat/i);
		await expect(page.getByTestId('chat-header-icon')).toBeVisible({ timeout: 30_000 });
		await expect(page.getByTestId('chat-header-summary')).not.toHaveText('', { timeout: 30_000 });

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: 60_000 });
		const reloadedHeaderTitle = page.getByTestId('chat-header-title');
		await expect(reloadedHeaderTitle).toBeVisible({ timeout: 30_000 });
		await expect(reloadedHeaderTitle).not.toContainText(/untitled|creating new chat/i);
		await expect(page.getByTestId('chat-header-icon')).toBeVisible({ timeout: 30_000 });
		await expect(page.getByTestId('chat-header-summary')).not.toHaveText('', { timeout: 30_000 });
		const reloadedMessage = page.locator(`[data-message-id="${pendingMessageId}"]`);
		await expect(reloadedMessage).toContainText(TRANSCRIPTION_TEXT);
		await expect(reloadedMessage.getByTestId('recording-preview')).toHaveCount(0);
		await expect(page.getByTestId('message-field').last().getByTestId('message-editor')).toBeEmpty();
		await page.getByTestId('message-field').last().click();
		const reloadedToggle = page.getByTestId('message-field').last().getByTestId('assistant-speech-toggle');
		await expect(reloadedToggle).toHaveAttribute('aria-pressed', 'true', { timeout: 30_000 });
		await expect(reloadedToggle).toHaveAccessibleName('Turn off speaking');
		await page.evaluate(() => {
			(window as any).__assistantSpeechPlaybackCalls = [];
		});
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

		await expect(player).toBeVisible({ timeout: SPEECH_TIMEOUT_MS });
		await expect(player).toHaveAttribute('data-presentation', 'replayable_track_queue', { timeout: SPEECH_TIMEOUT_MS });
		const waveform = player.getByTestId('assistant-speech-waveform');
		const regions = player.getByTestId('assistant-speech-waveform-region');
		await expect.poll(async () => regions.count(), { timeout: SPEECH_TIMEOUT_MS }).toBeGreaterThanOrEqual(2);
        await expect.poll(() => registeredSpeechSegments.size, { timeout: SPEECH_TIMEOUT_MS }).toBeGreaterThanOrEqual(1);
		await expect(async () => {
			const placeholder = await waveform.getAttribute('data-placeholder');
			const status = await player.getAttribute('data-status');
			expect(placeholder === 'false' || status === 'autoplay_blocked').toBeTruthy();
		}).toPass({ timeout: SPEECH_TIMEOUT_MS });
		await expect.poll(async () => page.evaluate(() => {
			const calls = (window as any).__assistantSpeechPlaybackCalls as Array<{ elementId: number; src: string }>;
			return new Set(calls.map((call) => call.src).filter(Boolean)).size;
		}), { timeout: SPEECH_TIMEOUT_MS }).toBeGreaterThanOrEqual(2);
		const speechPlaybackElementIds = await page.evaluate(() => {
			const calls = (window as any).__assistantSpeechPlaybackCalls as Array<{ elementId: number; src: string }>;
			return [...new Set(calls.filter((call) => call.src).map((call) => call.elementId))];
		});
		expect(speechPlaybackElementIds, 'confirmation and generated speech must retain one autoplay-authorized media element').toHaveLength(1);

		await expect(player.getByTestId('assistant-speech-primary-control').last()).toBeVisible({ timeout: 30_000 });
		await expect(player.getByTestId('assistant-speech-next-chapter')).toBeVisible();

		await expect(streamingAssistant).not.toHaveAttribute('data-streaming', 'true', { timeout: 300_000 });
		await expect(page.locator('[data-testid="embed-preview"][data-app-id="weather"][data-status="finished"]')).toBeVisible({ timeout: 120_000 });

		const firstSegmentId = await waveform.getAttribute('data-segment-id');
		const selectNextParagraph = () => player.getByTestId('assistant-speech-next-chapter').click();
		if (proof) {
			await proof.action('select-next-paragraph', selectNextParagraph);
		} else {
			await selectNextParagraph();
		}
		await expect(waveform).not.toHaveAttribute('data-segment-id', firstSegmentId || '');
		await expect(player.locator('[data-testid="assistant-speech-waveform-region"][data-position="current"]')).toHaveCount(1);
		await expect(player.getByTestId('assistant-speech-previous-chapter')).toBeVisible();
		await expectNoPlayerOverlap(page, player);
		await expect(page.locator('body')).not.toContainText(/encrypted_auto_speak_response|generated_asset_id|speakable_text/);

		if (proof) {
			await proof.assert('paragraph-navigation-visible', async () => {
				await expect(waveform).not.toHaveAttribute('data-segment-id', firstSegmentId || '');
				await expectNoPlayerOverlap(page, player);
			});
			await proof.checkpoint('paragraph-navigation-visible');
			await page.waitForTimeout(PROOF_FINAL_STATE_HOLD_MS);
			await proof.attach();
		}
		await player.getByTestId('assistant-speech-previous-chapter').click();
		await expect(waveform).toHaveAttribute('data-segment-id', firstSegmentId || '');
		const playPause = player.getByTestId('assistant-speech-primary-control').last();
		if ((await player.getAttribute('data-status')) !== 'paused') {
			if ((await playPause.getAttribute('aria-label')) === 'Play voice response') await playPause.click();
			await expect.poll(() => player.getAttribute('data-status')).toMatch(/playing|paused/);
			if ((await player.getAttribute('data-status')) === 'playing') await playPause.click();
		}
		await expect(player).toHaveAttribute('data-status', 'paused');
		await expect(player.getByTestId('assistant-speech-close')).toBeVisible();
		await player.getByTestId('assistant-speech-close').click();
		await expect(player).not.toBeVisible();
        expect(cancelledSpeechRequests).toBeGreaterThanOrEqual(1);
        expect(new Set(generationRequests).size).toBe(generationRequests.length);
		const reopenSpeakAction = streamingAssistant.getByTestId('assistant-message-speak');
		await reopenSpeakAction.focus();
		await expect(reopenSpeakAction).toBeFocused();
		await reopenSpeakAction.press('Enter');
        await expect.poll(() => requestedSpeechSequences.length).toBeGreaterThanOrEqual(2);
        expect(manualRequestDeferred).toBe(true);
        await expect.poll(() => acceptedSpeechSegments.map((segment) => segment.request_sequence).sort((a, b) => a - b), {
            timeout: 30_000,
        }).toEqual(requestedSpeechSequences);
        expect(acceptedSpeechSegments.every((segment) => segment.status !== 'error'), 'replay must retain all paragraphs after app summaries').toBe(true);

		await expect(player).toBeVisible({ timeout: 30_000 });
		await expect(player.getByTestId('assistant-speech-waveform')).toHaveAttribute('data-placeholder', 'false');
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
