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

const DEFAULT_SEEDED_CHAT_ID = '93a58f33-4505-49d9-8453-d473bcb3c7b0';
const DEFAULT_EXPECTED_TEXT = '2 Day Weather Forecast Berlin';
const SEEDED_CHAT_ID = process.env.OPENMATES_CHAT_WRAPPER_SEEDED_CHAT_ID || DEFAULT_SEEDED_CHAT_ID;
const EXPECTED_TEXT = process.env.OPENMATES_CHAT_WRAPPER_EXPECT_TEXT || DEFAULT_EXPECTED_TEXT;
const MIGRATION_COPY = /migration|migrate|upgrade encryption|repair key/i;
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test('existing seeded chat decrypts after chat key wrapper migration', async ({ page }: { page: any }) => {
	test.setTimeout(180000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
  test.skip(!SEEDED_CHAT_ID || !EXPECTED_TEXT, 'Missing seeded chat env for key-wrapper regression.');

  await page.setViewportSize({ width: 1440, height: 900 });
  await loginToTestAccount(page, (message: string) => console.log(`[CHAT_KEY_WRAPPER] ${message}`));
  await page.goto(getE2EDebugUrl(`/chat/${SEEDED_CHAT_ID}`), { waitUntil: 'domcontentloaded' });

  await expect(page.getByText(EXPECTED_TEXT, { exact: false })).toBeVisible({ timeout: 60000 });
  await expect(page.getByText(MIGRATION_COPY)).toHaveCount(0);
});
