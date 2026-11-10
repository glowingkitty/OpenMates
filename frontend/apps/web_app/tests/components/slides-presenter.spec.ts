// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
import { test, expect, type Page } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (component: string, variant = '') =>
  `/dev/preview/embeds/slides/${component}?${new URLSearchParams({ variant, chrome: '0' })}`;

const NOTE_ONE = 'Welcome everyone.';
const NOTE_TWO = 'Stress the eighteen percent.';
const NOTE_THREE = 'Mention the discount only if asked.';

async function open(page: Page, variant = '', size = { width: 1280, height: 720 }) {
  // A previous audience view may have put the window in full screen; a full-screen
  // window cannot be resized.
  await page.evaluate(() => (document.fullscreenElement ? document.exitFullscreen() : undefined));
  await page.setViewportSize(size);
  await page.goto(preview('SlidesPresentation', variant));
  await waitForComponentPreview(page);
}

const audience = (page: Page) => page.getByTestId('slides-audience');
const presenter = (page: Page) => page.getByTestId('slides-presenter');

test.describe('Slides presenter mode (local)', () => {
  // contract-test: direct surface=gui.web assertions=slides.format.positioned-elements
  test('audience view fills the window at the deck aspect for 16:9, 16:10 and 4:3', async ({ page }) => {
    const viewport = { width: 1280, height: 720 };
    for (const [variant, ratio] of [['', 16 / 9], ['aspect16x10', 16 / 10], ['aspect4x3', 4 / 3]] as const) {
      await open(page, variant, viewport);
      await expect(audience(page)).toBeVisible();
      const box = await audience(page).getByTestId('slide-canvas').boundingBox();
      expect(box).not.toBeNull();
      const { width, height } = box!;
      expect(width / height).toBeCloseTo(ratio, 1);
      // Letterboxed: the slide touches the window on at least one axis and never overflows.
      expect(Math.max(width / viewport.width, height / viewport.height)).toBeGreaterThan(0.99);
      expect(width).toBeLessThanOrEqual(viewport.width + 1);
      expect(height).toBeLessThanOrEqual(viewport.height + 1);
      // Centred in the window on both axes.
      expect(box!.x + width / 2).toBeCloseTo(viewport.width / 2, -1);
      expect(box!.y + height / 2).toBeCloseTo(viewport.height / 2, -1);
      const surround = await audience(page).evaluate((el) => getComputedStyle(el).backgroundColor);
      expect(surround).toBe('rgb(0, 0, 0)');
    }
  });

  // contract-test: direct surface=gui.web assertions=slides.present.presenter-view
  test('speaker notes are absent from the audience DOM and present in the presenter view', async ({ page }) => {
    await open(page, '');
    for (let slide = 0; slide < 3; slide += 1) {
      const html = await page.evaluate(() => document.documentElement.outerHTML);
      for (const note of [NOTE_ONE, NOTE_TWO, NOTE_THREE]) expect(html).not.toContain(note);
      await page.keyboard.press('ArrowRight');
    }
    await open(page, 'presenter');
    await expect(page.getByTestId('presenter-notes')).toContainText(NOTE_ONE);
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId('presenter-notes')).toContainText(NOTE_TWO);
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId('presenter-notes')).toContainText(NOTE_THREE);
  });

  // contract-test: direct surface=gui.web assertions=slides.present.presenter-view
  test('presenter view updates the next-slide preview and the position on advance', async ({ page }, testInfo) => {
    await open(page, 'presenter');
    await expect(presenter(page)).toBeVisible();
    await expect(page.getByTestId('presenter-position')).toHaveText('1 / 4');
    await expect(presenter(page).getByTestId('presenter-current').getByTestId('slide-canvas')).toHaveAttribute('data-slide-id', 's1');
    await expect(page.getByTestId('presenter-next-slide').getByTestId('slide-canvas')).toHaveAttribute('data-slide-id', 's2');
    await expect(page.getByTestId('presenter-prev')).toBeDisabled();

    await page.getByTestId('presenter-next').click();
    await expect(page.getByTestId('presenter-position')).toHaveText('2 / 4');
    await expect(presenter(page).getByTestId('presenter-current').getByTestId('slide-canvas')).toHaveAttribute('data-slide-id', 's2');
    await expect(page.getByTestId('presenter-next-slide').getByTestId('slide-canvas')).toHaveAttribute('data-slide-id', 's3');

    await page.getByTestId('presenter-prev').click();
    await expect(page.getByTestId('presenter-position')).toHaveText('1 / 4');
    // Top-bar buttons show readable labels (a global .text-button once made them transparent).
    for (const id of ['presenter-timer-reset', 'presenter-exit']) {
      const button = page.getByTestId(id);
      await expect(button).toHaveText(/\S/);
      const colors = await button.evaluate((el) => {
        const style = getComputedStyle(el);
        return { fill: getComputedStyle(el).getPropertyValue('-webkit-text-fill-color'), color: style.color, background: style.backgroundColor };
      });
      expect(colors.fill).not.toBe('rgba(0, 0, 0, 0)');
      expect(colors.color).not.toBe(colors.background);
      const box = await button.boundingBox();
      expect(box!.width).toBeGreaterThan(40);
    }

    await testInfo.attach('presenter-desktop', { body: await page.screenshot(), contentType: 'image/png' });
  });

  // contract-test: direct surface=gui.web assertions=slides.present.presenter-view
  test('slide list marks the current slide and jumps on click; next preview shows the next build step first', async ({ page }) => {
    await open(page, 'presenter');
    const items = page.getByTestId('presenter-slide-list-item');
    await expect(items).toHaveCount(4);
    await expect(items.nth(0)).toHaveAttribute('aria-current', 'true');
    await items.nth(2).click();
    await expect(page.getByTestId('presenter-position')).toHaveText('3 / 4');
    await expect(items.nth(2)).toHaveAttribute('aria-current', 'true');

    // Slide 3 has an element on build step 1: the preview shows that step before slide 4.
    const next = page.getByTestId('presenter-next-slide').getByTestId('slide-canvas');
    await expect(next).toHaveAttribute('data-slide-id', 's3');
    await expect(next.locator('[data-element-id="e8"]')).toHaveCount(1);
    await expect(presenter(page).getByTestId('presenter-current').locator('[data-element-id="e8"]')).toHaveCount(0);
    await page.keyboard.press('ArrowRight');
    await expect(next).toHaveAttribute('data-slide-id', 's4');

    // Notes get most of the side column and a readable size.
    const notes = await page.getByTestId('presenter-notes').boundingBox();
    const nextBox = await page.getByTestId('presenter-next-slide').boundingBox();
    expect(notes!.height).toBeGreaterThan(nextBox!.height);
  });

  // contract-test: direct surface=gui.web assertions=slides.present.presenter-view
  test('a build step advances before the slide changes', async ({ page }) => {
    await open(page, '');
    const slide = audience(page).getByTestId('slide-canvas');
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');
    await expect(audience(page)).toHaveAttribute('data-slide-index', '2');
    await expect(slide.locator('[data-element-id="e8"]')).toHaveCount(0);
    await page.keyboard.press('ArrowRight');
    await expect(audience(page)).toHaveAttribute('data-slide-index', '2');
    await expect(slide.locator('[data-element-id="e8"]')).toHaveCount(1);
    await page.keyboard.press('ArrowRight');
    await expect(audience(page)).toHaveAttribute('data-slide-index', '3');
  });

  // contract-test: direct surface=gui.web assertions=slides.present.presenter-view
  test('keyboard and click navigate and Esc exits', async ({ page }) => {
    await open(page, '');
    const index = () => audience(page).getAttribute('data-slide-index');
    await page.keyboard.press('ArrowRight');
    await expect(audience(page)).toHaveAttribute('data-slide-index', '1');
    await page.keyboard.press(' ');
    await expect(audience(page)).toHaveAttribute('data-slide-index', '2');
    await page.keyboard.press('PageDown'); // build step of slide 3
    await page.keyboard.press('PageDown');
    await expect(audience(page)).toHaveAttribute('data-slide-index', '3');
    await page.keyboard.press('PageUp');
    await page.keyboard.press('ArrowLeft');
    await expect(audience(page)).toHaveAttribute('data-slide-index', '2');
    await page.keyboard.press('Home');
    await expect(audience(page)).toHaveAttribute('data-slide-index', '0');
    await page.keyboard.press('End');
    await expect(audience(page)).toHaveAttribute('data-slide-index', '3');
    await page.keyboard.press('Home');
    await audience(page).click({ position: { x: 600, y: 300 } });
    await expect(audience(page)).toHaveAttribute('data-slide-index', '1');
    expect(await index()).toBe('1');

    await page.keyboard.press('Escape');
    expect(await page.evaluate(() => (window as unknown as { __slidesExitCount?: number }).__slidesExitCount)).toBe(1);
  });

  // contract-test: direct surface=gui.web assertions=slides.present.presenter-view
  test('timer runs and resets', async ({ page }) => {
    await open(page, 'presenter');
    const timer = page.getByTestId('presenter-timer');
    await expect(timer).toHaveText('00:00');
    await expect(timer).not.toHaveText('00:00', { timeout: 5_000 });
    await page.getByTestId('presenter-timer-reset').click();
    await expect(timer).toHaveText('00:00');
  });

  // contract-test: direct surface=gui.web assertions=slides.format.positioned-elements
  test('audience view on desktop and phone', async ({ page }, testInfo) => {
    for (const [name, size] of [['desktop', { width: 1280, height: 720 }], ['phone', { width: 390, height: 844 }]] as const) {
      await open(page, '', size);
      await page.keyboard.press('ArrowRight');
      const box = await audience(page).getByTestId('slide-canvas').boundingBox();
      expect(box!.width).toBeLessThanOrEqual(size.width + 1);
      expect(box!.width / box!.height).toBeCloseTo(16 / 9, 1);
      expect(box!.x + box!.width / 2).toBeCloseTo(size.width / 2, -1);
      expect(box!.y + box!.height / 2).toBeCloseTo(size.height / 2, -1);
      await testInfo.attach(`audience-${name}`, { body: await page.screenshot(), contentType: 'image/png' });
    }
  });

  // contract-test: direct surface=gui.web assertions=slides.present.presenter-view
  test('presenter view and audience window stay in sync and closing the window ends presenting', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(preview('SlidesDeckEmbedFullscreen'));
    await waitForComponentPreview(page);
    const [popup] = await Promise.all([
      page.waitForEvent('popup'),
      page.getByTestId('slides-present-presenter-view').click()
    ]);
    await expect(presenter(page)).toBeVisible();
    await expect(audience(popup)).toBeVisible({ timeout: 20_000 });
    await expect(audience(popup)).toHaveAttribute('data-slide-index', '0');

    await page.keyboard.press('ArrowRight');
    await expect(audience(popup)).toHaveAttribute('data-slide-index', '1');
    await popup.keyboard.press('ArrowRight');
    await expect(presenter(page)).toHaveAttribute('data-slide-index', '2');
    await expect(audience(popup)).toHaveAttribute('data-slide-index', '2');

    await page.getByTestId('presenter-slide-list-item').nth(3).click();
    await expect(audience(popup)).toHaveAttribute('data-slide-index', '3');
    await page.getByTestId('presenter-slide-list-item').nth(2).click();
    await expect(audience(popup)).toHaveAttribute('data-slide-index', '2');

    // Notes only in the presenter window.
    await expect(page.getByTestId('presenter-notes')).toContainText(NOTE_THREE);
    expect(await popup.evaluate(() => document.documentElement.outerHTML)).not.toContain(NOTE_THREE);

    await popup.close();
    await expect(presenter(page)).toHaveCount(0, { timeout: 5_000 });
    await expect(page.getByTestId('slides-deck-fullscreen')).toBeVisible();
  });

  // contract-test: direct surface=gui.web assertions=slides.present.presenter-view
  test('a blocked second window shows a message and presents in this window', async ({ page }) => {
    await page.addInitScript(() => {
      window.open = () => null;
    });
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(preview('SlidesDeckEmbedFullscreen'));
    await waitForComponentPreview(page);
    await page.getByTestId('slides-present-presenter-view').click();
    await expect(audience(page)).toBeVisible();
    await expect(page.getByTestId('slides-audience-notice')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(audience(page)).toHaveCount(0);
    await expect(page.getByTestId('slides-popup-blocked')).toBeVisible();
  });
});
