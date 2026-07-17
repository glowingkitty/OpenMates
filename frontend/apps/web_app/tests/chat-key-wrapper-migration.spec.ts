/* eslint-disable @typescript-eslint/no-require-imports */
// @privacy-promise: client-side-chat-encryption
/**
 * Chat key-wrapper migration regression.
 *
 * Uses an existing E2E test account and a pre-existing seeded chat to prove chat
 * decryptability survives wrapper migration without user-visible migration UI.
 * Run only through the repo test dispatcher after deploy:
 * python3 scripts/tests.py run --spec chat-key-wrapper-migration.spec.ts
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const DEFAULT_EXPECTED_TEXT = '2 Day Weather Forecast Berlin';
const SEEDED_CHAT_ID = process.env.OPENMATES_CHAT_WRAPPER_SEEDED_CHAT_ID?.trim() || '';
const EXPLICIT_EXPECTED_TEXT = process.env.OPENMATES_CHAT_WRAPPER_EXPECT_TEXT?.trim() || '';
const EXPECTED_TEXT = EXPLICIT_EXPECTED_TEXT || DEFAULT_EXPECTED_TEXT;
const MIGRATION_COPY = /migration|migrate|upgrade encryption|repair key/i;
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

function isRegularChatId(value: string): boolean {
	return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

async function ensureSidebarOpen(page: any): Promise<void> {
	const chatItems = page.getByTestId('chat-item-wrapper');
	if (await chatItems.first().isVisible({ timeout: 2000 }).catch(() => false)) return;

	const sidebarToggle = page.getByTestId('sidebar-toggle');
	if (await sidebarToggle.isVisible({ timeout: 5000 }).catch(() => false)) {
		await sidebarToggle.click();
	}
	await expect(chatItems.first()).toBeVisible({ timeout: 30000 });
}

async function rowChatInfo(row: any): Promise<{ chatId: string; title: string }> {
	const chatId = (await row.getAttribute('data-chat-id')) || '';
	const title = ((await row.getByTestId('chat-title').first().innerText({ timeout: 5000 }).catch(() => '')) || '').trim();
	return { chatId, title };
}

async function resolveSeededChat(page: any): Promise<{ chatId: string; expectedText: string }> {
	if (SEEDED_CHAT_ID) return { chatId: SEEDED_CHAT_ID, expectedText: EXPECTED_TEXT };
	await ensureSidebarOpen(page);

	const preferredRow = page.getByTestId('chat-item-wrapper').filter({ hasText: EXPECTED_TEXT }).first();
	if (await preferredRow.isVisible({ timeout: 5000 }).catch(() => false)) {
		const { chatId } = await rowChatInfo(preferredRow);
		if (chatId) return { chatId, expectedText: EXPECTED_TEXT };
	}

	if (EXPLICIT_EXPECTED_TEXT) {
		throw new Error(`No seeded chat matching "${EXPECTED_TEXT}" was found for this test account.`);
	}

	const rows = page.getByTestId('chat-item-wrapper');
	const count = await rows.count();
	for (let index = 0; index < Math.min(count, 20); index += 1) {
		const { chatId, title } = await rowChatInfo(rows.nth(index));
		if (isRegularChatId(chatId) && title && !/processing|untitled chat/i.test(title)) {
			return { chatId, expectedText: title };
		}
	}
	throw new Error(`No existing regular chat with visible decrypted text was found for this test account.`);
}

test('existing seeded chat decrypts after chat key wrapper migration', async ({ page }: { page: any }) => {
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	test.skip(!EXPECTED_TEXT, 'Missing expected text for key-wrapper regression.');

	await page.setViewportSize({ width: 1440, height: 900 });
	await loginToTestAccount(page, (message: string) => console.log(`[CHAT_KEY_WRAPPER] ${message}`));
	const { chatId, expectedText } = await resolveSeededChat(page);

	await page.goto(getE2EDebugUrl(`/chat/${chatId}`), { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('chat-header-title').filter({ hasText: expectedText })).toBeVisible({ timeout: 60000 });
	await expect(page.getByText(MIGRATION_COPY)).toHaveCount(0);
});
