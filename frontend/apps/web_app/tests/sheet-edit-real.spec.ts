/** Real dev sheet edit flow (price_products output). Held out of isolated CI. */
import { test, expect, chromium, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
// eslint-disable-next-line @typescript-eslint/no-require-imports -- helper is CommonJS, shared with other specs
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

// playwright-account: required reason=real_ai_personal_dev_only
const enabled = process.env.SHEET_EDIT_REAL_DEV === '1';
const APP = 'https://app.dev.openmates.org';
const chatId = process.env.SHEET_EDIT_CHAT_ID || '';
const profile = path.join(process.env.OPENMATES_STATE_DIR || '/tmp', 'sheet-edit-profile');
test.skip(!enabled, 'Requires explicit dev-only execution against a chat holding a sheet embed.');
test.describe.configure({ retries: 0, timeout: 180_000 });

const cell = (page: Page, id: string) => page.locator(`[data-testid="sheet-cell"][data-cell="${id}"]`);

// contract-test: infrastructure
test('edit an input in a fullscreen sheet, dependents recalc, value persists after reload', async () => {
  const ctx = await chromium.launchPersistentContext(profile, { headless: true, baseURL: APP,
    executablePath: process.env.PW_CHROMIUM, viewport: { width: 1280, height: 1000 } });
  try {
    const page = ctx.pages()[0] || await ctx.newPage();
    await page.goto('/');
    await page.waitForTimeout(4000);
    if (await page.getByTestId('header-login-signup-btn').isVisible()) await loginToTestAccount(page, () => {}, async () => {}, { credentials: {
      email: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_EMAIL,
      password: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_PASSWORD,
      otpKey: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_OTP_KEY } });
    const open = async () => {
      await page.goto(`/#chat-id=${chatId}`);
      const preview = page.locator('[data-testid="embed-preview"][data-app-id="sheets"]').first();
      await expect(preview).toBeVisible({ timeout: 60_000 });
      // Chat-result previews open fullscreen via the expand icon (last button), not the body.
      await preview.locator('button').last().click();
      await expect(page.getByTestId('sheet-edit-toggle')).toBeVisible({ timeout: 20_000 });
    };
    await open();
    const wage = (await cell(page, 'B5').innerText()).trim() === '20' ? 15 : 20;
    const labour = wage * 6, cost = 29 + labour + 15, price = (cost / 0.6).toFixed(2);
    await page.getByTestId('sheet-edit-toggle').click();
    await cell(page, 'B5').click();
    const input = page.getByTestId('sheet-cell-input');
    await input.fill(String(wage));
    await input.press('Enter');
    await expect(cell(page, 'B10')).toHaveText(String(labour));
    await expect(cell(page, 'B12')).toHaveText(String(cost));
    await expect(cell(page, 'B13')).toHaveText(new RegExp(price.replace('.', '[.,]')));
    await expect(page.getByTestId('sheet-save-status')).toHaveAttribute('data-state', 'saved', { timeout: 20_000 });
    await page.reload();
    await open();
    await expect(cell(page, 'B5')).toHaveText(String(wage));
    await expect(cell(page, 'B13')).toHaveText(new RegExp(price.replace('.', '[.,]')));
    fs.writeFileSync(test.info().outputPath('done.txt'), 'ok');
  } finally { await ctx.close(); }
});
