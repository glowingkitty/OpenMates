// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('SVG code cards render as image cards and open the image viewer', async ({ page }) => {
  await page.goto('/dev/preview/embeds/code/CodeEmbedPreview?chrome=0&variant=svg&width=520');
  await waitForComponentPreview(page);
  const image = page.locator('img.preview-image');
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBe(240);
  await expect(page.locator('.code-preview')).toHaveCount(0);
  await page.evaluate(() => document.addEventListener('imagefullscreen', event => {
    (window as Window & { svgFullscreen?: unknown }).svgFullscreen = (event as CustomEvent).detail;
  }, { once: true }));
  await page.getByTestId('embed-preview').hover();
  await page.getByTestId('embed-preview').click();
  await expect.poll(() => page.evaluate(() => (window as Window & { svgFullscreen?: { fileType: string } }).svgFullscreen?.fileType)).toBe('image/svg+xml');
});

for (const variant of ['svgFenced', 'svgUnlabelled', 'svgSavedCode']) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  test(`${variant} displays an SVG image immediately and after reload`, async ({ page }) => {
    await page.goto(`/dev/preview/ReadOnlyMessage?chrome=0&variant=${variant}&width=520`);
    await waitForComponentPreview(page);
    for (const reload of [false, true]) {
      if (reload) { await page.reload(); await waitForComponentPreview(page); }
      const message = page.getByTestId('message-content');
      const image = message.locator('img.preview-image');
      await expect(image).toBeVisible();
      await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBe(240);
      await expect(message.locator('.code-preview')).toHaveCount(0);
      await expect(message).not.toContainText('<svg');
    }
    if (variant === 'svgSavedCode') {
      await page.evaluate(() => document.dispatchEvent(new CustomEvent('preview:update-svg-code')));
      await expect.poll(() => page.getByTestId('message-content').locator('img.preview-image')
        .evaluate((node: HTMLImageElement) => node.naturalWidth)).toBe(320);
      await page.evaluate(() => document.dispatchEvent(new CustomEvent('preview:svg-to-html')));
      await expect(page.getByTestId('message-content').locator('img.preview-image')).toHaveCount(0);
      await expect(page.getByTestId('message-content').locator('.code-details')).toBeVisible();
    }
  });
}
