/* eslint-disable @typescript-eslint/no-require-imports */
/** Full browser/client-crypto smoke for the signed synthetic capacity replay path. */
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,storage.validation.synthetic-capacity
test('signed capacity calibration completes a real encrypted chat turn', async ({ page }: { page: any }) => {
	if (process.env.E2E_STORAGE_CAPACITY !== '1') throw new Error('Isolated capacity replay profile is required.');
	if (!getTestAccount().email) throw new Error('Disposable isolated test account is required.');
	test.setTimeout(180_000);
	const log = createSignupLogger('storage-capacity-calibration');
	const screenshot = createStepScreenshotter(log);
	await installE2EServerContentOverrideGate(page, 'storage-capacity-calibration');
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
	await expect.poll(async () => {
		const response = await page.request.get(
			`${apiUrl}/v1/chats/${encodeURIComponent(chatId!)}/messages/window?limit=20&respect_compression_boundary=false`,
			{ headers: { "X-OpenMates-Client-Capabilities": "agentic-storage-v2" } }
		);
		if (!response.ok()) return false;
		const window = await response.json();
		return window.messages?.some((message: any) =>
			message.role === 'assistant' && typeof message.encrypted_content === 'string' && message.encrypted_content.length > 0
		) === true;
	}, { timeout: 30_000, message: 'Synthetic assistant must be saved as encrypted canonical server content' }).toBe(true);
	await page.reload();
	await expect(page.getByTestId('message-assistant').filter({ hasText: 'Synthetic storage response' })).toBeVisible();
	await deleteActiveChat(page, log, screenshot, 'storage-capacity');
});
