import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { readFile } from 'node:fs/promises';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
test('reviewed public PDF has a readable page preview and original download', async ({ page }) => {
  const pdfPath = '/store-examples/community-garden-budget.pdf';
  const pageImagePath = '/store-examples/community-garden-budget-page-1.png';
  const [pdfResponse, imageResponse] = await Promise.all([
    page.request.get(pdfPath),
    page.request.get(pageImagePath),
  ]);
  expect(pdfResponse.ok()).toBe(true);
  expect(pdfResponse.headers()['content-type']).toContain('application/pdf');
  const pdfBytes = await pdfResponse.body();
  expect(pdfBytes.subarray(0, 8).toString()).toBe('%PDF-1.4');
  expect(pdfBytes.toString()).toContain('Community Garden Volunteer Budget');
  expect(imageResponse.ok()).toBe(true);
  expect(imageResponse.headers()['content-type']).toContain('image/png');
  expect((await imageResponse.body()).byteLength).toBeGreaterThan(10_000);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/embeds/pdf/PDFEmbedPreview?variant=guest&theme=light&background=%23dbeafe&width=390&chrome=0');
  await waitForComponentPreview(page);
  const preview = page.getByTestId('pdf-public-preview');
  const previewPage = page.getByTestId('pdf-public-preview-page');
  await expect(preview).toBeVisible();
  await expect(previewPage).toHaveAttribute('src', pageImagePath);
  await expect.poll(() => previewPage.evaluate((image) => (image as HTMLImageElement).naturalWidth)).toBe(1224);
  await expect(previewPage).toHaveCSS('object-position', '50% 0%');
  await page.screenshot({ path: test.info().outputPath('pdf-public-preview-phone.png') });

  await page.goto('/dev/preview/embeds/pdf/PDFEmbedFullscreen?variant=guest&theme=light&background=%23dbeafe&width=390&chrome=0');
  await waitForComponentPreview(page);
  const fullPage = page.getByTestId('pdf-public-page');
  await expect(fullPage).toBeVisible();
  await expect(fullPage).toHaveAttribute('src', pageImagePath);
  await expect.poll(() => fullPage.evaluate((image) => (image as HTMLImageElement).naturalHeight)).toBe(1584);
  const downloadLink = page.getByTestId('pdf-public-download');
  await expect(downloadLink).toHaveAttribute('href', pdfPath);
  const [download] = await Promise.all([page.waitForEvent('download'), downloadLink.click()]);
  expect(download.suggestedFilename()).toBe('community-garden-budget.pdf');
  const downloadedBytes = await readFile(await download.path());
  expect(downloadedBytes.subarray(0, 8).toString()).toBe('%PDF-1.4');
  expect(downloadedBytes.toString()).toContain('Community Garden Volunteer Budget');
  const scrollPane = page.getByTestId('pdf-public-document');
  await expect(scrollPane).toBeVisible();
  expect((await fullPage.boundingBox())!.width).toBeGreaterThanOrEqual(700);
  expect(await scrollPane.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('pdf-public-fullscreen-phone.png') });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/dev/preview/embeds/pdf/PDFEmbedFullscreen?variant=guest&theme=light&background=%23dbeafe&width=900&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('pdf-public-page')).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('pdf-public-fullscreen-laptop.png') });
});

// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
test('public PDF path is rejected for untrusted URLs and encrypted uploads', async ({ page }) => {
  await page.goto('/dev/preview/embeds/pdf/PDFEmbedPreview?variant=untrustedUrl&theme=light&background=%23dbeafe&width=390&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('pdf-public-preview-page')).toHaveCount(0);
  await expect(page.locator('.pdf-icon-center')).toBeVisible();

  await page.goto('/dev/preview/embeds/pdf/PDFEmbedFullscreen?variant=untrustedUrl&theme=light&background=%23dbeafe&width=390&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('pdf-public-document')).toHaveCount(0);
  await expect(page.getByTestId('pdf-info-fallback')).toBeVisible();

  await page.goto('/dev/preview/embeds/pdf/PDFEmbedFullscreen?variant=encrypted&theme=light&background=%23dbeafe&width=390&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('pdf-public-document')).toHaveCount(0);
  await expect(page.getByTestId('pdf-info-fallback')).toBeVisible();
});

for (const width of [700, 1280]) {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,chats.rendering.inline-entity-interaction
  test(`wide PDF preview preserves the whole horizontally centered page at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/dev/preview/embeds/pdf/PDFEmbedPreview?variant=guest&width=${width}&chrome=0&context=chat`);
    await waitForComponentPreview(page);
    const pageImage = page.getByTestId('pdf-public-preview-page');
    await expect.poll(() => pageImage.evaluate(image => image.parentElement!.clientWidth)).toBeGreaterThan(400);
    await expect.poll(() => pageImage.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(1224);
    await expect(pageImage).toHaveCSS('object-fit', 'contain');
    await expect(pageImage).toHaveCSS('object-position', '50% 0%');
    const geometry = await pageImage.evaluate(element => {
      const image = element as HTMLImageElement;
      const frame = image.parentElement!.getBoundingClientRect();
      const box = image.getBoundingClientRect();
      const scale = Math.min(box.width / image.naturalWidth, box.height / image.naturalHeight);
      const pageWidth = image.naturalWidth * scale;
      const pageHeight = image.naturalHeight * scale;
      return { centerDelta: Math.abs((box.left + box.right) / 2 - (frame.left + frame.right) / 2),
        pageWidth, pageHeight, imageWidth: box.width, imageHeight: box.height, frameWidth: frame.width, frameHeight: frame.height };
    });
    expect(geometry.centerDelta).toBeLessThanOrEqual(1);
    expect(geometry.imageWidth).toBeLessThanOrEqual(geometry.frameWidth + 1);
    expect(geometry.imageHeight).toBeLessThanOrEqual(geometry.frameHeight + 1);
    expect(geometry.pageWidth).toBeGreaterThan(0);
    expect(geometry.pageWidth).toBeLessThan(geometry.frameWidth);
    expect(geometry.pageHeight).toBeLessThanOrEqual(geometry.frameHeight + 1);
    await testInfo.attach(`pdf-centered-wide-${width}`, { body: await page.getByTestId('component-preview-canvas').screenshot(), contentType: 'image/png' });
  });
}
