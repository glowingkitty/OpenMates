// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (component: string, variant = '', width = 900) =>
  `/dev/preview/embeds/slides/${component}?${new URLSearchParams({ variant, width: String(width), chrome: '0' })}`;

test.describe('Slides deck embed (read-only rendering)', () => {
  // contract-test: direct surface=gui.web assertions=slides.format.positioned-elements
  test('card shows the first slide, title and slide count', async ({ page }) => {
    await page.goto(preview('SlidesDeckEmbedPreview', '', 420));
    await waitForComponentPreview(page);
    const card = page.getByTestId('slides-deck-preview');
    await expect(card).toBeVisible();
    await expect(card.getByTestId('slide-canvas')).toHaveAttribute('data-slide-id', 's1');
    await expect(page.getByText('Quarterly review').first()).toBeVisible();
    await expect(page.getByText('4 slides')).toBeVisible();
  });

  // contract-test: direct surface=gui.web assertions=slides.format.positioned-elements
  test('fullscreen navigates slides by buttons, thumbnails and arrow keys, build steps first', async ({ page }) => {
    await page.goto(preview('SlidesDeckEmbedFullscreen'));
    await waitForComponentPreview(page);
    const viewer = page.getByTestId('slides-deck-fullscreen');
    await expect(viewer).toBeVisible();
    await expect(page.getByTestId('slide-strip-item')).toHaveCount(4);
    await expect(page.getByTestId('slide-prev')).toBeDisabled();

    await page.getByTestId('slide-next').click();
    await expect(viewer).toHaveAttribute('data-slide-index', '1');
    await page.keyboard.press('ArrowRight');
    await expect(viewer).toHaveAttribute('data-slide-index', '2');

    // Slide 3 holds an element with build step 1: the first advance reveals it, the second changes slide.
    const stage = viewer.getByTestId('slide-canvas').first();
    await expect(stage.locator('[data-element-id="e8"]')).toHaveCount(0);
    await page.keyboard.press('ArrowRight');
    await expect(viewer).toHaveAttribute('data-slide-index', '2');
    await expect(stage.locator('[data-element-id="e8"]')).toHaveCount(1);
    await page.keyboard.press('ArrowRight');
    await expect(viewer).toHaveAttribute('data-slide-index', '3');
    await expect(page.getByTestId('slide-next')).toBeDisabled();

    await page.keyboard.press('ArrowLeft');
    await expect(viewer).toHaveAttribute('data-slide-index', '2');
    await page.getByTestId('slide-strip-item').first().click();
    await expect(viewer).toHaveAttribute('data-slide-index', '0');
  });

  // contract-test: direct surface=gui.web assertions=slides.format.positioned-elements
  test('canvas scales uniformly for 16:9, 16:10 and 4:3', async ({ page }) => {
    for (const [variant, ratio] of [['', 16 / 9], ['aspect16x10', 16 / 10], ['aspect4x3', 4 / 3]] as const) {
      await page.goto(preview('SlideCanvas', variant, 800));
      await waitForComponentPreview(page);
      const box = await page.getByTestId('slide-canvas').boundingBox();
      expect(box).not.toBeNull();
      expect((box?.width ?? 0) / (box?.height ?? 1)).toBeCloseTo(ratio, 1);
    }
  });

  // contract-test: direct surface=gui.web assertions=slides.security.host-rendered-and-isolated
  test('a hostile deck renders inert', async ({ page }) => {
    const requests: string[] = [];
    page.on('request', (request) => requests.push(request.url()));
    await page.goto(preview('SlideCanvas', 'hostile'));
    await waitForComponentPreview(page);
    const canvas = page.getByTestId('slide-canvas');
    await expect(canvas).toContainText('Safe title');
    expect(await page.evaluate(() => (window as unknown as Record<string, unknown>).__slidesPwned)).toBeUndefined();
    const html = await canvas.evaluate((element) => element.innerHTML.toLowerCase());
    for (const forbidden of ['<script', '<iframe', '<object', 'onclick', 'onerror', 'javascript:', 'evil.example', '<marquee']) {
      expect(html, forbidden).not.toContain(forbidden);
    }
    await expect(canvas.locator('a, img')).toHaveCount(0);
    expect(requests.filter((url) => url.includes('evil.example'))).toEqual([]);
  });

  // contract-test: direct surface=gui.web assertions=slides.format.positioned-elements
  test('card miniature fills the card at the deck aspect ratio with a visible edge', async ({ page }, testInfo) => {
    for (const [name, variant, ratio] of [['16x9', '', 16 / 9], ['16x10', 'aspect16x10', 16 / 10], ['4x3', 'aspect4x3', 4 / 3]] as const) {
      await page.goto(preview('SlidesDeckEmbedPreview', variant, 420));
      await waitForComponentPreview(page);
      const canvas = page.getByTestId('slides-deck-preview').getByTestId('slide-canvas');
      const box = await canvas.boundingBox();
      expect((box?.width ?? 0) / (box?.height ?? 1)).toBeCloseTo(ratio, 1);
      expect(box?.height ?? 0).toBeGreaterThan(100);
      const edge = await canvas.evaluate((el) => getComputedStyle(el, '::after').boxShadow);
      expect(edge).not.toBe('none');
      await testInfo.attach(`card-${name}`, { body: await page.screenshot(), contentType: 'image/png' });
    }
  });

  // contract-test: direct surface=gui.web assertions=slides.format.positioned-elements
  test('fullscreen strip shows scaled thumbnails fully inside the viewport (desktop and phone)', async ({ page }, testInfo) => {
    const viewports = [['desktop', 1280, 720], ['phone', 390, 844]] as const;
    for (const [name, vw, vh] of viewports) {
      for (const [aspectName, variant, ratio] of [['16x9', '', 16 / 9], ['16x10', 'aspect16x10', 16 / 10], ['4x3', 'aspect4x3', 4 / 3]] as const) {
        await page.setViewportSize({ width: vw, height: vh });
        await page.goto(preview('SlidesDeckEmbedFullscreen', variant, vw));
        await waitForComponentPreview(page);
        const items = page.getByTestId('slide-strip-item');
        await expect(items).toHaveCount(4);
        // The fullscreen slides in from below; measure only once it has settled.
        await page.waitForFunction(() => {
          const overlay = document.querySelector('.unified-embed-fullscreen-overlay');
          if (!overlay) return false;
          const transform = getComputedStyle(overlay).transform;
          return transform === 'none' || transform === 'matrix(1, 0, 0, 1, 0, 0)';
        });
        const first = await items.first().boundingBox();
        expect(first).not.toBeNull();
        expect((first?.width ?? 0) / (first?.height ?? 1)).toBeCloseTo(ratio, 1);
        expect(first?.height ?? 0).toBeGreaterThan(50);
        const thumb = await items.first().getByTestId('slide-canvas').boundingBox();
        expect((thumb?.width ?? 0) / (thumb?.height ?? 1)).toBeCloseTo(ratio, 1);
        expect((first?.y ?? 0) + (first?.height ?? 0)).toBeLessThanOrEqual(vh);
        const stage = await page.getByTestId('slides-deck-fullscreen').getByTestId('slide-canvas').first().boundingBox();
        expect((stage?.y ?? 0) + (stage?.height ?? 0)).toBeLessThanOrEqual(first?.y ?? 0);
        // The slide uses the free space instead of collapsing to its minimum.
        expect(stage?.height ?? 0).toBeGreaterThan(180);
        await testInfo.attach(`fullscreen-${name}-${aspectName}`, { body: await page.screenshot(), contentType: 'image/png' });
      }
    }
  });

  // contract-test: direct surface=gui.web assertions=slides.format.positioned-elements
  test('slides use the app font and the bare canvas has a visible edge', async ({ page }, testInfo) => {
    await page.goto(preview('SlideCanvas', '', 800));
    await waitForComponentPreview(page);
    const canvas = page.getByTestId('slide-canvas');
    const appFont = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
    const slideFont = await canvas.locator('.text-body').first().evaluate((el) => getComputedStyle(el).fontFamily);
    expect(slideFont).toBe(appFont);
    expect(await canvas.evaluate((el) => getComputedStyle(el, '::after').boxShadow)).not.toBe('none');
    await testInfo.attach('canvas-bare', { body: await page.screenshot(), contentType: 'image/png' });
  });
});
