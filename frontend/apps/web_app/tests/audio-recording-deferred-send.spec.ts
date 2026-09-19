/**
 * Regression coverage for sending voice recordings before transcription ends.
 * Mocks the paid realtime provider and external upload boundaries, holds
 * auto-correction, and verifies the same optimistic message is finalized in
 * place without making this a paid daily test.
 */

import { test, expect } from './helpers/cookie-audit';
/* eslint-disable @typescript-eslint/no-require-imports */
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { randomUUID } = require('node:crypto');

async function mockRecordingUpload(page: import('@playwright/test').Page): Promise<void> {
	await page.route('**/v1/upload/file', async (route) => {
		const origin = route.request().headers().origin ?? 'http://localhost:5173';
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			headers: {
				'access-control-allow-origin': origin,
				'access-control-allow-credentials': 'true',
			},
			body: JSON.stringify({
				embed_id: randomUUID(),
				filename: 'recording.webm',
				content_type: 'audio/webm',
				content_hash: 'synthetic-audio-hash',
				files: {
					original: {
						s3_key: 'ci/audio/recording.webm.enc',
						width: 0,
						height: 0,
						size_bytes: 1024,
						format: 'webm',
					},
				},
				s3_base_url: 'https://storage.ci.test',
				aes_key: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
				aes_nonce: 'AAAAAAAAAAAAAAAA',
				vault_wrapped_aes_key: 'vault:v1:ci-audio-key',
				malware_scan: 'clean',
				ai_detection: null,
				deduplicated: false,
			}),
		});
	});
}

test.use({
	launchOptions: {
		args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']
	},
	permissions: ['microphone']
});

// contract-test: direct surface=gui.web assertions=message-input.embeds.gated-send,chats.local-state.precedence,chats.message.identity-idempotent
test('sending while transcription is pending finalizes the same audio message', async ({ page }) => {
	test.setTimeout(180000);

	const log = (message: string, metadata?: Record<string, unknown>) => {
		console.log(`[TEST][deferred-audio-send] ${message}`, metadata ?? '');
	};
	let releaseCorrection!: () => void;
	let markRawTranscriptReady!: () => void;
	const rawTranscriptReady = new Promise<void>((resolve) => {
		markRawTranscriptReady = resolve;
	});
	const correctionRelease = new Promise<void>((resolve) => {
		releaseCorrection = resolve;
	});
	let sentLiveDelta = false;
	await mockRecordingUpload(page);

	await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, (socket) => {
		socket.send(JSON.stringify({
			type: 'session.ready',
			model: 'voxtral-mini-transcribe-realtime-2602',
			sample_rate: 16000,
		}));
		socket.onMessage(async (rawMessage) => {
			const message = JSON.parse(String(rawMessage));
			if (message.type === 'input_audio.append' && !sentLiveDelta) {
				sentLiveDelta = true;
				socket.send(JSON.stringify({
					type: 'transcription.text.delta',
					text: 'Please schedule the project review',
				}));
				return;
			}
			if (message.type !== 'input_audio.end') return;
			socket.send(JSON.stringify({
				type: 'transcription.done',
				transcript: 'Please schedule the project review for Thursday afternoon.',
				language: 'en',
				model: 'voxtral-mini-transcribe-realtime-2602',
			}));
			socket.send(JSON.stringify({ type: 'correction.started', model: 'gemini-3.5-flash' }));
			markRawTranscriptReady();
			await correctionRelease;
			socket.send(JSON.stringify({
				type: 'correction.done',
				title: 'Schedule project review',
				transcript: 'Please schedule the project review for Thursday afternoon.',
				correction_model: 'gemini-3.5-flash',
			}));
		});
	});

	await loginToTestAccount(page, log, async () => undefined);
	await startNewChat(page, log);

	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 20000 });
	await editor.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');

	const micButton = page.getByTestId('message-field').last().getByTestId('record-audio-button');
	await expect(micButton).toBeVisible({ timeout: 20000 });
	await micButton.dispatchEvent('mousedown', { button: 0 });
	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });
	await expect(overlay.getByTestId('recording-live-transcript')).toContainText(
		'Please schedule the project review',
		{ timeout: 10000 },
	);
	await overlay.getByTestId('record-finish-button').click();
	await expect(overlay).not.toBeVisible({ timeout: 10000 });
	await rawTranscriptReady;
	const composerRecording = page.getByTestId('recording-preview');
	await expect(composerRecording).toContainText('Please schedule the project review');
	await expect(composerRecording.getByTestId('recording-auto-correction')).toBeVisible();

	await page.locator('[data-action="send-message"]').click();
	const pendingMessage = page.locator('[data-message-id]').last();
	await expect(pendingMessage).toBeVisible({ timeout: 10000 });
	const pendingMessageId = await pendingMessage.getAttribute('data-message-id');
	expect(pendingMessageId).toBeTruthy();

	releaseCorrection();

	const finalizedMessage = page.locator(`[data-message-id="${pendingMessageId}"]`);
	await expect(finalizedMessage.getByTestId('recording-preview')).toBeVisible({ timeout: 60000 });
	await expect(finalizedMessage.getByTestId('recording-preview-waveform')).toBeVisible();
	await expect(finalizedMessage.getByText('No transcript available')).not.toBeVisible();
});

// contract-test: supporting surface=gui.web assertions=message-input.recording.lifecycle
test('a realtime failure falls back to one batch transcription', async ({ page }) => {
	test.setTimeout(180000);
	const log = (message: string, metadata?: Record<string, unknown>) => {
		console.log(`[TEST][audio-fallback] ${message}`, metadata ?? '');
	};
	let realtimeFailed = false;
	let batchRequests = 0;
	await mockRecordingUpload(page);

	await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, (socket) => {
		socket.send(JSON.stringify({ type: 'session.ready', sample_rate: 16000 }));
		socket.onMessage((rawMessage) => {
			const message = JSON.parse(String(rawMessage));
			if (message.type !== 'input_audio.append' || realtimeFailed) return;
			realtimeFailed = true;
			socket.send(JSON.stringify({
				type: 'session.error',
				message: 'Synthetic realtime outage',
			}));
		});
	});
	await page.route('**/v1/apps/audio/skills/transcribe', async (route) => {
		batchRequests += 1;
		const request = route.request().postDataJSON();
		const id = request.requests[0].id;
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				success: true,
				data: {
					results: [{
						id,
						results: [{
							title: 'Batch fallback recording',
							transcript: 'The recording was recovered by batch transcription.',
							transcript_original: 'The recording was recovered by batch transcription.',
							use_corrected: false,
							model: 'voxtral-mini-2602',
						}],
					}],
				},
			}),
		});
	});

	await loginToTestAccount(page, log, async () => undefined);
	await startNewChat(page, log);
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 20000 });
	await editor.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');

	const micButton = page.getByTestId('message-field').last().getByTestId('record-audio-button');
	await micButton.dispatchEvent('mousedown', { button: 0 });
	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });
	await expect.poll(() => realtimeFailed).toBe(true);
	await page.waitForTimeout(500);
	await overlay.getByTestId('record-finish-button').click();

	const preview = page.getByTestId('recording-preview');
	await expect(preview).toContainText(
		'The recording was recovered by batch transcription.',
		{ timeout: 60000 },
	);
	expect(batchRequests).toBe(1);
});
