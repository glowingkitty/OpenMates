/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Deployed billing settlement completion proof.
 *
 * A real paid multi-search chat must reach one successful terminal response and
 * remain complete after reload. Retryable credit conflicts are recovered by the
 * backend and must never replace the persisted assistant response with failure.
 */
export {};

const { test, expect } = require('./console-monitor');
const { getTestAccount, createSignupLogger, createStepScreenshotter } = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_DEVICE = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10) === 390
	? 'web-phone'
	: 'web-laptop';
const REQUEST_ANCHOR = 'two Berlin weekends';
const BILLING_RECOVERY_PROOF = defineVideoProof({
	id: 'billing-settlement-recovery',
	title: 'Paid response remains complete during billing settlement',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'paid-request-visible',
			text: 'A paid request asks OpenMates to search events for two Berlin weekends.',
			checkpoint: 'paid-request-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'response-completed',
			text: 'The assistant finishes processing and shows event results without an error.',
			checkpoint: 'response-completed',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'completion-survives-reload',
			text: 'After reload, the assistant response and event results remain visible.',
			checkpoint: 'completion-survives-reload',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'paid-request-visible',
			checkpoint: 'paid-request-visible',
			visual: 'The user request for two Berlin weekends is visible.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'response-completed',
			checkpoint: 'response-completed',
			visual: 'The assistant response and an event result card are visible with no processing error.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'completion-survives-reload',
			checkpoint: 'completion-survives-reload',
			visual: 'Reload preserves the assistant response and event result card.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

test.describe('Billing settlement recovery', () => {
	// contract-test: direct surface=gui.web assertions=billing.credits.retryable-completion-safe
	test('paid multi-search response completes and survives reload', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const log = createSignupLogger('billing-settlement-recovery');
		const screenshot = createStepScreenshotter(log);
		const proof = IS_PROOF_CAPTURE
			? createVideoProofRuntime(BILLING_RECOVERY_PROOF, {
				device: PROOF_DEVICE,
				attach: testInfo.attach.bind(testInfo),
				captureFrame: () => page.screenshot({ type: 'png' })
			})
			: null;

		await loginToTestAccount(page, log, screenshot);
		await startNewChat(page, log);
		const message = 'For two Berlin weekends, June 20-21 and June 27-28, 2026, search for technology events for each weekend and compare the best options.';
		await sendMessage(page, message, log, screenshot, 'billing-settlement-recovery');

		const userMessage = page.getByTestId('message-user').last();
		await expect(userMessage).toContainText(REQUEST_ANCHOR);
		if (proof) {
			await proof.assert('paid-request-visible', async () => {
				await expect(userMessage).toContainText(REQUEST_ANCHOR);
			});
			await proof.checkpoint('paid-request-visible');
		}

		const activeChat = page.getByTestId('active-chat-container');
		await expect(activeChat).toHaveAttribute('data-processing', 'false', { timeout: 240_000 });
		const assistantContent = page.getByTestId('message-content').last();
		await expect(assistantContent).toHaveAttribute('data-streaming', 'false', { timeout: 60_000 });
		const eventCards = page.locator('[data-testid="embed-preview"][data-app-id="events"][data-skill-id="search"]');
		await expect(eventCards.first()).toBeVisible({ timeout: 60_000 });
		expect(await eventCards.count()).toBeGreaterThan(0);
		await expect(page.getByTestId('typing-indicator')).toBeHidden({ timeout: 30_000 });
		await expect(page.getByText('The AI service encountered an error while processing your request.')).toHaveCount(0);
		if (proof) {
			await eventCards.first().scrollIntoViewIfNeeded();
			await proof.assert('response-completed', async () => {
				await expect(assistantContent).toHaveAttribute('data-streaming', 'false');
				await expect(eventCards.first()).toBeVisible();
			});
			await proof.checkpoint('response-completed');
		}

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-user').last()).toContainText(REQUEST_ANCHOR, { timeout: 60_000 });
		const reloadedAssistant = page.getByTestId('message-content').last();
		await expect(reloadedAssistant).toHaveAttribute('data-streaming', 'false', { timeout: 60_000 });
		const reloadedCards = page.locator('[data-testid="embed-preview"][data-app-id="events"][data-skill-id="search"]');
		await expect(reloadedCards.first()).toBeVisible({ timeout: 60_000 });
		await expect(page.getByText('The AI service encountered an error while processing your request.')).toHaveCount(0);
		if (proof) {
			await reloadedCards.first().scrollIntoViewIfNeeded();
			await proof.assert('completion-survives-reload', async () => {
				await expect(reloadedAssistant).toHaveAttribute('data-streaming', 'false');
				await expect(reloadedCards.first()).toBeVisible();
			});
			await proof.checkpoint('completion-survives-reload');
			await proof.attach();
			return;
		}

		await deleteActiveChat(page, log, screenshot, 'billing-settlement-recovery');
	});
});
