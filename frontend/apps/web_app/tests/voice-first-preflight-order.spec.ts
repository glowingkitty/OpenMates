/**
 * Focused regression for 6Z2NS: a recording used as the first chat message must
 * create the chat through preflight before persisting its speech preference.
 * Recorder, upload, and transcription boundaries are deterministic browser
 * fixtures; the authenticated chat/preflight/metadata protocol remains real.
 */

import { expect, test } from './helpers/cookie-audit';
import type { Page } from '@playwright/test';
/* eslint-disable @typescript-eslint/no-require-imports */
const { randomUUID } = require('node:crypto');
const {
	createSignupLogger,
	getTestAccount,
	withLiveMockMarker
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');

type ProtocolEvent = {
	direction: 'sent' | 'received';
	type: string;
	chatId?: string;
	messageId?: string;
	turnId?: string;
	preflightId?: string;
	errorCode?: string;
	hasPreflightChatMetadata?: boolean;
	hasSpeechPreference?: boolean;
};

function captureProtocolEvents(page: Page, events: ProtocolEvent[]): void {
	page.on('websocket', (websocket) => {
		const capture = (direction: ProtocolEvent['direction']) => (frame: { payload?: string | Buffer }) => {
			try {
				const message = JSON.parse(String(frame.payload));
				if (typeof message.type !== 'string') return;
				const payload = message.payload && typeof message.payload === 'object' ? message.payload : {};
				const messagePayload = message.type === 'chat_message_added' ? payload.message : payload;
				events.push({
					direction,
					type: message.type,
					chatId: typeof payload.chat_id === 'string' ? payload.chat_id : undefined,
					messageId: typeof messagePayload?.message_id === 'string' ? messagePayload.message_id : undefined,
					turnId: typeof payload.turn_id === 'string' ? payload.turn_id : undefined,
					preflightId: typeof payload.preflight_id === 'string' ? payload.preflight_id : undefined,
					errorCode: typeof payload.code === 'string' ? payload.code : undefined,
					hasPreflightChatMetadata: !!payload.encrypted_chat_metadata,
					hasSpeechPreference: typeof payload.encrypted_auto_speak_response === 'string'
				});
			} catch {
				// Ignore non-JSON WebSocket control frames.
			}
		};
		websocket.on('framesent', capture('sent'));
		websocket.on('framereceived', capture('received'));
	});
}

async function installRecordingFixtures(page: Page): Promise<void> {
	await page.route('**/v1/upload/file', async (route) => {
		const origin = route.request().headers().origin ?? 'http://localhost:5173';
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: {
				'access-control-allow-origin': origin,
				'access-control-allow-credentials': 'true'
			},
			body: JSON.stringify({
				embed_id: randomUUID(),
				filename: 'voice-first-regression.webm',
				content_type: 'audio/webm',
				content_hash: 'voice-first-regression-audio',
				files: {
					original: {
						s3_key: 'ci/audio/voice-first-regression.webm.enc',
						width: 0,
						height: 0,
						size_bytes: 1024,
						format: 'webm'
					}
				},
				s3_base_url: 'https://storage.ci.test',
				aes_key: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
				aes_nonce: 'AAAAAAAAAAAAAAAA',
				vault_wrapped_aes_key: 'vault:v1:ci-voice-first-key',
				malware_scan: 'clean',
				ai_detection: null,
				deduplicated: false
			})
		});
	});

	let sentLiveDelta = false;
	await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, (socket) => {
		socket.send(JSON.stringify({
			type: 'session.ready',
			model: 'voxtral-mini-transcribe-realtime-2602',
			sample_rate: 16000
		}));
		socket.onMessage((rawMessage) => {
			const message = JSON.parse(String(rawMessage));
			if (message.type === 'input_audio.append' && !sentLiveDelta) {
				sentLiveDelta = true;
				socket.send(JSON.stringify({
					type: 'transcription.text.delta',
					text: 'Calculate the square root of 144'
				}));
				return;
			}
			if (message.type !== 'input_audio.end') return;
			socket.send(JSON.stringify({
				type: 'transcription.done',
				transcript: 'Calculate the square root of 144.',
				language: 'en',
				model: 'voxtral-mini-transcribe-realtime-2602'
			}));
			socket.send(JSON.stringify({ type: 'correction.started', model: 'gemini-3.5-flash' }));
			socket.send(JSON.stringify({
				type: 'correction.done',
				title: 'Square root recording',
				transcript: 'Calculate the square root of 144.',
				correction_model: 'gemini-3.5-flash'
			}));
		});
	});
}

function findEventIndex(
	events: ProtocolEvent[],
	direction: ProtocolEvent['direction'],
	type: string,
	predicate: (event: ProtocolEvent) => boolean = () => true
): number {
	return events.findIndex((event) => event.direction === direction && event.type === type && predicate(event));
}

test.use({
	launchOptions: {
		args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']
	},
	permissions: ['microphone']
});

// contract-test: direct surface=gui.web assertions=assistant-speech.preference.chat-scoped-default-off,assistant-speech.preference.voice-recording-visible-activation,chats.completion.lease-fenced,chats.persistence.client-encrypted,message-input.recording.lifecycle,message-input.embeds.gated-send
test('voice-first chat preflights before persisting its speech preference', async ({ page }) => {
	test.setTimeout(180_000);
	test.skip(!getTestAccount().email, 'Test account credentials required.');

	const markedPrompt = withLiveMockMarker('Calculate the square root of 144', 'math_calculate_web');
	expect(markedPrompt).toMatch(/<<<TEST_LIVE_MOCK:math_calculate_web(?::[^>]*)?>>>$/);

	const log = createSignupLogger('voice-first-preflight-order');
	const events: ProtocolEvent[] = [];
	captureProtocolEvents(page, events);
	await installRecordingFixtures(page);
	await loginToTestAccount(page, log, async () => undefined);
	await startNewChat(page, log);

	const messageField = page.getByTestId('message-field').last();
	const editor = messageField.getByTestId('message-editor');
	await editor.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');
	await messageField.getByTestId('record-audio-button').dispatchEvent('mousedown', { button: 0 });

	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5_000 });
	await expect(overlay.getByTestId('recording-live-transcript')).toContainText(
		'Calculate the square root of 144',
		{ timeout: 10_000 }
	);
	await overlay.getByTestId('record-finish-button').click();
	await expect(overlay).not.toBeVisible({ timeout: 10_000 });
	await expect(messageField.getByTestId('recording-preview')).toContainText(
		'Calculate the square root of 144.',
		{ timeout: 20_000 }
	);

	// Recording intentionally exercises the voice preference activation. Turn it
	// back off before dispatch so this protocol-only test cannot generate paid TTS.
	// The retained false intent follows the same sender bug branch as true intent:
	// before the fix, any intent eagerly wrote metadata ahead of new-chat preflight.
	const voiceToggle = messageField.getByTestId('assistant-speech-toggle');
	await expect(voiceToggle).toHaveAttribute('aria-pressed', 'true');
	await voiceToggle.click();
	await expect(voiceToggle).toHaveAttribute('aria-pressed', 'false');

	await editor.click();
	await page.keyboard.type(markedPrompt);
	await page.locator('[data-action="send-message"]').click();

	await expect.poll(
		() => findEventIndex(events, 'sent', 'chat_turn_preflight'),
		{ timeout: 30_000, intervals: [100, 250, 500, 1_000] }
	).toBeGreaterThanOrEqual(0);
	const preflightIndex = findEventIndex(events, 'sent', 'chat_turn_preflight');
	const preflight = events[preflightIndex];
	expect(preflight.chatId).toBeTruthy();
	expect(preflight.messageId).toBeTruthy();
	expect(preflight.turnId).toBeTruthy();
	expect(preflight.hasPreflightChatMetadata).toBe(true);

	await expect.poll(
		() => findEventIndex(events, 'received', 'chat_turn_preflight_ack', (event) => event.turnId === preflight.turnId),
		{ timeout: 30_000, intervals: [100, 250, 500, 1_000] }
	).toBeGreaterThan(preflightIndex);
	const preflightAckIndex = findEventIndex(
		events,
		'received',
		'chat_turn_preflight_ack',
		(event) => event.turnId === preflight.turnId
	);

	await expect.poll(
		() => findEventIndex(events, 'received', 'chat_message_confirmed', (event) => event.messageId === preflight.messageId),
		{ timeout: 30_000, intervals: [100, 250, 500, 1_000] }
	).toBeGreaterThan(preflightAckIndex);
	const confirmedIndex = findEventIndex(
		events,
		'received',
		'chat_message_confirmed',
		(event) => event.messageId === preflight.messageId
	);

	await expect.poll(
		() => findEventIndex(events, 'sent', 'encrypted_chat_metadata', (event) => (
			event.chatId === preflight.chatId && event.hasSpeechPreference === true
		)),
		{ timeout: 30_000, intervals: [100, 250, 500, 1_000] }
	).toBeGreaterThan(confirmedIndex);
	const preferenceMetadataIndex = findEventIndex(events, 'sent', 'encrypted_chat_metadata', (event) => (
		event.chatId === preflight.chatId && event.hasSpeechPreference === true
	));

	await expect.poll(
		() => findEventIndex(events, 'received', 'encrypted_metadata_stored', (event) => event.chatId === preflight.chatId),
		{ timeout: 30_000, intervals: [100, 250, 500, 1_000] }
	).toBeGreaterThan(preferenceMetadataIndex);

	expect(events.some((event) => event.errorCode === 'existing_chat_metadata_forbidden'), JSON.stringify(events)).toBe(false);
	await expect(page.locator(`[data-message-id="${preflight.messageId}"]`)).toHaveAttribute('data-status', 'synced');
});
