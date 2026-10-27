/**
 * Finish leaves corrected dictation editable; recording Send submits it once
 * after correction, through the same message pipeline as ordinary text.
 * The paid realtime provider is mocked; chat sends use the existing isolated
 * inference fixture. Audio upload, batch transcription and embed-reference
 * requests are rejected so a regression cannot permanently store the recording.
 */
import { test, expect } from './helpers/cookie-audit';
import type { Page } from '@playwright/test';
import { allowFixtureMicrophone } from './helpers/recording-permission';
/* eslint-disable @typescript-eslint/no-require-imports */
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { withMockMarker } = require('./signup-flow-helpers');

const AUDIO_SEND_PROMPT = withMockMarker('Please respond to this voice note.', 'test_hello');
const RAW_TRANSCRIPT = 'please schedule project review thursday';
const CORRECTED_TRANSCRIPT = 'Please schedule the project review for Thursday afternoon.';
const ADDED_NOTES = ' Include the design team in the review.';

async function rejectPermanentRecordingStorage(page: Page): Promise<string[]> {
	const requests: string[] = [];
	await page.route(/\/v1\/(?:upload\/file|apps\/audio\/skills\/transcribe|embeds\/chats\/[^/]+\/references\/availability)(?:\?|$)/, (route) => {
		requests.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
		return route.abort('blockedbyclient');
	});
	return requests;
}

async function mockRealtimeRecording(page: Page, options: {
	correctionRelease?: Promise<void>;
	failCorrection?: boolean;
} = {}): Promise<void> {
	let sentLiveDelta = false;
	await page.routeWebSocket(/\/v1\/apps\/audio\/realtime-transcription(?:\?|$)/, (socket) => {
		socket.send(JSON.stringify({ type: 'session.ready', sample_rate: 16000 }));
		socket.onMessage(async (rawMessage) => {
			const message = JSON.parse(String(rawMessage));
			if (message.type === 'input_audio.append' && !sentLiveDelta) {
				sentLiveDelta = true;
				socket.send(JSON.stringify({ type: 'transcription.text.delta', text: RAW_TRANSCRIPT }));
				return;
			}
			if (message.type !== 'input_audio.end') return;
			socket.send(JSON.stringify({ type: 'transcription.done', transcript: RAW_TRANSCRIPT, model: 'test-realtime' }));
			socket.send(JSON.stringify({ type: 'correction.started', model: 'test-correction' }));
			if (options.correctionRelease) await options.correctionRelease;
			socket.send(JSON.stringify(options.failCorrection
				? { type: 'session.error', message: 'Synthetic correction failure' }
				: { type: 'correction.done', transcript: CORRECTED_TRANSCRIPT, correction_model: 'test-correction' }));
		});
	});
}

async function openAuthenticatedRecording(page: Page): Promise<void> {
	const log = (message: string, metadata?: Record<string, unknown>) => {
		console.log(`[TEST][audio-transcript-send] ${message}`, metadata ?? '');
	};
	await loginToTestAccount(page, log, async () => undefined);
	await startNewChat(page, log);
	const editor = page.getByTestId('message-editor').locator('.ProseMirror');
	await expect(editor).toBeVisible({ timeout: 20000 });
	await editor.fill(`${AUDIO_SEND_PROMPT} `);
	await editor.press('End');
	await page.getByTestId('message-field').last().getByTestId('record-audio-button')
		.dispatchEvent('mousedown', { button: 0 });
	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toBeVisible({ timeout: 5000 });
	await expect(overlay.getByTestId('recording-live-transcript')).toContainText(RAW_TRANSCRIPT, { timeout: 10000 });
}

async function expectEditableTranscript(page: Page): Promise<void> {
	await expect(page.getByTestId('record-overlay')).not.toBeVisible({ timeout: 20000 });
	const editor = page.getByTestId('message-editor').locator('.ProseMirror');
	await expect(editor).toContainText(AUDIO_SEND_PROMPT);
	await expect(editor).toContainText(CORRECTED_TRANSCRIPT);
	await expect(editor).not.toContainText(RAW_TRANSCRIPT);
	await expect(editor).toBeFocused();
	await expect(page.getByTestId('message-field').last()).toHaveAttribute('data-focused', 'true');
	await expect(page.getByTestId('recording-preview')).toHaveCount(0);
	await expect(editor.locator('audio, video, [data-embed-id]')).toHaveCount(0);
	await expect(page.getByTestId('message-user')).toHaveCount(0);
}

async function addNotesAndSend(page: Page): Promise<void> {
	const editor = page.getByTestId('message-editor').locator('.ProseMirror');
	await editor.press('ControlOrMeta+End');
	await page.keyboard.type(ADDED_NOTES);
	await expect(editor).toContainText(CORRECTED_TRANSCRIPT);
	await expect(editor).toContainText(ADDED_NOTES.trim());
	await page.getByTestId('composer-send-button').filter({ visible: true }).click();
	const message = page.getByTestId('message-user');
	await expect(message).toHaveCount(1);
	await expect(message).toContainText(CORRECTED_TRANSCRIPT);
	await expect(message).toContainText(ADDED_NOTES.trim());
	const messageId = await message.getAttribute('data-message-id');
	expect(messageId).toBeTruthy();
	await expect(message).toHaveAttribute('data-status', 'synced', { timeout: 60000 });
	await expect(message).toHaveAttribute('data-message-id', messageId!);
	await expect(message.getByTestId('recording-preview')).toHaveCount(0);
	await expect(editor).toHaveText('');
	await expect(page.getByText(/Something went wrong while processing the embeds/i)).not.toBeVisible();
}

async function expectDirectTranscriptSent(page: Page): Promise<void> {
	await expect(page.getByTestId('record-overlay')).not.toBeVisible({ timeout: 20000 });
	const message = page.getByTestId('message-user');
	await expect(message).toHaveCount(1);
	await expect(message).toContainText('Please respond to this voice note.');
	await expect(message).toContainText(CORRECTED_TRANSCRIPT);
	await expect(message).not.toContainText(RAW_TRANSCRIPT);
	const messageId = await message.getAttribute('data-message-id');
	expect(messageId).toBeTruthy();
	await expect(message).toHaveAttribute('data-status', 'synced', { timeout: 60000 });
	await expect(message).toHaveAttribute('data-message-id', messageId!);
	await expect(message).toHaveCount(1);
	await expect(message.getByTestId('recording-preview')).toHaveCount(0);
	await expect(page.getByTestId('message-editor').locator('.ProseMirror')).toHaveText('');
	await expect(page.getByTestId('message-field').last()).toHaveAttribute('data-focused', 'false');
	await expect(page.getByTestId('new-chat-button')).toBeVisible();
}

test.use({
	launchOptions: {
		args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']
	},
	permissions: ['microphone']
});

test.beforeEach(async ({ page }) => {
	await allowFixtureMicrophone(page, '**/*');
});

for (const phase of ['recording', 'correction']) {
	// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.embeds.gated-send,chats.message.identity-idempotent
	test(`round Send during ${phase} waits for corrected text and submits once`, async ({ page }) => {
		test.setTimeout(180000);
		const storageRequests = await rejectPermanentRecordingStorage(page);
		let releaseCorrection!: () => void;
		const correctionRelease = new Promise<void>((resolve) => { releaseCorrection = resolve; });
		await mockRealtimeRecording(page, { correctionRelease });
		await openAuthenticatedRecording(page);
		const overlay = page.getByTestId('record-overlay');
		const field = page.getByTestId('message-field').last();
		await expect(field).toHaveCSS('height', '180px');
		if (phase === 'correction') {
			await overlay.getByTestId('record-finish-button').click();
			await expect(overlay).toHaveAttribute('data-recording-processing', 'true');
			await expect(field).toHaveCSS('height', '180px');
		}
		const send = overlay.getByTestId('record-send-button');
		await expect(send).toHaveAccessibleName('Send');
		await expect(send).toBeEnabled();
		await send.click();
		await expect(send).toBeDisabled();
		await expect(field).toHaveAttribute('data-focused', 'false');
		await expect(page.getByTestId('new-chat-button')).toBeHidden();
		await expect(page.getByTestId('input-dismiss-button')).toHaveCount(0);
		await expect(field).toHaveCSS('height', '180px');
		await expect(overlay).toHaveCSS('height', /^(48|60)px$/);
		await expect(overlay.getByTestId('recording-processing-text')).toBeVisible();
		await expect(overlay.getByTestId('record-cancel-button')).toBeVisible();
		await expect(overlay.getByTestId('record-finish-button')).toBeHidden();
		await expect(overlay).toHaveAttribute('data-recording-processing', 'true');
		await expect(page.getByTestId('message-user')).toHaveCount(0);
		await expect(page.getByTestId('message-editor').locator('.ProseMirror')).toHaveText(AUDIO_SEND_PROMPT);
		releaseCorrection();
		await expectDirectTranscriptSent(page);
		expect(storageRequests).toEqual([]);
	});
}

// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.recording.lifecycle
test('cancelling a pending recording Send preserves notes without submitting', async ({ page }) => {
	test.setTimeout(120000);
	const storageRequests = await rejectPermanentRecordingStorage(page);
	await mockRealtimeRecording(page, { correctionRelease: new Promise(() => {}) });
	await openAuthenticatedRecording(page);
	const overlay = page.getByTestId('record-overlay');
	await overlay.getByTestId('record-send-button').click();
	await expect(overlay).toHaveAttribute('data-recording-processing', 'true');
	await expect(overlay.getByTestId('record-send-button')).toBeDisabled();
	await overlay.getByTestId('record-cancel-button').click();
	await expect(overlay).not.toBeVisible();
	await expect(page.getByTestId('message-editor').locator('.ProseMirror')).toHaveText(AUDIO_SEND_PROMPT);
	await expect(page.getByTestId('message-user')).toHaveCount(0);
	expect(storageRequests).toEqual([]);
});

// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,message-input.recording.lifecycle,chats.local-state.precedence,chats.message.identity-idempotent
test('held correction returns editable transcript and notes before one explicit send', async ({ page }) => {
	test.setTimeout(180000);
	const storageRequests = await rejectPermanentRecordingStorage(page);
	let releaseCorrection!: () => void;
	const correctionRelease = new Promise<void>((resolve) => { releaseCorrection = resolve; });
	await mockRealtimeRecording(page, { correctionRelease });
	await openAuthenticatedRecording(page);
	await page.getByTestId('record-overlay').getByTestId('record-finish-button').click();
	const overlay = page.getByTestId('record-overlay');
	await expect(overlay).toHaveAttribute('data-recording-processing', 'true');
	await expect(overlay.getByTestId('record-finish-button')).toBeDisabled();
	await expect(page.getByTestId('message-editor').locator('.ProseMirror')).toHaveText(AUDIO_SEND_PROMPT);
	await expect(page.getByTestId('message-user')).toHaveCount(0);
	releaseCorrection();
	await expectEditableTranscript(page);
	await addNotesAndSend(page);
	expect(storageRequests).toEqual([]);
});

// contract-test: direct surface=gui.web assertions=message-input.audio.editable-transcript,chats.local-state.precedence,chats.message.identity-idempotent
test('plain corrected dictation sends without an audio embed reference probe', async ({ page }) => {
	test.setTimeout(180000);
	const storageRequests = await rejectPermanentRecordingStorage(page);
	await mockRealtimeRecording(page);
	await openAuthenticatedRecording(page);
	await page.getByTestId('record-overlay').getByTestId('record-finish-button').click();
	await expectEditableTranscript(page);
	await addNotesAndSend(page);
	expect(storageRequests).toEqual([]);
});

for (const shortcut of [
	{
		name: 'a second Enter within 500ms',
		activate: async (page: Page) => {
			await page.keyboard.press('Enter');
			await page.waitForTimeout(150);
			await page.keyboard.press('Enter');
		},
	},
	{
		name: 'holding Enter for one second',
		activate: async (page: Page) => {
			await page.keyboard.down('Enter');
			await page.waitForTimeout(1100);
			await page.keyboard.up('Enter');
		},
	},
]) {
	// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle,message-input.audio.editable-transcript,chats.message.identity-idempotent
	test(`${shortcut.name} finishes into editable text without auto-sending`, async ({ page }) => {
		test.setTimeout(180000);
		const storageRequests = await rejectPermanentRecordingStorage(page);
		await mockRealtimeRecording(page);
		await openAuthenticatedRecording(page);
		await shortcut.activate(page);
		await expectEditableTranscript(page);
		await addNotesAndSend(page);
		expect(storageRequests).toEqual([]);
	});
}

// contract-test: direct surface=gui.web assertions=message-input.recording.lifecycle,message-input.audio.editable-transcript,chats.local-state.precedence
test('realtime correction failure preserves notes without upload or batch fallback', async ({ page }) => {
	test.setTimeout(120000);
	const storageRequests = await rejectPermanentRecordingStorage(page);
	await mockRealtimeRecording(page, { failCorrection: true });
	await openAuthenticatedRecording(page);
	await page.getByTestId('record-overlay').getByTestId('record-send-button').click();
	await expect(page.getByTestId('record-overlay')).not.toBeVisible({ timeout: 20000 });
	const editor = page.getByTestId('message-editor').locator('.ProseMirror');
	await expect(editor).toHaveText(AUDIO_SEND_PROMPT);
	await expect(page.getByTestId('recording-preview')).toHaveCount(0);
	await expect(page.getByTestId('message-user')).toHaveCount(0);
	expect(storageRequests).toEqual([]);
});
