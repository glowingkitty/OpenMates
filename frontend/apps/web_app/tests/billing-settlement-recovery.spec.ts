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
	deleteActiveChat,
	dismissSecurityReminderIfPresent
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
			text: 'After reload, the completed event results remain visible without an error.',
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
			visual: 'Reload preserves visible completed event results with no processing error.',
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
		await dismissSecurityReminderIfPresent(page, log);
		await startNewChat(page, log);
		const message = 'For the next two Berlin weekends, search for technology events for each weekend, compare the best options, and only include events located in Berlin.';
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
		const eventCards = page.locator(
			'[data-testid="embed-preview"][data-app-id="events"][data-skill-id="search"][data-status="finished"]'
		);
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
			await page.waitForTimeout(750);
			await proof.checkpoint('response-completed');
		}

		if (proof) {
			await proof.action('reload-completed-chat', async () => {
				await page.reload({ waitUntil: 'domcontentloaded' });
			});
		} else {
			await page.reload({ waitUntil: 'domcontentloaded' });
		}
		await expect(page.getByTestId('message-user').last()).toContainText(REQUEST_ANCHOR, { timeout: 60_000 });
		const reloadedAssistant = page.getByTestId('message-content').last();
		await expect(reloadedAssistant).toHaveAttribute('data-streaming', 'false', { timeout: 60_000 });
		const reloadedCards = page.locator(
			'[data-testid="embed-preview"][data-app-id="events"][data-skill-id="search"][data-status="finished"]'
		);
		await expect(reloadedCards.first()).toBeVisible({ timeout: 60_000 });
		const reloadedMapView = page.getByTestId('embeds-map-view').last();
		await expect(reloadedMapView).toBeVisible({ timeout: 60_000 });
		await expect(reloadedMapView.getByTestId('embeds-map-view-count')).not.toHaveText('0 shown', { timeout: 60_000 });
		await expect(reloadedMapView.getByText('Loading referenced embeds...')).toHaveCount(0);
		await expect(reloadedMapView.locator('[data-testid="embeds-map-view-card"][data-entry-status="loading"]')).toHaveCount(0, { timeout: 60_000 });
		await expect(reloadedMapView.getByText('Waiting for source results')).toHaveCount(0);
		await expect(reloadedMapView.getByTestId('embeds-map-view-map')).not.toHaveAttribute('data-marker-count', '0');
		await expect(page.getByText('The AI service encountered an error while processing your request.')).toHaveCount(0);
		if (proof) {
			await reloadedAssistant.evaluate((element: HTMLElement) => {
				const responseEnd = element.lastElementChild || element;
				responseEnd.scrollIntoView({ block: 'end', behavior: 'instant' });
			});
			await proof.assert('completion-survives-reload', async () => {
				await expect(reloadedAssistant).toHaveAttribute('data-streaming', 'false');
				await expect(reloadedCards.first()).toBeVisible();
			});
			await page.waitForTimeout(8_000);
			await proof.checkpoint('completion-survives-reload');
			await proof.attach();
			return;
		}

		await deleteActiveChat(page, log, screenshot, 'billing-settlement-recovery');
	});
});
