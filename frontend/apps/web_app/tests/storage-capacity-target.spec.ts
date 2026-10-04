/* eslint-disable @typescript-eslint/no-require-imports */
/** Full browser/client-crypto smoke for the signed synthetic capacity replay path. */
export {};

const { test, expect } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,storage.validation.synthetic-capacity
test('target capacity profile starts with a real encrypted chat turn', async ({ page }: { page: any }) => {
	if (process.env.E2E_STORAGE_CAPACITY_TARGET !== '1') throw new Error('Isolated target capacity profile is required.');
	if (!getTestAccount().email) throw new Error('Disposable isolated test account is required.');
	test.setTimeout(180_000);
	const log = createSignupLogger('storage-capacity-replay');
	const screenshot = createStepScreenshotter(log);
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	await sendMessage(
		page,
		'Synthetic storage page and client crypto test. STORAGE_CAPACITY_SCENARIO:round <<<TEST_LIVE_MOCK:storage_capacity_v1>>>',
		log, screenshot, 'storage-capacity'
	);
	const assistant = await waitForAssistantMessage(page, { contains: 'Synthetic storage response' });
	await expect(assistant).toBeVisible();
	await page.reload();
	await expect(page.getByTestId('message-assistant').filter({ hasText: 'Synthetic storage response' })).toBeVisible();
	await deleteActiveChat(page, log, screenshot, 'storage-capacity');
});
