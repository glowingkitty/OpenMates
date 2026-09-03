/**
 * Regression coverage for sending voice recordings before transcription ends.
 * Holds the real transcription response at the browser boundary so the composer
 * takes its deferred-send path, then verifies the same optimistic message is
 * finalized in place with its transcript and waveform.
 */

import { test, expect } from './helpers/cookie-audit';
/* eslint-disable @typescript-eslint/no-require-imports */
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');

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
	let releaseTranscriptionResponse!: () => void;
	let markTranscriptionReady!: () => void;
	const transcriptionReady = new Promise<void>((resolve) => {
		markTranscriptionReady = resolve;
	});
	const transcriptionRelease = new Promise<void>((resolve) => {
		releaseTranscriptionResponse = resolve;
	});

	await page.route('**/v1/apps/audio/skills/transcribe', async (route) => {
		const response = await route.fetch();
		markTranscriptionReady();
		await transcriptionRelease;
		await route.fulfill({ response });
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
	await page.waitForTimeout(2000);
	await overlay.getByTestId('record-finish-button').click();
	await expect(overlay).not.toBeVisible({ timeout: 10000 });
	await transcriptionReady;

	await page.locator('[data-action="send-message"]').click();
	const pendingMessage = page.locator('[data-message-id]').last();
	await expect(pendingMessage).toBeVisible({ timeout: 10000 });
	const pendingMessageId = await pendingMessage.getAttribute('data-message-id');
	expect(pendingMessageId).toBeTruthy();

	releaseTranscriptionResponse();

	const finalizedMessage = page.locator(`[data-message-id="${pendingMessageId}"]`);
	await expect(finalizedMessage.getByTestId('recording-preview')).toBeVisible({ timeout: 60000 });
	await expect(finalizedMessage.getByTestId('recording-preview-waveform')).toBeVisible();
	await expect(finalizedMessage.getByText('No transcript available')).not.toBeVisible();
});
