import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { landingAppExamples, landingAppOrder } from '../../../../packages/public-site/src/components/landing/landingPageContent';

// playwright-account: not_required reason=isolated_component_preview

const APP = 'https://app.dev.openmates.org';
const preview = (width: number) =>
  `/dev/preview/landing/LandingPage?${new URLSearchParams({ theme: 'light', background: '#dbeafe', width: String(width), chrome: '0' })}`;

for (const { width, height } of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.destinations,marketing-landing.hero-app-rail,marketing-landing.interactive-rail,marketing-landing.feature-layout,marketing-landing.independent-scroll
  test(`opening a wheel example preserves scroll sections when observations stall (${width}px)`, async ({ page }) => {
    test.setTimeout(45_000);
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.stack ?? error.message));
    page.on('crash', () => errors.push('original landing page crashed'));
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.addInitScript(() => {
      const NativeObserver = window.IntersectionObserver;
      window.IntersectionObserver = class extends NativeObserver {
        constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
          super((entries, observer) => {
            if (!document.documentElement.hasAttribute('data-test-pause-reveals')) callback(entries, observer);
          }, options);
        }
      };
    });
    await page.context().route(`${APP}/**`, route => route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>Example chat</title>' }));
    await page.goto(preview(width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);

    const landingUrl = page.url();
    const rail = page.getByTestId('landing-app-rail');
    const prompt = page.getByTestId('landing-prompt');
    const travel = rail.locator('.rail-group:nth-child(2) [data-app-id="travel"]');
    await travel.evaluate((button: HTMLButtonElement) => button.click());
    await expect(prompt).toHaveAttribute('data-active-app', 'travel');
    const expectedPopupUrl = `${APP}/#chat-id=${encodeURIComponent(landingAppExamples.travel)}`;
    await expect(prompt).toHaveAttribute('href', expectedPopupUrl);
    await expect(prompt).toHaveAttribute('target', '_blank');
    // Reproduce the missed-observation condition caused by background-tab throttling.
    await page.evaluate(() => document.documentElement.setAttribute('data-test-pause-reveals', ''));

    const [popup] = await Promise.all([page.context().waitForEvent('page'), prompt.click()]);
    await expect.poll(() => popup.url()).toBe(expectedPopupUrl);
    await expect(page.getByTestId('landing-page')).toBeVisible();
    expect(page.url()).toBe(landingUrl);
    await page.bringToFront();
    await expect(rail).toHaveAttribute('data-active-app', (await prompt.getAttribute('data-active-app'))!);
    for (const id of ['actionable', 'privacy', 'model-choice', 'workflows', 'devices', 'open-source']) {
      const section = page.getByTestId(`landing-feature-${id}`);
      await section.scrollIntoViewIfNeeded();
      await expect(section).toHaveClass(/revealed/);
      await expect(section.getByRole('heading')).toHaveCSS('opacity', '1');
      await expect(section.locator('.feature-copy p')).toHaveCSS('opacity', '1');
      await expect(section.locator('.feature-example')).toHaveCSS('opacity', '1');
      for (const image of await section.locator('img.device-screen:visible').all()) {
        await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true);
      }
    }
    for (const id of ['landing-newsletter-reveal', 'landing-events', 'landing-news', 'landing-blog']) {
      const section = page.getByTestId(id);
      await section.scrollIntoViewIfNeeded();
      await expect(section).toHaveClass(/revealed/);
      await expect(id === 'landing-newsletter-reveal' ? section : section.locator('.publication-intro')).toHaveCSS('opacity', '1');
    }
    const footer = page.locator('.site-footer');
    await footer.scrollIntoViewIfNeeded();
    await expect(footer.locator('.social-icon')).toHaveCount(8);
    expect(await footer.locator('.social-icon').evaluateAll(elements => {
      const probe = document.createElement('span');
      probe.style.backgroundColor = 'var(--color-grey-80)';
      document.body.append(probe);
      const color = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return elements.every(element => getComputedStyle(element).backgroundColor === color && getComputedStyle(element).maskImage.includes('/icons/'));
    })).toBe(true);

    const track = rail.locator('.rail-track');
    const beforeWheel = await track.evaluate(element => getComputedStyle(element).transform);
    const prevented = await rail.evaluate(element => {
      const event = new WheelEvent('wheel', { deltaX: 90, deltaY: 0, bubbles: true, cancelable: true });
      element.dispatchEvent(event);
      return event.defaultPrevented;
    });
    expect(prevented).toBe(true);
    expect(await track.evaluate(element => getComputedStyle(element).transform)).not.toBe(beforeWheel);

    const nextApp = landingAppOrder[(landingAppOrder.indexOf('travel') + 1) % landingAppOrder.length];
    await rail.locator(`.rail-group:nth-child(2) [data-app-id="${nextApp}"]`).evaluate((button: HTMLButtonElement) => button.click());
    await expect(prompt).toHaveAttribute('data-active-app', nextApp);
    await expect(rail).toHaveAttribute('data-active-app', nextApp);
    await expect.poll(() => prompt.getAttribute('data-active-app'), { timeout: 8_000 }).not.toBe(nextApp);
    await expect(rail).toHaveAttribute('data-active-app', (await prompt.getAttribute('data-active-app'))!);
    expect(page.url()).toBe(landingUrl);
    expect(errors, 'original landing errors after opening and returning from the example').toEqual([]);
    await popup.close();
  });
}
