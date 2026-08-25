/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Live DeepSeek V4 Pro browser contract.
 *
 * Selects the exact model, waits for terminal attribution, and cold-reloads the
 * saved chat so provider completion cannot leave the chat surface unavailable.
 */
export {};

const { test, expect } = require('./console-monitor');
const {
	archiveExistingScreenshots,
	createSignupLogger,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { selectMentionResult } = require('./helpers/mention-test-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_VIDEO_WIDTH = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10);
const PROOF_DEVICE = PROOF_VIDEO_WIDTH === 390 ? 'web-phone' : 'web-laptop';
const DEMONSTRATION_REVIEW_HOLD_MS = 3_500;

const proofContract = defineVideoProof({
	id: 'deepseek-v4-pro-live-chat',
	title: 'DeepSeek V4 Pro completes and survives chat reload',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'model-selected',
			text: 'The composer selects the exact DeepSeek V4 Pro model for a new chat.',
			checkpoint: 'deepseek-model-selected',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'response-complete',
			text: 'DeepSeek V4 Pro returns the requested response and reaches terminal model attribution.',
			checkpoint: 'deepseek-response-complete',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'reload-complete',
			text: 'After a cold page reload, the completed DeepSeek response and chat remain available.',
			checkpoint: 'deepseek-reload-complete',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'deepseek.model-selected',
			checkpoint: 'deepseek-model-selected',
			visual: 'The message composer contains the DeepSeek V4 Pro mention.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'deepseek.response-complete',
			checkpoint: 'deepseek-response-complete',
			visual: 'The assistant response is complete and attributed to DeepSeek V4 Pro without error text.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'deepseek.reload-complete',
			checkpoint: 'deepseek-reload-complete',
			visual: 'The same completed response remains visible after reload with no loading or error state.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

// contract-test: direct surface=gui.web assertions=chats.surface.semantic-parity,chats.completion.pending-delivery
test('DeepSeek V4 Pro completes and the chat remains available after reload', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(240_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logCheckpoint = createSignupLogger('DEEPSEEK_MODEL_OVERRIDE');
	await archiveExistingScreenshots(logCheckpoint);
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, { filenamePrefix: 'deepseek' });
	const proof = IS_PROOF_CAPTURE
		? createVideoProofRuntime(proofContract, {
				device: PROOF_DEVICE,
				attach: testInfo.attach.bind(testInfo),
				captureFrame: () => page.screenshot({ type: 'png' })
			})
		: null;

	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);
	await selectMentionResult(page, 'deepseek-v4-pro', 'DeepSeek V4 Pro');
	const editor = page.getByTestId('message-editor');
	await expect(editor).toContainText('@DeepSeek-V4-Pro');
	if (proof) {
		await proof.assert('deepseek.model-selected', async () => {
			await expect(editor).toContainText('@DeepSeek-V4-Pro');
		});
		await proof.checkpoint('deepseek-model-selected');
	}

	await page.keyboard.type(' Reply with exactly: DEEPSEEK-WEB-OK');
	await page.locator('[data-action="send-message"]').click();
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15_000 });

	const assistant = page.getByTestId('message-assistant').last();
	await expect(assistant).toContainText('DEEPSEEK-WEB-OK', { timeout: 120_000 });
	await expect(assistant).not.toContainText('Sorry, something went wrong');
	const generatedBy = assistant.getByTestId('generated-by');
	await expect(generatedBy).toContainText('DeepSeek V4 Pro', { timeout: 120_000 });
	if (proof) {
		await proof.assert('deepseek.response-complete', async () => {
			await expect(assistant).toContainText('DEEPSEEK-WEB-OK');
			await expect(generatedBy).toContainText('DeepSeek V4 Pro');
		});
		await proof.checkpoint('deepseek-response-complete');
		await page.waitForTimeout(DEMONSTRATION_REVIEW_HOLD_MS);
	}

	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 30_000 });
	const reloadedAssistant = page.getByTestId('message-assistant').last();
	await expect(reloadedAssistant).toContainText('DEEPSEEK-WEB-OK', { timeout: 60_000 });
	await expect(reloadedAssistant).not.toContainText('Sorry, something went wrong');
	await expect(reloadedAssistant.getByTestId('generated-by')).toContainText('DeepSeek V4 Pro');
	if (proof) {
		await proof.assert('deepseek.reload-complete', async () => {
			await expect(reloadedAssistant).toContainText('DEEPSEEK-WEB-OK');
			await expect(reloadedAssistant.getByTestId('generated-by')).toContainText('DeepSeek V4 Pro');
		});
		await proof.checkpoint('deepseek-reload-complete');
		await page.waitForTimeout(DEMONSTRATION_REVIEW_HOLD_MS);
	}

	if (!proof) {
		await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'deepseek-cleanup');
	}
});
