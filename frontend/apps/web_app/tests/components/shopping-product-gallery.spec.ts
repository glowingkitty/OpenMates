import { expect, test } from '../helpers/cookie-audit';
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const productPreview = '/dev/preview/embeds/shopping/ShoppingResultEmbedFullscreen';
const searchPreview = '/dev/preview/embeds/shopping/ShoppingSearchEmbedFullscreen';
const photos = ['/store-examples/generate-1.webp', '/store-examples/events-1.webp', '/store-examples/generate-draft-1.webp'];
const transportPhotos = ['front', 'back', 'detail'].map((view) => `https://shopping.example/product-${view}.jpg`);

async function mockTransportPhotos(page: Page) {
  const fixture = await page.request.get('/images/examples/group1.jpg');
  expect(fixture.ok()).toBeTruthy();
  const bytes = await fixture.body();
  await page.route('**/api/v1/image?*', (route) => new URL(route.request().url()).searchParams.get('url')?.startsWith('https://shopping.example/')
    ? route.fulfill({ status: 200, contentType: 'image/jpeg', body: bytes }) : route.fallback());
}

async function expectPhoto(page: Page, index: number, external = false) {
  const image = page.getByTestId('shopping-product-image');
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  const source = new URL((await image.getAttribute('src'))!, page.url());
  if (external) {
    expect(source.pathname).toBe('/api/v1/image');
    expect(source.searchParams.get('url')).toBe(transportPhotos[index]);
    expect(source.searchParams.get('max_width')).toBe('1200');
  } else expect(source.pathname).toBe(photos[index]);
}

for (const { width, theme } of [{ width: 1100, theme: 'light' }, { width: 390, theme: 'dark' }]) {
  // specification: feature.app-skill.shopping-search@1
  // contract-test: supporting surface=gui.web assertions=shopping-search.products.supplied-gallery
  test(`all supplied shopping photos support pointer and keyboard navigation at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
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
    const images = gallery.locator('img');
    expect(await images.evaluateAll(nodes => nodes.map(node => node.getAttribute('src')))).toEqual(photos);
    await expect.poll(() => images.evaluateAll(nodes => nodes.every(node =>
      (node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth > 0
    ))).toBe(true);
  });
}

// specification: feature.app-skill.shopping-search@1
// contract-test: supporting surface=gui.web assertions=shopping-search.products.supplied-gallery
test('TOON decoded galleries, primary-only products and missing photos retain compatibility', async ({ page }) => {
  await mockTransportPhotos(page);
  const config = 'theme=light&background=%23dbeafe&width=1100&chrome=0';
  await page.goto(`${productPreview}?${config}&variant=toonGallery`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('shopping-product-gallery').getByRole('button')).toHaveCount(3);
  await page.getByTestId('shopping-product-gallery').getByRole('button').nth(2).click();
  await expectPhoto(page, 2, true);
  for (const image of await page.getByTestId('shopping-product-gallery').locator('img').all()) {
    const source = new URL((await image.getAttribute('src'))!, page.url());
    expect(source.pathname).toBe('/api/v1/image');
    expect(source.searchParams.get('max_width')).toBe('120');
  }
  await page.unroute('**/api/v1/image?*');
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
  await page.route(`**${photos[0]}`, route => route.fulfill({ status: 404, body: '' }));
  await page.goto(`${productPreview}?theme=light&background=%23dbeafe&width=1100&chrome=0`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('shopping-product-placeholder')).toBeVisible();
  await page.getByTestId('shopping-product-gallery').getByRole('button').nth(1).click();
  await expectPhoto(page, 1);
});
