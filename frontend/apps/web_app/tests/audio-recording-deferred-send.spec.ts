/**
 * Regression coverage for sending voice recordings before transcription ends.
 * Mocks the paid realtime provider and external upload boundaries, holds
 * auto-correction, and verifies the same optimistic message is finalized in
 * place without making this a paid daily test.
 */

import { test, expect } from './helpers/cookie-audit';
/* eslint-disable @typescript-eslint/no-require-imports */
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { withMockMarker } = require('./signup-flow-helpers');
const { randomUUID } = require('node:crypto');

// Keep the real Send button and recording shortcuts while routing the resulting
// inference through a committed fixture in the isolated CI stack.
const AUDIO_SEND_PROMPT = withMockMarker('Please respond to this voice note.', 'test_hello');

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

async function mockCompletedRealtimeRecording(page: import('@playwright/test').Page): Promise<void> {
	let sentLiveDelta = false;
	await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, (socket) => {
		socket.send(JSON.stringify({
			type: 'session.ready',
			model: 'voxtral-mini-transcribe-realtime-2602',
			sample_rate: 16000,
		}));
		socket.onMessage((rawMessage) => {
			const message = JSON.parse(String(rawMessage));
			if (message.type === 'input_audio.append' && !sentLiveDelta) {
				sentLiveDelta = true;
				socket.send(JSON.stringify({
					type: 'transcription.text.delta',
					text: 'Send this completed recording',
				}));
				return;
			}
			if (message.type !== 'input_audio.end') return;
			socket.send(JSON.stringify({
				type: 'transcription.done',
				transcript: 'Send this completed recording directly.',
				language: 'en',
				model: 'voxtral-mini-transcribe-realtime-2602',
			}));
			socket.send(JSON.stringify({ type: 'correction.started', model: 'gemini-3.5-flash' }));
			socket.send(JSON.stringify({
				type: 'correction.done',
				title: 'Direct recording send',
				transcript: 'Send this completed recording directly.',
				correction_model: 'gemini-3.5-flash',
			}));
		});
	});
}

async function openAuthenticatedRecording(page: import('@playwright/test').Page): Promise<void> {
	const log = (message: string, metadata?: Record<string, unknown>) => {
		console.log(`[TEST][audio-enter-send] ${message}`, metadata ?? '');
	};
	await mockRecordingUpload(page);
	await mockCompletedRealtimeRecording(page);
	await loginToTestAccount(page, log, async () => undefined);
	await startNewChat(page, log);

	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 20000 });
	await editor.click();
	await page.keyboard.type(' ');
	await page.keyboard.press('Backspace');
	await page.keyboard.type(AUDIO_SEND_PROMPT);
	await page.getByTestId('message-field').last().getByTestId('record-audio-button')
		.dispatchEvent('mousedown', { button: 0 });
	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });
	await expect(overlay.getByTestId('recording-live-transcript')).toContainText(
		'Send this completed recording',
		{ timeout: 10000 },
	);
}

test.use({
	launchOptions: {
		args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']
	},
	permissions: ['microphone']
});

// contract-test: direct surface=gui.web assertions=message-input.embeds.gated-send,chats.local-state.precedence,chats.message.identity-idempotent
test('sending as correction finishes publishes the stored audio embed before the message', async ({ page }) => {
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
	await page.keyboard.type(AUDIO_SEND_PROMPT);

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

	// Reproduce NWWRB: correction finishes immediately before Send. The node must
	// remain blocking until its EmbedStore entry and contentRef are both ready.
	const sendErrors: string[] = [];
	const availabilityTraffic: string[] = [];
	page.on('console', (message) => {
		if (message.type() === 'error' && /\[ChatSyncService:Senders\]|\[handleSend\]|\[executeDeferredSend\]/.test(message.text())) {
			sendErrors.push(message.text().slice(0, 500));
		}
	});
	page.on('request', (request) => {
		if (new URL(request.url()).pathname.includes('/references/availability')) {
			availabilityTraffic.push(`${request.method()} requested`);
		}
	});
	page.on('requestfailed', (request) => {
		if (new URL(request.url()).pathname.includes('/references/availability')) {
			availabilityTraffic.push(`${request.method()} failed: ${request.failure()?.errorText}`);
		}
	});
	releaseCorrection();
	await expect(composerRecording.getByTestId('recording-auto-correction')).not.toBeVisible({
		timeout: 20000,
	});
	const availabilityResponse = page.waitForResponse((response) =>
		response.request().method() === 'POST' &&
		/^\/v1\/embeds\/chats\/[^/]+\/references\/availability$/.test(new URL(response.url()).pathname),
		{ timeout: 30000 },
	);
	await page.locator('[data-action="send-message"]').click();
	const availability = await availabilityResponse.catch((error: Error) => {
		throw new Error(`${error.message}; availability traffic: ${availabilityTraffic.join(', ') || 'none'}; send errors: ${sendErrors.join(' | ') || 'none'}`);
	});
	expect(availability.status()).toBe(200);
	expect(availability.headers()['access-control-allow-origin']).toBe(new URL(page.url()).origin);
	expect(availability.headers()['access-control-allow-credentials']).toBe('true');
	const pendingMessage = page.locator('[data-message-id]').last();
	await expect(pendingMessage).toBeVisible({ timeout: 10000 });
	const pendingMessageId = await pendingMessage.getAttribute('data-message-id');
	expect(pendingMessageId).toBeTruthy();

	const finalizedMessage = page.locator(`[data-message-id="${pendingMessageId}"]`);
	await expect(finalizedMessage).toHaveAttribute('data-status', 'synced', { timeout: 60000 });
	await expect(finalizedMessage.getByTestId('recording-preview')).toBeVisible({ timeout: 60000 });
	await expect(finalizedMessage.getByTestId('recording-preview-waveform')).toBeVisible();
	await expect(finalizedMessage.getByText('No transcript available')).not.toBeVisible();
	await expect(page.getByText(/Something went wrong while processing the embeds/i)).not.toBeVisible();
});

// contract-test: direct surface=gui.web assertions=message-input.embeds.gated-send,chats.local-state.precedence
test('an unavailable reference probe leaves one failed voice message for retry', async ({ page }) => {
	test.setTimeout(180000);
	await openAuthenticatedRecording(page);
	await page.getByTestId('record-overlay').getByTestId('record-finish-button').click();
	await expect(page.getByTestId('record-overlay')).not.toBeVisible({ timeout: 10000 });
	await expect(page.getByTestId('recording-preview')).toContainText('Send this completed recording directly.', {
		timeout: 20000,
	});
	let availabilityRequests = 0;
	let availabilityChatId: string | undefined;
	await page.route('**/v1/embeds/chats/*/references/availability*', (route) => {
		expect(route.request().method()).toBe('POST');
		availabilityChatId = new URL(route.request().url()).pathname.split('/')[4];
		availabilityRequests += 1;
		return route.abort('failed');
	});
	await page.locator('[data-action="send-message"]').click();
	await expect.poll(() => availabilityRequests).toBe(1);
	expect(availabilityChatId).toBeTruthy();
	// A synchronous send rejection keeps the editable recording in the composer.
	// Verify its optimistic row directly in encrypted local storage instead of
	// requiring a chat-history preview that this path does not render.
	await expect.poll(() => page.evaluate(async (chatId) => {
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			const request = indexedDB.open('chats_db');
			request.onsuccess = () => resolve(request.result);
			request.onerror = () => reject(request.error);
		});
		try {
			const rows = await new Promise<Array<Record<string, unknown>>>((resolve, reject) => {
				const request = db.transaction('messages', 'readonly').objectStore('messages').getAll();
				request.onsuccess = () => resolve(request.result as Array<Record<string, unknown>>);
				request.onerror = () => reject(request.error);
			});
			return rows.filter((row) => row.chat_id === chatId && row.role === 'user').map((row) => ({
				status: row.status,
				hasEncryptedContent: typeof row.encrypted_content === 'string' && row.encrypted_content.length > 0,
				hasPlaintextContent: Boolean(row.content),
			}));
		} finally {
			db.close();
		}
	}, availabilityChatId), { timeout: 30000 }).toEqual([{
		status: 'failed',
		hasEncryptedContent: true,
		hasPlaintextContent: false,
	}]);
	await expect(page.getByTestId('message-editor').getByTestId('recording-preview')).toBeVisible();
	expect(availabilityRequests).toBe(1);
});

for (const shortcut of [
	{
		name: 'a second Enter within 500ms',
		activate: async (page: import('@playwright/test').Page) => {
			await page.keyboard.press('Enter');
			await page.waitForTimeout(150);
			await page.keyboard.press('Enter');
		},
	},
	{
		name: 'holding Enter for one second',
		activate: async (page: import('@playwright/test').Page) => {
			await page.keyboard.down('Enter');
			await page.waitForTimeout(1100);
			await page.keyboard.up('Enter');
		},
	},
]) {
	// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
	test(`${shortcut.name} finishes and directly sends the voice recording`, async ({ page }) => {
		test.setTimeout(180000);
		await openAuthenticatedRecording(page);
		await shortcut.activate(page);
		await expect(page.getByTestId('record-overlay')).not.toBeVisible({ timeout: 10000 });

		const sentMessage = page
			.locator('[data-message-id]')
			.filter({ has: page.getByTestId('recording-preview') })
			.last();
		await expect(sentMessage).toBeVisible({ timeout: 60000 });
		await expect(sentMessage).toHaveAttribute('data-status', 'synced', { timeout: 60000 });
		await expect(sentMessage.getByTestId('recording-preview')).toContainText(
			'Send this completed recording directly.',
			{ timeout: 60000 },
		);
		await expect(page.getByTestId('message-editor')).toHaveText('');
		await expect(page.getByText(/Something went wrong while processing the embeds/i)).not.toBeVisible();
	});
}

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
