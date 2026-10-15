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
    const marker = getComputedStyle(element, '::before');
    const probe = document.createElement('span');
    probe.style.cssText = 'position:absolute;visibility:hidden;color:var(--color-font-primary);background:rgba(250,204,21,.35);border-radius:2px;padding:0 2px';
    element.append(probe);
    const expected = getComputedStyle(probe);
    const result = {
      actual: { color: getComputedStyle(element).color, background: marker.backgroundColor, radius: marker.borderRadius },
      expected: { color: expected.color, background: expected.backgroundColor, radius: expected.borderRadius },
      position: marker.position, layer: marker.zIndex, transform: marker.transform,
      textBackground: getComputedStyle(element).backgroundColor,
    };
    probe.remove();
    return result;
  });
  expect(styles.actual).toEqual(styles.expected);
  expect(styles.position).toBe('absolute');
  expect(styles.layer).toBe('-1');
  expect(styles.textBackground).toBe('rgba(0, 0, 0, 0)');
  expect(styles.transform).toBe('matrix(1, 0, 0, 1, 0, 0)');
};

const scrollToFeature = async (page: import('@playwright/test').Page, id: string, offset = 0) => {
  await page.getByTestId('landing-scroll-container').evaluate((element, target) => {
    const section = element.querySelector<HTMLElement>(`#${target.id}`)!;
    const top = section.getBoundingClientRect().top - element.getBoundingClientRect().top + element.scrollTop;
    element.scrollTo({ top: top + target.offset, behavior: 'auto' });
  }, { id, offset });
};

const expectSectionAtTop = async (section: import('@playwright/test').Locator) => {
  await expect.poll(() => section.evaluate(element => Math.abs(element.getBoundingClientRect().top - element.closest('.scroll-container')!.getBoundingClientRect().top))).toBeLessThan(3);
};

// Wait for the browser's media change event and the component's subsequent
// frame work. Back-to-back emulation commands can otherwise be coalesced,
// leaving the rail in manual momentum while the test assumes natural drift.
const settleRailMotionPreference = async (page: import('@playwright/test').Page, preference: 'reduce' | 'no-preference') => {
  await page.getByTestId('landing-app-rail').evaluate((element, preference) => {
    element.setAttribute('data-motion-preference-ready', 'pending');
    const query = matchMedia('(prefers-reduced-motion: reduce)');
    const settle = () => requestAnimationFrame(() => requestAnimationFrame(() => {
      element.setAttribute('data-motion-preference-ready', query.matches ? 'reduce' : 'no-preference');
    }));
    if (query.matches === (preference === 'reduce')) settle();
    else query.addEventListener('change', settle, { once: true });
  }, preference);
  await page.emulateMedia({ reducedMotion: preference });
  const rail = page.getByTestId('landing-app-rail');
  await expect(rail).toHaveAttribute('data-motion-preference-ready', preference);
  if (preference === 'reduce') {
    const transforms = await rail.locator('.rail-track').evaluate(async element => {
      const samples: string[] = [];
      for (let frame = 0; frame < 3; frame++) {
        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
        samples.push(getComputedStyle(element).transform);
      }
      return samples;
    });
    expect(new Set(transforms).size).toBe(1);
  }
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
    test.setTimeout(90_000);
    await page.setViewportSize({ width: 820, height: 1180 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto(preview(820), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 60_000);
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
  test(`composer changes its prompt only after three natural app changes (${available ? 'available' : 'unavailable'})`, async ({ page }) => {
    test.setTimeout(60_000);
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
      for (let change = 0; change < 6; change++) {
        await rail.press(direction);
        await expect(composer).toHaveText(primary);
      }
    }
    // Pointer swipes can cross several indices without changing the label.
    const swipeBounds = await rail.boundingBox();
    expect(swipeBounds).not.toBeNull();
    for (let swipe = 0; swipe < 3; swipe++) {
      await page.mouse.move(swipeBounds!.x + swipeBounds!.width * .7, swipeBounds!.y + swipeBounds!.height / 2);
      await page.mouse.down();
      await page.mouse.move(swipeBounds!.x + swipeBounds!.width * .25, swipeBounds!.y + swipeBounds!.height / 2, { steps: 6 });
      await page.mouse.up();
      await expect(composer).toHaveText(primary);
    }
    // Clicking another app and reselecting it are both manual progression.
    for (const index of [2, 4, 6, 6]) {
      await rail.locator('.rail-group:nth-child(2) .rail-icon').nth(index).evaluate((node: HTMLButtonElement) => node.click());
      await expect(composer).toHaveText(primary);
    }
    await rail.evaluate(element => {
      element.setAttribute('data-composer-observations', '[]');
      new MutationObserver(() => {
        const observations = JSON.parse(element.getAttribute('data-composer-observations')!) as { app: string | null; label: string }[];
        observations.push({ app: element.getAttribute('data-active-app'), label: document.querySelector('[data-testid="landing-compose"]')!.textContent!.trim() });
        element.setAttribute('data-composer-observations', JSON.stringify(observations));
      }).observe(element, { attributes: true, attributeFilter: ['data-active-app'] });
    });
    const observations = () => rail.evaluate(element => JSON.parse(element.getAttribute('data-composer-observations')!) as { app: string | null; label: string }[]);
    await settleRailMotionPreference(page, 'no-preference');
    const bounds = await rail.boundingBox();
    expect(bounds).not.toBeNull();
    await page.mouse.move(bounds!.x + bounds!.width * .6, bounds!.y + bounds!.height / 2);
    await page.mouse.wheel(220, 0);
    // One manual wheel gesture coasts across multiple apps. Neither direct
    // movement nor subsequent inertia may consume natural progression counts.
    await expect.poll(async () => (await observations()).length, { timeout: 3500 }).toBeGreaterThanOrEqual(3);
    expect((await observations()).every(item => item.label === primary)).toBe(true);
    await expect(composer).toHaveText(primary);
    // Stop manual momentum via the supported accessibility preference before
    // observing a fresh uninterrupted run of actual automatic app changes.
    await settleRailMotionPreference(page, 'reduce');
    await rail.evaluate(element => element.setAttribute('data-composer-observations', '[]'));
    await settleRailMotionPreference(page, 'no-preference');
    await expect.poll(async () => (await observations()).length, { timeout: 25_000 }).toBeGreaterThanOrEqual(6);
    const natural = (await observations()).slice(0, 6);
    expect(natural.every((item, index) => index === 0 || item.app !== natural[index - 1].app)).toBe(true);
    expect(natural.map(item => item.label)).toEqual([primary, primary, alternative, alternative, alternative, primary]);
    await expect(composer).toHaveAttribute('href', destination);
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
  await expect.poll(() => highlight.evaluate(element => getComputedStyle(element, '::before').transform)).toBe('matrix(1, 0, 0, 1, 0, 0)');
  const markerMotion = await highlight.evaluate(element => {
    const style = getComputedStyle(element, '::before');
    const animation = element.getAnimations({ subtree: true }).find(item =>
      (item.effect as KeyframeEffect | null)?.getKeyframes().some(frame => String(frame.transform).includes('scaleX')));
    return { name: style.animationName, origin: style.transformOrigin, frames: (animation?.effect as KeyframeEffect | null)?.getKeyframes().map(frame => String(frame.transform)) };
  });
  expect(markerMotion.name).toContain('privacy-marker');
  expect(markerMotion.origin).toMatch(/^0px /);
  expect(markerMotion.frames).toEqual(['scaleX(0)', 'scaleX(1)']);
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
  await expect.poll(() => highlight.evaluate(element => getComputedStyle(element, '::before').animationName)).toBe('none');
  await expectSensitiveDataMarker(highlight);
});

for (const width of [390, 1440]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.independent-scroll,marketing-landing.six-feature-viewport
  test(`native free scrolling keeps its reading position and section arrows preserve clearance (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(preview(width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const scroller = page.getByTestId('landing-scroll-container');
    await expect(scroller).toHaveCSS('scroll-snap-type', 'none');
    await expect(scroller).toHaveCSS('overscroll-behavior-y', 'auto');
    const geometry = await scroller.evaluate(element => [...element.querySelectorAll<HTMLElement>('.feature')].map(section => ({ snap: getComputedStyle(section).scrollSnapAlign, bottomPadding: parseFloat(getComputedStyle(section).paddingBottom) })));
    expect(geometry.every(section => section.snap === 'none' && section.bottomPadding >= 112)).toBe(true);
    const modelChoice = page.getByTestId('landing-feature-model-choice');
    await expect(modelChoice.getByTestId('landing-model-selection-link')).toHaveAttribute('href', `${APP}/blog`);
    await expect(modelChoice.getByTestId('landing-data-ownership-link')).toHaveAttribute('href', `${APP}/blog`);
    const feature = page.getByTestId('landing-feature-actionable');
    await scrollToFeature(page, 'actionable', -137);
    const before = await scroller.evaluate(element => element.scrollTop);
    await expect.poll(() => feature.evaluate(element => element.getBoundingClientRect().top - element.closest('.scroll-container')!.getBoundingClientRect().top)).toBeGreaterThan(130);
    // Real WebKit wheel input follows native scrolling. Observe cancellation only;
    // never prevent an event or replace the browser's wheel/momentum behavior.
    await scroller.evaluate(element => {
      element.setAttribute('data-wheel-observed', '0');
      element.setAttribute('data-wheel-cancelled', 'false');
      element.addEventListener('wheel', event => {
        queueMicrotask(() => {
          element.setAttribute('data-wheel-observed', String(Number(element.getAttribute('data-wheel-observed')) + 1));
          if (event.defaultPrevented) element.setAttribute('data-wheel-cancelled', 'true');
        });
      }, { passive: true });
    });
    const bounds = await scroller.boundingBox();
    expect(bounds).not.toBeNull();
    await page.mouse.move(bounds!.x + bounds!.width * .72, bounds!.y + bounds!.height * .65);
    for (const delta of [70, 55, 35]) await page.mouse.wheel(0, delta);
    await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(before + 80);
    await expect.poll(async () => Number(await scroller.getAttribute('data-wheel-observed'))).toBeGreaterThan(0);
    await expect(scroller).toHaveAttribute('data-wheel-cancelled', 'false');
    const positions: number[] = [];
    await expect.poll(async () => {
      positions.push(await scroller.evaluate(element => element.scrollTop));
      return positions.length >= 3 && Math.max(...positions.slice(-3)) - Math.min(...positions.slice(-3)) < 2;
    }, { intervals: [100, 200, 300] }).toBe(true);
    const restingOffset = await feature.evaluate(element => element.getBoundingClientRect().top - element.closest('.scroll-container')!.getBoundingClientRect().top);
    expect(Math.abs(restingOffset)).toBeGreaterThan(5);
    const url = page.url();
    await expect(page.getByTestId('landing-next-section')).toBeVisible();
    await page.getByTestId('landing-next-section').click();
    await expectSectionAtTop(page.getByTestId('landing-feature-privacy'));
    expect(page.url()).toBe(url);
    await page.getByTestId('landing-previous-section').click();
    await expectSectionAtTop(feature);
    expect(page.url()).toBe(url);
    const clearance = await feature.evaluate(element => {
      const root = element.closest('.landing-page')!;
      const heading = element.querySelector('h2')!.getBoundingClientRect();
      const paragraph = element.querySelector('.story-copy p')!.getBoundingClientRect();
      return { headingTop: heading.top, paragraphBottom: paragraph.bottom,
        previousBottom: root.querySelector('[data-testid="landing-previous-section"]')!.getBoundingClientRect().bottom,
        composerTop: root.querySelector('[data-testid="landing-compose"]')!.getBoundingClientRect().top };
    });
    expect(clearance.headingTop).toBeGreaterThan(clearance.previousBottom);
    expect(clearance.paragraphBottom).toBeLessThan(clearance.composerTop);
    // Tall phone sections retain native internal reading space below the fold.
    if (width === 390) {
      const top = await scroller.evaluate(element => element.scrollTop);
      // The preceding click left the pointer on the fixed previous-section
      // button outside the scroller. Send native wheel input over its content.
      await page.mouse.move(bounds!.x + bounds!.width * .72, bounds!.y + bounds!.height * .65);
      await page.mouse.wheel(0, 120);
      await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(top + 80);
    }
    await page.reload({ waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeLessThan(2);
    await expect(page.getByTestId('landing-previous-section')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=marketing-landing.section-stories,marketing-landing.independent-scroll
  test(`section stories show natural requests and clicks, then preserve completed reading views (${width}px)`, async ({ page }) => {
    test.setTimeout(75_000);
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto(preview(width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const actionable = page.getByTestId('landing-feature-actionable');
    const privacy = page.getByTestId('landing-feature-privacy');
    await expect(actionable).toHaveAttribute('data-story-state', 'pending');
    await expect(privacy).toHaveAttribute('data-story-state', 'pending');
    const url = page.url();
    await page.getByTestId('landing-scroll-cue').click();
    await expect(actionable).toHaveAttribute('data-story-state', 'playing');
    const story = actionable.getByTestId('landing-feature-animation');
    await expect(story).toHaveAttribute('data-active-stage', 'user-request');
    await expect(story).toContainText('Find tech events in Berlin');
    await expect(actionable.getByTestId('landing-skip-actionable')).toBeVisible();
    await expect(actionable.locator('.story-copy')).toHaveCount(0);
    await expect(actionable.getByTestId('device-screenshots')).toHaveCount(0);
    await expect(story).toHaveAttribute('data-active-stage', 'assistant-response', { timeout: 4000 });
    await expect(story).toContainText('Of course, here you go:');
    await expect(story).toHaveAttribute('data-active-stage', 'event-preview', { timeout: 4000 });
    await expect(story.getByTestId('landing-actionable-event-preview')).toContainText('DEPIN DAY BERLIN');
    await expect(story).toHaveAttribute('data-interaction-state', 'preview-targeted', { timeout: 2500 });
    await expect(story).toHaveAttribute('data-interaction-state', 'preview-clicked', { timeout: 2000 });
    await expect(story).toHaveAttribute('data-active-stage', 'luma-cta', { timeout: 2500 });
    await expect(story.getByTestId('landing-actionable-luma-button')).toHaveText('Open on Luma');
    await expect(story).toHaveAttribute('data-interaction-state', 'cta-clicked', { timeout: 2200 });
    await expect(actionable).toHaveAttribute('data-story-state', 'complete', { timeout: 2500 });
    await expect(actionable.locator('.story-copy p')).toBeVisible();
    await expect(actionable.getByTestId('device-screenshots')).toBeVisible();
    await expect(actionable.getByTestId('landing-explore-apps')).toHaveAttribute('href', `${APP}/#apps`);
    await expect(story).toHaveCount(0);
    await page.getByTestId('landing-next-section').click();
    await expect(privacy).toHaveAttribute('data-story-state', 'playing');
    await expect(privacy.getByTestId('landing-feature-animation')).toContainText('Only your devices can decrypt all your data.');
    await expect(privacy.locator('.story-copy')).toHaveCount(0);
    await privacy.getByTestId('landing-skip-privacy').click();
    await expect(privacy).toHaveAttribute('data-story-state', 'complete');
    await expect(privacy.locator('.story-copy p')).toBeVisible();
    await expect(privacy.getByTestId('device-screenshots')).toBeVisible();
    await expect(privacy.getByTestId('landing-feature-animation')).toHaveCount(0);
    await page.getByTestId('landing-previous-section').click();
    await expectSectionAtTop(actionable);
    await expect(actionable).toHaveAttribute('data-story-state', 'complete');
    await expect(actionable.getByTestId('landing-skip-actionable')).toHaveCount(0);
    await page.getByTestId('landing-next-section').click();
    await expectSectionAtTop(privacy);
    await expect(privacy).toHaveAttribute('data-story-state', 'complete');
    await expect(privacy.getByTestId('landing-skip-privacy')).toHaveCount(0);
    expect(page.url()).toBe(url);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    await expect.poll(() => page.getByTestId('landing-scroll-container').evaluate(element => element.scrollTop)).toBeLessThan(2);
    await expect(actionable).toHaveAttribute('data-story-state', 'pending');
    await expect(privacy).toHaveAttribute('data-story-state', 'pending');
  });
}

// contract-test: direct surface=gui.web assertions=marketing-landing.section-stories
test('desktop privacy story naturally completes every encryption, PII and permission scene', async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto(preview(1440), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 30_000);
  await scrollToFeature(page, 'privacy');
  const privacy = page.getByTestId('landing-feature-privacy');
  const story = privacy.getByTestId('landing-feature-animation');
  await expect(story).toHaveAttribute('data-active-stage', 'saved-data-copy');
  await expect(story).toHaveAttribute('data-active-stage', 'encryption-lock', { timeout: 3500 });
  await expect(story.locator('.locked')).toBeVisible();
  await expect(story).toHaveAttribute('data-active-stage', 'pii-copy', { timeout: 5000 });
  await expect(story).toHaveAttribute('data-active-stage', 'pii-detection', { timeout: 3500 });
  await expect(story.locator('[data-pii-state]')).toHaveAttribute('data-pii-state', 'highlighted', { timeout: 1500 });
  await expect(story.locator('[data-pii-state]')).toHaveAttribute('data-pii-state', 'placeholder', { timeout: 2000 });
  await expect(story).toContainText('[EMAIL_1]');
  await expect(story).toHaveAttribute('data-active-stage', 'originals-copy', { timeout: 2500 });
  await expect(story).toHaveAttribute('data-active-stage', 'pii-reveal', { timeout: 3500 });
  await expect(story).toContainText('[EMAIL_1]');
  await expect(story.locator('.pii-value.revealed')).toHaveText('alex@example.com', { timeout: 2000 });
  await expect(story).toHaveAttribute('data-active-stage', 'personalized-copy', { timeout: 3000 });
  await expect(story).toHaveAttribute('data-active-stage', 'trip-request', { timeout: 3500 });
  await expect(story).toContainText('Recommended places for my next trip?');
  await expect(story).toHaveAttribute('data-active-stage', 'memory-permission', { timeout: 3500 });
  const permission = story.getByTestId('app-settings-memories-permission-card');
  await expect(permission).toContainText('Include these memories in this chat, for a more personalized response?');
  await expect(permission).toContainText('Trips');
  await expect(privacy).toHaveAttribute('data-story-state', 'complete', { timeout: 5500 });
  await expect(privacy.locator('.story-copy p')).toBeVisible();
  await expect(privacy.getByTestId('device-screenshots')).toBeVisible();
  await expect(story).toHaveCount(0);
});

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
    await expect(page.getByTestId('landing-compose')).toHaveText('Test for free');
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await expect(page.getByTestId('landing-compose')).toHaveText('Tap to ask anything', { timeout: 15_000 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.evaluate(() => localStorage.setItem('preferredLanguage', 'de'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    await expect(page.getByTestId('landing-privacy-highlight')).toHaveText('Privatsphäre');
    await expectSensitiveDataMarker(page.getByTestId('landing-privacy-highlight'));
  });
});
