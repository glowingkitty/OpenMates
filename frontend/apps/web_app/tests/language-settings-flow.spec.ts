import { expect, test } from './helpers/cookie-audit';
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { getTestAccount } = require('./signup-flow-helpers');

// contract-test: direct surface=gui.web assertions=language-preferences.manual-choice,language-preferences.first-paint,language-preferences.resolution
test('Account language saves German, restores before text, and Automatic leaves the account choice intact', async ({ page }) => {
  test.setTimeout(150_000);
  const account = getTestAccount();
  test.skip(!account.email || !account.password || !account.otpKey, 'An isolated authenticated test account is required.');
  await loginToTestAccount(page, () => {}, async () => {});
  await page.goto('/#settings/account');
  await expect(page.getByTestId('account-language')).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('account-language').click();
  const saved = page.waitForResponse(response => response.url().includes('/v1/settings/user/language') && response.request().method() === 'POST');
  await page.getByTestId('language-option-de').click();
  expect((await saved).ok()).toBe(true);
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  await expect(page.getByTestId('language-option-de').locator('input')).toBeChecked();

  // Clear the fast preference mirror, retaining the genuine account's existing IndexedDB.
  await page.evaluate(() => {
    for (const key of ['preferredLanguage', 'openmatesLanguageMode', 'openmatesAccountLanguage']) localStorage.removeItem(key);
    for (const key of ['om_language', 'om_language_dev']) document.cookie = `${key}=; Max-Age=0; Path=/`;
  });
  await page.addInitScript(() => {
    const frames: {lang: string; text: string}[] = [];
    Object.assign(window, { __accountLanguageFrames: frames });
    new MutationObserver(() => {
      const heading = document.querySelector('[data-testid="chat-welcome-heading"]');
      if (heading?.textContent?.trim()) frames.push({ lang: document.documentElement.lang, text: heading.textContent.trim() });
    }).observe(document, { childList: true, subtree: true, characterData: true });
  });
  const restored = page.waitForResponse(response => response.url().endsWith('/v1/auth/session') && response.ok());
  await page.reload();
  const restoredSession = await (await restored).json();
  expect(restoredSession.user.language, 'Independent session readback must contain the saved language').toBe('de');
  await expect(page.getByTestId('language-option-de').locator('input')).toBeChecked({ timeout: 30_000 });
  const frames = await page.evaluate(() => (window as any).__accountLanguageFrames);
  expect(frames.length).toBeGreaterThan(0);
  expect(frames.every((frame: {lang: string; text: string}) => frame.lang === 'de' && !frame.text.startsWith('Hey'))).toBe(true);

  let accountWrites = 0;
  page.on('request', request => { if (request.url().includes('/v1/settings/user/language') && request.method() === 'POST') accountWrites += 1; });
  await page.getByTestId('language-option-auto').click();
  await expect(page.getByTestId('language-option-auto').locator('input')).toBeChecked();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  const autoRestored = page.waitForResponse(response => response.url().endsWith('/v1/auth/session') && response.ok());
  await page.reload();
  expect((await (await autoRestored).json()).user.language).toBe('de');
  await expect(page.getByTestId('language-option-auto').locator('input')).toBeChecked({ timeout: 30_000 });
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  expect(accountWrites, 'Automatic is local to the browser and must preserve the account manual choice').toBe(0);

  await page.route('**/v1/settings/user/language', route => route.fulfill({ status: 503, json: { detail: 'Temporary account-save failure' } }));
  await page.getByTestId('language-option-de').click();
  await expect(page.getByTestId('language-save-error')).toContainText('Konto');
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBe('de');
});
