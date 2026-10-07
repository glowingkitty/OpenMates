import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');

const APP = 'https://app.dev.openmates.org';
const sections = ['actionable', 'privacy', 'workflows', 'devices', 'open-source'] as const;
const preview = (width: number, theme = 'light') =>
  `/dev/preview/landing/LandingPage?${new URLSearchParams({ theme, background: theme === 'dark' ? '#161616' : '#dbeafe', width: String(width), chrome: '0' })}`;

const proofContract = defineVideoProof({
  id: 'marketing-landing-component',
  title: 'Explore the OpenMates landing page',
  surface: 'web',
  devices: ['web-phone', 'web-laptop'],
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'hero', text: 'The public landing page introduces OpenMates and offers a message composer link.', checkpoint: 'hero', devices: ['web-phone', 'web-laptop'] },
    { id: 'features', text: 'Visitors scroll through five illustrated features with working app and blog destinations.', checkpoint: 'features', devices: ['web-phone', 'web-laptop'] },
    { id: 'publications', text: 'Events, news, and blog links remain available when there are no featured records.', checkpoint: 'publications', devices: ['web-phone', 'web-laptop'] },
  ],
  assertions: [
    { id: 'marketing-landing.independent-scroll', checkpoint: 'features', visual: 'Normal scrolling reveals each feature without automatic transitions.', devices: ['web-phone', 'web-laptop'] },
    { id: 'marketing-landing.feature-layout', checkpoint: 'features', visual: 'Ordered features have distinct visible icons and readable responsive copy and screenshots.', devices: ['web-phone', 'web-laptop'] },
    { id: 'marketing-landing.destinations', checkpoint: 'hero', visual: 'App, signup, blog, and example links have the expected dev destinations.', devices: ['web-phone', 'web-laptop'] },
    { id: 'marketing-landing.real-screenshots', checkpoint: 'features', visual: 'Local product screenshots load and mobile web images have accurate alternative text.', devices: ['web-phone', 'web-laptop'] },
    { id: 'marketing-landing.public-content', checkpoint: 'publications', visual: 'Empty publication rows offer honest browse actions.', devices: ['web-phone', 'web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 3, minimumHoldMs: 900, maximumHoldMs: 2200 },
});

type Rect = { left: number; right: number; top: number; bottom: number };

function intersects(a: Rect, b: Rect): boolean {
  return a.left < b.right - 1 && a.right > b.left + 1 && a.top < b.bottom - 1 && a.bottom > b.top + 1;
}

for (const { device, width, height } of [
  { device: 'web-phone' as const, width: 390, height: 844 },
  { device: 'web-laptop' as const, width: 1440, height: 900 },
]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.independent-scroll,marketing-landing.feature-layout,marketing-landing.destinations,marketing-landing.real-screenshots,marketing-landing.public-content
  test(`visitor explores landing preview (${device})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    const proof = createVideoProofRuntime(proofContract, {
      device,
      attach: testInfo.attach.bind(testInfo),
    });
    await page.goto(preview(width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const root = page.getByTestId('landing-page');
    const viewport = page.getByTestId('landing-viewport-container');
    const scroller = page.getByTestId('landing-scroll-container');
    const compose = page.getByTestId('landing-compose');
    await expect(root).toBeVisible();
    await expect(viewport).toBeVisible();
    await expect(scroller).toBeVisible();
    await expect(root.getByRole('heading', { level: 1 })).toContainText('Your privacy first');
    const firstView = await page.evaluate(() => {
      const viewport = document.querySelector('[data-testid="landing-viewport-container"]')!;
      const scroller = document.querySelector('[data-testid="landing-scroll-container"]')!;
      const hero = document.querySelector('[data-testid="landing-hero"]')!;
      const compose = document.querySelector('[data-testid="landing-compose"]')!;
      return { viewport: viewport.getBoundingClientRect().toJSON(), scroller: scroller.getBoundingClientRect().toJSON(), hero: hero.getBoundingClientRect().toJSON(), compose: compose.getBoundingClientRect().toJSON(), heroHeight: hero.getBoundingClientRect().height, scrollerHeight: scroller.getBoundingClientRect().height };
    });
    expect(firstView.heroHeight).toBeGreaterThanOrEqual(firstView.scrollerHeight - 2);
    expect(firstView.heroHeight).toBeLessThanOrEqual(firstView.scrollerHeight + 2);
    expect(firstView.hero.top).toBeGreaterThanOrEqual(firstView.scroller.top - 2);
    expect(firstView.hero.top).toBeLessThanOrEqual(firstView.scroller.top + 2);
    expect(firstView.compose.bottom).toBeLessThanOrEqual(firstView.viewport.bottom + 1);
    expect(firstView.compose.bottom).toBeLessThanOrEqual(height);
    expect(firstView.compose.bottom).toBeGreaterThan(firstView.viewport.bottom - 100);
    const scrollCue = await root.locator('.scroll-cue').boundingBox();
    expect(scrollCue).not.toBeNull();
    expect(scrollCue!.y + scrollCue!.height).toBeLessThan(firstView.compose.top);

    await proof.assert('marketing-landing.destinations', async () => {
      await expect(page.getByTestId('landing-signup')).toHaveAttribute('href', `${APP}/#signup/basics`);
      await expect(page.getByTestId('landing-compose')).toHaveAttribute('href', `${APP}/#compose`);
      for (const [id, fragment] of [['landing-explore-apps', '#apps'], ['landing-explore-workflows', '#workflows']] as const) {
        const link = page.getByTestId(id);
        await expect(link).toHaveAttribute('href', `${APP}/${fragment}`);
        await expect(link).toHaveAttribute('target', '_blank');
        await expect(link).toHaveAttribute('rel', /noopener/);
        await expect(link).toHaveAttribute('rel', /noreferrer/);
      }
      await expect(page.getByRole('link', { name: /learn more about privacy/i })).toHaveAttribute('href', `${APP}/blog`);
      await expect(page.locator('#actionable .example-link')).toHaveAttribute('href', `${APP}/#chat-id=example-ai-workshops-meetups-berlin`);
      await expect(page.locator('#privacy .example-link')).toHaveAttribute('href', `${APP}/#chat-id=example-plumber-message-email-phone`);
    });
    await page.getByTestId('landing-signup').focus();
    await expect(page.getByTestId('landing-signup')).toBeFocused();
    await expect(page.getByTestId('landing-signup')).toHaveCSS('outline-style', 'solid');
    const hoverBefore = await compose.evaluate(element => getComputedStyle(element).boxShadow);
    await compose.hover();
    expect(await compose.evaluate(element => getComputedStyle(element).boxShadow)).not.toBe(hoverBefore);
    const request = page.locator('.example-prompt[data-active-app]');
    const firstApp = await request.getAttribute('data-active-app');
    await expect(page.locator('.app-rail').first()).toHaveCSS('animation-name', /rail-move-left$/);
    await expect.poll(() => request.getAttribute('data-active-app'), { timeout: 6_000 }).not.toBe(firstApp);
    await expect(request).toContainText(/Find events|Build a web app|Catch up on the news|Find doctor appointments/);
    await proof.checkpoint('hero');

    await proof.assert('marketing-landing.independent-scroll', async () => {
      const initial = await scroller.evaluate(element => element.scrollTop);
      await scroller.evaluate(element => element.scrollTo({ top: element.clientHeight, behavior: 'instant' }));
      await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(initial);
      await page.getByTestId('landing-feature-privacy').scrollIntoViewIfNeeded();
      await expect(page.getByTestId('landing-feature-privacy')).toBeVisible();
      await page.getByTestId('landing-feature-workflows').scrollIntoViewIfNeeded();
      await expect(page.getByTestId('landing-feature-workflows')).toBeVisible();
      expect(await scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(initial);
      expect(await page.evaluate(() => window.scrollY)).toBe(0);
      const fixed = await compose.evaluate(element => element.getBoundingClientRect().toJSON());
      expect(Math.abs(fixed.bottom - firstView.compose.bottom)).toBeLessThanOrEqual(2);
      expect(Math.abs(fixed.top - firstView.compose.top)).toBeLessThanOrEqual(2);
      await scroller.evaluate(element => {
        const target = element.querySelector('#workflows h2')!;
        element.scrollTo({ top: element.scrollTop + target.getBoundingClientRect().top - element.getBoundingClientRect().top - 24, behavior: 'instant' });
      });
      const heading = await page.locator('#workflows h2').evaluate(element => element.getBoundingClientRect().toJSON());
      const composer = await compose.evaluate(element => element.getBoundingClientRect().toJSON());
      expect(heading.bottom).toBeLessThan(composer.top);
    });

    await proof.assert('marketing-landing.feature-layout', async () => {
      const layout = await root.evaluate((element, ids) => {
        const features = ids.map((id: string) => element.querySelector(`[data-testid="landing-feature-${id}"]`) as HTMLElement);
        const boxes = features.map(feature => feature.getBoundingClientRect().toJSON());
        const icons = features.map(feature => {
          const icon = feature.querySelector('.feature-icon') as HTMLElement;
          const mask = getComputedStyle(icon, '::after').maskImage || getComputedStyle(icon, '::after').webkitMaskImage;
          return { mask, width: icon.getBoundingClientRect().width, height: icon.getBoundingClientRect().height };
        });
        const media = features.slice(0, 3).map(feature => {
          const copy = feature.querySelector('.feature-copy')!.getBoundingClientRect().toJSON();
          const pair = feature.querySelector('.screenshot-pair')!.getBoundingClientRect().toJSON();
          const links = [...feature.querySelectorAll('a')].map(link => link.getBoundingClientRect().toJSON());
          return { copy, pair, links };
        });
        return { boxes, icons, media, pageWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth };
      }, sections);
      expect(layout.boxes.every((box: Rect, index: number) => index === 0 || box.top >= layout.boxes[index - 1].bottom - 1)).toBe(true);
      expect(new Set(layout.icons.map((icon: { mask: string }) => icon.mask)).size).toBe(sections.length);
      for (const icon of layout.icons) {
        expect(icon.mask).toMatch(/url\(/);
        expect(icon.mask).not.toBe('none');
        expect(icon.width).toBeGreaterThan(20);
        expect(icon.height).toBeGreaterThan(20);
      }
      for (const { copy, pair, links } of layout.media) {
        expect(intersects(copy, pair)).toBe(false);
        expect(links.every((link: Rect) => !intersects(link, pair))).toBe(true);
        if (device === 'web-phone') expect(pair.top).toBeGreaterThanOrEqual(copy.bottom - 1);
        else expect(pair.left).toBeGreaterThanOrEqual(copy.right - 1);
      }
      expect(layout.pageWidth).toBeLessThanOrEqual(layout.clientWidth + 1);
      for (const id of sections) {
        const feature = page.getByTestId(`landing-feature-${id}`);
        const heading = feature.getByRole('heading');
        await scroller.evaluate((element, selector) => {
          const target = element.querySelector(selector)!;
          element.scrollTo({ top: element.scrollTop + target.getBoundingClientRect().top - element.getBoundingClientRect().top - 24, behavior: 'instant' });
        }, `#${id} h2`);
        const headingRect = await heading.evaluate(element => element.getBoundingClientRect().toJSON());
        const composerRect = await compose.evaluate(element => element.getBoundingClientRect().toJSON());
        expect(headingRect.top).toBeGreaterThanOrEqual(firstView.scroller.top - 1);
        expect(headingRect.bottom).toBeLessThan(composerRect.top);
        const firstLink = feature.getByRole('link').first();
        await scroller.evaluate((element, selector) => {
          const target = element.querySelector(selector)!;
          element.scrollTo({ top: element.scrollTop + target.getBoundingClientRect().top - element.getBoundingClientRect().top - 24, behavior: 'instant' });
        }, `#${id} a`);
        const linkRect = await firstLink.evaluate(element => element.getBoundingClientRect().toJSON());
        expect(linkRect.top).toBeGreaterThanOrEqual(firstView.scroller.top - 1);
        expect(linkRect.bottom).toBeLessThan(composerRect.top);
      }
    });

    await proof.assert('marketing-landing.real-screenshots', async () => {
      const images = root.locator('img[src^="/landing/screenshots/"]');
      await expect(images).toHaveCount(8);
      for (const image of await images.all()) {
        await image.scrollIntoViewIfNeeded();
        await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true);
        const alt = await image.getAttribute('alt');
        expect(alt?.trim()).toBeTruthy();
        expect(alt).not.toMatch(/iPhone app|native iPhone/i);
      }
    });
    await page.getByTestId('landing-feature-open-source').scrollIntoViewIfNeeded();
    await proof.checkpoint('features');

    await proof.assert('marketing-landing.public-content', async () => {
      for (const [heading, browse] of [
        [/Upcoming free.*OpenMates events/i, 'Browse events'],
        [/Latest OpenMates.*news/i, 'Browse news'],
        [/Blog posts/i, 'Browse the blog'],
      ] as const) {
        const row = root.locator('.publication-row').filter({ has: page.getByRole('heading', { name: heading }) });
        await expect(row).toBeVisible();
        await expect(row.getByRole('link', { name: browse })).toBeVisible();
        await expect(row.locator('.publication-card')).toHaveCount(0);
        await expect(row.locator('.empty-publication')).toBeVisible();
      }
      await expect(root.getByRole('link', { name: 'Browse events' })).toHaveAttribute('href', `${APP}/events`);
    });
    await root.locator('.publication-row').last().scrollIntoViewIfNeeded();
    await proof.checkpoint('publications');
    await proof.attach();
  });
}

// contract-test: direct surface=gui.web assertions=marketing-landing.feature-layout
test('landing remains readable at 320px and in dark mode', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(preview(320), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 30_000);
  const root = page.getByTestId('landing-page');
  await expect(root).toBeVisible();
  await expect(root.locator('.example-prompt')).toHaveText('Find doctor appointments');
  await expect(root.locator('.app-rail').first()).toHaveCSS('animation-name', 'none');
  for (const id of sections) await expect(page.getByTestId(`landing-feature-${id}`)).toBeVisible();
  const phoneGeometry = await root.evaluate(element => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    innerScrollWidth: element.querySelector('[data-testid="landing-scroll-container"]')!.scrollWidth,
    innerClientWidth: element.querySelector('[data-testid="landing-scroll-container"]')!.clientWidth,
    links: [...element.querySelectorAll('a')].map(link => ({ left: link.getBoundingClientRect().left, right: link.getBoundingClientRect().right })),
  }));
  expect(phoneGeometry.scrollWidth).toBeLessThanOrEqual(phoneGeometry.clientWidth + 1);
  expect(phoneGeometry.innerScrollWidth).toBeLessThanOrEqual(phoneGeometry.innerClientWidth + 1);
  expect(phoneGeometry.links.every(link => link.left >= -1 && link.right <= 321)).toBe(true);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(preview(390, 'dark'), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 30_000);
  await expect(root.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByTestId('landing-feature-privacy').getByRole('heading')).toBeVisible();
  const darkColors = await root.evaluate(element => {
    const title = element.querySelector('#privacy h2')!;
    const titleStyle = getComputedStyle(title);
    const rootStyle = getComputedStyle(element);
    return { foreground: titleStyle.color, background: rootStyle.backgroundColor };
  });
  expect(darkColors.foreground).not.toBe(darkColors.background);
});
