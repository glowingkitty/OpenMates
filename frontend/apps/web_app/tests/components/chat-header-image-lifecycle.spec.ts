import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('bounds failed image decoding across equivalent streamed metadata updates', async ({ page }) => {
  await page.addInitScript(() => {
    const state = window as typeof window & { headerImageDecodeCount: number };
    state.headerImageDecodeCount = 0;
    Image.prototype.decode = function () {
      if (this.src.includes('header-image-lifecycle-unavailable')) {
        state.headerImageDecodeCount += 1;
        return Promise.reject(new DOMException('Unavailable fixture image', 'EncodingError'));
      }
      return Promise.resolve();
    };
  });
  await page.route('**/header-image-lifecycle-unavailable.jpg', route => route.fulfill({ status: 404, body: '' }));
  await page.goto('/dev/preview/ChatHeaderImageLifecyclePreviewHarness?theme=light&background=%23dbeafe&width=520&chrome=0');
  await waitForComponentPreview(page);
  const decodeCount = () => page.evaluate(() =>
    (window as typeof window & { headerImageDecodeCount: number }).headerImageDecodeCount);
  await expect.poll(decodeCount).toBe(1);
  for (let index = 0; index < 12; index += 1) {
    await page.evaluate(async () => {
      window.dispatchEvent(new Event('preview:header-refresh'));
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    });
  }
  expect(await decodeCount()).toBe(1);
  await expect(page.getByTestId('chat-header-title')).toHaveText('Capoeira classes');
  await expect(page.getByTestId('component-preview-canvas')).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event('preview:header-switch-chat')));
  await expect.poll(decodeCount).toBe(2);
  await page.screenshot({ path: test.info().outputPath('header-with-unavailable-image.png') });
});
