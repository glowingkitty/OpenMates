import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const PREVIEW = '/dev/preview/embeds/images/ImageGenerateEmbedPreview?chrome=0&theme=light&background=%23dbeafe';
const FULLSCREEN = '/dev/preview/embeds/images/ImageGenerateEmbedFullscreen?chrome=0&theme=light&background=%23dbeafe';
test.use({ viewport: { width: 1000, height: 800 }, trace: 'retain-on-failure' });

type Box = { x: number; y: number; width: number; height: number };

function overlaps(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
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
  const picture: Box = await card.getByTestId('image-generate-preview-image').evaluate((img: HTMLImageElement) => {
    const r = img.getBoundingClientRect();
    const scale = Math.min(r.width / img.naturalWidth, r.height / img.naturalHeight);
    const w = img.naturalWidth * scale;
    const h = img.naturalHeight * scale;
    return { x: r.x + (r.width - w) / 2, y: r.y + (r.height - h) / 2, width: w, height: h };
  });
  expect(badgeBox.x).toBeGreaterThanOrEqual(picture.x - 1);
  expect(badgeBox.x + badgeBox.width).toBeLessThanOrEqual(picture.x + picture.width + 1);
  expect(badgeBox.y).toBeGreaterThanOrEqual(picture.y - 1);
  expect(badgeBox.y + badgeBox.height).toBeLessThanOrEqual(picture.y + picture.height + 1);
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
  const badgeBox = (await badge.boundingBox())!;
  const imageBox = (await page.locator('img.full-image').first().boundingBox())!;
  expect(badgeBox.x).toBeGreaterThanOrEqual(imageBox.x - 1);
  expect(badgeBox.x + badgeBox.width).toBeLessThanOrEqual(imageBox.x + imageBox.width + 1);
  expect(badgeBox.y).toBeGreaterThanOrEqual(imageBox.y - 1);
  await badge.click();
  await expect(badge.getByText('AI generated', { exact: true })).toBeVisible();
  await testInfo.attach('ai-generated-badge-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
});
