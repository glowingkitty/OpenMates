import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed

const PREVIEW = '/dev/preview/embeds/images/ImageGenerateEmbedPreview?chrome=0&theme=light&background=%23dbeafe';
const FULLSCREEN = '/dev/preview/embeds/images/ImageGenerateEmbedFullscreen?chrome=0&theme=light&background=%23dbeafe';
test.use({ viewport: { width: 1000, height: 800 }, trace: 'retain-on-failure' });

type Box = { x: number; y: number; width: number; height: number };

function overlaps(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/** The visible picture of an `object-fit: contain` image, without its letterbox bars. */
function visiblePicture(img: import('@playwright/test').Locator): Promise<Box> {
  return img.evaluate((el: HTMLImageElement) => {
    const r = el.getBoundingClientRect();
    const scale = Math.min(r.width / el.naturalWidth, r.height / el.naturalHeight);
    const w = el.naturalWidth * scale;
    const h = el.naturalHeight * scale;
    return { x: r.x + (r.width - w) / 2, y: r.y + (r.height - h) / 2, width: w, height: h };
  });
}

function expectInside(inner: Box, outer: Box) {
  expect(inner.x).toBeGreaterThanOrEqual(outer.x - 1);
  expect(inner.x + inner.width).toBeLessThanOrEqual(outer.x + outer.width + 1);
  expect(inner.y).toBeGreaterThanOrEqual(outer.y - 1);
  expect(inner.y + inner.height).toBeLessThanOrEqual(outer.y + outer.height + 1);
}

async function open(page: import('@playwright/test').Page, base: string, query = '') {
  await page.goto(`${base}${query}&width=420`);
  await waitForComponentPreview(page);
}

// contract-test: supporting surface=gui.web assertions=images-generate.provenance.ai-label
test('marks a finished generated image preview without covering its buttons or version badge', async ({ page }, testInfo) => {
  await open(page, PREVIEW, '&variant=versionTwoOfThree');
  const card = page.getByTestId('embed-preview').first();
  const badge = card.getByTestId('ai-generated-badge');
  await expect(badge).toBeVisible();
  await expect(badge).toHaveAccessibleName(/AI generated/);
  await expect(badge).toHaveAttribute('aria-expanded', 'false');
  const badgeBox = (await badge.boundingBox())!;
  // The picture is letterboxed (object-fit: contain): the badge must sit on the visible picture, not on the bars.
  expectInside(badgeBox, await visiblePicture(card.getByTestId('image-generate-preview-image')));
  const others = [card.getByTestId('result-preview-expand'), card.getByTestId('preview-tools'), card.getByTestId('image-generate-version-badge')];
  for (const other of others) {
    if ((await other.count()) === 0) continue;
    const box = await other.first().boundingBox();
    if (box) expect(overlaps(badgeBox, box)).toBe(false);
  }
  await testInfo.attach('ai-generated-badge-preview-collapsed', { body: await card.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=images-generate.provenance.ai-label
test('expands the preview badge on click and shows the label', async ({ page }, testInfo) => {
  await open(page, PREVIEW);
  const card = page.getByTestId('embed-preview').first();
  const badge = card.getByTestId('ai-generated-badge');
  await badge.click();
  await expect(badge).toHaveAttribute('aria-expanded', 'true');
  await expect(badge.getByText('AI generated', { exact: true })).toBeVisible();
  await testInfo.attach('ai-generated-badge-preview-expanded', { body: await card.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=images-generate.provenance.ai-label
test('shows the badge over the image in fullscreen', async ({ page }, testInfo) => {
  await open(page, FULLSCREEN);
  const badge = page.getByTestId('ai-generated-badge').first();
  await expect(badge).toBeVisible();
  // On the visible picture, not on the margin beside a letterboxed image.
  const fullImage = page.locator('img.full-image').first();
  await expect.poll(() => fullImage.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
  await expect.poll(async () => {
    const [b, p] = [(await badge.boundingBox())!, await visiblePicture(fullImage)];
    return b.x >= p.x - 1 && b.y >= p.y - 1 && b.x + b.width <= p.x + p.width + 1 && b.y + b.height <= p.y + p.height + 1;
  }).toBe(true);
  expectInside((await badge.boundingBox())!, await visiblePicture(fullImage));
  await testInfo.attach('ai-generated-badge-fullscreen-collapsed', { body: await page.screenshot(), contentType: 'image/png' });
  await badge.click();
  await expect(badge.getByText('AI generated', { exact: true })).toBeVisible();
  await testInfo.attach('ai-generated-badge-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
});
