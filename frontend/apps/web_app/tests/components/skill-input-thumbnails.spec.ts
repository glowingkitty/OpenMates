import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

// contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
test('source image strip opens the original image and fits mobile width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/embeds/InputEmbedThumbnails?theme=light&background=%23dbeafe&width=300&chrome=0');
  await waitForComponentPreview(page);
  const strip = page.getByTestId('skill-input-images');
  await expect(strip).toContainText('Image used');
  const button = strip.getByRole('button', { name: 'Open source image' });
  await expect(button).toBeEnabled();
  await expect.poll(() => strip.locator('img').evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
  await page.evaluate(() => document.addEventListener('imagefullscreen', ((event: CustomEvent) => {
    document.body.dataset.openedSource = `${event.detail.embedId}:${event.detail.filename}`;
  }) as EventListener));
  await button.hover();
  await button.focus();
  await expect(button).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('body')).toHaveAttribute('data-opened-source', 'call-source-preview-image:source-frame.jpg');
  const box = await strip.boundingBox();
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
});
