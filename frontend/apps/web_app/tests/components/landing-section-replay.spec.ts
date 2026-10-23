import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { landingSectionExamples } from '../../../../packages/public-site/src/components/landing/landingPageContent';
import type { Page } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview
const APP = 'https://app.dev.openmates.org';
const sections = ['actionable', 'privacy', 'model-choice', 'workflows', 'devices', 'open-source'] as const;
const preview = (width: number) => `/dev/preview/landing/LandingPage?${new URLSearchParams({ width: String(width), chrome: '0', theme: 'light' })}`;

async function reach(page: Page, id: string) {
  await page.getByTestId('landing-scroll-container').evaluate((element, id) => {
    const target = element.querySelector(`#${id}`)!;
    element.scrollTo({ top: target.getBoundingClientRect().top - element.getBoundingClientRect().top + element.scrollTop, behavior: 'instant' });
  }, id);
}

test.beforeEach(async ({ page }) => {
  await page.route('**/v1/settings/server-status', route => route.fulfill({ json: { anonymous_free_usage: { active: true, can_send_text: true } } }));
});

for (const width of [390, 1440]) {
  // contract-test: direct surface=gui.web assertions=marketing-landing.section-stories,marketing-landing.real-screenshots,marketing-landing.feature-layout,marketing-landing.hero-app-rail
  test(`section intros, Replay and admitted device screen links at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(90_000);
    await page.setViewportSize({ width, height: width < 760 ? 844 : 1000 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.goto(preview(width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 60_000);
    await expect(page.locator('#hero-title')).toBeVisible();
    await expect(page.getByTestId('landing-privacy-highlight')).toHaveCount(0);
    await expect(page.locator('#hero-title')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');

    for (const id of sections) {
      const section = page.getByTestId(`landing-feature-${id}`);
      const media = section.getByTestId(`landing-feature-media-${id}`);
      await reach(page, id);
      await expect(section).toHaveAttribute('data-story-state', 'playing');
      await expect(section.getByRole('heading')).toBeVisible();
      await expect(section.locator('.story-copy')).toHaveCount(0);
      await expect(media).toHaveCount(0);
      await expect(section.getByTestId(`landing-skip-${id}`)).toBeVisible();
      if (id === 'actionable' || id === 'privacy') {
        await expect(section.getByTestId('landing-feature-animation')).toHaveCount(1);
        await section.getByTestId(`landing-skip-${id}`).click();
      } else {
        await expect(section.getByTestId('landing-feature-animation')).toHaveCount(0);
        // No invented demo: visible title time naturally reveals the real content.
      }
      await expect(section).toHaveAttribute('data-story-state', 'complete', { timeout: 8_000 });
      await expect(section.locator('.story-copy')).toHaveCSS('opacity', '1');
      await expect(media).toHaveCSS('opacity', '1');
      const replay = section.getByTestId(`landing-replay-${id}`);
      await expect(replay).toBeVisible();
      if (id === 'open-source') {
        await expect(media.locator('img, .device-frame')).toHaveCount(0);
        await expect(media.getByTestId('landing-source-github')).toHaveAttribute('href', 'https://github.com/glowingkitty/OpenMates');
        await expect(media.getByTestId('landing-source-github')).toHaveAttribute('target', '_blank');
      } else {
        if (id === 'privacy') {
          const composite = media.getByTestId('device-screenshots');
          await expect(composite).toBeVisible();
          await expect(composite).toHaveJSProperty('tagName', 'DIV');
          await expect(composite).not.toHaveAttribute('href');
          await expect(media.locator('a, [href]')).toHaveCount(0);
          await expect(section.getByTestId('landing-open-example-privacy')).toHaveCount(0);
          await expect(composite.locator('.device-frame.phone')).toBeVisible();
          await expect(composite.locator('.device-frame.laptop')).toHaveCount(1);
          if (width >= 760) await expect(composite.locator('.device-frame.laptop')).toBeVisible();
        } else {
          const destination = id === 'workflows' ? `${APP}/#workflows` : `${APP}/?lang=en#chat-id=${landingSectionExamples[id]}`;
          const link = media.locator('a.device-screenshots');
          await expect(link).toHaveAttribute('href', destination);
          await expect(link).toHaveAttribute('target', '_blank');
          await expect(link).toHaveAttribute('rel', /noopener/);
          await expect(link).toHaveAccessibleName(/.+/);
          const example = section.getByTestId(`landing-open-example-${id}`);
          if (id === 'workflows') await expect(example).toHaveCount(0);
          else {
            await expect(example).toHaveAttribute('href', destination);
            await expect(example).not.toContainText('↗');
            const positions = await section.locator('.feature-actions').evaluate(element => {
              const replay = element.querySelector('button')!.getBoundingClientRect();
              const example = element.querySelector('a')!.getBoundingClientRect();
              return { replay: { x: replay.x, right: replay.right, y: replay.y }, example: { x: example.x, y: example.y } };
            });
            expect(positions.replay.y).toBeLessThanOrEqual(positions.example.y + 1);
            if (Math.abs(positions.replay.y - positions.example.y) < 4) expect(positions.replay.right).toBeLessThanOrEqual(positions.example.x + 1);
          }
        }
        await expect(media.locator('.device-frame.laptop')).toHaveCount(1);
        if (width < 760) await expect(media.locator('.device-frame.laptop')).toBeHidden();
        const visibleFrames = media.locator('.device-frame:visible');
        for (const frame of await visibleFrames.all()) {
          const image = frame.locator('img.device-screen');
          await image.scrollIntoViewIfNeeded();
          await expect.poll(() => image.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
          const geometry = await frame.evaluate(element => {
            const screen = element.querySelector<HTMLElement>('.screen-aperture')!;
            const image = screen.querySelector('img')!;
            const outer = element.getBoundingClientRect(), aperture = screen.getBoundingClientRect(), pixels = image.getBoundingClientRect();
            return { hidden: getComputedStyle(screen).overflow, radius: getComputedStyle(screen).borderTopLeftRadius, within: aperture.left >= outer.left - 1 && aperture.top >= outer.top - 1 && aperture.right <= outer.right + 1 && aperture.bottom <= outer.bottom + 1, width: Math.abs(pixels.width - aperture.width), height: Math.abs(pixels.height - aperture.height) };
          });
          expect(geometry.hidden).toBe('hidden');
          expect(parseFloat(geometry.radius)).toBeGreaterThan(0);
          expect(geometry.within).toBe(true);
          expect(geometry.width).toBeLessThan(1);
          expect(geometry.height).toBeLessThan(1);
        }
      }
      if (id === 'privacy') {
        await replay.click();
        await expect(section).toHaveAttribute('data-story-state', 'playing');
        await expect(media).toHaveCount(0);
        await expect(section.getByTestId('landing-feature-animation')).toBeVisible();
        await section.getByTestId('landing-skip-privacy').click();
        await expect(section).toHaveAttribute('data-story-state', 'complete');
        await expect(media.getByTestId('device-screenshots')).toBeVisible();
        await expect(media.locator('a, [href]')).toHaveCount(0);
      }
    }
    const actionable = page.getByTestId('landing-feature-actionable');
    await reach(page, 'actionable');
    await expect(actionable).toHaveAttribute('data-story-state', 'complete');
    await actionable.getByTestId('landing-replay-actionable').click();
    await expect(actionable).toHaveAttribute('data-story-state', 'playing');
    await expect(actionable.getByTestId('landing-skip-actionable')).toBeVisible();
    await expect(actionable.getByTestId('landing-feature-media-actionable')).toHaveCount(0);
    // Shared EventResultCard content must stay current with real app previews.
    const event = actionable.getByTestId('landing-actionable-event-preview');
    await expect(event).toBeVisible({ timeout: 7_000 });
    await expect(event.getByTestId('result-card-title')).toHaveText('Amsterdam Music Meetup');
    const image = event.getByTestId('result-card-media').locator('img');
    await expect(image).toHaveAttribute('src', /meetup.*\.webp/);
    await expect(image).toHaveCSS('object-fit', 'contain');
    await expect.poll(() => image.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
    await expect(event.getByTestId('embed-calendar-date')).toHaveAttribute('datetime', '2026-08-29T16:30:00.000Z');
    await expect(event.getByTestId('embed-calendar-date').locator('strong')).toHaveText('29');
    await expect(event.getByTestId('event-preview-rsvps')).toContainText('460 RSVPs');
    await expect(event.locator('.result-corner')).toBeVisible();
    await expect(event.locator('.result-corner span')).toHaveCSS('mask-image', /^url\(/);
    await expect(event.getByTestId('result-card-title')).toHaveCSS('text-align', 'start');
    const card = await event.evaluate(element => {
      const frame = element.getBoundingClientRect();
      const title = element.querySelector('[data-testid="result-card-title"]')!.getBoundingClientRect();
      const date = element.querySelector('[data-testid="embed-calendar-date"]')!.getBoundingClientRect();
      const media = element.querySelector('[data-testid="result-card-media"]')!.getBoundingClientRect();
      return { width: element.clientWidth, height: element.clientHeight,
        titleBelowMedia: title.top >= media.bottom - 1,
        dateInside: date.left >= frame.left && date.right <= frame.right && date.top >= frame.top && date.bottom <= frame.bottom };
    });
    expect(card.width).toBe(300); expect(card.height).toBe(200);
    expect(card.titleBelowMedia).toBe(true); expect(card.dateInside).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`landing-current-embed-${width}.png`) });
    await actionable.getByTestId('landing-skip-actionable').click();
    await expect(actionable).toHaveAttribute('data-story-state', 'complete');
    await page.screenshot({ path: testInfo.outputPath(`landing-linked-devices-${width}.png`) });
    // Follow the actual image anchor with the destination isolated from the owner app.
    // Context routing also intercepts the popup's first request; page routing cannot.
    await page.context().route(`${APP}/?lang=en`, route => route.fulfill({ contentType: 'text/html', body: '<h1>Example destination</h1>' }));
    const popup = page.waitForEvent('popup');
    await actionable.locator('a.device-screenshots').click({ position: { x: 40, y: 50 } });
    const exampleTab = await popup;
    await expect(exampleTab).toHaveURL(`${APP}/?lang=en#chat-id=${landingSectionExamples.actionable}`);
    await exampleTab.close();
    await reach(page, 'open-source');
    await expect(page.getByTestId('landing-feature-open-source')).toHaveAttribute('data-story-state', 'complete');
    await expect(page.getByTestId('landing-source-github')).toBeVisible();
  });
}

// contract-test: direct surface=gui.web assertions=marketing-landing.section-stories,marketing-landing.real-screenshots
 test('reduced motion shows every final section immediately', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(preview(1440), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 60_000);
  for (const id of sections) {
    const section = page.getByTestId(`landing-feature-${id}`);
    await reach(page, id);
    await expect(section).toHaveAttribute('data-story-state', 'complete');
    await expect(section.locator('.story-copy')).toHaveCSS('opacity', '1');
    await expect(section.getByTestId(`landing-feature-media-${id}`)).toBeVisible();
    await expect(section.getByTestId(`landing-skip-${id}`)).toHaveCount(0);
    await expect(section.getByTestId(`landing-replay-${id}`)).toHaveCount(0);
    await expect(section.getByTestId('landing-feature-animation')).toHaveCount(0);
  }
});
