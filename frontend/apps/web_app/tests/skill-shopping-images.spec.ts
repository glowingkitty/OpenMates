/** Saved shopping galleries remain usable without invoking unavailable search. */
import { test, expect } from './helpers/cookie-audit';
import { waitForComponentPreview } from './helpers/component-preview';

// contract-test: direct surface=gui.web assertions=shopping-search.products.supplied-gallery,app-skills.history.renderable
test('historical gallery keeps every distinct supplied photo and supports selection', async ({ page }) => {
  await page.goto('/dev/preview/embeds/shopping/ShoppingResultEmbedFullscreen?chrome=0&width=390');
  await waitForComponentPreview(page);
  const gallery = page.getByTestId('shopping-product-gallery');
  const thumbnails = gallery.getByRole('button');
  await expect(thumbnails).toHaveCount(3);
  await expect(thumbnails.first()).toHaveAttribute('aria-pressed', 'true');
  await thumbnails.nth(2).click();
  await expect(thumbnails.nth(2)).toHaveAttribute('aria-pressed', 'true');
  await expect(thumbnails.first()).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByTestId('result-embed-content')).toContainText('1,39');
});
