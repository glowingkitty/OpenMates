import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { landingAppOrder } from '../../../../packages/public-site/src/components/landing/landingPageContent';

test.beforeEach(async ({ page }) => {
  await page.route('**/v1/settings/server-status', route => route.fulfill({
    json: { anonymous_free_usage: { active: true, can_send_text: true } },
  }));
});

// playwright-account: not_required reason=isolated_component_preview
const execFileAsync = promisify(execFile);
const APP = 'https://app.dev.openmates.org';

const expectSensitiveDataMarker = async (highlight: import('@playwright/test').Locator) => {
  const styles = await highlight.evaluate(element => {
    const probe = document.createElement('span');
    probe.style.cssText = 'position:absolute;visibility:hidden;color:var(--color-font-primary);background-image:linear-gradient(rgba(250,204,21,.35),rgba(250,204,21,.35));border-radius:2px;padding:0 2px';
    element.append(probe);
    const read = (node: Element) => {
      const style = getComputedStyle(node);
      return { color: style.color, background: style.backgroundImage, radius: style.borderRadius, padding: style.padding };
    };
    const result = { actual: read(element), expected: read(probe) };
    probe.remove();
    return result;
  });
  expect(styles.actual).toEqual(styles.expected);
};

const preview = (width: number, theme = 'light', props?: object) =>
  `/dev/preview/landing/LandingPage?${new URLSearchParams({ theme, background: theme === 'dark' ? '#161616' : '#dbeafe', ...(width <= 2560 ? { width: String(width) } : {}), chrome: '0', ...(props ? { props: JSON.stringify(props) } : {}) })}`;

test.use({ browserName: 'webkit', launchOptions: { args: [] }, hasTouch: false });
  test.beforeAll(async () => {
    // The isolated component CI image installs Chromium only. Install pinned WebKit
    // before Playwright creates either test's page fixture.
    test.setTimeout(180_000);
    await execFileAsync('npx', ['--no-install', 'playwright', 'install', '--with-deps', 'webkit'], { timeout: 170_000, maxBuffer: 8 * 1024 * 1024 });
  });

test.describe('iPad scrolling', () => {
  test.use({ hasTouch: true });
  // contract-test: direct surface=gui.web assertions=marketing-landing.hero-app-rail
  test('iPad landing native glyphs stay rendered after scrolling away and back', async ({ page }, testInfo) => {
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
      await page.getByTestId('landing-page').screenshot({ path, animations: 'disabled' });
      await testInfo.attach(name, { path, contentType: 'image/png' });
    };
    const nativeGlyphs = async () => page.getByTestId('landing-page').evaluate(element => {
      const selectors = ['.hero-ai-glyph svg', '.composer-ai svg', '.composer-mic svg', '.github-link svg', '.language-button svg'];
      return selectors.map(selector => {
        const svg = element.querySelector<SVGSVGElement>(selector);
        if (!svg) return { selector, painted: false };
        const rect = svg.getBoundingClientRect();
        const bounds = svg.getBBox();
        const paths = [...svg.querySelectorAll<SVGPathElement>('path')];
        const fillPaints = paths.every(path => {
          const fill = getComputedStyle(path).fill;
          if (fill === 'none' || fill === 'rgba(0, 0, 0, 0)') return false;
          if (!fill.includes('url(')) return true;
          const id = fill.match(/#([^"')]+)/)?.[1];
          return !!id && !!document.getElementById(id)?.querySelector('stop');
        });
        return { selector, painted: rect.width > 0 && rect.height > 0 && bounds.width > 0 && bounds.height > 0 && paths.length > 0 && fillPaints && getComputedStyle(svg).visibility === 'visible' };
      });
    });
    const expectNativeGlyphs = async () => {
      await expect.poll(async () => (await nativeGlyphs()).every(glyph => glyph.painted)).toBe(true);
    };
    for (let cycle = 1; cycle <= 2; cycle++) {
      await expect.poll(loadedImages).toBe(true);
      await expect.poll(visibleGlyphs).toBeGreaterThanOrEqual(3);
      await expectNativeGlyphs();
      await capture(`ipad-native-icons-before-scroll-${cycle}`);
      await scroller.evaluate(element => element.scrollTo({ top: element.clientHeight * 1.5, behavior: 'auto' }));
      await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(800);
      await scroller.evaluate(element => element.scrollTo({ top: 0, behavior: 'auto' }));
      await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeLessThan(2);
      await expect.poll(loadedImages).toBe(true);
      await expect.poll(visibleGlyphs).toBeGreaterThanOrEqual(3);
      await expectNativeGlyphs();
      await capture(`ipad-native-icons-after-scroll-${cycle}`);
    }
  });

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

for (const available of [true, false]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.composer-focus
  test(`composer changes its prompt after three actual app changes (${available ? 'available' : 'unavailable'})`, async ({ page }) => {
    await page.route('**/v1/settings/server-status', route => route.fulfill({ json: { anonymous_free_usage: { active: available, can_send_text: available } } }));
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(preview(1440), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const rail = page.getByTestId('landing-app-rail');
    const composer = page.getByTestId('landing-compose');
    const primary = available ? 'Test for free' : 'Try out now';
    const destination = `${APP}/${available ? '#compose' : '#signup/basics'}`;
    await expect(composer).toHaveText(primary);
    await expect(composer).toHaveAttribute('href', destination);
    const touch = await page.evaluate(() => matchMedia('(pointer: coarse)').matches || navigator.maxTouchPoints > 0);
    const alternative = `${touch ? 'Tap' : 'Click'} to ask anything`;
    await rail.focus();
    for (const direction of ['ArrowRight', 'ArrowLeft']) {
      await rail.press(direction);
      await expect(composer).toHaveText(direction === 'ArrowRight' ? primary : alternative);
      const active = await rail.getAttribute('data-active-app');
      // Selecting the current app must not consume another change.
      await rail.locator(`.rail-group:nth-child(2) [data-app-id="${active}"]`).evaluate((node: HTMLButtonElement) => node.click());
      await expect(composer).toHaveText(direction === 'ArrowRight' ? primary : alternative);
      await rail.press(direction);
      await expect(composer).toHaveText(direction === 'ArrowRight' ? primary : alternative);
      await rail.press(direction);
      await expect(composer).toHaveText(direction === 'ArrowRight' ? alternative : primary);
      await expect(composer).toHaveAttribute('href', destination);
    }
    await expect(composer.locator('.composer-ai svg path')).toHaveCount(1);
    await expect(composer.locator('.composer-mic svg linearGradient stop')).toHaveCount(2);
    const colors = await composer.evaluate(element => {
      const probe = document.createElement('span');
      probe.style.color = 'var(--color-font-tertiary)';
      element.append(probe);
      const expected = getComputedStyle(probe).color;
      const actual = getComputedStyle(element.querySelector('.composer-label')!).color;
      probe.remove();
      return { expected, actual };
    });
    expect(colors.actual).toBe(colors.expected);
  });
}

// contract-test: direct surface=gui.web assertions=marketing-landing.hero-entrance,marketing-landing.independent-scroll
test('hero privacy marker settles accessibly and browser return restarts rendering', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.context().route('https://events.example.test/return-preview', route => route.fulfill({ contentType: 'text/html', body: '<h1>Event details</h1>' }));
  await page.goto(preview(1440, 'light', { events: [{ id: 'return-event', title: 'Event details', href: 'https://events.example.test/return-preview' }] }), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 30_000);
  const highlight = page.getByTestId('landing-privacy-highlight');
  await expect(highlight).toHaveText('privacy first');
  await expect.poll(() => highlight.evaluate(element => getComputedStyle(element).backgroundSize)).toBe('100% 100%');
  await expectSensitiveDataMarker(highlight);
  const scroller = page.getByTestId('landing-scroll-container');
  await expect(page.getByTestId('landing-hero-media')).toHaveCSS('transform', 'none');
  await scroller.evaluate(element => element.scrollTo({ top: element.clientHeight, behavior: 'auto' }));
  const section = page.getByTestId('landing-feature-actionable');
  await expect(section).toHaveClass(/revealed/);
  await expect(page.getByTestId('landing-hero-media')).toHaveCSS('transform', 'none');
  // Exercise the reported external event link and return to the landing page.
  const eventLink = page.getByTestId('landing-event-card');
  await eventLink.scrollIntoViewIfNeeded();
  const popupPromise = page.waitForEvent('popup');
  await eventLink.click();
  const popup = await popupPromise;
  await popup.waitForLoadState('domcontentloaded');
  await popup.bringToFront();
  await popup.close();
  await page.bringToFront();
  await scroller.evaluate(element => element.scrollTo({ top: element.clientHeight, behavior: 'auto' }));
  await expect(section.locator('.feature-copy h2')).toHaveCSS('opacity', '1');
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true })));
  await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
  const rail = page.getByTestId('landing-app-rail');
  const active = await rail.getAttribute('data-active-app');
  await expect.poll(() => rail.getAttribute('data-active-app'), { timeout: 7000 }).not.toBe(active);
  await scroller.evaluate(element => element.scrollTo({ top: element.clientHeight * 2, behavior: 'auto' }));
  await expect(page.getByTestId('landing-feature-privacy')).toHaveClass(/revealed/);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(highlight).toHaveCSS('animation-name', 'none');
  await expect(highlight).toHaveCSS('background-size', '100% 100%');
});

for (const width of [390, 1440]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.independent-scroll,marketing-landing.six-feature-viewport
  test(`native section settling reserves composer space and leaves tall sections scrollable (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(preview(width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const scroller = page.getByTestId('landing-scroll-container');
    const expectedSnapType = await scroller.evaluate(element => {
      // Browsers can omit the default proximity keyword when serializing CSSOM.
      // Compare explicit proximity using the same engine, still rejecting mandatory.
      const probe = document.createElement('div');
      probe.style.cssText = 'position:absolute;visibility:hidden;scroll-snap-type:y proximity';
      element.append(probe);
      const expected = getComputedStyle(probe).scrollSnapType;
      probe.remove();
      return expected;
    });
    await expect(scroller).toHaveCSS('scroll-snap-type', expectedSnapType);
    const modelChoice = page.getByTestId('landing-feature-model-choice');
    await expect(modelChoice.getByTestId('landing-model-selection-link')).toHaveAttribute('href', `${APP}/blog`);
    await expect(modelChoice.getByTestId('landing-data-ownership-link')).toHaveAttribute('href', `${APP}/blog`);
    const geometry = await scroller.evaluate(element => [...element.querySelectorAll<HTMLElement>('.feature')].map(section => ({ height: section.offsetHeight, viewport: element.clientHeight, snap: getComputedStyle(section).scrollSnapAlign, bottomPadding: parseFloat(getComputedStyle(section).paddingBottom) })));
    expect(geometry.every(section => section.bottomPadding >= 112)).toBe(true);
    for (const section of geometry) expect(section.snap).toBe(section.height <= section.viewport + 1 ? 'start' : 'none');
    const feature = page.getByTestId('landing-feature-actionable');
    await scroller.evaluate(element => {
      const section = element.querySelector<HTMLElement>('#actionable')!;
      element.scrollTo({ top: section.offsetTop - element.offsetTop - 20, behavior: 'auto' });
    });
    if (geometry[0].snap === 'start') {
      await expect.poll(() => feature.evaluate(element => Math.abs(element.getBoundingClientRect().top - element.closest('.scroll-container')!.getBoundingClientRect().top))).toBeLessThan(2);
      const bounds = await feature.evaluate(element => ({ copy: element.querySelector('.feature-copy')!.getBoundingClientRect().bottom, composer: document.querySelector('[data-testid="landing-compose"]')!.getBoundingClientRect().top }));
      expect(bounds.copy).toBeLessThan(bounds.composer);
    } else {
      const before = await scroller.evaluate(element => element.scrollTop);
      await scroller.evaluate(element => element.scrollBy({ top: 100, behavior: 'auto' }));
      await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(before + 90);
    }
  });
}

test.describe('touch landing composer', () => {
  test.use({ hasTouch: true });
  // contract-test: direct surface=gui.web assertions=marketing-landing.composer-focus,marketing-landing.hero-entrance
  test('touch input uses Tap and German highlights only Privatsphäre', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(preview(390), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const rail = page.getByTestId('landing-app-rail');
    await rail.focus();
    for (let change = 0; change < 3; change++) await rail.press('ArrowRight');
    await expect(page.getByTestId('landing-compose')).toHaveText('Tap to ask anything');
    await page.evaluate(() => localStorage.setItem('preferredLanguage', 'de'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    await expect(page.getByTestId('landing-privacy-highlight')).toHaveText('Privatsphäre');
    await expectSensitiveDataMarker(page.getByTestId('landing-privacy-highlight'));
  });
});
