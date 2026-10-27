/**
 * Keep the public landing aligned with admitted capabilities and real media.
 * Exercise centered copy and retained links in bare component preview only.
 * Removed connector demos must not return through screenshots or story playback.
 * Phone and laptop cases cover the same English and German promises.
 * Product destinations are isolated so this spec needs no account or inference.
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { landingAppExamples } from '../../../../packages/public-site/src/components/landing/landingPageContent';

// playwright-account: not_required reason=isolated_component_preview
const APP = 'https://app.dev.openmates.org';

for (const width of [390, 1440]) {
  for (const language of ['en', 'de']) {
    // contract-test: direct surface=gui.web assertions=marketing-landing.feature-layout,marketing-landing.real-screenshots,marketing-landing.example-catalog-alignment,marketing-landing.destinations
    test(`admitted landing copy and media fit ${width}px ${language}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      const obsoleteRequests: string[] = [];
      page.on('request', request => {
        if (/\/landing\/screenshots\/(events|devices|hero)-/.test(request.url())) obsoleteRequests.push(request.url());
      });
      await page.route('**/v1/settings/server-status', route => route.fulfill({ json: {} }));
      const query = new URLSearchParams({ chrome: '0', width: String(width), theme: 'light', props: JSON.stringify({ initialLanguage: language, initialLanguageMode: 'manual' }) });
      await page.goto(`/dev/preview/landing/LandingPage?${query}`, { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page, 30_000);
      const root = page.getByTestId('landing-page');
      await expect(root.locator('.feature')).toHaveCount(6);
      await expect(root.getByTestId('landing-actionable-event-preview')).toHaveCount(0);
      await expect(root.locator('a[href*="#chat-id=undefined"]')).toHaveCount(0);
      const actionable = page.getByTestId('landing-feature-actionable');
      await expect(actionable.locator('.story-copy p')).not.toContainText(/doctor appointments|apartments|travel connections|Arzttermine|Wohnungen|Reiseverbindungen/i);
      await expect(actionable.locator('.story-copy p')).toContainText(language === 'de' ? 'Tabellen und Code' : 'tables');
      for (const id of ['actionable', 'devices']) {
        const section = page.getByTestId(`landing-feature-${id}`);
        await page.getByTestId('landing-scroll-container').evaluate((element, id) => {
          const target = element.querySelector(`#${id}`)!;
          element.scrollTo({ top: target.getBoundingClientRect().top - element.getBoundingClientRect().top + element.scrollTop, behavior: 'instant' });
        }, id);
        await expect(section.locator('.story-copy p')).toBeVisible();
        await expect(section.locator('img, .story-stage, .feature-example')).toHaveCount(0);
        const geometry = await section.evaluate(element => {
          const copy = element.querySelector('.feature-copy')!.getBoundingClientRect();
          const frame = element.getBoundingClientRect();
          const composer = element.closest('[data-testid="landing-page"]')!.querySelector('[data-testid="landing-compose"]')!.getBoundingClientRect();
          return { centered: Math.abs((copy.left + copy.right) / 2 - (frame.left + frame.right) / 2), inside: copy.left >= frame.left && copy.right <= frame.right, bottom: copy.bottom, composerTop: composer.top, overflow: element.scrollWidth > element.clientWidth, align: getComputedStyle(element).textAlign };
        });
        expect(geometry.centered).toBeLessThanOrEqual(2);
        expect(geometry.inside).toBe(true);
        expect(geometry.overflow).toBe(false);
        expect(geometry.align).toBe('center');
        expect(geometry.bottom).toBeLessThan(geometry.composerTop);
      }
      for (const id of ['privacy', 'model-choice', 'workflows']) {
        const section = page.getByTestId(`landing-feature-${id}`);
        await expect(section.getByTestId('device-screenshots')).toHaveCount(1);
        await expect(section.locator('img.device-screen')).toHaveCount(2);
      }
      await expect(root.locator('a.device-screenshots')).toHaveCount(1);
      expect(obsoleteRequests).toEqual([]);
      await page.getByTestId('landing-scroll-container').evaluate(element => element.scrollTo({ top: 0, behavior: 'instant' }));
      await page.getByTestId('landing-app-rail').locator('.rail-group:nth-child(2) [data-app-id="web"]').evaluate((element: HTMLButtonElement) => element.click());
      const destination = `${APP}/?lang=${language}#chat-id=${encodeURIComponent(landingAppExamples.web)}`;
      const prompt = page.getByTestId('landing-prompt');
      await expect(prompt).toHaveAttribute('href', destination);
      await page.context().route(`${APP}/**`, route => route.fulfill({ contentType: 'text/html', body: '<h1>Admitted example destination</h1>' }));
      const popupPromise = page.waitForEvent('popup');
      await prompt.click();
      const popup = await popupPromise;
      await expect(popup).toHaveURL(destination);
      await popup.close();
    });
  }
}
