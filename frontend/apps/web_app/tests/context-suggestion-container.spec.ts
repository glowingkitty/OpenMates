/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Post-processor context suggestion container between chat history and follow-up suggestions.
 * A suggestion is seeded through the E2E hook (same adapter as the live post-processing event);
 * the server wire names stay isolated in services/contextSuggestionWire.ts.
 * Not yet run: needs an authenticated dev session.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const CHAT_ID = '11111111-1111-4111-8111-11111111e2e1';
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function openSeededChat(page: any, suggestion: Record<string, unknown>): Promise<void> {
	await page.evaluate(async ({ chatId, suggestion: seeded }: { chatId: string; suggestion: Record<string, unknown> }) => {
		const w = window as any;
		const now = Math.floor(Date.now() / 1000);
		const chat = { chat_id: chatId, messages_v: 1, title_v: 0, draft_v: 0, created_at: now, updated_at: now, last_edited_overall_timestamp: now, unread_count: 0 };
		await w.__openmatesE2ESeedChat({ chat, messages: [
			{ message_id: '22222222-2222-4222-8222-22222222e2e1', chat_id: chatId, role: 'user', sender_name: 'user', content: 'Staging uses port 8002 now', status: 'synced', created_at: now },
			{ message_id: '22222222-2222-4222-8222-22222222e2e2', chat_id: chatId, role: 'assistant', content: 'Noted.', status: 'synced', created_at: now + 1 },
		] });
		await w.__openmatesE2ELoadLocalChat({ chatId, chat });
		await w.__openmatesE2ESeedContextSuggestion({ chatId, suggestion: seeded });
	}, { chatId: CHAT_ID, suggestion });
}

test.describe('Context suggestion container', () => {
	test.beforeEach(async ({ page }: { page: any }) => {
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		test.setTimeout(180000);
		await loginToTestAccount(page, (message: string) => console.log(message), async () => undefined);
	});

	// contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
	test('memory update shows the title only, Preview, and remembers dismissal', async ({ page }: { page: any }) => {
		await openSeededChat(page, { kind: 'memory_update', memory_id: 'personal:e2e', title: 'Staging API' });
		const container = page.getByTestId('context-suggestion');
		await expect(container).toBeVisible();
		await expect(page.getByTestId('context-suggestion-title')).toContainText('Staging API');
		await expect(page.getByTestId('context-suggestion-preview')).toBeVisible();
		await expect(page.getByTestId('context-suggestion-summary')).toHaveCount(0);
		await page.getByTestId('context-suggestion-dismiss').click();
		await expect(container).toHaveCount(0);
		await openSeededChat(page, { kind: 'memory_update', memory_id: 'personal:e2e', title: 'Staging API' });
		await expect(container).toHaveCount(0);
	});

	// contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
	test('new memory Preview opens an unsaved draft without saving', async ({ page }: { page: any }) => {
		await page.evaluate(() => localStorage.removeItem('openmates.contextSuggestionDismissals.v1'));
		await openSeededChat(page, { kind: 'memory_create', title: 'Release notes tone', body: '---\ntitle: Release notes tone\nwhen_to_use: writing release notes\nload_mode: ask_first\n---\n\nKeep release notes short.\n' });
		await page.getByTestId('context-suggestion-preview').click();
		await expect(page.getByTestId('memory-draft-banner')).toBeVisible();
		await expect(page.getByTestId('rule-body')).toContainText('Keep release notes short.');
	});

	// contract-test: supporting surface=gui.web assertions=app-memories.suggestions.post-processor
	test('workflow suggestion shows title and summary with Create instead of Preview', async ({ page }: { page: any }) => {
		await page.evaluate(() => localStorage.removeItem('openmates.contextSuggestionDismissals.v1'));
		await openSeededChat(page, { kind: 'workflow_create', title: 'Weekly city events', summary: 'Every Monday, summarize new events.' });
		await expect(page.getByTestId('context-suggestion-title')).toContainText('Weekly city events');
		await expect(page.getByTestId('context-suggestion-summary')).toContainText('Every Monday');
		await expect(page.getByTestId('context-suggestion-preview')).toHaveCount(0);
		await expect(page.getByTestId('context-suggestion-create')).toBeVisible();
	});
});
