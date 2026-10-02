// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers expose CommonJS exports. */
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const { expect, test } = require('../helpers/cookie-audit');

async function openHeader(page: Page, width: number, signedIn = false): Promise<void> {
  await page.setViewportSize({ width, height: 844 });
  await page.goto(`/dev/preview/Header?${new URLSearchParams({
    theme: 'light', background: '#dbeafe', width: String(width), chrome: '0',
    ...(signedIn ? { variant: 'signedIn' } : {}),
  })}`, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
}

async function expectGuestControlsFit(page: Page): Promise<void> {
  const header = page.getByTestId('global-header');
  const menu = page.getByTestId('sidebar-toggle');
  const select = page.getByTestId('workspace-mobile-select');
  const cta = page.getByTestId('header-login-signup-btn');
  await expect(header.locator('.mobile-logo-icon')).toBeHidden();
  for (const control of [menu, select, cta]) await expect(control).toBeVisible();
  const [headerBox, menuBox, selectBox, ctaBox, rightBox] = await Promise.all([
    header.boundingBox(), menu.boundingBox(), select.boundingBox(), cta.boundingBox(),
    header.locator('.right-section').boundingBox(),
  ]);
  for (const box of [headerBox, menuBox, selectBox, ctaBox, rightBox]) expect(box).not.toBeNull();
  expect(selectBox!.x).toBeGreaterThanOrEqual(menuBox!.x + menuBox!.width + 4);
  expect(selectBox!.x + selectBox!.width).toBeLessThanOrEqual(rightBox!.x + 1);
  expect(ctaBox!.x + ctaBox!.width).toBeLessThanOrEqual(headerBox!.x + headerBox!.width - 50);
  expect(await cta.evaluate(element => {
    const rect = element.getBoundingClientRect();
    return [0.1, 0.5, 0.9].every(fraction => {
      const target = document.elementFromPoint(rect.x + rect.width * fraction, rect.y + rect.height / 2);
      return target === element || element.contains(target);
    });
  })).toBe(true);
  const viewport = await page.getByTestId('component-preview-viewport').evaluate(element => ({
    scroll: element.scrollWidth, client: element.clientWidth,
  }));
  expect(viewport.scroll).toBeLessThanOrEqual(viewport.client + 1);
}

test.beforeEach(async ({ page }: { page: Page }) => {
  await page.route('**/v1/features/availability', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ disabled: [] }),
  }));
});

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible,landing-onboarding.signup-cta
test('keeps the signed-out Sign up button unobscured at compact widths', async ({ page }: { page: Page }) => {
  for (const width of [320, 390, 730]) {
    await openHeader(page, width);
    await expect(page.getByTestId('header-login-signup-btn')).toHaveText('Sign up', { useInnerText: true });
    await expectGuestControlsFit(page);
  }
});

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible,landing-onboarding.signup-cta
test('keeps the returning guest Login button unobscured and clickable', async ({ page }: { page: Page }) => {
  await page.addInitScript(() => localStorage.setItem('openmates:last-auth-method', 'email'));
  for (const width of [320, 390, 730]) {
    await openHeader(page, width);
    const cta = page.getByTestId('header-login-signup-btn');
    await expect(cta).toHaveText('Login', { useInnerText: true });
    await expectGuestControlsFit(page);
    await cta.focus();
    await expect(cta).toBeFocused();
    await cta.hover();
    const loginRequested = page.evaluate(() => new Promise<void>(resolve => {
      window.addEventListener('openLoginInterface', () => resolve(), { once: true });
    }));
    await cta.click();
    await loginRequested;
    if (width === 390) await page.screenshot({ path: test.info().outputPath('guest-mobile-login.png') });
  }
});

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
test('preserves the signed-in favicon and centered mobile dropdown', async ({ page }: { page: Page }) => {
  for (const width of [320, 390, 730]) {
    await openHeader(page, width, true);
    const header = page.getByTestId('global-header');
    await expect(header.locator('.mobile-logo-icon')).toBeVisible();
    await expect(page.getByTestId('header-login-signup-btn')).toBeHidden();
    const select = page.getByTestId('workspace-mobile-select');
    await expect(select).toBeVisible();
    const [navBox, selectBox] = await Promise.all([header.locator('nav').boundingBox(), select.boundingBox()]);
    expect(navBox).not.toBeNull();
    expect(selectBox).not.toBeNull();
    expect(Math.abs(selectBox!.x + selectBox!.width / 2 - navBox!.x - navBox!.width / 2)).toBeLessThanOrEqual(1);
    if (width === 390) await page.screenshot({ path: test.info().outputPath('signed-in-mobile.png') });
  }
});

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
test('preserves the signed-out desktop logo and workspace tabs', async ({ page }: { page: Page }) => {
  await openHeader(page, 1280);
  await expect(page.getByTestId('global-header').locator('.logo-link strong')).toBeVisible();
  await expect(page.getByTestId('workspace-mobile-select')).toBeHidden();
  await expect(page.getByTestId('chats-nav-link')).toBeVisible();
  await expect(page.getByTestId('apps-nav-link')).toBeVisible();
  await expect(page.getByTestId('header-login-signup-btn')).toBeVisible();
});
