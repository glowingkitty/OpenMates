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
const { deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');

const DEFAULT_EXPECTED_TEXT = '2 Day Weather Forecast Berlin';
const SEEDED_CHAT_ID = process.env.OPENMATES_CHAT_WRAPPER_SEEDED_CHAT_ID?.trim() || '';
const EXPLICIT_EXPECTED_TEXT = process.env.OPENMATES_CHAT_WRAPPER_EXPECT_TEXT?.trim() || '';
const EXPECTED_TEXT = EXPLICIT_EXPECTED_TEXT || DEFAULT_EXPECTED_TEXT;
const MIGRATION_COPY = /migration|migrate|upgrade encryption|repair key/i;
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

type DiscoveredChat = { id?: unknown; title?: unknown; summary?: unknown; chat_summary?: unknown };

function chatVisibleText(chat: DiscoveredChat): string {
	return [chat.title, chat.summary, chat.chat_summary].find(
		(value): value is string => typeof value === 'string' && value.trim().length > 0
	) || '';
}

async function resolveSeededChat(): Promise<{ chatId: string; expectedText: string }> {
	if (SEEDED_CHAT_ID) return { chatId: SEEDED_CHAT_ID, expectedText: EXPECTED_TEXT };
	if (!process.env.OPENMATES_TEST_ACCOUNT_API_KEY) {
		throw new Error('OPENMATES_TEST_ACCOUNT_API_KEY required to discover the seeded chat.');
	}

	const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	const searchResult = await runCli(apiUrl, ['chats', 'search', EXPECTED_TEXT, '--json'], 45_000);
	expectCliSuccess(searchResult, 'seeded chat search');
	const searchParsed = parseCliJson(searchResult);
	const searchMatches: DiscoveredChat[] = Array.isArray(searchParsed)
		? searchParsed
		: Array.isArray(searchParsed?.chats)
			? searchParsed.chats
			: [];
	const searchMatch = searchMatches.find((chat) => {
		if (typeof chat.id !== 'string' || !chat.id) return false;
		return [chat.title, chat.summary, chat.chat_summary, chat.id]
			.filter((value): value is string => typeof value === 'string')
			.some((value) => value.includes(EXPECTED_TEXT));
	});
	if (typeof searchMatch?.id === 'string') {
		return { chatId: searchMatch.id, expectedText: EXPECTED_TEXT };
	}
	if (EXPLICIT_EXPECTED_TEXT) {
		throw new Error(`No seeded chat matching "${EXPECTED_TEXT}" was found for this test account.`);
	}

	const listResult = await runCli(apiUrl, ['chats', 'list', '--limit', '20', '--json'], 45_000);
	expectCliSuccess(listResult, 'seeded chat fallback list');
	const listParsed = parseCliJson(listResult);
	const listChats: DiscoveredChat[] = Array.isArray(listParsed?.chats) ? listParsed.chats : [];
	const fallback = listChats.find((chat) => typeof chat.id === 'string' && chatVisibleText(chat));
	if (typeof fallback?.id !== 'string') {
		throw new Error(`No existing chat with visible decrypted text was found for this test account.`);
	}
	return { chatId: fallback.id, expectedText: chatVisibleText(fallback) };
}

test('existing seeded chat decrypts after chat key wrapper migration', async ({ page }: { page: any }) => {
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	test.skip(!EXPECTED_TEXT, 'Missing expected text for key-wrapper regression.');

	const { chatId, expectedText } = await resolveSeededChat();

	await page.setViewportSize({ width: 1440, height: 900 });
	await loginToTestAccount(page, (message: string) => console.log(`[CHAT_KEY_WRAPPER] ${message}`));
	await page.goto(getE2EDebugUrl(`/chat/${chatId}`), { waitUntil: 'domcontentloaded' });

	await expect(page.getByText(expectedText, { exact: false })).toBeVisible({ timeout: 60000 });
	await expect(page.getByText(MIGRATION_COPY)).toHaveCount(0);
});
