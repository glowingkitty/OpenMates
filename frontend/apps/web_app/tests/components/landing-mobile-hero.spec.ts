import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const execFileAsync = promisify(execFile);
test.use({ browserName: 'webkit', launchOptions: { args: [] }, hasTouch: true });
test.beforeAll(async () => {
  test.setTimeout(180_000);
  await execFileAsync('npx', ['--no-install', 'playwright', 'install', '--with-deps', 'webkit'], { timeout: 170_000, maxBuffer: 8 * 1024 * 1024 });
});

// contract-test: direct surface=gui.web assertions=marketing-landing.hero-app-rail,marketing-landing.destinations
test('mobile hero elements are prominent and fit above the fixed composer', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  // The 720px case accounts for visible Safari chrome; the short phone catches
  // cramped layouts, and the desktop verifies that the phone rule stays scoped.
  for (const viewport of [{ width: 390, height: 720 }, { width: 430, height: 932 }, { width: 320, height: 568 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    const query = new URLSearchParams({ theme: 'dark', background: '#161616', width: String(viewport.width), chrome: '0' });
    await page.goto(`/dev/preview/landing/LandingPage?${query}`, { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    await page.evaluate(() => document.fonts.ready.then(() => true));
    for (const language of ['en', 'de']) {
      const languageButton = page.getByTestId('landing-language-button');
      await languageButton.click();
      await page.getByTestId('landing-language-panel').getByRole('button', { name: language === 'en' ? 'English' : 'Deutsch', exact: true }).click();
      const rail = page.getByTestId('landing-app-rail');
      await rail.getByTestId('landing-rail-group').nth(1).locator('[data-app-id="social_media"]').evaluate((button: HTMLButtonElement) => button.click());
      await expect(rail).toHaveAttribute('data-active-app', 'social_media');
      const layout = await page.getByTestId('landing-page').evaluate(element => {
        const node = (selector: string) => element.querySelector<HTMLElement>(selector)!;
        const rect = (selector: string) => node(selector).getBoundingClientRect().toJSON();
        const font = (selector: string) => parseFloat(getComputedStyle(node(selector)).fontSize);
        return {
          hero: rect('[data-testid="landing-hero"]'),
          rows: ['.hero-visual', '#hero-title', '.hero-prompt-entrance', '.hero-speed', '.rail-window', '.scroll-cue'].map(rect),
          glyph: rect('.hero-ai-glyph'), iconSize: parseFloat(getComputedStyle(node('.rail-icon')).width),
          titleFont: font('#hero-title'), promptFont: font('.prompt-bubble'), speedFont: font('.hero-speed'), cueFont: font('.scroll-cue'),
          composer: rect('[data-testid="landing-compose"]'),
          glyphsLoaded: [...element.querySelectorAll<HTMLImageElement>('.rail-glyph')].every(image => image.complete && image.naturalWidth > 0),
          overflow: document.documentElement.scrollWidth > window.innerWidth,
        };
      });
      expect(layout.overflow).toBe(false);
      expect(layout.glyphsLoaded).toBe(true);
      for (let i = 0; i < layout.rows.length; i++) {
        const row = layout.rows[i];
        expect(row.left).toBeGreaterThanOrEqual(layout.hero.left - 1);
        expect(row.right).toBeLessThanOrEqual(layout.hero.right + 1);
        expect(row.top).toBeGreaterThanOrEqual(layout.hero.top - 1);
        if (i) expect(layout.rows[i - 1].bottom, `${viewport.width}x${viewport.height} ${language}: separate hero rows`).toBeLessThanOrEqual(row.top + 1);
      }
      expect(layout.rows.at(-1)!.bottom).toBeLessThan(layout.composer.top - 3);
      expect(layout.composer.bottom).toBeLessThanOrEqual(viewport.height);
      const available = layout.composer.top - layout.hero.top;
      expect((layout.rows.at(-1)!.bottom - layout.rows[0].top) / available, 'Hero content fills useful mobile space').toBeGreaterThan(.6);
      if (viewport.width < 600) {
        const compact = viewport.height < 600;
        expect(layout.titleFont).toBeGreaterThanOrEqual(compact ? (language === 'de' ? 26 : 30) : (language === 'de' ? 32 : 36));
        expect(layout.glyph.width).toBeGreaterThanOrEqual(compact ? 56 : 74);
        expect(layout.promptFont).toBeGreaterThanOrEqual(compact ? 18 : 20);
        expect(layout.speedFont).toBeGreaterThanOrEqual(compact ? 17 : 18);
        expect(layout.iconSize).toBeGreaterThanOrEqual(compact ? 64 : 80);
        expect(layout.cueFont).toBeGreaterThanOrEqual(compact ? 15 : 16);
      }
      await expect(page.getByTestId('landing-open-web-app')).toBeVisible();
      await page.mouse.move(1, 1);
      await page.screenshot({ path: testInfo.outputPath(`hero-${viewport.width}x${viewport.height}-${language}.png`) });
    }
  }
  expect(errors).toEqual([]);
});
