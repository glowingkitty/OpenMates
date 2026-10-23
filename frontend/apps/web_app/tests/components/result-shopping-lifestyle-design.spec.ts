import { expect, test } from '../helpers/cookie-audit';
import type { Page, TestInfo } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const previews = [
  { app: 'shopping', name: 'ShoppingResultEmbed', title: 'Bio Vollmilch-Joghurt Naturell', image: '/store-examples/generate-1.webp' },
  { app: 'nutrition', name: 'NutritionRecipeEmbed', title: 'Spaghetti Aglio e Olio', image: '/store-examples/generate-1.webp' },
  { app: 'fitness', name: 'FitnessResultEmbed', title: 'Morning Yoga Flow', image: '/store-examples/home-2.webp' },
];
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
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`fitness search preview keeps only query, provider and count at ${width}px`, async ({ page }, testInfo) => {
    await open(page, 'fitness', 'FitnessSearchEmbedPreview', width);
    const body = page.getByTestId('fitness-search-preview');
    await expect(body.locator(':scope > *')).toHaveCount(3);
    await expect(body.locator('.fitness-search-query')).toHaveText('yoga near Sorauer Str. 12');
    await expect(body.locator('.fitness-search-provider')).toHaveText('Urban Sports Club');
    await expect(body.getByTestId('fitness-search-result-count')).toHaveText('2 classes');
    await expect(body).not.toContainText('Morning Yoga Flow');
    await expect(body).not.toContainText('Searched all Urban Sports plans');
    await expect(body.locator('.fitness-search-chips')).toHaveCount(0);
    const bounded = await body.evaluate(el => {
      const bounds = el.getBoundingClientRect();
      return [...el.children].every(child => {
        const childBounds = child.getBoundingClientRect();
        return childBounds.left >= bounds.left && childBounds.right <= bounds.right + 1 && childBounds.bottom <= bounds.bottom + 1;
      });
    });
    expect(bounded).toBe(true);
    await checkpoint(page, testInfo, `fitness-search-minimal-${width}px`);
    await open(page, 'fitness', 'FitnessSearchEmbedPreview', width, 'processing');
    await expect(body.getByTestId('fitness-search-result-count')).toHaveCount(0);
    await expect(body.locator('.fitness-search-query')).toBeVisible();
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`fitness result uses supplied venue fallback and class image precedence at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const base = `/dev/preview/embeds/fitness/FitnessResultEmbedPreview?chrome=0&theme=light&width=${width}`;
    for (const source of [
      { venue_image_url: '/store-examples/home-2.webp', expected: '/store-examples/home-2.webp' },
      { class_image_url: '/store-examples/generate-1.webp', venue_image_url: '/store-examples/home-2.webp', expected: '/store-examples/generate-1.webp' },
    ]) {
      const props = encodeURIComponent(JSON.stringify({ result: { name: 'Supplied class', time_range: '07:30 - 08:30', venue_name: 'Yoga Studio', ...source }, skillId: 'search_classes' }));
      await page.goto(`${base}&props=${props}`);
      await waitForComponentPreview(page);
      const image = page.getByTestId('result-card-media').locator('img');
      await expect(image).toHaveAttribute('src', source.expected);
      await expect.poll(() => image.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0);
      await expect(page.locator('.fitness-extra-facts')).toBeHidden();
      await expect(page.getByTestId('fitness-class-time')).toHaveText('07:30');
      await expect(page.getByTestId('fitness-class-venue')).toHaveText('Yoga Studio');
    }
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`fitness class calendar and time/venue stay visible without inventing dates at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const path = `/dev/preview/embeds/fitness/FitnessResultEmbedPreview?chrome=0&theme=light&width=${width}&context=chat`;
    await page.goto(path);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('embed-calendar-date')).toHaveAttribute('datetime', '2026-07-10T00:00:00.000Z');
    await expect(page.getByTestId('result-card-content')).not.toContainText('2026-07-10');
    const time = page.getByTestId('fitness-class-time');
    const venue = page.getByTestId('fitness-class-venue');
    await expect(time).toBeVisible();
    await expect(time).toHaveText('07:30');
    await expect(time).toHaveAttribute('title', '07:30 - 08:30');
    await expect(venue).toBeVisible();
    await expect(venue).toHaveText('Yoga Studio Kreuzberg');
    expect(await venue.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    expect(await time.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    if (width > 401) expect((await page.getByTestId('embed-preview').boundingBox())!.width).toBeGreaterThan(401);
    await checkpoint(page, testInfo, `fitness-class-calendar-${width}px`);
    for (const date of [undefined, 'not-a-date', '2026-02-30']) {
      const props = encodeURIComponent(JSON.stringify({ result: {
        name: 'Morning Yoga Flow', date, time_range: '07:30 - 08:30', venue_name: 'Yoga Studio Kreuzberg',
        image_url: '/store-examples/home-2.webp',
      }, skillId: 'search_classes' }));
      await page.goto(`${path}&props=${props}`);
      await waitForComponentPreview(page);
      await expect(page.getByTestId('embed-calendar-date')).toHaveCount(0);
      await expect(time).toBeVisible();
      await expect(venue).toBeVisible();
    }
    const gymProps = encodeURIComponent(JSON.stringify({ skillId: 'search_locations', result: {
      name: 'Local gym', date: '2026-07-10', time_range: '07:30 - 08:30', image_url: '/store-examples/home-2.webp',
    } }));
    await page.goto(`${path}&props=${gymProps}`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('embed-calendar-date')).toHaveCount(0);
    await expect(time).toHaveCount(0);
    await expect(venue).toHaveCount(0);
  });
  for (const result of previews) {
    // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    test(`${result.app} preview keeps image, fallback and long title inside ${width}px`, async ({ page }, testInfo) => {
      await open(page, result.app, `${result.name}Preview`, width);
      await expect(page.getByTestId('result-card-title')).toHaveText(result.title);
      const image = page.getByTestId('result-card-media').locator('img');
      await expect(image).toBeVisible();
      expect(new URL((await image.getAttribute('src'))!, page.url()).pathname).toBe(result.image);
      await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
      if (result.app === 'fitness') {
        await expect(page.getByTestId('embed-calendar-date')).toHaveAttribute('datetime', '2026-07-10T00:00:00.000Z');
        await expect(page.getByTestId('fitness-class-time')).toHaveText('07:30');
        await expect(page.getByTestId('fitness-class-time')).toHaveAttribute('title', '07:30 - 08:30');
        await expect(page.getByTestId('fitness-class-time')).toBeVisible();
        await expect(page.getByTestId('fitness-class-venue')).toHaveText('Yoga Studio Kreuzberg');
        await expect(page.getByTestId('fitness-class-venue')).toBeVisible();
      }
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
      await open(page, result.app, `${result.name}Fullscreen`, width);
      await expect(page.getByTestId('result-embed-content')).toBeVisible();
      const image = result.app === 'shopping' ? page.getByTestId('shopping-product-image')
        : result.app === 'nutrition' ? page.getByTestId('nutrition-recipe-image')
        : page.locator('.fitness-detail-image');
      await expect(image).toBeVisible();
      await expect(image).toHaveCSS('object-fit', 'contain');
      expect(new URL((await image.getAttribute('src'))!, page.url()).pathname).toBe(result.image);
      await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
      if (result.app === 'shopping') {
        await expect(page.getByTestId('result-facts')).toContainText('1,39 €');
        await expect(page.getByTestId('shopping-product-gallery').getByRole('button')).toHaveCount(3);
        const thumbnails = page.getByTestId('shopping-product-gallery').locator('img');
        await expect.poll(() => thumbnails.evaluateAll(images => images.length === 3 && images.every(image =>
          (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0
        ))).toBe(true);
        expect(await thumbnails.evaluateAll(images => images.map(image => image.getAttribute('src')))).toEqual([
          '/store-examples/generate-1.webp', '/store-examples/events-1.webp', '/store-examples/generate-draft-1.webp',
        ]);
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
    await open(page, 'nutrition', 'NutritionRecipeEmbedFullscreen', width, 'zero');
    await expect(page.getByTestId('result-facts')).toContainText('0 min');
    await expect(page.locator('.ingredients-list li')).toHaveCount(6);
    await expect(page.locator('.instructions-list li')).toHaveCount(5);
    await expect(page.getByTestId('nutrition-recipe-details')).toContainText('0g');
    await expect(page.getByTestId('nutrition-recipe-image')).toHaveCSS('object-fit', 'contain');
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`fitness keeps class identity, zero distance and provider action at ${width}px`, async ({ page }) => {
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
