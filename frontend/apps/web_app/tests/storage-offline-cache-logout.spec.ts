/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};

const { expect, test } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const { email, password, otpKey } = getTestAccount();

// contract-test: direct surface=gui.web assertions=teams.cache.bounded-isolated
test('logout purges app-owned plaintext connected download staging', async ({ page }: { page: any }) => {
  skipWithoutCredentials(test, email, password, otpKey);
  await loginToTestAccount(page, undefined, undefined, { waitForEditor: true });

  const tempName = await page.evaluate(async () => {
    sessionStorage.setItem('openmates:team-invite:logout-proof', 'private-fragment-key');
    const name = `openmates-download-v2-${Date.now()}-${crypto.randomUUID()}`;
    const root = await navigator.storage.getDirectory();
    const handle = await root.getFileHandle(name, { create: true });
    const writable = await handle.createWritable();
    await writable.write(new TextEncoder().encode('temporary private download'));
    await writable.close();
    return name;
  });

  await page.getByTestId('profile-container').click();
  await page.getByRole('menuitem', { name: /logout|abmelden/i }).click();
  await expect(page.locator('[data-authenticated="true"]')).toHaveCount(0, { timeout: 15000 });
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('openmates:team-invite:logout-proof'))).toBeNull();
  await expect.poll(() => page.evaluate(async (name: string) => {
    try {
      await (await navigator.storage.getDirectory()).getFileHandle(name);
      return false;
    } catch (error) {
      return error instanceof DOMException && error.name === 'NotFoundError';
    }
  }, tempName), { timeout: 15000 }).toBe(true);
});
