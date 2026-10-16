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

// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.recording.lifecycle
test('real speech becomes editable composer text without storing audio', async ({ page }) => {
	test.setTimeout(300_000);
	const serverEvents: string[] = [];
	let realtimeSocketCount = 0;
	let audioUploads = 0;
	let batchTranscriptionRequests = 0;
	page.on('websocket', (socket) => {
		if (!socket.url().includes('/v1/apps/audio/realtime-transcription')) return;
		realtimeSocketCount += 1;
		socket.on('framereceived', ({ payload }) => {
			try {
				const message = JSON.parse(String(payload));
				if (typeof message.type === 'string') serverEvents.push(message.type);
			} catch { /* Ignore non-JSON protocol frames. */ }
		});
	});
	page.on('request', (request) => {
		if (request.method() !== 'POST') return;
		if (request.url().includes('/v1/upload/file')) audioUploads += 1;
		if (request.url().includes('/v1/apps/audio/skills/transcribe')) batchTranscriptionRequests += 1;
	});
	await loginToTestAccount(page, () => undefined, async () => undefined);
	await startNewChat(page, () => undefined);
	const messageField = page.getByTestId('message-field').filter({ visible: true });
	await expect(messageField).toHaveCount(1);
	await messageField.click();
	const editor = messageField.getByTestId('message-editor').locator('[contenteditable="true"]');
	await expect(editor).toBeVisible({ timeout: 20_000 });
	await editor.fill('Please ');
	const userMessageCount = await page.getByTestId('user-message-content').count();
	const micButton = messageField.getByTestId('record-audio-button');
	await expect(micButton).toBeVisible({ timeout: 20_000 });
	await micButton.click();
	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 10_000 });
	await expect(overlay.getByTestId('recording-live-transcript')).toContainText(EXPECTED_TRANSCRIPT_FRAGMENT, { timeout: 60_000 });
	await overlay.getByTestId('record-finish-button').click();
	await expect(overlay).not.toBeVisible({ timeout: 10_000 });
	await expect.poll(() => serverEvents.includes('correction.done') || serverEvents.includes('correction.skipped'), { timeout: 60_000 }).toBe(true);
	await expect(editor).toContainText(EXPECTED_TRANSCRIPT_FRAGMENT, { timeout: 60_000 });
	await expect(editor).toHaveText(/^Please /);
	await expect(editor).toBeFocused();
	await expect(messageField.getByTestId('recording-preview')).toHaveCount(0);
	const sendButton = messageField.getByTestId('composer-send-button').filter({ visible: true });
	await expect(sendButton).toHaveCount(1);
	await expect(sendButton).toBeVisible();
	await page.keyboard.type('!');
	await expect(editor).toContainText('!');
	await expect(page.getByTestId('user-message-content')).toHaveCount(userMessageCount);

	expect(realtimeSocketCount).toBe(1);
	expect(audioUploads).toBe(0);
	expect(batchTranscriptionRequests).toBe(0);
});
