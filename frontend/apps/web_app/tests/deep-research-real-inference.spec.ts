/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Deployed Deep research end-to-end proof.
 *
 * Selects the real focus mention, delegates three bounded child chats through
 * live inference, and verifies the final parent synthesis without route mocks.
 */
export {};

const { test, expect } = require('./console-monitor');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { dismissVisibleNotifications } = require('./helpers/embed-test-helpers');
const { selectMentionResult } = require('./helpers/mention-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const DEMONSTRATION_REVIEW_HOLD_MS = 3_500;
const PROOF_DOMAIN = 'app.dev.openmates.org';

async function captureBrowserProofFrame(page: any): Promise<Buffer> {
	return page.screenshot({ type: 'png' });
}

const proofContract = defineVideoProof({
	id: 'deep-research-real-inference',
	title: 'Deep research delegates to child chats and returns a final synthesis',
	surface: 'web',
	devices: ['web-laptop'],
	domain: PROOF_DOMAIN,
	transcript: [
		{
			id: 'focus-request',
			text: 'The request uses the Deep research focus mention in a new OpenMates chat.',
			checkpoint: 'deep-research-focus-visible',
			devices: ['web-laptop']
		},
		{
			id: 'delegated-children',
			text: 'OpenMates activates Deep research and shows three delegated child-chat cards.',
			checkpoint: 'deep-research-children-visible',
			devices: ['web-laptop']
		},
		{
			id: 'child-opened',
			text: 'A child chat opens from the carousel while the parent remains reachable.',
			checkpoint: 'deep-research-child-opened',
			devices: ['web-laptop']
		},
		{
			id: 'parent-synthesis',
			text: 'Returning to the parent shows the final synthesis with structured research sections.',
			checkpoint: 'deep-research-parent-synthesis',
			devices: ['web-laptop']
		}
	],
	assertions: [
		{
			id: 'deep_research.focus_visible',
			checkpoint: 'deep-research-focus-visible',
			visual: 'The Deep research focus bar is visible after the request.',
			devices: ['web-laptop']
		},
		{
			id: 'deep_research.children_visible',
			checkpoint: 'deep-research-children-visible',
			visual: 'Three child-chat cards are visible without raw protocol text or AI error text.',
			devices: ['web-laptop']
		},
		{
			id: 'deep_research.child_navigation',
			checkpoint: 'deep-research-child-opened',
			visual: 'Opening a child chat shows the return-to-parent control.',
			devices: ['web-laptop']
		},
		{
			id: 'deep_research.parent_synthesis',
			checkpoint: 'deep-research-parent-synthesis',
			visual: 'The parent assistant message shows final synthesis sections and no typing indicator.',
			devices: ['web-laptop']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

async function sendDeepResearchMessage(
	page: any,
	prompt: string,
	log: (message: string, metadata?: Record<string, unknown>) => void,
	screenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	const messageField = page.getByTestId('message-field').last();
	const editor = messageField.getByTestId('message-editor');
	await expect(editor).toBeVisible();
	await selectMentionResult(page, 'deep', 'Deep research');
	await page.keyboard.insertText(` ${prompt}`);
	await screenshot(page, 'deep-research-request-typed');

	const userMessages = page.getByTestId('message-user');
	const userCount = await userMessages.count();
	const sendButton = messageField.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 10_000 });
	await sendButton.click();
	await expect(userMessages).toHaveCount(userCount + 1, { timeout: 30_000 });
	log('Sent explicit Deep research focus mention request.');
}

// contract-test: direct surface=gui.web assertions=chats.surface.semantic-parity,chats.local-state.precedence
test('Deep research delegates three angles and renders the final parent synthesis', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(900_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const proof = createVideoProofRuntime(proofContract, {
		device: 'web-laptop',
		attach: testInfo.attach.bind(testInfo),
		captureFrame: () => captureBrowserProofFrame(page)
	});

	const log = createSignupLogger('deep-research-real-inference');
	await archiveExistingScreenshots(log);
	const screenshot = createStepScreenshotter(log);

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	await page.evaluate(() => {
		const state = window as Window & { __subChatRawProtocolObserved?: boolean };
		state.__subChatRawProtocolObserved = false;
		new MutationObserver(() => {
			const cardText = Array.from(document.querySelectorAll('[data-testid="sub-chat-card"]'))
				.map((card) => card.textContent || '')
				.join('\n');
			if (cardText.includes('app_skill_use') || cardText.includes('```json')) {
				state.__subChatRawProtocolObserved = true;
			}
		}).observe(document.body, { childList: true, subtree: true, characterData: true });
	});

	const prompt =
		'Investigate how the EU AI Act general-purpose AI obligations affect open-source model providers, cloud hosts, and downstream startups. ' +
		'Delegate exactly three distinct regulatory, market-incentive, and counterargument/source-quality angles, use current sources, and synthesize what is confirmed, likely, plausible, and uncertain.';

	await sendDeepResearchMessage(page, prompt, log, screenshot);

	const focusBar = page.getByTestId('focus-mode-bar').filter({ hasText: 'Deep research' }).first();
	await expect(focusBar).toBeVisible({ timeout: 120_000 });
	await proof.assert('deep_research.focus_visible', async () => {
		await expect(focusBar).toBeVisible();
	});
	await proof.checkpoint('deep-research-focus-visible');
	await screenshot(page, 'deep-research-activated');

	const carousel = page.getByTestId('sub-chats-carousel');
	await expect(carousel).toBeVisible({ timeout: 240_000 });
	await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-processing', 'false', { timeout: 240_000 });
	const subChatCards = page.getByTestId('sub-chat-card');
	await expect(subChatCards).toHaveCount(3, { timeout: 240_000 });
	for (let index = 0; index < 3; index += 1) {
		const card = subChatCards.nth(index);
		const title = card.getByTestId('sub-chat-title');
		await expect(title).not.toContainText('...');
		expect(await title.evaluate((element: HTMLElement) => element.scrollHeight <= element.clientHeight + 1)).toBe(true);
		await expect(card).toHaveAttribute('data-category', /^(?!general_knowledge$).+/);
		await expect(card).toHaveAttribute('data-icon', /^(?!help-circle$).+/);
		await expect(card.getByTestId('sub-chat-open-cta')).toContainText('Click to open sub chat');
		await expect(card).not.toContainText('Active');
		await expect(card).not.toContainText('Done');
		await expect(card).not.toContainText('"type":"app_skill_use"');
		await expect(card).not.toContainText('The AI service encountered an error');
		await expect(card).not.toContainText('Sub-chat failed before completion');
	}
	await proof.assert('deep_research.children_visible', async () => {
		await expect(subChatCards).toHaveCount(3);
		for (let index = 0; index < 3; index += 1) {
			await expect(subChatCards.nth(index)).not.toContainText('"type":"app_skill_use"');
			await expect(subChatCards.nth(index)).not.toContainText('The AI service encountered an error');
			await expect(subChatCards.nth(index)).not.toContainText('Sub-chat failed before completion');
		}
	});
	await proof.checkpoint('deep-research-children-visible');
	await screenshot(page, 'deep-research-initial-child-cards');

	await subChatCards.first().click();
	const returnToParent = page.getByTestId('return-to-parent-button');
	await expect(returnToParent).toBeVisible({ timeout: 30_000 });
	await expect(returnToParent).toBeInViewport();
	await expect(returnToParent).toContainText('Return to parent chat', { timeout: 30_000 });
	await proof.assert('deep_research.child_navigation', async () => {
		await expect(returnToParent).toBeVisible();
		await expect(returnToParent).toBeInViewport();
		await expect(returnToParent).toContainText('Return to parent chat');
	});
	await proof.checkpoint('deep-research-child-opened');
	await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-processing', 'true');
	await screenshot(page, 'deep-research-active-child-open');
	await page.waitForTimeout(DEMONSTRATION_REVIEW_HOLD_MS);

	await returnToParent.click();
	await expect(carousel).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId('active-chat-container')).toHaveAttribute('data-processing', 'false');
	await screenshot(page, 'deep-research-returned-to-waiting-parent');

	const finalAssistant = page.getByTestId('message-assistant').last();
	await expect(finalAssistant).toContainText('Short Answer', { timeout: 600_000 });
	await expect(finalAssistant).toHaveAttribute('data-streaming', 'false', { timeout: 60_000 });
	await expect(finalAssistant).toContainText('Surface Explanation');
	await expect(finalAssistant).toContainText('What Else May Be Going On');
	await expect(finalAssistant).toContainText('Evidence');
	await expect(finalAssistant).toContainText('Counterarguments');
	await expect(finalAssistant).toContainText('Bottom Line');
	await expect(finalAssistant).not.toContainText('The AI service encountered an error');
	await expect(finalAssistant).not.toContainText('Sub-chat failed before completion');
	await expect(page.getByTestId('typing-indicator')).not.toBeVisible();
	await expect(page.getByTestId('sub-chat-open-cta')).toHaveCount(0);
	await expect(page.getByTestId('sub-chat-summary')).toHaveCount(3);
	await expect(page.getByTestId('sub-chat-status-completed')).toHaveCount(3);
	expect(await page.evaluate(() =>
		(window as Window & { __subChatRawProtocolObserved?: boolean }).__subChatRawProtocolObserved
	)).toBe(false);

	const visibleSynthesisSections = [
		['Short Answer', 'deep-research-synthesis-start'],
		['What Else May Be Going On', 'deep-research-synthesis-middle'],
		['Bottom Line', 'deep-research-synthesis-end']
	];
	for (const [section, label] of visibleSynthesisSections) {
		const heading = finalAssistant.getByText(section, { exact: true }).first();
		await heading.scrollIntoViewIfNeeded();
		await expect(heading).toBeInViewport();
		await dismissVisibleNotifications(page);
		await screenshot(page, label);
		// Keep each asserted proof state visible in the recorded Playwright artifact.
		await page.waitForTimeout(DEMONSTRATION_REVIEW_HOLD_MS);
	}
	await proof.assert('deep_research.parent_synthesis', async () => {
		await expect(finalAssistant).toContainText('Short Answer');
		await expect(finalAssistant).toContainText('Bottom Line');
		await expect(finalAssistant).not.toContainText('Sub-chat failed before completion');
		await expect(page.getByTestId('typing-indicator')).not.toBeVisible();
	});
	await proof.checkpoint('deep-research-parent-synthesis');
	await proof.attach();

	await deleteActiveChat(page, log, screenshot, 'deep-research-cleanup');
	log('Deep research completed with three children and a final parent synthesis.');
});
