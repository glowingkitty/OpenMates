/**
 * Manual paid proof for the complete message-input transcription pipeline.
 *
 * Chromium replays a committed speech WAV that was generated once through
 * OpenMates audio.speak (ElevenLabs). The test itself never calls ElevenLabs;
 * it sends the prerecorded microphone stream through the real authenticated
 * realtime transcription and correction services on dev.
 *
 * This spec is classified manual_expensive in daily_ai_test_manifest.json and
 * is therefore excluded from scheduled daily discovery.
 */

import fs from 'node:fs';
import path from 'node:path';
import { test, expect } from './helpers/cookie-audit';
/* eslint-disable @typescript-eslint/no-require-imports */
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');

const SPEECH_FIXTURE = fs.existsSync(
	'/workspace/backend/tests/fixtures/realtime_transcription_speech.wav',
)
	? '/workspace/backend/tests/fixtures/realtime_transcription_speech.wav'
	: path.resolve(
			__dirname,
			'../../../../backend/tests/fixtures/realtime_transcription_speech.wav',
		);
const EXPECTED_TRANSCRIPT_FRAGMENT = /working correctly in openmates/i;

test.use({
	launchOptions: {
		args: [
			'--use-fake-device-for-media-stream',
			'--use-fake-ui-for-media-stream',
			`--use-file-for-fake-audio-capture=${SPEECH_FIXTURE}`,
		],
	},
	permissions: ['microphone'],
});

// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle,message-input.embeds.gated-send,chats.local-state.precedence,chats.message.identity-idempotent
test('real speech streams a live transcript and finalizes the sent recording in place', async ({ page }) => {
	test.setTimeout(300_000);

	const log = (message: string, metadata?: Record<string, unknown>) => {
		console.log(`[TEST][live-audio-transcription] ${message}`, metadata ?? '');
	};
	const serverEvents: string[] = [];
	let realtimeSocketCount = 0;
	let batchTranscriptionRequests = 0;

	page.on('websocket', (socket) => {
		if (!socket.url().includes('/v1/apps/audio/realtime-transcription')) return;
		realtimeSocketCount += 1;
		socket.on('framereceived', ({ payload }) => {
			try {
				const message = JSON.parse(String(payload));
				if (typeof message.type === 'string') serverEvents.push(message.type);
			} catch {
				// Ignore non-JSON protocol frames; application events are JSON.
			}
		});
	});
	page.on('request', (request) => {
		if (
			request.method() === 'POST' &&
			request.url().includes('/v1/apps/audio/skills/transcribe')
		) {
			batchTranscriptionRequests += 1;
		}
	});

	await loginToTestAccount(page, log, async () => undefined);
	await startNewChat(page, log);

	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 20_000 });
	await editor.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');

	const messageField = page.getByTestId('message-field').last();
	const micButton = messageField.getByTestId('record-audio-button');
	await expect(micButton).toBeVisible({ timeout: 20_000 });
	await micButton.click();

	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 10_000 });
	const liveTranscript = overlay.getByTestId('recording-live-transcript');
	await expect(liveTranscript).toContainText(EXPECTED_TRANSCRIPT_FRAGMENT, {
		timeout: 60_000,
	});
	await expect(overlay.getByTestId('release-text')).not.toContainText(/recording/i);
	await expect.poll(() => serverEvents.includes('transcription.text.delta')).toBe(true);

	await overlay.getByTestId('record-finish-button').click();
	await expect(overlay).not.toBeVisible({ timeout: 10_000 });

	const composerRecording = messageField.getByTestId('recording-preview');
	await expect(composerRecording).toBeVisible({ timeout: 20_000 });
	await expect(composerRecording).toContainText(EXPECTED_TRANSCRIPT_FRAGMENT, {
		timeout: 20_000,
	});

	// Send immediately while finalization/correction is still allowed to finish.
	const sendButton = page.locator('[data-action="send-message"]').last();
	await expect(sendButton).toBeVisible({ timeout: 10_000 });
	await sendButton.click();

	const sentMessage = page
		.locator('[data-message-id]')
		.filter({ has: page.getByTestId('recording-preview') })
		.last();
	await expect(sentMessage).toBeVisible({ timeout: 20_000 });
	const sentMessageId = await sentMessage.getAttribute('data-message-id');
	expect(sentMessageId).toBeTruthy();

	await expect.poll(() => serverEvents.includes('transcription.done'), {
		timeout: 60_000,
	}).toBe(true);
	await expect.poll(() => serverEvents.includes('correction.started'), {
		timeout: 60_000,
	}).toBe(true);
	await expect.poll(() => serverEvents.includes('correction.done'), {
		timeout: 60_000,
	}).toBe(true);

	const finalizedMessage = page.locator(`[data-message-id="${sentMessageId}"]`);
	const finalizedRecording = finalizedMessage.getByTestId('recording-preview');
	await expect(finalizedRecording).toBeVisible({ timeout: 60_000 });
	await expect(finalizedRecording).toHaveAttribute('data-transcript', 'available');
	await expect(finalizedRecording).toContainText(EXPECTED_TRANSCRIPT_FRAGMENT);
	await expect(finalizedRecording.getByTestId('recording-preview-waveform')).toBeVisible();

	expect(realtimeSocketCount).toBeGreaterThanOrEqual(1);
	expect(batchTranscriptionRequests, 'successful realtime transcription must not use batch fallback').toBe(0);
	log('Real realtime transcription and correction completed.', {
		realtimeSocketCount,
		serverEvents,
		sentMessageId,
	});
});
