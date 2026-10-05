/* eslint-disable @typescript-eslint/no-require-imports */
/** Full browser/client-crypto smoke for the signed synthetic capacity replay path. */
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');

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
