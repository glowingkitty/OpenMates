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
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const SEEDED_CHAT_ID = process.env.OPENMATES_CHAT_WRAPPER_SEEDED_CHAT_ID || '';
const EXPECTED_TEXT = process.env.OPENMATES_CHAT_WRAPPER_EXPECT_TEXT || '';
const MIGRATION_COPY = /migration|migrate|upgrade encryption|repair key/i;

test('existing seeded chat decrypts after chat key wrapper migration', async ({ page }: { page: any }) => {
  test.setTimeout(180000);
  skipWithoutCredentials(test);
  test.skip(!SEEDED_CHAT_ID || !EXPECTED_TEXT, 'Missing seeded chat env for key-wrapper regression.');

  await page.setViewportSize({ width: 1440, height: 900 });
  await loginToTestAccount(page, (message: string) => console.log(`[CHAT_KEY_WRAPPER] ${message}`));
  await page.goto(getE2EDebugUrl(`/chat/${SEEDED_CHAT_ID}`), { waitUntil: 'domcontentloaded' });

  await expect(page.getByText(EXPECTED_TEXT, { exact: false })).toBeVisible({ timeout: 60000 });
  await expect(page.getByText(MIGRATION_COPY)).toHaveCount(0);
});
