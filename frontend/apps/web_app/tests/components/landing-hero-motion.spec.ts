import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { landingAppOrder } from '../../../../packages/public-site/src/components/landing/landingPageContent';

// playwright-account: not_required reason=isolated_component_preview
const execFileAsync = promisify(execFile);
const APP = 'https://app.dev.openmates.org';
const preview = (width: number, theme = 'light', props?: object) =>
  `/dev/preview/landing/LandingPage?${new URLSearchParams({ theme, background: theme === 'dark' ? '#161616' : '#dbeafe', ...(width <= 2560 ? { width: String(width) } : {}), chrome: '0', ...(props ? { props: JSON.stringify(props) } : {}) })}`;

test.use({ browserName: 'webkit', launchOptions: { args: [] }, hasTouch: true });
  test.beforeAll(async () => {
    // The isolated component CI image installs Chromium only. Install pinned WebKit
    // before Playwright creates either test's page fixture.
    test.setTimeout(180_000);
    await execFileAsync('npx', ['--no-install', 'playwright', 'install', '--with-deps', 'webkit'], { timeout: 170_000, maxBuffer: 8 * 1024 * 1024 });
  });

  // contract-test: direct surface=gui.web assertions=marketing-landing.hero-app-rail
  test('iPad landing wheel glyphs stay loaded after scrolling away and back', async ({ page }, testInfo) => {
    test.setTimeout(75_000);
    await page.setViewportSize({ width: 820, height: 1180 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto(preview(820), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const rail = page.getByTestId('landing-app-rail');
    const scroller = page.getByTestId('landing-scroll-container');
    const images = rail.locator('.rail-glyph');
    await expect(images).toHaveCount(landingAppOrder.length * 3);
    const loadedImages = async () => images.evaluateAll(nodes => nodes.every(node => {
      const image = node as HTMLImageElement;
      return image.complete && image.naturalWidth > 0 && image.naturalHeight > 0;
    }));
    const visibleGlyphs = async () => rail.evaluate(element => {
      const railRect = element.getBoundingClientRect();
      return [...element.querySelectorAll<HTMLImageElement>('.rail-glyph')].filter(image => {
        const rect = image.getBoundingClientRect();
        const icon = image.closest<HTMLElement>('.rail-icon')!;
        return rect.right > railRect.left + railRect.width * .15 && rect.left < railRect.right - railRect.width * .15 && getComputedStyle(icon).opacity !== '0';
      }).length;
    });
    const capture = async (name: string) => {
      const path = testInfo.outputPath(`${name}.png`);
      await rail.screenshot({ path, animations: 'disabled' });
      await testInfo.attach(name, { path, contentType: 'image/png' });
    };
    for (let cycle = 1; cycle <= 2; cycle++) {
      await expect.poll(loadedImages).toBe(true);
      await expect.poll(visibleGlyphs).toBeGreaterThanOrEqual(3);
      await capture(`ipad-wheel-before-scroll-${cycle}`);
      await scroller.evaluate(element => element.scrollTo({ top: element.clientHeight * 1.5, behavior: 'auto' }));
      await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(800);
      await scroller.evaluate(element => element.scrollTo({ top: 0, behavior: 'auto' }));
      await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeLessThan(2);
      await expect.poll(loadedImages).toBe(true);
      await expect.poll(visibleGlyphs).toBeGreaterThanOrEqual(3);
      await capture(`ipad-wheel-after-scroll-${cycle}`);
    }
  });

// contract-test: direct surface=gui.web assertions=marketing-landing.hero-entrance
test('landing hero entrance staggers its content, settles, and respects reduced motion', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto(preview(1440), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 30_000);
  const root = page.getByTestId('landing-page');
  const composer = page.getByTestId('landing-compose');
  await expect(composer).toBeVisible();
  await expect(composer).toHaveAttribute('href', `${APP}/#compose`);

  const sequence = await root.evaluate(element => {
    const selectors = ['.hero-ai-entrance', '#hero-title', '.hero-prompt-entrance', '.rail-window', '.hero-speed', '.scroll-cue'];
    return selectors.map(selector => {
      const node = element.querySelector<HTMLElement>(selector)!;
      const style = getComputedStyle(node);
      const entrance = node.getAnimations().find(animation => (animation.effect as KeyframeEffect | null)?.getKeyframes().some(frame => String(frame.opacity) === '0'));
      return { delay: parseFloat(style.animationDelay) * 1000, name: style.animationName, keyframes: (entrance?.effect as KeyframeEffect | null)?.getKeyframes().map(frame => String(frame.opacity)) };
    });
  });
  expect(sequence.every(item => item.name.endsWith('hero-entrance'))).toBe(true);
  const firstStage = sequence.slice(0, 2).map(item => item.delay);
  const secondStage = sequence.slice(2, 5).map(item => item.delay);
  expect(Math.max(...firstStage)).toBeLessThan(Math.min(...secondStage));
  expect(sequence[5].delay).toBeGreaterThan(Math.max(...secondStage));
  expect(sequence.every(item => item.keyframes?.[0] === '0' && item.keyframes.at(-1) === '1')).toBe(true);
  await expect(root.locator('#hero-title')).toHaveCSS('opacity', '1');
  await expect(page.getByTestId('landing-prompt')).toHaveCSS('opacity', '1');
  await expect(page.getByTestId('landing-app-rail')).toHaveCSS('opacity', '1');
  await expect(page.getByTestId('landing-scroll-cue')).toHaveCSS('opacity', '1');
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await expect(root).toHaveClass(/hero-entrance-complete/);
  await expect(root.locator('#hero-title')).toHaveCSS('animation-name', 'none');
  await expect(page.getByTestId('landing-prompt')).toHaveCSS('opacity', '1');

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 30_000);
  for (const selector of ['.hero-ai-entrance', '#hero-title', '.hero-prompt-entrance', '.rail-window', '.hero-speed', '.scroll-cue']) {
    await expect(page.getByTestId('landing-page').locator(selector)).toHaveCSS('animation-name', 'none');
    await expect(page.getByTestId('landing-page').locator(selector)).toHaveCSS('opacity', '1');
  }
  await expect(page.getByTestId('landing-compose')).toBeVisible();
});
