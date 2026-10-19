import { expect, test } from '../helpers/cookie-audit';
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const productPreview = '/dev/preview/embeds/shopping/ShoppingResultEmbedFullscreen';
const searchPreview = '/dev/preview/embeds/shopping/ShoppingSearchEmbedFullscreen';
const photos = ['front', 'back', 'detail'].map((view) => `https://shopping.example/product-${view}.jpg`);

async function mockPhotos(page: Page) {
  const fixture = await page.request.get('/images/examples/group1.jpg');
  expect(fixture.ok()).toBeTruthy();
  const bytes = await fixture.body();
  await page.route('**/api/v1/image?*', (route) => route.fulfill({
    status: 200, contentType: 'image/jpeg', body: bytes,
  }));
}

async function expectPhoto(page: Page, index: number) {
  const image = page.getByTestId('shopping-product-image');
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  const source = new URL((await image.getAttribute('src'))!, page.url());
  expect(source.pathname).toBe('/api/v1/image');
  expect(source.searchParams.get('url')).toBe(photos[index]);
  expect(source.searchParams.get('max_width')).toBe('1200');
}

for (const { width, theme } of [{ width: 1100, theme: 'light' }, { width: 390, theme: 'dark' }]) {
  // specification: feature.app-skill.shopping-search@1
  // contract-test: supporting surface=gui.web assertions=shopping-search.products.supplied-gallery
  test(`all supplied shopping photos support pointer and keyboard navigation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockPhotos(page);
    await page.goto(`${productPreview}?theme=${theme}&background=%23dbeafe&width=${width}&chrome=0`);
    await waitForComponentPreview(page);
    await expectPhoto(page, 0);
    const gallery = page.getByTestId('shopping-product-gallery');
    const thumbnails = gallery.getByRole('button');
    await expect(thumbnails).toHaveCount(3);
    await expect(thumbnails.nth(0)).toHaveAttribute('aria-pressed', 'true');
    await thumbnails.nth(1).hover();
    await thumbnails.nth(1).click();
    await expectPhoto(page, 1);
    await expect(thumbnails.nth(1)).toHaveAttribute('aria-pressed', 'true');
    await thumbnails.nth(1).focus();
    await page.keyboard.press('ArrowRight');
    await expectPhoto(page, 2);
    await expect(thumbnails.nth(2)).toBeFocused();
    await page.keyboard.press('ArrowRight');
    await expectPhoto(page, 0);
    await page.keyboard.press('End');
    await expectPhoto(page, 2);
    await page.keyboard.press('Home');
    await expectPhoto(page, 0);
    await page.keyboard.press('ArrowLeft');
    await expectPhoto(page, 2);
    await expect(page.locator('.gallery-counter')).toHaveText('3 / 3');
    const box = await gallery.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    for (const image of await gallery.locator('img').all()) {
      const source = new URL((await image.getAttribute('src'))!, page.url());
      expect(source.pathname).toBe('/api/v1/image');
      expect(source.searchParams.get('max_width')).toBe('120');
    }
  });
}

// specification: feature.app-skill.shopping-search@1
// contract-test: supporting surface=gui.web assertions=shopping-search.products.supplied-gallery
test('TOON decoded galleries, primary-only products and missing photos retain compatibility', async ({ page }) => {
  await mockPhotos(page);
  const config = 'theme=light&background=%23dbeafe&width=1100&chrome=0';
  await page.goto(`${productPreview}?${config}&variant=toonGallery`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('shopping-product-gallery').getByRole('button')).toHaveCount(3);
  await page.getByTestId('shopping-product-gallery').getByRole('button').nth(2).click();
  await expectPhoto(page, 2);
  await page.goto(`${productPreview}?${config}&variant=primaryOnly`);
  await waitForComponentPreview(page);
  await expectPhoto(page, 0);
  await expect(page.getByTestId('shopping-product-gallery')).toHaveCount(0);
  await page.goto(`${productPreview}?${config}&variant=missingImages`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('shopping-product-placeholder')).toBeVisible();
  await expect(page.getByTestId('shopping-product-image')).toHaveCount(0);
  await expect(page.getByTestId('shopping-product-gallery')).toHaveCount(0);
});

// specification: feature.app-skill.shopping-search@1
// contract-test: supporting surface=gui.web assertions=shopping-search.products.supplied-gallery
test('search child fullscreens retain their supplied gallery and reset on product navigation', async ({ page }) => {
  await mockPhotos(page);
  await page.goto(`${searchPreview}?theme=light&background=%23dbeafe&width=1100&chrome=0`);
  await waitForComponentPreview(page);
  const cards = page.getByTestId('search-template-grid').getByTestId('embed-preview');
  await expect(cards).toHaveCount(4);
  await cards.first().click();
  const gallery = page.getByTestId('shopping-product-gallery');
  await expect(gallery.getByRole('button')).toHaveCount(3);
  await gallery.getByRole('button').nth(2).click();
  await expectPhoto(page, 2);
  await page.getByRole('button', { name: 'Next embed', exact: true }).last().click();
  await expect(gallery).toHaveCount(0);
  await expect(page.getByTestId('shopping-product-placeholder')).toBeVisible();
  await page.getByRole('button', { name: 'Previous embed', exact: true }).last().click();
  await expectPhoto(page, 0);
});

// specification: feature.app-skill.shopping-search@1
// contract-test: supporting surface=gui.web assertions=shopping-search.products.supplied-gallery
test('a failed photo leaves the remaining gallery selectable', async ({ page }) => {
  await mockPhotos(page);
  await page.route('**/api/v1/image?*', (route) => {
    const source = new URL(route.request().url());
    return source.searchParams.get('url') === photos[0]
      ? route.fulfill({ status: 404, body: '' }) : route.fallback();
  });
  await page.goto(`${productPreview}?theme=light&background=%23dbeafe&width=1100&chrome=0`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('shopping-product-placeholder')).toBeVisible();
  await page.getByTestId('shopping-product-gallery').getByRole('button').nth(1).click();
  await expectPhoto(page, 1);
});
