// playwright-account: not_required reason=public_guest_header
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers expose CommonJS exports. */
import type { Browser, Page, TestInfo } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

async function expectGuestHeaderLogin(page: Page, width: number): Promise<void> {
  await page.addInitScript(() => localStorage.setItem('openmates:last-auth-method', 'email'));
  await page.setViewportSize({ width, height: 844 });
  await page.goto(getE2EDebugUrl('/#apps'), { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('apps-workspace-home')).toBeVisible({ timeout: 30000 });
  const header = page.getByTestId('global-header');
  const select = page.getByTestId('workspace-mobile-select');
  const login = page.getByTestId('header-login-signup-btn');
  const profile = page.getByTestId('profile-container');
  await expect(header.locator('.mobile-logo-icon')).toBeHidden();
  await expect(select).toBeVisible();
  await expect(select).toHaveAttribute('data-active-workspace', '/#apps');
  await expect(login).toBeVisible();
  await expect(login).toHaveText('Login', { useInnerText: true });
  await expect(profile).toBeVisible();
  const [selectBox, rightBox, loginBox, profileBox] = await Promise.all([
    select.boundingBox(), header.locator('.right-section').boundingBox(),
    login.boundingBox(), profile.boundingBox(),
  ]);
  for (const box of [selectBox, rightBox, loginBox, profileBox]) expect(box).not.toBeNull();
  expect(selectBox!.x + selectBox!.width).toBeLessThanOrEqual(rightBox!.x + 1);
  expect(loginBox!.x + loginBox!.width).toBeLessThanOrEqual(profileBox!.x + 1);
  expect(await login.evaluate(element => {
    const rect = element.getBoundingClientRect();
    return [0.1, 0.5, 0.9].every(fraction => {
      const target = document.elementFromPoint(rect.x + rect.width * fraction, rect.y + rect.height / 2);
      return target === element || element.contains(target);
    });
  })).toBe(true);
  if (width === 390) await page.screenshot({ path: test.info().outputPath('guest-app-header-mobile.png') });
  await login.click();
  await expect(page.getByTestId('login-modal')).toBeVisible();
}

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
test('the compact workspace picker switches the real app and keeps the active workspace', async ({ page }: { page: Page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
  const picker = page.getByTestId('workspace-mobile-select');
  const panel = page.getByTestId('workspace-picker-panel');
  await picker.click();
  await expect(panel.getByRole('link', { name: /chats?/i })).toHaveAttribute('aria-current', 'page');
  await panel.getByRole('link', { name: 'Apps', exact: true }).click();
  await expect(page.getByTestId('apps-workspace-home')).toBeVisible({ timeout: 30_000 });
  await expect(panel).toBeHidden();
  await expect(picker).toHaveAttribute('data-active-workspace', '/#apps');
  await picker.click();
  await expect(panel.getByRole('link', { name: 'Apps', exact: true })).toHaveAttribute('aria-current', 'page');
  await test.info().attach('apps-selected-in-compact-picker', { body: await page.screenshot(), contentType: 'image/png' });
  await panel.getByRole('link', { name: /chats?/i }).click();
  await expect(picker).toHaveAttribute('data-active-workspace', '/');
  await expect(panel).toBeHidden();
});

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
test('returning guests can open Login from the 320px app header', async ({ page }: { page: Page }) => {
  await expectGuestHeaderLogin(page, 320);
});

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
test('returning guests can open Login from the 390px app header', async ({ page }: { page: Page }) => {
  await expectGuestHeaderLogin(page, 390);
});

for (const viewport of [
  { name: 'phone', width: 390, height: 844 },
  { name: 'tablet', width: 820, height: 1180 },
  { name: 'desktop', width: 1280, height: 800 },
]) {
  // contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell
  test(`first-load signed-out header at ${viewport.name} matches the state after reload`, async ({ browser }: { browser: Browser }, testInfo: TestInfo) => {
    const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
    const page = await context.newPage();
    const measure = async () => page.evaluate(() => {
      const box = (selector: string) => {
        const element = document.querySelector(selector);
        const rect = element?.getBoundingClientRect();
        return rect && rect.width > 0 ? { left: rect.left, right: rect.right } : null;
      };
      // Phones show the compact select; tablet and desktop show the icon tab bar instead.
      return {
        switcher: box('[data-testid="header-workspace-switcher"]')
          ?? box('[data-testid="global-header"] .webapp-center-tabs'),
        login: box('[data-testid="header-login-signup-btn"]'),
        logoIconShown: [...document.querySelectorAll('[data-testid="global-header"] .mobile-logo-icon')]
          .some(element => getComputedStyle(element).display !== 'none'),
      };
    });
    try {
      await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('global-header')).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('header-login-signup-btn')).toBeAttached();
      await page.evaluate(() => document.fonts.ready);
      await expect.poll(async () => (await measure()).switcher !== null, { timeout: 15000 }).toBe(true);
      const first = await measure();
      await testInfo.attach(`first-load-${viewport.name}`, {
        body: await page.screenshot(), contentType: 'image/png',
      });
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('global-header')).toBeVisible({ timeout: 30000 });
      await expect.poll(async () => (await measure()).switcher !== null, { timeout: 15000 }).toBe(true);
      const reloaded = await measure();
      await testInfo.attach(`after-reload-${viewport.name}`, {
        body: await page.screenshot(), contentType: 'image/png',
      });
      if (first.login) expect(first.switcher!.right).toBeLessThanOrEqual(first.login.left + 1);
      expect(first.logoIconShown).toBe(reloaded.logoIconShown);
      expect(Math.abs(first.switcher!.left - reloaded.switcher!.left)).toBeLessThanOrEqual(2);
    } finally {
      await context.close();
    }
  });
}
