/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Real anonymous-chat regressions for production issues H753F and 2PUJ3.
 *
 * These opt-in tests use the deployed dev browser and anonymous inference paths
 * without request mocks. Real AI inference verification runs on dev only.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, assertNoMissingTranslations } = require('./signup-flow-helpers');

const REPORTED_PROMPT =
	'is it practical to run clo3d in a VM in virtual box? heard there is a 256mb vram max for vms? is that true? if so, this would be a no go...';
const PROCESSING_ERROR = /AI service encountered an error|Sorry, something went wrong while I was trying to process your message|try again in a moment/i;
async function startAnonymousChat(page: any): Promise<void> {
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle');
	const skipInterests = page.getByTestId('guest-interest-skip');
	if (await skipInterests.isVisible({ timeout: 5_000 }).catch(() => false)) {
		await skipInterests.click();
	}
	const newChatButton = page
		.locator('[data-testid="new-chat-cta-fullwidth"], [data-testid="new-chat-button"]')
		.first();
	if (!(await newChatButton.isVisible({ timeout: 1_000 }).catch(() => false))) {
		const introCard = page
			.locator('[data-testid="resume-chat-large-card"], [data-testid="resume-chat-card"]')
			.first();
		await expect(introCard).toBeVisible({ timeout: 10_000 });
		await introCard.click();
	}
	await expect(newChatButton).toBeVisible({ timeout: 15_000 });
	await newChatButton.click();
	await expect(page.getByTestId('message-editor').locator('[contenteditable="true"]').first()).toBeVisible({
		timeout: 10_000
	});
}

async function typeMessage(page: any, text: string): Promise<void> {
	const editor = page.getByTestId('message-editor');
	const editable = editor.locator('[contenteditable="true"]').first();
	await page.getByTestId('message-field').click();
	await editable.click();
	await editable.pressSequentially(text);
	await expect(editor).toContainText(text);
}

async function sendAndAwaitAnswer(page: any, text: string, expected?: RegExp): Promise<number> {
	await typeMessage(page, text);
	const startedAt = Date.now();
	await page.locator('[data-action="send-message"]').click();

	const assistant = page.getByTestId('message-assistant').last();
	await expect(assistant).toBeVisible({ timeout: 120_000 });
	await expect(assistant).toHaveAttribute('data-streaming', 'false', { timeout: 120_000 });
	await expect(assistant).not.toContainText(PROCESSING_ERROR);
	const messageContent = assistant.getByTestId('message-content').last();
	await expect(messageContent).toBeVisible({ timeout: 15_000 });
	await expect
		.poll(async () => (await messageContent.innerText()).trim().length, { timeout: 15_000 })
		.toBeGreaterThan(40);
	if (expected) await expect(messageContent).toContainText(expected);
	await expect(page.getByTestId('chat-processing-indicator')).toBeHidden();
	return Date.now() - startedAt;
}

async function runReliabilityCase(
	page: any,
	testInfo: any,
	options: {
		viewport: { width: number; height: number };
		prompt: string;
		followUp: string;
		expected: RegExp;
	}
): Promise<void> {
	await page.setViewportSize(options.viewport);
	await page.addInitScript((anonymousId: string) => {
		localStorage.removeItem('openmates:last-auth-method');
		localStorage.setItem('openmates_anonymous_id', anonymousId);
	}, `h753f-web-${Date.now()}-${Math.random().toString(16).slice(2)}`);

	await startAnonymousChat(page);
	const initialMs = await sendAndAwaitAnswer(page, options.prompt, options.expected);
	const followUpMs = await sendAndAwaitAnswer(page, options.followUp);

	await expect(page.getByTestId('message-user')).toHaveCount(2);
	await expect(page.getByTestId('message-assistant')).toHaveCount(2);
	for (const attribution of await page.getByTestId('generated-by').all()) {
		await expect(attribution).toBeVisible({ timeout: 15_000 });
		await expect(attribution).not.toContainText('openmates-ai');
		await expect(attribution).not.toHaveText('');
	}
	await assertNoMissingTranslations(page);
	await testInfo.attach('anonymous-turn-timings.json', {
		body: JSON.stringify({ initialMs, followUpMs }),
		contentType: 'application/json'
	});
}

test.describe('Anonymous production repair', () => {
	// contract-test: direct surface=gui.web assertions=chats.streaming.ordered-final,chats.surface.semantic-parity
	test('completes reported CLO3D prompt and follow-up on phone', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(300_000);
		await runReliabilityCase(page, testInfo, {
			viewport: { width: 390, height: 844 },
			prompt: REPORTED_PROMPT,
			followUp: 'What setup would you recommend instead?',
			expected: /CLO3D|VirtualBox|VRAM/i
		});
	});

	// contract-test: direct surface=gui.web assertions=chats.streaming.ordered-final,chats.surface.semantic-parity
	test('completes plain-language prompt and follow-up on phone', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(300_000);
		await runReliabilityCase(page, testInfo, {
			viewport: { width: 390, height: 844 },
			prompt: 'In one short paragraph, explain why rainbows appear after rain.',
			followUp: 'Name the first three colors in order.',
			expected: /rainbow|light|water/i
		});
	});

	// contract-test: direct surface=gui.web assertions=chats.streaming.ordered-final,chats.surface.semantic-parity
	test('completes troubleshooting prompt and follow-up on laptop', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(300_000);
		await runReliabilityCase(page, testInfo, {
			viewport: { width: 1440, height: 900 },
			prompt: 'Give me two practical checks when a local development server will not start.',
			followUp: 'Which check should I run first?',
			expected: /port|process|log|configuration|dependency/i
		});
	});

	// contract-test: direct surface=gui.web assertions=chats.streaming.ordered-final,chats.surface.semantic-parity
	test('completes anonymous web search and preserves its final answer on laptop', async ({ page }: { page: any }) => {
		test.setTimeout(300_000);
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.addInitScript((anonymousId: string) => {
			localStorage.removeItem('openmates:last-auth-method');
			localStorage.setItem('openmates_anonymous_id', anonymousId);
		}, `prod2puj3-web-${Date.now()}-${Math.random().toString(16).slice(2)}`);

		await startAnonymousChat(page);
		const assistantCountBeforeSearch = await page.getByTestId('message-assistant').count();
		await typeMessage(
			page,
			`Search the web for the official OpenMates website and answer with its domain from the result. Reliability check ${Date.now()}`
		);
		await page.locator('[data-action="send-message"]').click();

		const assistantMessages = page.getByTestId('message-assistant');
		await expect(assistantMessages).toHaveCount(assistantCountBeforeSearch + 1, { timeout: 120_000 });
		const assistant = assistantMessages.nth(assistantCountBeforeSearch);
		await expect(assistant).toHaveAttribute('data-streaming', 'false', { timeout: 120_000 });
		await expect(assistant).not.toContainText(PROCESSING_ERROR);
		const messageContent = assistant.getByTestId('message-content').last();
		await expect(messageContent).toContainText(/OpenMates|openmates\.org/i, { timeout: 15_000 });

		const finishedSearchEmbed = assistant.locator(
			'[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"][data-status="finished"]'
		).first();
		await expect(finishedSearchEmbed).toBeVisible({ timeout: 120_000 });
		const embedId = await finishedSearchEmbed.getAttribute('data-embed-id');
		expect(embedId).toBeTruthy();
		const authoritativeText = (await messageContent.innerText()).trim();
		expect(authoritativeText.length).toBeGreaterThan(20);
		await expect(page.getByTestId('chat-processing-indicator')).toBeHidden();

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant')).toHaveCount(assistantCountBeforeSearch + 1, { timeout: 30_000 });
		const reloadedAssistant = page.getByTestId('message-assistant').nth(assistantCountBeforeSearch);
		await expect(reloadedAssistant).toHaveAttribute('data-streaming', 'false');
		await expect(reloadedAssistant).not.toContainText(PROCESSING_ERROR);
		await expect(reloadedAssistant.getByTestId('message-content').last()).toHaveText(authoritativeText);
		await expect(reloadedAssistant.locator(
			`[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"][data-status="finished"][data-embed-id="${embedId}"]`
		).first()).toBeVisible({ timeout: 30_000 });
		await assertNoMissingTranslations(page);
	});
});
