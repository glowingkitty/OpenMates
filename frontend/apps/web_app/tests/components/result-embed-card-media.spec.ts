// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const WIDTHS = [390, 330, 1100]; // phone, narrow chat column, wide
const VARIANTS = ['squareLogo', 'wideBanner', 'tallPoster', 'brokenImage'] as const;
const CARD_HEIGHT = 200; // the compact result card height

function previewUrl(variant: string, theme: 'light' | 'dark', width: number) {
  const background = theme === 'dark' ? '%2318202c' : '%23dbeafe';
  return `/dev/preview/embeds/ResultEmbedCard?theme=${theme}&background=${background}&width=${width}&chrome=0&variant=${variant}`;
}

for (const width of WIDTHS) for (const theme of ['light', 'dark'] as const) for (const variant of VARIANTS) {
  // contract-test: direct surface=gui.web assertions=authored-results.presentation.whole-image-and-title
  test(`result card ${variant} shows its whole image and its title at ${width}px ${theme}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: Math.max(width, 390), height: 900 });
    await page.goto(previewUrl(variant, theme, width));
    await waitForComponentPreview(page);
    const card = page.getByTestId('result-card-content').first();
    await expect(card).toBeVisible();
    // The compact card is 200px high; the harness pins it the way the results view does.
    await card.evaluate((element, height) => { (element as HTMLElement).style.height = `${height}px`; }, CARD_HEIGHT);

    const cardBox = (await card.boundingBox())!;
    expect(cardBox.height).toBeCloseTo(CARD_HEIGHT, 0);

    // The title is always shown, non-empty and inside the card, whatever the image is.
    const title = card.getByTestId('result-card-title');
    await expect(title).toBeVisible();
    await expect(title).not.toHaveText('');
    const titleBox = (await title.boundingBox())!;
    expect(titleBox.width).toBeGreaterThan(20);
    expect(titleBox.height).toBeGreaterThan(10);
    expect(titleBox.x).toBeGreaterThanOrEqual(cardBox.x - 1);
    expect(titleBox.y).toBeGreaterThanOrEqual(cardBox.y - 1);
    expect(titleBox.x + titleBox.width).toBeLessThanOrEqual(cardBox.x + cardBox.width + 1);
    expect(titleBox.y + titleBox.height).toBeLessThanOrEqual(cardBox.y + cardBox.height + 1);
    // A title is clamped to two lines (line-height 1.25 of the heading size).
    const lineHeight = await title.evaluate(element => parseFloat(getComputedStyle(element).lineHeight));
    expect(titleBox.height).toBeLessThanOrEqual(lineHeight * 2 + 2);

    const media = card.getByTestId('result-card-media');
    if (variant === 'brokenImage') {
      // A failed image is dropped: no media area, no broken-image icon, title still present.
      await expect(media).toHaveCount(0);
      await expect(card.getByRole('img', { name: 'Event illustration' })).toHaveCount(0);
    } else {
      const image = media.locator('img');
      await expect(image).toBeVisible();
      await expect.poll(() => image.evaluate(element => (element as HTMLImageElement).complete
        && (element as HTMLImageElement).naturalWidth > 0)).toBe(true);
      // Whole image: contain, letterboxed, pinned to the media box.
      await expect(image).toHaveCSS('object-fit', 'contain');
      await expect(image).toHaveCSS('position', 'absolute');
      await expect(media).toHaveCSS('background-color', theme === 'dark' ? 'rgb(0, 0, 0)' : 'rgb(255, 255, 255)');
      const mediaBox = (await media.boundingBox())!;
      const imageBox = (await image.boundingBox())!;
      expect(mediaBox.width).toBeGreaterThan(40);
      expect(mediaBox.height).toBeGreaterThan(40);
      expect(imageBox.x).toBeGreaterThanOrEqual(mediaBox.x - 1);
      expect(imageBox.y).toBeGreaterThanOrEqual(mediaBox.y - 1);
      expect(imageBox.x + imageBox.width).toBeLessThanOrEqual(mediaBox.x + mediaBox.width + 1);
      expect(imageBox.y + imageBox.height).toBeLessThanOrEqual(mediaBox.y + mediaBox.height + 1);
      expect(imageBox.width).toBeCloseTo(mediaBox.width, 0);
      expect(imageBox.height).toBeCloseTo(mediaBox.height, 0);
      // The media area never covers the title.
      if (width <= 400) expect(mediaBox.y + mediaBox.height).toBeLessThanOrEqual(titleBox.y + 1);
    }
    await testInfo.attach(`result-card-${variant}-${width}-${theme}`, {
      body: await card.screenshot({ animations: 'disabled' }), contentType: 'image/png',
    });
  });
}
