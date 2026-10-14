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
  await page.route('**/api/server-status', route => route.fulfill({ json: { anonymous_free_usage: { active: true, can_send_text: true } } }));
  // The 720px case accounts for visible Safari chrome; the short phone catches
  // cramped layouts, and the desktop verifies that the phone rule stays scoped.
  for (const viewport of [{ width: 390, height: 720 }, { width: 430, height: 932 }, { width: 320, height: 568 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    const query = new URLSearchParams({ theme: 'dark', background: '#161616', width: String(viewport.width), chrome: '0', props: JSON.stringify({ serverStatusUrl: '/api/server-status' }) });
    await page.goto(`/dev/preview/landing/LandingPage?${query}`, { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    await expect(page.getByTestId('landing-compose')).toHaveAttribute('href', 'https://app.dev.openmates.org/#compose');
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
          titleLines: rect('#hero-title').height / parseFloat(getComputedStyle(node('#hero-title')).lineHeight),
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
        const bounds = compact
          ? { title: language === 'de' ? [22, 26] : [28, 32], glyph: [50, 58], prompt: [17, 20], speed: [16, 18], icon: [60, 70], cue: [14, 16] }
          : { title: language === 'de' ? [27, 33] : [34, 42], glyph: [68, 90], prompt: [19, 24], speed: [17, 21], icon: [76, 90], cue: [15, 18] };
        for (const [value, range] of [[layout.titleFont, bounds.title], [layout.glyph.width, bounds.glyph], [layout.promptFont, bounds.prompt], [layout.speedFont, bounds.speed], [layout.iconSize, bounds.icon], [layout.cueFont, bounds.cue]] as const) {
          expect(value, 'Phone elements stay readable without becoming oversized').toBeGreaterThanOrEqual(range[0]);
          expect(value, 'Phone elements stay readable without becoming oversized').toBeLessThanOrEqual(range[1]);
        }
        expect(layout.titleLines, 'Both English and German headings fit on two lines').toBeCloseTo(2, 1);
      }
      await expect(page.getByTestId('landing-open-web-app')).toBeVisible();
      await page.mouse.move(1, 1);
      await page.screenshot({ path: testInfo.outputPath(`hero-${viewport.width}x${viewport.height}-${language}.png`) });
    }
  }
  expect(errors).toEqual([]);
});

// contract-test: direct surface=gui.web assertions=marketing-landing.composer-focus
test('composer waits for availability and chooses the free-testing or signup destination', async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 720 });
  const url = '/dev/preview/landing/LandingPage?theme=dark&background=%23161616&width=390&chrome=0';
  let releaseStatus!: () => void;
  const pending = new Promise<void>(resolve => { releaseStatus = resolve; });
  await page.route('**/v1/settings/server-status', async route => {
    await pending;
    await route.fulfill({ json: { anonymous_free_usage: { active: true, can_send_text: true } } });
  });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 30_000);
  const composer = page.getByTestId('landing-compose');
  await expect(composer).toHaveCount(0);
  releaseStatus();
  await expect(composer).toHaveText('Test for free');
  await expect(composer).toHaveAttribute('href', 'https://app.dev.openmates.org/#compose');
  await expect.poll(() => composer.evaluate(element => Number(getComputedStyle(element).opacity))).toBe(1);
  await page.getByTestId('landing-language-button').click();
  await page.getByTestId('landing-language-panel').getByRole('button', { name: 'Deutsch', exact: true }).click();
  await expect(composer).toHaveText('Kostenlos testen');
  await page.screenshot({ path: testInfo.outputPath('composer-free-testing-de.png') });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const state of ['disabled', 'exhausted', 'error', 'timeout'] as const) {
    await page.unroute('**/v1/settings/server-status');
    await page.route('**/v1/settings/server-status', async route => {
      if (state === 'error') return route.abort('failed');
      if (state === 'timeout') return; // Leave the request pending until the bounded check aborts it.
      await route.fulfill({ json: { anonymous_free_usage: { active: state === 'exhausted', can_send_text: false } } });
    });
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    await expect(composer).toHaveText('Jetzt ausprobieren', { timeout: 7000 });
    await expect(composer).toHaveAttribute('href', 'https://app.dev.openmates.org/#signup/basics');
    await expect(composer).toHaveCSS('animation-name', 'none');
  }
  await page.getByTestId('landing-language-button').click();
  await page.getByTestId('landing-language-panel').getByRole('button', { name: 'English', exact: true }).click();
  await expect(composer).toHaveText('Try out now');
  await page.screenshot({ path: testInfo.outputPath('composer-signup-en.png') });
});
