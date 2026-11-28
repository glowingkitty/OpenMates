/* eslint-disable @typescript-eslint/no-require-imports -- The shared Playwright helpers expose CommonJS exports. */
import { performance } from 'node:perf_hooks';
import { expect, test as auditedTest } from './helpers/cookie-audit';
import { proofAudioLaunchArgs, useProofMicrophone, withProofAudio } from './helpers/proof-audio';
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { requireRealInference } = require('./helpers/real-inference-guard');
const test = withProofAudio(auditedTest);

test.use({ launchOptions: { args: proofAudioLaunchArgs() }, permissions: ['microphone'] });

for (const mode of ['baseline', 'gated'] as const) {
	// contract-test: direct surface=gui.web assertions=message-input.audio.correction-gate,message-input.audio.editable-transcript
	test(`${mode} real microphone dictation becomes editable composer text`, async ({
		page, baseURL
	}, testInfo) => {
		requireRealInference('Composer dictation', baseURL!);
		test.setTimeout(180_000);
		const terminal = new Set(['correction.done', 'correction.skipped', 'correction.failed', 'session.error']);
		let rawTranscript = '';
		let result: { type: string; transcript?: string; title?: string } | undefined;
		let audioStorageRequests = 0;
		let recordingSessionState = 'socket not opened';
		if (mode === 'baseline') {
			// Select the original title-generating correction policy with the same
			// microphone, browser and backend. All frames still go to the real server.
			await page.addInitScript(() => {
				const NativeWebSocket = window.WebSocket;
				window.WebSocket = class extends NativeWebSocket {
					constructor(url: string | URL, protocols?: string | string[]) {
						const target = new URL(url, window.location.href);
						if (target.pathname === '/v1/apps/audio/realtime-transcription') {
							target.searchParams.delete('correction_context');
						}
						super(target, protocols);
					}
				};
			});
		}

		page.on('request', (request) => {
			if (request.method() === 'POST' && /\/v1\/(upload\/file|apps\/audio\/skills\/transcribe)/.test(request.url())) {
				audioStorageRequests += 1;
			}
		});
		page.on('websocket', (socket) => {
			if (!socket.url().includes('/v1/apps/audio/realtime-transcription')) return;
			recordingSessionState = 'awaiting session.ready';
			expect(new URL(socket.url()).searchParams.get('correction_context'))
				.toBe(mode === 'gated' ? 'dictation' : null);
			socket.on('socketerror', () => { recordingSessionState = 'WebSocket connection error'; });
			socket.on('framereceived', ({ payload }) => {
				if (typeof payload !== 'string') return;
				const message = JSON.parse(payload);
				if (message.type === 'session.ready' || message.type === 'session.error') {
					recordingSessionState = message.type;
				}
				if (message.type === 'transcription.done') rawTranscript = message.transcript;
				if (terminal.has(message.type)) result = message;
			});
		});

		await loginToTestAccount(page, () => undefined, async () => undefined);
		await startNewChat(page, () => undefined);
		await useProofMicrophone(page);
		const field = page.getByTestId('message-field').filter({ visible: true });
		const editor = field.getByTestId('message-editor').locator('[contenteditable="true"]');
		await editor.fill('Notes: ');
		await editor.press('End');
		await field.getByTestId('record-audio-button').dispatchEvent('mousedown', { button: 0 });
		const overlay = page.getByTestId('record-overlay');
		await expect(overlay).toBeVisible();
		await expect.poll(() => recordingSessionState, { timeout: 15_000 }).toBe('session.ready');
		await expect(editor).toContainText(/working correctly in Open\s?Mates/i, { timeout: 25_000 });
		const finishAt = performance.now();
		await overlay.getByTestId('record-finish-button').click();
		await expect(overlay).not.toBeVisible({ timeout: 45_000 });
		await expect(editor).toBeFocused();
		const finishToEditorMs = Math.round(performance.now() - finishAt);
		expect(result?.type).toBe('correction.done');
		if (mode === 'gated') expect(result?.title).toBeUndefined();
		else expect(typeof result?.title).toBe('string');
		expect(rawTranscript).toMatch(/working correctly in Open\s?Mates/i);
		await expect(editor).toContainText(result!.transcript!);
		await expect(editor).toHaveText(/^Notes: /);
		await expect(field.getByTestId('recording-preview')).toHaveCount(0);
		await expect(page.getByTestId('message-user')).toHaveCount(0);
		expect(audioStorageRequests).toBe(0);
		await testInfo.attach('editable-dictation', {
			body: await field.screenshot(), contentType: 'image/png',
		});
		await testInfo.attach('finish-to-editable-latency', {
			body: JSON.stringify({ mode, finishToEditorMs }), contentType: 'application/json',
		});
	});
}
