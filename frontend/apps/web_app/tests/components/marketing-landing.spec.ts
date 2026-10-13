import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { landingAppOrder, landingAppExamples } from '../../../../packages/public-site/src/components/landing/landingPageContent';

// playwright-account: not_required reason=isolated_component_preview

const APP = 'https://app.dev.openmates.org';
const sections = ['actionable', 'privacy', 'model-choice', 'workflows', 'devices', 'open-source'] as const;
const preview = (width: number, theme = 'light', props?: object) =>
  `/dev/preview/landing/LandingPage?${new URLSearchParams({ theme, background: theme === 'dark' ? '#161616' : '#dbeafe', width: String(width), chrome: '0', ...(props ? { props: JSON.stringify(props) } : {}) })}`;

for (const { width, height } of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.independent-scroll,marketing-landing.feature-layout,marketing-landing.destinations,marketing-landing.real-screenshots,marketing-landing.hero-app-rail,marketing-landing.six-feature-viewport,marketing-landing.capability-rail-and-prompts
  test(`landing hero and illustrated sections remain usable (${width}px)`, async ({ page }, testInfo) => {
    test.setTimeout(75_000);
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto(preview(width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const root = page.getByTestId('landing-page');
    const scroller = page.getByTestId('landing-scroll-container');
    const compose = page.getByTestId('landing-compose');
    await expect(root).toBeVisible();
    const deferredFeature = page.getByTestId('landing-feature-privacy');
    await expect(deferredFeature).toHaveClass(/reveal-ready/);
    await expect(deferredFeature).not.toHaveClass(/revealed/);
    await expect(deferredFeature.locator('.feature-copy h2')).toHaveCSS('opacity', '0');
    await expect(deferredFeature.locator('.feature-example')).toHaveCSS('opacity', '0');
    const newsletter = page.getByTestId('landing-newsletter-reveal');
    await expect(newsletter).toHaveClass(/reveal-ready/);
    await expect(newsletter).not.toHaveClass(/revealed/);
    await expect(newsletter).toHaveCSS('opacity', '0');
    for (const id of ['landing-events', 'landing-news', 'landing-blog']) {
      const row = page.getByTestId(id);
      await expect(row).toHaveClass(/reveal-ready/);
      await expect(row).not.toHaveClass(/revealed/);
      await expect(row.locator('.publication-intro')).toHaveCSS('opacity', '0');
    }
    await expect(root.getByTestId('public-site-header').locator('.wordmark')).toHaveAttribute('href', `${APP}/`);
    const geometry = await root.evaluate(element => {
      const rect = (id: string) => element.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect().toJSON();
      return { hero: rect('landing-hero'), viewport: rect('landing-viewport-container'), scroller: rect('landing-scroll-container'), compose: rect('landing-compose'), cue: rect('landing-scroll-cue') };
    });
    expect(Math.abs(geometry.hero.height - geometry.scroller.height)).toBeLessThan(2);
    expect(geometry.hero.top).toBeGreaterThanOrEqual(geometry.scroller.top - 1);
    const visualSlot = (await page.getByTestId('landing-hero-media').boundingBox())!;
    const aiVisual = page.getByTestId('landing-hero-ai-icon');
    const iconBox = (await aiVisual.boundingBox())!;
    expect(visualSlot.height).toBeGreaterThan(0);
    expect(iconBox.height).toBeLessThanOrEqual(visualSlot.height + 1);
    const titleTop = (await root.locator('#hero-title').boundingBox())!.y;
    expect(iconBox.y).toBeGreaterThanOrEqual(geometry.hero.top - 1);
    expect(iconBox.y + iconBox.height).toBeLessThanOrEqual(titleTop + 1);
    expect(titleTop - (iconBox.y + iconBox.height), 'AI icon and title must stay together without a large empty gap').toBeLessThanOrEqual(32);
    await expect(aiVisual).toHaveAttribute('aria-hidden', 'true');
    await expect(page.getByTestId('landing-hero-media').locator('.device-frame')).toHaveCount(0);
    expect(await aiVisual.locator('.hero-ai-glyph').evaluate(element => getComputedStyle(element).maskImage)).toContain('/icons/ai.svg');
    await expect(aiVisual).toHaveCSS('animation-name', /hero-ai-float$/);
    expect(geometry.cue.bottom).toBeLessThan(geometry.compose.top);
    const cueCenters = await page.getByTestId('landing-scroll-cue').locator('svg, span').evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect();
      return box.top + box.height / 2;
    }));
    expect(Math.max(...cueCenters) - Math.min(...cueCenters)).toBeLessThan(1);
    expect(geometry.compose.bottom).toBeLessThanOrEqual(height);
    expect(geometry.compose.bottom).toBeGreaterThan(geometry.viewport.bottom - 100);
    for (const [id, fragment] of [['chats', ''], ['apps', '#apps'], ['workflows', '#workflows']] as const) {
      const link = page.getByTestId(`landing-nav-${id}`);
      await expect(link).toHaveAttribute('href', `${APP}/${fragment}`);
      await expect(link).not.toHaveAttribute('aria-current');
      await expect(link.locator('.header-mask')).toBeVisible();
      expect((await link.innerText()).trim()).toBe('');
      const tab = await link.boundingBox();
      const icon = await link.locator('.header-mask').boundingBox();
      expect(tab?.width).toBeCloseTo(72, 0);
      expect(tab?.height).toBeCloseTo(44.8, 0);
      expect(icon?.width).toBe(20);
      expect(icon?.height).toBe(20);
    }
    await expect(root.locator('.menu-link, .settings-link')).toHaveCount(0);
    await expect(page.getByTestId('landing-signup')).toHaveAttribute('href', `${APP}/#signup/basics`);
    expect((await page.getByTestId('landing-signup').boundingBox())?.height).toBe(41);
    await expect(compose).toHaveAttribute('href', `${APP}/#compose`);
    for (const id of ['landing-explore-apps', 'landing-explore-workflows']) {
      await expect(page.getByTestId(id)).toHaveAttribute('target', '_blank');
      await expect(page.getByTestId(id)).toHaveAttribute('rel', /noopener/);
    }
    await page.getByTestId('landing-signup').focus();
    await expect(page.getByTestId('landing-signup')).toBeFocused();
    await expect(page.getByTestId('landing-signup')).toHaveCSS('outline-style', 'solid');
    const shadow = await compose.evaluate(element => getComputedStyle(element).boxShadow);
    await compose.hover();
    expect(await compose.evaluate(element => getComputedStyle(element).boxShadow)).not.toBe(shadow);

    const groups = page.getByTestId('landing-rail-group');
    await expect(groups).toHaveCount(3);
    expect(await groups.nth(1).locator('[data-app-id]').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-app-id')))).toEqual(landingAppOrder);
    for (const id of ['plans', 'plan', 'reminders', 'reminder', 'workflows', 'workflow']) expect(landingAppOrder).not.toContain(id);
    await expect(groups.nth(1).locator('.rail-icon')).toHaveCount(landingAppOrder.length);
    for (const icon of await groups.nth(1).locator('.rail-icon').all()) {
      const id = await icon.getAttribute('data-app-id');
      await expect(icon).toHaveAttribute('type', 'button');
      await expect(icon).toHaveAttribute('aria-label', `Show ${id} example`);
    }
    const railGeometry = await groups.nth(1).locator('.rail-icon').evaluateAll(nodes => nodes.map(node => {
      const rect = node.getBoundingClientRect();
      const glyph = node.querySelector<HTMLElement>('.rail-glyph')!;
      const glyphRect = glyph.getBoundingClientRect();
      const style = getComputedStyle(glyph);
      return { id: node.getAttribute('data-app-id'), centerY: rect.y + rect.height / 2, width: rect.width, height: rect.height, baseWidth: parseFloat(getComputedStyle(node).width), radius: getComputedStyle(node).borderTopLeftRadius, glyphWidth: glyphRect.width, glyphHeight: glyphRect.height, glyphOffsetX: glyphRect.x + glyphRect.width / 2 - (rect.x + rect.width / 2), glyphOffsetY: glyphRect.y + glyphRect.height / 2 - (rect.y + rect.height / 2), glyphColor: style.backgroundColor, mask: style.maskImage || style.webkitMaskImage };
    }));
    expect(Math.max(...railGeometry.map(icon => icon.centerY)) - Math.min(...railGeometry.map(icon => icon.centerY))).toBeLessThan(2);
    expect(railGeometry.every(icon => icon.width >= 60 && icon.width <= 122 && icon.mask.includes('url('))).toBe(true);
    const nonSquareIcons = railGeometry.filter(icon => Math.abs(icon.width - icon.height) >= 1);
    expect(nonSquareIcons, `App icons must be square: ${JSON.stringify(nonSquareIcons)}`).toEqual([]);
    const glyphDefects = railGeometry.filter(icon => icon.glyphWidth < (width < 760 ? 20 : 30) || icon.glyphHeight < (width < 760 ? 20 : 30) || Math.abs(icon.glyphWidth / icon.width - 0.53) > 0.02 || Math.abs(icon.glyphHeight / icon.height - 0.53) > 0.02 || Math.abs(icon.glyphOffsetX) > 1 || Math.abs(icon.glyphOffsetY) > 1 || icon.glyphColor === 'rgba(0, 0, 0, 0)' || !icon.mask.includes('url('));
    expect(glyphDefects, `Rendered app glyph geometry: ${JSON.stringify(glyphDefects)}`).toEqual([]);
    expect(railGeometry.every(icon => icon.radius === `${Math.round(icon.baseWidth * 0.25)}px`)).toBe(true);
    for (const path of ['/icons/event.svg', '/icons/travel.svg']) {
      const response = await page.request.get(new URL(path, page.url()).toString());
      expect(response.ok()).toBe(true);
      expect(response.headers()['content-type']).toMatch(/image\/svg\+xml/);
      expect(await response.text()).toMatch(/<svg\b/);
    }
    const prompt = page.getByTestId('landing-prompt');
    await expect(prompt).toHaveCSS('opacity', '1');
    await expect(prompt).not.toContainText('↗');
    const initialPrompt = await prompt.evaluate((element) => ({ id: (element as HTMLElement).dataset.activeApp, href: element.getAttribute('href'), target: element.getAttribute('target') }));
    const initialApp = initialPrompt.id;
    if (initialApp && landingAppExamples[initialApp]) {
      expect(initialPrompt.href).toBe(`${APP}/#chat-id=${landingAppExamples[initialApp]}`);
      expect(initialPrompt.target).toBe('_blank');
    }
    await expect.poll(() => page.getByTestId('landing-prompt').getAttribute('data-active-app'), { timeout: 7_000 }).not.toBe(initialApp);
    await expect(page.getByTestId('landing-app-rail')).toHaveAttribute('data-active-app', (await page.getByTestId('landing-prompt').getAttribute('data-active-app'))!);
    const promptStyle = await page.getByTestId('landing-prompt').evaluate(element => ({ tail: getComputedStyle(element, '::after').maskImage, origin: getComputedStyle(element).transformOrigin }));
    expect(promptStyle.tail).toContain('url(');
    expect(promptStyle.origin).not.toBe('0px 0px');
    await prompt.evaluate(async element => {
      await Promise.all(element.getAnimations().map(animation => animation.finished.catch(() => undefined)));
    });
    await expect(prompt).toHaveCSS('opacity', '1');
    const background = await prompt.evaluate(element => getComputedStyle(element).backgroundColor);
    expect(background).toMatch(/^rgb\(\d+, \d+, \d+\)$/);
    const [bubbleBox, speedBox, railBox] = await Promise.all([
      prompt.boundingBox(), page.getByTestId('landing-hero-speed').boundingBox(), page.getByTestId('landing-app-rail').boundingBox(),
    ]);
    expect(bubbleBox && speedBox && railBox).toBeTruthy();
    expect(speedBox!.y).toBeGreaterThanOrEqual(bubbleBox!.y + bubbleBox!.height - 1);
    expect(speedBox!.y + speedBox!.height).toBeLessThanOrEqual(railBox!.y + 1);
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.mouse.move(1, 1);
    await expect.poll(() => compose.evaluate(element => getComputedStyle(element).boxShadow)).toBe(shadow);
    await expect(prompt).toHaveCSS('opacity', '1');
    await page.screenshot({ path: testInfo.outputPath(`landing-hero-${width}.png`) });

    // A full-cycle manual move must render the same icons at the same coordinates.
    const seamOffset = await page.getByTestId('landing-app-rail').evaluate(element => {
      const group = element.querySelector<HTMLElement>('.rail-group:nth-child(2)')!;
      const first = group.querySelector<HTMLElement>('.rail-icon')!;
      const before = first.getBoundingClientRect().x;
      element.dispatchEvent(new WheelEvent('wheel', { deltaX: group.getBoundingClientRect().width, bubbles: true, cancelable: true }));
      return Math.abs(first.getBoundingClientRect().x - before);
    });
    expect(seamOffset).toBeLessThan(2);

    const icons: string[] = [];
    for (const id of sections) {
      const section = page.getByTestId(`landing-feature-${id}`);
      await section.scrollIntoViewIfNeeded();
      await expect(section.getByRole('heading')).toBeVisible();
      await expect(section).toHaveClass(/revealed/);
      if (id === 'privacy') {
        await expect(section.locator('.feature-icon')).toHaveCSS('opacity', '1');
        await expect(section.locator('.feature-copy h2')).toHaveCSS('opacity', '1');
        await expect(section.locator('.feature-copy p')).toHaveCSS('opacity', '1');
        await expect(section.locator('.feature-copy .text-link').first()).toHaveCSS('opacity', '1');
        await expect(section.locator('.feature-example')).toHaveCSS('opacity', '1');
        await expect(section.locator('.feature-example')).toHaveCSS('transform', 'none');
      }
      expect((await section.boundingBox())!.height).toBeGreaterThanOrEqual(geometry.scroller.height - 1);
      const media = section.getByTestId(`landing-feature-media-${id}`);
      await expect(media).toHaveCSS('transform', 'none');
      const copyRect = await section.locator('.feature-copy').boundingBox();
      const mediaRect = await media.boundingBox();
      expect(copyRect).not.toBeNull(); expect(mediaRect).not.toBeNull();
      if (width < 760) expect(mediaRect!.y).toBeGreaterThanOrEqual(copyRect!.y + copyRect!.height - 1);
      else expect(mediaRect!.x).toBeGreaterThanOrEqual(copyRect!.x + copyRect!.width - 1);
      const exampleLink = media.locator('.example-link');
      if (await exampleLink.count()) {
        const linkRect = (await exampleLink.boundingBox())!;
        const scrollerRect = (await scroller.boundingBox())!;
        expect(linkRect.x).toBeGreaterThanOrEqual(scrollerRect.x - 1);
        expect(linkRect.x + linkRect.width).toBeLessThanOrEqual(scrollerRect.x + scrollerRect.width + 1);
      }
      icons.push(await section.getByTestId('landing-feature-icon').evaluate(element => getComputedStyle(element).maskImage));
      for (const image of await media.locator('img.device-screen:visible').all()) {
        await image.scrollIntoViewIfNeeded();
        await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true);
        expect((await image.getAttribute('alt'))?.trim()).toBeTruthy();
      }
      await expect(media.locator('.device-frame.phone')).toHaveCount(1);
      await expect(media.locator('.device-frame.laptop')).toHaveCount(1);
      await expect(media.locator('.device-frame.phone')).toBeVisible();
      if (width < 760) await expect(media.locator('.device-frame.laptop')).toBeHidden();
      else await expect(media.locator('.device-frame.laptop')).toBeVisible();
    }
    expect(new Set(icons).size).toBeGreaterThanOrEqual(5);
    expect(icons.every(icon => icon.includes('url('))).toBe(true);
    await newsletter.scrollIntoViewIfNeeded();
    await expect(newsletter).toHaveClass(/revealed/);
    await expect(newsletter).toHaveCSS('opacity', '1');
    await expect(newsletter).toHaveCSS('transform', 'none');
    for (const id of ['landing-events', 'landing-news', 'landing-blog']) {
      const row = page.getByTestId(id);
      await row.scrollIntoViewIfNeeded();
      await expect(row).toHaveClass(/revealed/);
      await expect(row.locator('.publication-intro')).toHaveCSS('opacity', '1');
      await expect(row.locator('.empty-publication')).toHaveCSS('opacity', '1');
      await expect(row.locator('.empty-publication')).toHaveCSS('transform', 'none');
    }
    await expect(newsletter).toHaveCSS('opacity', '1');
    expect(await scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
    const after = await compose.boundingBox();
    expect(Math.abs(after!.y + after!.height - geometry.compose.bottom)).toBeLessThan(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    await expect(root.locator('img.device-screen:visible')).toHaveCount(width < 760 ? 6 : 12);
  });
}

// contract-test: direct surface=gui.web assertions=marketing-landing.language-theme,marketing-landing.hero-app-rail,marketing-landing.feature-layout,marketing-landing.public-content,marketing-landing.destinations
test('320px reduced-motion landing offers language-only settings and all event/social links', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const events = Array.from({ length: 4 }, (_, index) => ({ id: `event-${index}`, title: `Upcoming event ${index}`, href: `${APP}/#embed-id=fixture-event-${index}`, label: 'Oct 14, 2026' }));
  await page.goto(preview(320, 'dark', { events }), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 30_000);
  const root = page.getByTestId('landing-page');
  const staticFeature = page.getByTestId('landing-feature-privacy');
  await expect(staticFeature).not.toHaveClass(/reveal-ready/);
  await expect(staticFeature.locator('.feature-copy h2')).toHaveCSS('opacity', '1');
  await expect(staticFeature.locator('.feature-example')).toHaveCSS('opacity', '1');
  await expect(staticFeature.locator('.feature-example')).toHaveCSS('transform', 'none');
  const staticNewsletter = page.getByTestId('landing-newsletter-reveal');
  await expect(staticNewsletter).not.toHaveClass(/reveal-ready/);
  await expect(staticNewsletter).toHaveCSS('opacity', '1');
  for (const id of ['landing-events', 'landing-news', 'landing-blog']) {
    const row = page.getByTestId(id);
    const content = row.locator(id === 'landing-events' ? '.event-cards' : '.empty-publication');
    await expect(row).not.toHaveClass(/reveal-ready/);
    await expect(row.locator('.publication-intro')).toHaveCSS('opacity', '1');
    await expect(content).toHaveCSS('opacity', '1');
    await expect(content).toHaveCSS('transform', 'none');
  }
  const compactTab = await page.getByTestId('landing-nav-chats').boundingBox();
  expect(compactTab?.width).toBeLessThan(72);
  expect(compactTab?.width).toBeGreaterThanOrEqual(48);
  expect(compactTab?.height).toBeCloseTo(44.8, 0);
  await expect(page.getByTestId('landing-prompt')).toHaveCSS('opacity', '1');
  await expect(page.getByTestId('landing-prompt')).toHaveAttribute('data-active-app', 'events');
  await expect(page.getByTestId('landing-prompt')).toHaveAttribute('href', `${APP}/#chat-id=${landingAppExamples.events}`);
  await expect(page.getByTestId('landing-prompt')).toHaveAttribute('target', '_blank');
  const rail = root.locator('.rail-track');
  await expect(rail).toHaveCSS('animation-name', 'none');
  await expect(page.getByTestId('landing-scroll-cue')).toHaveCSS('animation-name', 'none');
  const language = page.getByTestId('landing-language-button');
  await expect(language).toContainText('EN');
  await language.click();
  const panel = page.getByTestId('landing-language-panel');
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('button', { name: /Deutsch/ })).toBeVisible();
  await expect(panel.getByText(/account|payment|chat settings/i)).toHaveCount(0);
  await panel.getByRole('button', { name: /Deutsch/ }).click();
  await expect(language).toContainText('DE');
  await expect(language).toBeFocused();
  await expect(root.getByRole('heading', { level: 1 })).toContainText('Privatsphäre');
  const mobileSpacing = await root.evaluate((element) => ({
    cue: element.querySelector('[data-testid="landing-scroll-cue"]')!.getBoundingClientRect().bottom,
    composer: element.querySelector('[data-testid="landing-compose"]')!.getBoundingClientRect().top
  }));
  expect(mobileSpacing.cue).toBeLessThan(mobileSpacing.composer);
  expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBe('de');
  await language.click(); await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0); await expect(language).toBeFocused();
  await page.reload(); await waitForComponentPreview(page, 30_000);
  await expect(language).toContainText('DE');
  const cards = page.getByTestId('landing-event-card');
  await expect(cards).toHaveCount(4);
  for (const card of await cards.all()) {
    await expect(card).toHaveAttribute('target', '_blank');
    await expect(card).toHaveAttribute('href', /\/#embed-id=fixture-event-/);
    await expect(card).toHaveAttribute('rel', /noopener.*noreferrer/);
  }
  await expect(page.getByTestId('landing-events').getByRole('link', { name: /browse/i })).toHaveCount(0);
  const eventRail = page.getByTestId('landing-event-cards');
  expect(await eventRail.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
  const newsletter = root.locator('#newsletter');
  expect((await newsletter.boundingBox())!.y).toBeLessThan((await page.getByTestId('landing-events').boundingBox())!.y);
  const socials = root.locator('.social-links a');
  await expect(socials).toHaveCount(8);
  for (const social of await socials.all()) {
    await expect(social).toHaveAttribute('target', '_blank');
    await expect(social).toHaveAttribute('rel', /noopener.*noreferrer/);
    const icon = social.locator('.social-icon');
    await expect(icon).toHaveCount(1);
    expect(await icon.evaluate(element => {
      const probe = document.createElement('span');
      probe.style.backgroundColor = 'var(--color-grey-80)';
      element.append(probe);
      const matches = getComputedStyle(element).backgroundColor === getComputedStyle(probe).backgroundColor;
      probe.remove();
      return matches && getComputedStyle(element).maskImage.includes('/icons/');
    })).toBe(true);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
});

for (const width of [390, 1440]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.interactive-rail,marketing-landing.hero-app-rail
  test(`landing swipe release carries momentum without pausing (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: width < 760 ? 844 : 900 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto(preview(width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const rail = page.getByTestId('landing-app-rail');
    const box = (await rail.boundingBox())!;
    const cdp = await page.context().newCDPSession(page);
    if (width < 760) await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
    const startX = box.x + box.width * .65;
    const y = box.y + box.height / 2;
    for (const direction of [-1, 1]) {
      if (width < 760) {
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: startX, y, id: 1 }] });
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: startX + 70 * direction, y, id: 1 }] });
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: startX + 140 * direction, y, id: 1 }] });
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      } else {
        await page.mouse.move(startX, y);
        await page.mouse.down();
        await page.mouse.move(startX + 70 * direction, y);
        await page.mouse.move(startX + 140 * direction, y);
        await page.mouse.up();
      }
      const samples = await rail.evaluate(async element => {
        const group = element.querySelector<HTMLElement>('.rail-group')!;
        const track = element.querySelector<HTMLElement>('.rail-track')!;
        const period = group.getBoundingClientRect().width;
        let previous = new DOMMatrix(getComputedStyle(track).transform).m41;
        const result: number[] = [];
        for (let frame = 0; frame < 20; frame++) {
          await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
          const current = new DOMMatrix(getComputedStyle(track).transform).m41;
          // Map identical rendered cycles into the same continuous coordinate system.
          result.push((current - previous + period * 1.5) % period - period / 2);
          previous = current;
        }
        return result;
      });
      expect(samples.slice(0, 4).some(delta => Math.abs(delta) > .5), 'release must continue immediately').toBe(true);
      const early = samples.slice(0, 5).reduce((sum, delta) => sum + delta, 0);
      const late = samples.slice(-5).reduce((sum, delta) => sum + delta, 0);
      expect(early * direction, 'momentum must preserve swipe direction').toBeGreaterThan(2);
      expect(Math.abs(late), 'momentum must slow naturally').toBeLessThan(Math.abs(early));
      await expect(rail).toHaveAttribute('data-active-app', (await page.getByTestId('landing-prompt').getAttribute('data-active-app'))!);
    }
    await cdp.detach();
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const track = rail.locator('.rail-track');
    const stopped = await track.evaluate(element => getComputedStyle(element).transform);
    await page.waitForTimeout(200);
    expect(await track.evaluate(element => getComputedStyle(element).transform)).toBe(stopped);
  });
}

// contract-test: direct surface=gui.web assertions=marketing-landing.interactive-rail,marketing-landing.hero-app-rail
test('landing app rail selects, pauses, resumes and accepts manual input', async ({ page }) => {
  test.setTimeout(35_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto(preview(1440), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 30_000);
  const rail = page.getByTestId('landing-app-rail');
  const icons = rail.getByTestId('landing-rail-group').nth(1).locator('.rail-icon');
  const prompt = page.getByTestId('landing-prompt');
  const selected = landingAppOrder[1];
  const travel = icons.nth(1);
  await expect(travel).toBeVisible();
  await expect(travel).toBeEnabled();
  const travelBounds = (await travel.boundingBox())!;
  const railBounds = (await rail.boundingBox())!;
  const clickX = travelBounds.x + travelBounds.width / 2;
  const clickY = travelBounds.y + travelBounds.height / 2;
  expect(clickX).toBeGreaterThan(railBounds.x + 10);
  expect(clickX).toBeLessThan(railBounds.x + railBounds.width - 10);
  await page.mouse.click(clickX, clickY);
  await expect(prompt).toHaveAttribute('data-active-app', selected);
  await expect(rail).toHaveAttribute('data-active-app', selected);
  await expect(icons.nth(1)).toHaveAttribute('aria-pressed', 'true');
  const position = () => rail.locator('.rail-track').evaluate(element => getComputedStyle(element).transform);
  await expect.poll(async () => {
    const bounds = await icons.nth(1).boundingBox();
    const window = await rail.boundingBox();
    return Math.abs((bounds!.x + bounds!.width / 2) - (window!.x + window!.width / 2));
  }).toBeLessThan(2);
  await expect.poll(async () => {
    const first = await position();
    await page.waitForTimeout(80);
    return first === await position();
  }).toBe(true);
  const held = await position();
  await page.waitForTimeout(900);
  expect(await position()).toBe(held);
  await expect.poll(async () => (await position()) !== held, { timeout: 3000 }).toBe(true);

  const beforeWheel = await position();
  const wheelResult = await rail.evaluate(element => {
    const event = new WheelEvent('wheel', { deltaX: 90, deltaY: 0, bubbles: true, cancelable: true });
    element.dispatchEvent(event);
    return event.defaultPrevented;
  });
  expect(wheelResult).toBe(true);
  expect(await position()).not.toBe(beforeWheel);
  const verticalWheel = await rail.evaluate(element => {
    const event = new WheelEvent('wheel', { deltaX: 0, deltaY: 90, bubbles: true, cancelable: true });
    element.dispatchEvent(event);
    return event.defaultPrevented;
  });
  expect(verticalWheel).toBe(false);

  await page.emulateMedia({ reducedMotion: 'reduce' });
  const reducedPosition = await position();
  await page.waitForTimeout(200);
  expect(await position()).toBe(reducedPosition);
  await rail.focus();
  const beforeKey = (await prompt.getAttribute('data-active-app'))!;
  await rail.press('ArrowRight');
  await expect(prompt).toHaveAttribute('data-active-app', landingAppOrder[(landingAppOrder.indexOf(beforeKey) + 1) % landingAppOrder.length]);
  await expect(rail).toHaveCSS('touch-action', 'pan-y');
  await page.setViewportSize({ width: 390, height: 844 });
  const afterResize = await position();
  await page.waitForTimeout(150);
  expect(await position()).toBe(afterResize);
  const box = (await rail.boundingBox())!;
  const x = box.x + box.width * 0.65;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, box.y - 30);
  await page.mouse.up();
  expect(await position()).toBe(afterResize);
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x - 120, y, { steps: 4 });
  await page.mouse.up();
  expect(await position()).not.toBe(afterResize);
  const beforeTouch = await position();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 1 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x - 140, y, id: 1 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  expect(await position()).not.toBe(beforeTouch);
  await cdp.detach();
});

for (const width of [390, 1440]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.hero-app-rail,marketing-landing.interactive-rail
  test(`landing rail highlight crosses the speed-label center symmetrically at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width < 760 ? 844 : 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(preview(width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const rail = page.getByTestId('landing-app-rail');
    const speed = page.getByTestId('landing-hero-speed');
    const icons = rail.getByTestId('landing-rail-group').nth(1).locator('.rail-icon');
    const geometry = await rail.evaluate((element) => {
      const first = element.querySelector<HTMLElement>('.rail-group:nth-child(2) .rail-icon')!;
      const next = first.nextElementSibling as HTMLElement;
      const railBox = element.getBoundingClientRect();
      const speedBox = document.querySelector('[data-testid="landing-hero-speed"]')!.getBoundingClientRect();
      const firstBox = first.getBoundingClientRect();
      const nextBox = next.getBoundingClientRect();
      const iconCenter = firstBox.left + firstBox.width / 2;
      return { pitch: nextBox.left + nextBox.width / 2 - iconCenter, iconCenter, railCenter: railBox.left + railBox.width / 2, speedCenter: speedBox.left + speedBox.width / 2 };
    });
    expect(Math.abs(geometry.iconCenter - geometry.speedCenter)).toBeLessThan(2);
    expect(Math.abs(geometry.railCenter - geometry.speedCenter)).toBeLessThan(2);
    const wheel = async (deltaX: number) => rail.evaluate((element, delta) => element.dispatchEvent(new WheelEvent('wheel', { deltaX: delta, bubbles: true, cancelable: true })), deltaX);
    await wheel(geometry.pitch * .49);
    await expect(rail).toHaveAttribute('data-active-app', landingAppOrder[0]);
    await wheel(geometry.pitch * .02);
    await expect(rail).toHaveAttribute('data-active-app', landingAppOrder[1]);
    const rightBoundary = await icons.nth(1).evaluate(element => { const box = element.getBoundingClientRect(); return box.left + box.width / 2; });
    await wheel(geometry.pitch);
    await expect(rail).toHaveAttribute('data-active-app', landingAppOrder[2]);
    const leftBoundary = await icons.nth(1).evaluate(element => { const box = element.getBoundingClientRect(); return box.left + box.width / 2; });
    expect(Math.abs((rightBoundary - geometry.speedCenter) + (leftBoundary - geometry.speedCenter))).toBeLessThan(geometry.pitch * .05);
    expect(Math.abs(Math.abs(rightBoundary - geometry.speedCenter) - geometry.pitch / 2)).toBeLessThan(geometry.pitch * .05);
    expect(Math.abs(Math.abs(leftBoundary - geometry.speedCenter) - geometry.pitch / 2)).toBeLessThan(geometry.pitch * .05);
    await expect(speed).toHaveText('In seconds');
  });
}

// contract-test: direct surface=gui.web assertions=marketing-landing.hero-app-rail,marketing-landing.interactive-rail
test('landing app rail crosses its automatic loop without a visible seam', async ({ page }) => {
  test.setTimeout(40_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto(preview(1440), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 30_000);
  const rail = page.getByTestId('landing-app-rail');
  await rail.getByTestId('landing-rail-group').nth(1).locator('.rail-icon').last().evaluate((button: HTMLButtonElement) => button.click());
  await expect(rail).toHaveAttribute('data-active-app', landingAppOrder.at(-1)!);
  await expect.poll(async () => {
    const first = await rail.locator('.rail-track').evaluate(element => getComputedStyle(element).transform);
    await page.waitForTimeout(80);
    return first === await rail.locator('.rail-track').evaluate(element => getComputedStyle(element).transform);
  }).toBe(true);
  const seam = await rail.evaluate(async (windowEl, ids) => {
    const track = windowEl.querySelector<HTMLElement>('.rail-track')!;
    const period = windowEl.querySelector<HTMLElement>('.rail-group')!.getBoundingClientRect().width;
    const center = windowEl.getBoundingClientRect().left + windowEl.clientWidth / 2;
    const visualX = (id: string) => [...track.querySelectorAll<HTMLElement>(`[data-app-id="${id}"]`)]
      .map(icon => icon.getBoundingClientRect().left)
      .sort((a, b) => Math.abs(a - center) - Math.abs(b - center))[0];
    let previous = { transform: new DOMMatrix(getComputedStyle(track).transform).m41, last: visualX(ids.last), first: visualX(ids.first) };
    const deadline = performance.now() + 8500;
    while (performance.now() < deadline) {
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      const current = { transform: new DOMMatrix(getComputedStyle(track).transform).m41, last: visualX(ids.last), first: visualX(ids.first) };
      if (current.transform - previous.transform > period / 2) {
        return { wrapped: true, lastMovement: Math.abs(current.last - previous.last), firstMovement: Math.abs(current.first - previous.first), period };
      }
      previous = current;
    }
    return { wrapped: false, lastMovement: Infinity, firstMovement: Infinity, period };
  }, { last: landingAppOrder.at(-1)!, first: landingAppOrder[0] });
  expect(seam.wrapped).toBe(true);
  expect(Math.abs(seam.period / landingAppOrder.length - Math.round(seam.period / landingAppOrder.length))).toBeGreaterThan(0.01);
  expect(seam.lastMovement).toBeLessThan(3);
  expect(seam.firstMovement).toBeLessThan(3);
});
