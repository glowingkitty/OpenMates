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
    await expect(root.getByTestId('public-site-header').locator('.wordmark')).toHaveAttribute('href', `${APP}/`);
    const geometry = await root.evaluate(element => {
      const rect = (id: string) => element.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect().toJSON();
      return { hero: rect('landing-hero'), viewport: rect('landing-viewport-container'), scroller: rect('landing-scroll-container'), compose: rect('landing-compose'), cue: rect('landing-scroll-cue') };
    });
    expect(Math.abs(geometry.hero.height - geometry.scroller.height)).toBeLessThan(2);
    expect(geometry.hero.top).toBeGreaterThanOrEqual(geometry.scroller.top - 1);
    const visualSlot = (await page.getByTestId('landing-hero-media').boundingBox())!;
    const deviceScale = (await page.getByTestId('landing-hero-media').locator('.hero-device-scale').boundingBox())!;
    expect(visualSlot.height).toBeGreaterThan(0);
    expect(deviceScale.height).toBeLessThanOrEqual(visualSlot.height + 1);
    const titleTop = (await root.locator('#hero-title').boundingBox())!.y;
    for (const frame of await page.getByTestId('landing-hero-media').locator(width < 760 ? '.device-frame.phone' : '.device-frame').all()) {
      const bounds = (await frame.boundingBox())!;
      expect(bounds.y).toBeGreaterThanOrEqual(geometry.hero.top - 1);
      expect(bounds.y + bounds.height).toBeLessThanOrEqual(titleTop + 1);
    }
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
      await expect(icon).toHaveAttribute('href', `${APP}/#apps/${id}`);
      await expect(icon).toHaveAttribute('target', '_blank');
      await expect(icon).toHaveAttribute('rel', /noopener/);
    }
    const railGeometry = await groups.nth(1).locator('.rail-icon').evaluateAll(nodes => nodes.map(node => {
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle(node, '::before');
      return { centerY: rect.y + rect.height / 2, width: rect.width, radius: getComputedStyle(node).borderTopLeftRadius, mask: style.maskImage || style.webkitMaskImage };
    }));
    expect(Math.max(...railGeometry.map(icon => icon.centerY)) - Math.min(...railGeometry.map(icon => icon.centerY))).toBeLessThan(2);
    expect(railGeometry.every(icon => icon.width >= 60 && icon.width <= 122 && icon.mask.includes('url('))).toBe(true);
    expect(railGeometry.every(icon => icon.radius === '34%')).toBe(true);
    const prompt = page.getByTestId('landing-prompt');
    await expect(prompt).toHaveCSS('opacity', '1');
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

    // Pause at the real repeating boundary: matching visible icons must not jump.
    const seam = await root.evaluate(element => {
      const windowEl = element.querySelector('[data-testid="landing-app-rail"]')!;
      const track = element.querySelector('.rail-track')!;
      const animation = track.getAnimations()[0];
      animation.pause();
      const duration = Number(animation.effect!.getTiming().duration);
      const sample = () => {
        const clip = windowEl.getBoundingClientRect();
        return [...track.querySelectorAll<HTMLElement>('[data-app-id]')].map(node => ({ id: node.dataset.appId, rect: node.getBoundingClientRect() })).filter(item => item.rect.left > clip.left + 10 && item.rect.right < clip.right - 10).map(item => ({ id: item.id, left: item.rect.left }));
      };
      animation.currentTime = duration - 1;
      const before = sample();
      animation.currentTime = duration;
      const after = sample();
      animation.play();
      return { before, after };
    });
    expect(seam.before.length).toBeGreaterThan(1);
    expect(seam.after.map(item => item.id)).toEqual(seam.before.map(item => item.id));
    for (let i = 0; i < seam.before.length; i++) expect(Math.abs(seam.before[i].left - seam.after[i].left)).toBeLessThan(1);

    const icons: string[] = [];
    for (const id of sections) {
      const section = page.getByTestId(`landing-feature-${id}`);
      await section.scrollIntoViewIfNeeded();
      await expect(section.getByRole('heading')).toBeVisible();
      expect((await section.boundingBox())!.height).toBeGreaterThanOrEqual(geometry.scroller.height - 1);
      const media = section.getByTestId(`landing-feature-media-${id}`);
      const copyRect = await section.locator('.feature-copy').boundingBox();
      const mediaRect = await media.boundingBox();
      expect(copyRect).not.toBeNull(); expect(mediaRect).not.toBeNull();
      if (width < 760) expect(mediaRect!.y).toBeGreaterThanOrEqual(copyRect!.y + copyRect!.height - 1);
      else expect(mediaRect!.x).toBeGreaterThanOrEqual(copyRect!.x + copyRect!.width - 1);
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
    expect(await scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(0);
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
    const after = await compose.boundingBox();
    expect(Math.abs(after!.y + after!.height - geometry.compose.bottom)).toBeLessThan(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    await expect(root.locator('img.device-screen:visible')).toHaveCount(width < 760 ? 7 : 14);
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
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
});
