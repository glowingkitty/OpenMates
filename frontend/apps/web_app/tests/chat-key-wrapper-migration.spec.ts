/* eslint-disable @typescript-eslint/no-require-imports */
// @privacy-promise: client-side-chat-encryption
/**
 * Chat key-wrapper migration regression.
 *
 * Uses an existing E2E test account and a seeded or pre-existing chat to prove
 * chat decryptability survives wrapper migration without user-visible migration UI.
 * Run only through the repo test dispatcher after deploy:
 * python3 scripts/tests.py run --spec chat-key-wrapper-migration.spec.ts
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');

const DEFAULT_EXPECTED_TEXT = '2 Day Weather Forecast Berlin';
const SEEDED_CHAT_ID = process.env.OPENMATES_CHAT_WRAPPER_SEEDED_CHAT_ID?.trim() || '';
const EXPLICIT_EXPECTED_TEXT = process.env.OPENMATES_CHAT_WRAPPER_EXPECT_TEXT?.trim() || '';
const EXPECTED_TEXT = EXPLICIT_EXPECTED_TEXT || DEFAULT_EXPECTED_TEXT;
const MIGRATION_COPY = /migration|migrate|upgrade encryption|repair key/i;
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

type ResolvedChat = { chatId: string; expectedText: string; expectedSurface: 'header' | 'transcript' };

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

async function currentChatId(page: any): Promise<string> {
	const urlChatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null;
	if (urlChatId) return urlChatId;
	return (await page.locator('[data-action="message-input"]').last().getAttribute('data-current-chat-id').catch(() => '')) || '';
}

async function createSeededChat(page: any): Promise<ResolvedChat> {
	const seedMessage = `${DEFAULT_EXPECTED_TEXT} key wrapper smoke`;
	await startNewChat(page, (message: string) => console.log(`[CHAT_KEY_WRAPPER] ${message}`));
	await sendMessage(
		page,
		withMockMarker(seedMessage, 'chat_flow_capital'),
		(message: string) => console.log(`[CHAT_KEY_WRAPPER] ${message}`),
		undefined,
		'chat-key-wrapper-seed'
	);
	const chatId = await currentChatId(page);
	if (!isRegularChatId(chatId)) {
		throw new Error(`Seed chat was created without a regular chat id: ${chatId || '(missing)'}`);
	}
	return { chatId, expectedText: seedMessage, expectedSurface: 'transcript' };
}

async function resolveSeededChat(page: any): Promise<ResolvedChat> {
	if (SEEDED_CHAT_ID) return { chatId: SEEDED_CHAT_ID, expectedText: EXPECTED_TEXT, expectedSurface: 'header' };
	await ensureSidebarOpen(page);

	const preferredRow = page.getByTestId('chat-item-wrapper').filter({ hasText: EXPECTED_TEXT }).first();
	if (await preferredRow.isVisible({ timeout: 5000 }).catch(() => false)) {
		const { chatId } = await rowChatInfo(preferredRow);
		if (chatId) return { chatId, expectedText: EXPECTED_TEXT, expectedSurface: 'header' };
	}

	if (EXPLICIT_EXPECTED_TEXT) {
		throw new Error(`No seeded chat matching "${EXPECTED_TEXT}" was found for this test account.`);
	}

	const rows = page.getByTestId('chat-item-wrapper');
	const count = await rows.count();
	for (let index = 0; index < Math.min(count, 20); index += 1) {
		const { chatId, title } = await rowChatInfo(rows.nth(index));
		if (isRegularChatId(chatId) && title && !/processing|untitled chat/i.test(title)) {
			return { chatId, expectedText: title, expectedSurface: 'header' };
		}
	}
	return createSeededChat(page);
}

test('existing seeded chat decrypts after chat key wrapper migration', async ({ page }: { page: any }) => {
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	test.skip(!EXPECTED_TEXT, 'Missing expected text for key-wrapper regression.');

	await page.setViewportSize({ width: 1440, height: 900 });
	await loginToTestAccount(page, (message: string) => console.log(`[CHAT_KEY_WRAPPER] ${message}`));
	const { chatId, expectedText, expectedSurface } = await resolveSeededChat(page);

	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`), { waitUntil: 'domcontentloaded' });
	if (expectedSurface === 'header') {
		await expect(page.getByTestId('chat-header-title').filter({ hasText: expectedText })).toBeVisible({ timeout: 60000 });
	} else {
		await expect(page.getByTestId('message-user').filter({ hasText: expectedText })).toBeVisible({ timeout: 60000 });
	}
	await expect(page.getByText(MIGRATION_COPY)).toHaveCount(0);
});
