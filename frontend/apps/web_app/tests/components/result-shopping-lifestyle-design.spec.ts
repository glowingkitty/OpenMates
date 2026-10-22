import { expect, test } from '../helpers/cookie-audit';
import type { Page, TestInfo } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const previews = [
  { app: 'shopping', name: 'ShoppingResultEmbed', title: 'Bio Vollmilch-Joghurt Naturell' },
  { app: 'nutrition', name: 'NutritionRecipeEmbed', title: 'Spaghetti Aglio e Olio' },
  { app: 'fitness', name: 'FitnessResultEmbed', title: 'Morning Yoga Flow' },
];
async function mockPhotos(page: Page) {
  const response = await page.request.get('/images/examples/group1.jpg');
  expect(response.ok()).toBeTruthy();
  const body = await response.body();
  await page.route('**/api/v1/image?*', route => route.fulfill({ status: 200, contentType: 'image/jpeg', body }));
}
async function open(page: Page, app: string, name: string, width: number, variant?: string) {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(`/dev/preview/embeds/${app}/${name}?chrome=0&theme=light&width=${width}${variant ? `&variant=${variant}` : ''}`);
  await waitForComponentPreview(page);
}
async function checkpoint(page: Page, testInfo: TestInfo, name: string) {
  await testInfo.attach(name, {
    body: await page.screenshot({ animations: 'disabled' }),
    contentType: 'image/png',
  });
}
for (const width of [390, 1100]) {
  for (const result of previews) {
    // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    test(`${result.app} preview keeps image, fallback and long title inside ${width}px`, async ({ page }, testInfo) => {
      await mockPhotos(page);
      await open(page, result.app, `${result.name}Preview`, width);
      await expect(page.getByTestId('result-card-title')).toHaveText(result.title);
      const image = page.getByTestId('result-card-media').locator('img');
      await expect(image).toBeVisible();
      expect(new URL((await image.getAttribute('src'))!, page.url()).pathname).toBe('/api/v1/image');
      await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
      await checkpoint(page, testInfo, `${result.app}-preview-default-${width}px`);
      await open(page, result.app, `${result.name}Preview`, width, 'noImage');
      await expect(page.getByTestId('result-card-media')).toHaveCount(0);
      await expect(page.getByTestId('result-card-title')).toHaveText(result.title);
      await checkpoint(page, testInfo, `${result.app}-preview-no-image-${width}px`);
      await open(page, result.app, `${result.name}Preview`, width, 'longTitle');
      const card = page.getByTestId('embed-preview');
      const bounds = await card.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
      expect(await card.evaluate(el => el.scrollWidth <= el.clientWidth)).toBeTruthy();
    });
    // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    test(`${result.app} default fullscreen retains result content at ${width}px`, async ({ page }, testInfo) => {
      await mockPhotos(page);
      await open(page, result.app, `${result.name}Fullscreen`, width);
      await expect(page.getByTestId('result-embed-content')).toBeVisible();
      const image = result.app === 'shopping' ? page.getByTestId('shopping-product-image')
        : result.app === 'nutrition' ? page.getByTestId('nutrition-recipe-image')
        : page.locator('.fitness-detail-image');
      await expect(image).toBeVisible();
      await expect(image).toHaveCSS('object-fit', 'contain');
      await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
      if (result.app === 'shopping') {
        await expect(page.getByTestId('result-facts')).toContainText('1,39 €');
        await expect(page.getByTestId('shopping-product-gallery').getByRole('button')).toHaveCount(3);
      } else if (result.app === 'nutrition') {
        await expect(page.getByTestId('result-facts')).toContainText('25 min');
        await expect(page.locator('.ingredients-list li')).toHaveCount(6);
        await expect(page.locator('.instructions-list li')).toHaveCount(5);
      } else {
        await expect(page.getByTestId('result-facts')).toContainText('0.90 km');
        await expect(page.getByTestId('result-map')).toBeVisible();
        await expect(page.getByTestId('fitness-open-urban-sports')).toBeVisible();
      }
      await checkpoint(page, testInfo, `${result.app}-fullscreen-default-${width}px`);
    });
  }
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`shopping zero stock and price remain factual with accessible availability at ${width}px`, async ({ page }) => {
    await mockPhotos(page);
    await open(page, 'shopping', 'ShoppingResultEmbedFullscreen', width, 'zero');
    await expect(page.getByTestId('result-facts')).toContainText('0,00 €');
    await expect(page.getByTestId('result-facts')).toContainText('0');
    const availability = page.locator('.info-trigger[data-state="no"]').first();
    await availability.hover();
    await expect(page.getByRole('tooltip')).toBeVisible();
    await availability.focus();
    await expect(page.getByRole('tooltip')).toBeVisible();
    await availability.click();
    await expect(availability).toHaveAttribute('data-pinned', 'true');
    await page.keyboard.press('Escape');
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    await expect(page.getByTestId('shopping-product-image')).toHaveCSS('object-fit', 'contain');
    await expect(page.getByTestId('shopping-product-gallery').getByRole('button')).toHaveCount(3);
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`recipe details preserve all ingredients, steps and zero nutrients at ${width}px`, async ({ page }) => {
    await mockPhotos(page);
    await open(page, 'nutrition', 'NutritionRecipeEmbedFullscreen', width, 'zero');
    await expect(page.getByTestId('result-facts')).toContainText('0 min');
    await expect(page.locator('.ingredients-list li')).toHaveCount(6);
    await expect(page.locator('.instructions-list li')).toHaveCount(5);
    await expect(page.getByTestId('nutrition-recipe-details')).toContainText('0g');
    await expect(page.getByTestId('nutrition-recipe-image')).toHaveCSS('object-fit', 'contain');
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`fitness keeps class identity, zero distance and provider action at ${width}px`, async ({ page }) => {
    await mockPhotos(page);
    await open(page, 'fitness', 'FitnessResultEmbedFullscreen', width, 'zero');
    await expect(page.getByTestId('result-facts')).toContainText('0.00 km');
    await expect(page.getByTestId('result-facts')).toContainText('0 spots left');
    await expect(page.getByTestId('fitness-result-fullscreen')).toContainText('Yoga Studio Kreuzberg');
    await expect(page.getByTestId('fitness-open-urban-sports')).toHaveAttribute('href', 'https://urbansportsclub.com/en/venues/yoga-studio');
    await expect(page.getByTestId('result-map')).toBeVisible();
    await expect(page.locator('.fitness-detail-image')).toHaveCSS('object-fit', 'contain');
  });
}
// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('assistant result cards retain selectable copy and explicit expand', async ({ page }) => {
  await mockPhotos(page);
  for (const result of previews) {
    await open(page, result.app, `${result.name}Preview`, 1100, 'assistant');
    const card = page.getByTestId('embed-preview');
    await expect(page.getByTestId('result-preview-expand')).toBeVisible();
    await expect(page.getByTestId('result-preview-more')).toBeVisible();
    await expect(card).not.toHaveAttribute('role', 'button');
    await expect(page.getByTestId('result-card-title')).not.toHaveCSS('user-select', 'none');
  }
});
// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('missing result metadata stays absent and unavailable product state stays unknown', async ({ page }) => {
  await open(page, 'shopping', 'ShoppingResultEmbedFullscreen', 390, 'noPrice');
  const unknown = page.locator('.info-trigger[data-state="unknown"]');
  await expect(unknown).toHaveCount(1);
  await unknown.click();
  await expect(page.getByRole('tooltip')).toBeVisible();
  await expect(unknown).toHaveAttribute('data-pinned', 'true');
  await page.getByTestId('shopping-product-placeholder').click();
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await open(page, 'nutrition', 'NutritionRecipeEmbedFullscreen', 390, 'minimal');
  await expect(page.getByTestId('nutrition-recipe-image')).toHaveCount(0);
  await expect(page.locator('.ingredients-list')).toHaveCount(0);
  await expect(page.locator('.nutrition-grid')).toHaveCount(0);
  await open(page, 'fitness', 'FitnessResultEmbedFullscreen', 390, 'minimal');
  await expect(page.getByTestId('result-map')).toHaveCount(0);
  await expect(page.locator('.fitness-detail-image')).toHaveCount(0);
  await expect(page.getByTestId('fitness-open-urban-sports')).toHaveCount(0);
});
