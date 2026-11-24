// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers expose CommonJS exports. */
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const { expect, test } = require('../helpers/cookie-audit');

async function openHeader(page: Page, width: number, signedIn = false, theme = 'light'): Promise<void> {
  await page.setViewportSize({ width, height: 844 });
  await page.goto(`/dev/preview/Header?${new URLSearchParams({
    theme, background: '#dbeafe', width: String(width), chrome: '0',
    ...(signedIn ? { variant: 'signedIn' } : {}),
  })}`, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
}

async function expectGuestControlsFit(page: Page, compact = true): Promise<void> {
  const header = page.getByTestId('global-header');
  const menu = page.getByTestId('sidebar-toggle');
  const select = page.getByTestId('workspace-mobile-select');
  const cta = page.getByTestId('header-login-signup-btn');
  const logo = header.locator('.mobile-logo-icon');
  if (compact) await expect(logo).toBeHidden();
  else await expect(logo).toBeVisible();
  for (const control of [menu, select, cta]) await expect(control).toBeVisible();
  const [headerBox, menuBox, selectBox, ctaBox, rightBox] = await Promise.all([
    header.boundingBox(), menu.boundingBox(), select.boundingBox(), cta.boundingBox(),
    header.locator('.right-section').boundingBox(),
  ]);
  for (const box of [headerBox, menuBox, selectBox, ctaBox, rightBox]) expect(box).not.toBeNull();
  expect(selectBox!.x).toBeGreaterThanOrEqual(menuBox!.x + menuBox!.width + 4);
  expect(selectBox!.x + selectBox!.width).toBeLessThanOrEqual(rightBox!.x + 1);
  expect(ctaBox!.x + ctaBox!.width).toBeLessThanOrEqual(headerBox!.x + headerBox!.width - 50);
  if (!compact) {
    const navBox = await header.locator('nav').boundingBox();
    const logoBox = await logo.boundingBox();
    expect(navBox).not.toBeNull();
    expect(logoBox).not.toBeNull();
    expect(Math.abs(selectBox!.x + selectBox!.width / 2 - navBox!.x - navBox!.width / 2)).toBeLessThanOrEqual(1);
    expect(selectBox!.x).toBeGreaterThanOrEqual(logoBox!.x + logoBox!.width);
  }
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

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.compact-picker-appearance,workspace-shell.nav.released-surfaces-visible
test('compact workspace picker matches the native panel in light and dark', async ({ page }, testInfo) => {
  for (const [width, theme] of [[390, 'light'], [640, 'dark']] as const) {
    await openHeader(page, width, true, theme);
    const trigger = page.getByTestId('workspace-mobile-select');
    const panel = page.getByTestId('workspace-picker-panel');
    const rows = panel.getByTestId('workspace-picker-option');
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(panel).toBeHidden();
    await trigger.focus();
    await page.keyboard.press('Enter');
    await expect(panel).toBeVisible();
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await expect(panel.getByRole('button', { name: /close workspace switcher/i })).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(rows.first()).toBeFocused();
    await expect(rows.first()).toHaveAttribute('aria-current', 'page');
    await expect(rows.first().getByTestId('workspace-option-check')).toBeVisible();
    await expect(rows).toHaveText([/chats?/i, 'Apps', 'Projects', 'Workflows', 'Tasks']);
    await expect(panel).toHaveCSS('background-image', /linear-gradient/);
    await expect(rows.first()).toHaveCSS('color', 'rgb(255, 255, 255)');
    for (const row of await rows.all()) {
      await expect(row).toHaveCSS('min-height', '60px');
      await expect(row.getByTestId('workspace-option-icon')).toHaveCSS('mask-image', /url\(/);
    }
    const bounds = (await panel.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await testInfo.attach(`workspace-picker-${theme}-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    await page.keyboard.press('Escape');
    await expect(panel).toBeHidden();
    await expect(trigger).toBeFocused();
    await trigger.click();
    await expect(panel).toBeVisible();
    await page.mouse.click(2, bounds.y + bounds.height + 10);
    await expect(panel).toBeHidden();
  }
  await openHeader(page, 1280, true, 'dark');
  await expect(page.getByTestId('workspace-mobile-select')).toBeHidden();
  await expect(page.getByTestId('chats-nav-link')).toHaveAttribute('aria-current', 'page');
  await testInfo.attach('workspace-tabs-dark-1280', { body: await page.screenshot(), contentType: 'image/png' });
});

for (const { width, touch } of [{ width: 390, touch: true }, { width: 640, touch: false }]) {
  test.describe(touch ? 'phone picker motion' : 'narrow desktop picker motion', () => {
    test.use({ hasTouch: touch, isMobile: touch, viewport: { width, height: 844 } });

    // contract-test: direct surface=gui.web assertions=workspace-shell.nav.compact-picker-dismissal
    test('fades the picker and backdrop and dismisses without activating the background control', async ({ page }, testInfo) => {
      await page.goto(`/dev/preview/Header?chrome=0&theme=light&background=%23dbeafe&width=${width}&variant=guestCtaToggle`);
      await waitForComponentPreview(page);
      const behindId = touch ? 'header-login-signup-btn' : 'sidebar-toggle';
      const behind = page.getByTestId(behindId);
      const signup = page.getByTestId('header-login-signup-btn');
      const trigger = page.getByTestId('workspace-mobile-select');
      const dialog = page.getByTestId('workspace-picker-dialog');
      const backdrop = page.getByTestId('workspace-picker-backdrop');
      await expect(signup).toBeVisible();
      const point = await behind.evaluate((button, rightEdge) => {
        const { left, right, top, height } = button.getBoundingClientRect();
        return { x: rightEdge ? right - 3 : left + 3, y: top + height / 2 };
      }, touch);
      const hitTarget = () => page.evaluate(({ x, y }) =>
        document.elementFromPoint(x, y)?.closest('[data-testid]')?.getAttribute('data-testid'), point);
      expect(await hitTarget()).toBe(behindId);
      await behind.evaluate(button => {
        button.addEventListener('click', () => button.setAttribute('data-activated', 'true'));
      });

      async function watchFade(control: string, phase: 'opening' | 'closing') {
        await dialog.evaluate((element, { control, phase, point }) => {
          document.querySelector(`[data-testid="${control}"]`)?.addEventListener('click', () => {
            requestAnimationFrame(() => {
              const animation = element.getAnimations()[0];
              const effect = animation?.effect as KeyframeEffect | undefined;
              const keyframes = effect?.getKeyframes() ?? [];
              const opacity = keyframes.map(frame => Number(frame.opacity));
              const duration = Number(effect?.getTiming().duration);
              const hitsBackdrop = document.elementFromPoint(point.x, point.y)?.getAttribute('data-testid') ===
                'workspace-picker-backdrop';
              const fading = duration > 0 && opacity.length === 2 &&
                (phase === 'opening' ? opacity[0] === 0 && opacity[1] === 1 :
                  opacity[0] > 0 && opacity[1] === 0);
              element.setAttribute(`data-fade-${phase}`, String(fading && hitsBackdrop));
            });
          }, { once: true });
        }, { control, phase, point });
      }

      await watchFade('workspace-mobile-select', 'opening');
      if (touch) await trigger.tap();
      else await trigger.click();
      await expect(dialog).toHaveAttribute('data-fade-opening', 'true');
      await expect(dialog).toHaveCSS('opacity', '1');
      await expect(backdrop).toBeVisible();
      await testInfo.attach(`picker-backdrop-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
      await watchFade('workspace-picker-backdrop', 'closing');
      if (touch) await page.touchscreen.tap(point.x, point.y);
      else await page.mouse.click(point.x, point.y);
      await expect(dialog).toHaveAttribute('data-fade-closing', 'true');
      await expect(dialog).toBeHidden();
      await expect(trigger).toBeFocused();
      await expect(signup).toBeVisible();
      expect(await behind.getAttribute('data-activated')).toBeNull();
      expect(await hitTarget()).toBe(behindId);
    });
  });
}

// contract-test: direct surface=gui.web assertions=workspace-shell.nav.compact-picker-dismissal
test('dismisses immediately with reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await openHeader(page, 640, true);
  const trigger = page.getByTestId('workspace-mobile-select');
  const dialog = page.getByTestId('workspace-picker-dialog');
  await trigger.click();
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(element => element.getAnimations().length)).toBe(0);
  await page.mouse.click(5, 600);
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
});

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
test('keeps the signed-out Sign up button unobscured at compact widths', async ({ page }: { page: Page }) => {
  for (const width of [320, 390]) {
    await openHeader(page, width);
    await expect(page.getByTestId('header-login-signup-btn')).toHaveText('Sign up', { useInnerText: true });
    await expectGuestControlsFit(page);
  }
});

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
test('keeps the returning guest Login button unobscured and clickable', async ({ page }: { page: Page }) => {
  await page.addInitScript(() => localStorage.setItem('openmates:last-auth-method', 'email'));
  for (const width of [320, 390]) {
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
test('keeps the guest favicon and centered dropdown when all controls fit', async ({ page }: { page: Page }) => {
  for (const label of ['Sign up', 'Login']) {
    if (label === 'Login') await page.addInitScript(() => localStorage.setItem('openmates:last-auth-method', 'email'));
    for (const width of [480, 600, 730]) {
      await openHeader(page, width);
      await expect(page.getByTestId('header-login-signup-btn')).toHaveText(label, { useInnerText: true });
      await expectGuestControlsFit(page, false);
      if (width === 600 && label === 'Login') await page.screenshot({ path: test.info().outputPath('guest-roomy-login.png') });
    }
  }
});

// contract-test: supporting surface=gui.web assertions=workspace-shell.nav.released-surfaces-visible
test('updates guest header positioning as available width changes', async ({ page }: { page: Page }) => {
  await page.addInitScript(() => localStorage.setItem('openmates:last-auth-method', 'email'));
  await openHeader(page, 730);
  await expectGuestControlsFit(page, false);
  await page.setViewportSize({ width: 390, height: 844 });
  await expectGuestControlsFit(page);
  await page.setViewportSize({ width: 600, height: 844 });
  await expectGuestControlsFit(page, false);
  await page.setViewportSize({ width: 390, height: 844 });
  await expectGuestControlsFit(page);
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
