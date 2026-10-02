// playwright-account: not_required reason=public_guest_header
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers expose CommonJS exports. */
import type { Page } from '@playwright/test';

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
  await expect(select).toHaveValue('/#apps');
  await expect(login).toBeVisible();
  await expect(login).toHaveText('Login');
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

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible,landing-onboarding.signup-cta
test('returning guests can open Login from the 320px app header', async ({ page }: { page: Page }) => {
  await expectGuestHeaderLogin(page, 320);
});

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible,landing-onboarding.signup-cta
test('returning guests can open Login from the 390px app header', async ({ page }: { page: Page }) => {
  await expectGuestHeaderLogin(page, 390);
});
