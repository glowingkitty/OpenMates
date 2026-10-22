/* eslint-disable @typescript-eslint/no-require-imports */
/** Full browser/client-crypto smoke for the signed synthetic capacity replay path. */
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage, waitForChatReady, deleteActiveChat } = require('./helpers/chat-test-helpers');

const PROTOCOL_PREFIX = 'Verified prefix: The available conversation is enough.';
const PROTOCOL_CONTINUATION = 'The safe continuation is complete.';
const INTERNAL_PROTOCOL = /```(?:toon|tool_code)|app_id:|skill_id:|app_skill_use|embed_ref|Invented post-protocol prose/i;
const TERMINAL_ERROR = /AI service encountered an error|Sorry, something went wrong while I was trying to process your message|try again in a moment|protocol_guard/i;

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,storage.validation.synthetic-capacity
test('signed capacity replay completes a real encrypted chat turn', async ({ page }: { page: any }) => {
	if (process.env.E2E_STORAGE_CAPACITY !== '1') throw new Error('Isolated capacity replay profile is required.');
	if (!getTestAccount().email) throw new Error('Disposable isolated test account is required.');
	test.setTimeout(180_000);
	const log = createSignupLogger('storage-capacity-replay');
	const screenshot = createStepScreenshotter(log);
	await installE2EServerContentOverrideGate(page, 'storage-capacity-replay');
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	await sendMessage(
		page,
		'Synthetic storage page and client crypto test. STORAGE_CAPACITY_SCENARIO:round <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
		log, screenshot, 'storage-capacity'
	);
	const assistant = await waitForAssistantMessage(page, { contains: 'Synthetic storage response' });
	await expect(assistant).toBeVisible();
	const chatId = new URL(page.url()).hash.match(/chat-id=([0-9a-f-]{36})/i)?.[1];
	expect(chatId, 'Synthetic turn must have a canonical chat ID').toBeTruthy();
	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
	let readbackShape = { http_status: 0, messages_array: false, row_count: 0, assistant_count: 0, encrypted_assistant_count: 0 };
	await expect.poll(async () => {
		const response = await page.request.get(
			`${apiUrl}/v1/chats/${encodeURIComponent(chatId!)}/messages/window?limit=20&respect_compression_boundary=false`,
			{ headers: { "X-OpenMates-Client-Capabilities": "agentic-storage-v2" } }
		);
		readbackShape = { http_status: response.status(), messages_array: false, row_count: 0, assistant_count: 0, encrypted_assistant_count: 0 };
		if (!response.ok()) return false;
		const window = await response.json();
		const messages = Array.isArray(window.messages) ? window.messages : [];
		const assistants = messages.filter((message: any) => message?.role === 'assistant');
		const encryptedAssistants = assistants.filter((message: any) =>
			typeof message.encrypted_content === 'string' && message.encrypted_content.length > 0
		);
		readbackShape = { http_status: response.status(), messages_array: Array.isArray(window.messages),
			row_count: Math.min(messages.length, 20), assistant_count: Math.min(assistants.length, 20),
			encrypted_assistant_count: Math.min(encryptedAssistants.length, 20) };
		return encryptedAssistants.length > 0;
	}, { timeout: 30_000, message: 'Synthetic assistant must be saved as encrypted canonical server content' }).toBe(true).catch(() => {
		throw new Error(`Synthetic canonical readback failed: ${JSON.stringify(readbackShape)}`);
	});
	await page.reload();
	await expect(page.getByTestId('message-assistant').filter({ hasText: 'Synthetic storage response' })).toBeVisible();
	await deleteActiveChat(page, log, screenshot, 'storage-capacity');
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,ai-model-routing.recovery.affordable-current-models
test('fabricated tool protocol recovers without skill-dispatch instructions as one persisted turn', async ({ page }: { page: any }) => {
	if (process.env.E2E_STORAGE_CAPACITY !== '1') throw new Error('Isolated signed zero-provider CI profile is required.');
	if (!getTestAccount().email) throw new Error('Disposable isolated test account is required.');
	test.setTimeout(180_000);

	const log = createSignupLogger('storage-protocol-recovery');
	const screenshot = createStepScreenshotter(log);
	await installE2EServerContentOverrideGate(page, 'storage-protocol-recovery');
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	const previousCount = await page.getByTestId('message-assistant').count();
	// The signed provider fixture keeps rejecting recovery while skill-dispatch
	// guidance remains in the real answer-only system prompt.
	await sendMessage(page,
		'Summarize only the available conversation. STORAGE_CAPACITY_SCENARIO:recovery_protocol <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
		log, screenshot, 'storage-protocol-recovery');

	const messages = page.getByTestId('message-assistant');
	await expect(messages).toHaveCount(previousCount + 1, { timeout: 90_000 });
	const answer = messages.nth(previousCount);
	await expect(answer).toContainText(PROTOCOL_CONTINUATION, { timeout: 90_000 });
	await expect(answer.getByTestId('generated-by')).toContainText('Gemini 3.8 Flash');
	await expect(answer).toHaveAttribute('data-streaming', 'false', { timeout: 90_000 });
	await expect(page.getByTestId('stop-processing-button')).toBeHidden({ timeout: 90_000 });
	await expect(messages).toHaveCount(previousCount + 1);
	const assertSafeAnswer = async (message: any) => {
		const visible = await message.innerText();
		expect(visible.split(PROTOCOL_PREFIX).length - 1).toBe(1);
		expect(visible).toContain(PROTOCOL_CONTINUATION);
		expect(visible).not.toMatch(INTERNAL_PROTOCOL);
		expect(visible).not.toMatch(TERMINAL_ERROR);
		await expect(message.locator('[data-testid="embed-preview"][data-skill-id]')).toHaveCount(0);
	};
	await assertSafeAnswer(answer);
	await page.reload({ waitUntil: 'domcontentloaded' });
	await waitForChatReady(page, log);
	await expect(messages).toHaveCount(previousCount + 1, { timeout: 90_000 });
	await expect(messages.nth(previousCount)).toContainText(PROTOCOL_CONTINUATION, { timeout: 90_000 });
	await assertSafeAnswer(messages.nth(previousCount));
	await deleteActiveChat(page, log, screenshot, 'storage-protocol-recovery');
});

// contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,chats.rendering.assistant-document-convergence,issue-reporting.logs.authenticated-capture
test('reuses a completed search member and captures every report text segment', async ({ page }: { page: any }) => {
	if (process.env.E2E_STORAGE_CAPACITY !== '1') throw new Error('Isolated signed zero-provider CI profile is required.');
	test.setTimeout(180_000);
	const log = createSignupLogger('search-member-reuse');
	const screenshot = createStepScreenshotter(log);
	await installE2EServerContentOverrideGate(page, 'search-member-reuse');
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	await sendMessage(page,
		'Compare the synthetic options. STORAGE_CAPACITY_SCENARIO:search_reuse <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
		log, screenshot, 'search-member-reuse');
	const answer = await waitForAssistantMessage(page, { contains: 'Search reuse closing sentence.' });
	await expect(answer).toHaveAttribute('data-streaming', 'false', { timeout: 90_000 });
	await expect(page.getByTestId('stop-processing-button')).toBeHidden();
	const verifyAnswer = async () => {
		const current = page.getByTestId('message-assistant').filter({ hasText: 'Search reuse closing sentence.' });
		const text = await current.innerText();
		expect(text.split('Search reuse final answer.').length - 1).toBe(1);
		expect(text).not.toContain('Duplicate synthesis should never appear.');
		expect(text).not.toMatch(TERMINAL_ERROR);
		for (const toggle of await current.getByTestId('assistant-activity-toggle').all()) {
			if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click();
		}
		await expect(current.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]')).toHaveCount(3);
		await expect(current.getByTestId('embed-error-banner')).toHaveCount(0);
		return current;
	};
	await verifyAnswer();
	await page.reload({ waitUntil: 'domcontentloaded' });
	await waitForChatReady(page, log);
	await expect(page.getByTestId('message-assistant').filter({ hasText: 'Search reuse closing sentence.' })).toBeVisible();
	const persisted = await verifyAnswer();
	await expect(persisted.locator('.read-only-message .ProseMirror')).not.toHaveCount(1);

	const payloads: Array<Record<string, unknown>> = [];
	await page.route('**/v1/settings/issues', async (route: any) => {
		if (route.request().method() !== 'POST') return route.continue();
		payloads.push(route.request().postDataJSON());
		await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
			success: true, issue_id: '00000000-0000-4000-8000-000000000001', short_issue_id: 'ABCDE', screenshot_uploaded: false,
		}) });
	});
	await page.locator('#settings-menu-toggle').click();
	await page.locator('[data-testid="settings-menu"].visible').getByRole('menuitem', { name: /report.*issue|issue.*report|problem.*melden/i }).first().click();
	await expect(page.getByTestId('report-issue-form')).toBeVisible();
	await expect(page.locator('#share-chat-toggle')).toBeChecked();
	await page.getByTestId('report-issue-title').fill('Synthetic segmented message capture');
	await page.getByTestId('report-issue-submit').click();
	await expect(page.getByTestId('report-issue-confirmation')).toBeVisible({ timeout: 30_000 });
	expect(payloads).toHaveLength(1);
	const captured = String(payloads[0].last_messages_html);
	for (const marker of ['Search reuse introduction.', 'Search reuse final answer.', 'Search reuse closing sentence.']) {
		expect(captured.split(marker).length - 1).toBe(1);
	}
	expect(captured.indexOf('Search reuse introduction.')).toBeLessThan(captured.indexOf('Search reuse final answer.'));
	expect(captured.indexOf('Search reuse final answer.')).toBeLessThan(captured.indexOf('Search reuse closing sentence.'));
	await page.getByTestId('report-issue-submit-another').click();
	await page.locator('label[for="share-chat-toggle"]').click();
	await page.getByTestId('report-issue-title').fill('Synthetic capture opt out');
	await page.getByTestId('report-issue-submit').click();
	await expect(page.getByTestId('report-issue-confirmation')).toBeVisible();
	expect(payloads).toHaveLength(2);
	expect(payloads[1].last_messages_html).toBeNull();
	expect(payloads[1].chat_or_embed_url).toBeNull();
});
