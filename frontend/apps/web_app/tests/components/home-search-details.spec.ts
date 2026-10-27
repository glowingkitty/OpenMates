import type { Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const listingPath = '/dev/preview/embeds/home/HomeListingEmbedFullscreen';
const searchPath = '/dev/preview/embeds/home/HomeSearchEmbedFullscreen';
const capture = (width: number, variant = '') => `theme=light&background=%23dbeafe&width=${width}&chrome=0${variant ? `&variant=${variant}` : ''}`;

async function openHomeInfo(page: Page, id: string) {
  const trigger = page.getByTestId(id);
  if (await trigger.getAttribute('data-pinned') !== 'true') await trigger.click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
}


for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=home-search.images.complete-gallery,home-search.listings.rich-provider-evidence,app-skills.history.renderable,home-search.location.precision
  test(`home listing gallery and compact provider facts remain usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${listingPath}?${capture(width)}`);
    await waitForComponentPreview(page);
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay').first());
    const gallery = page.getByTestId('home-gallery');
    const thumbnails = gallery.getByRole('group').getByRole('button');
    const image = page.getByTestId('home-gallery-image');
    await expect(thumbnails).toHaveCount(3);
    await expect(page.getByTestId('home-gallery-counter')).toHaveCount(0);
    await expect(image).toHaveAttribute('src', '/store-examples/home-1.webp');
    await expect(image).toHaveCSS('object-fit', 'contain');
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    await page.getByRole('button', {name: 'Next photo', exact: true}).click();
    await expect(image).toHaveAttribute('src', '/store-examples/home-2.webp');
    await page.getByRole('button', {name: 'Photo 2', exact: true}).focus();
    await page.keyboard.press('End');
    await expect(image).toHaveAttribute('src', '/store-examples/home-3.webp');
    await expect(page.getByRole('button', {name: 'Photo 3', exact: true})).toHaveAttribute('aria-pressed', 'true');
    await page.keyboard.press('ArrowRight');
    await expect(image).toHaveAttribute('src', '/store-examples/home-1.webp');
    await page.getByRole('button', {name: 'Previous photo', exact: true}).click();
    await expect(image).toHaveAttribute('src', '/store-examples/home-3.webp');
    const amenities = page.getByTestId('home-amenities');
    await expect(amenities.getByRole('button', {name: 'Balcony: Yes', exact: true})).toHaveAttribute('data-state', 'yes');
    await expect(amenities.getByRole('button', {name: 'Furnished: No', exact: true})).toHaveAttribute('data-state', 'no');
    await expect(amenities.getByRole('button', {name: 'Pets allowed: Unknown', exact: true})).toHaveAttribute('data-state', 'unknown');
    await openHomeInfo(page, 'home-amenity-balcony');
    await expect(page.getByRole('tooltip')).toContainText('Advertised');
    await expect(page.getByRole('tooltip')).toContainText('Uncertain');
    await expect(page.getByRole('tooltip')).toContainText('2 / 3 photos assessed');
    await expect(page.getByTestId('home-advertised-evidence')).toContainText('Yes');
    await page.keyboard.press('Escape');
    await openHomeInfo(page, 'home-price-info');
    const prices = page.getByTestId('home-price-summary');
    await expect(prices.locator('div').filter({hasText: 'Cold rent'})).toContainText('1000 EUR');
    await expect(prices.locator('div').filter({has: page.locator('dt').filter({hasText: /^Warm rent$/})})).toContainText('1250 EUR');
    await expect(prices.locator('div').filter({hasText: 'Utilities'})).toContainText('250 EUR');
    await expect(prices.locator('div').filter({hasText: 'Deposit'})).toContainText('3000');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('home-location-label')).toContainText('Approximate location');
    await expect(page.getByTestId('home-location-area-label')).toContainText('1200 m radius');
    for (const id of ['home-details-info','home-match-info','home-visual-info','home-neighborhood-info','home-location-info']) await expect(page.getByTestId(id)).toHaveCount(0);
    await gallery.scrollIntoViewIfNeeded();
    const bounds = (await gallery.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await expect(page.getByRole('button', {name: 'Next photo', exact: true})).toBeInViewport();
  });

  // contract-test: direct surface=gui.web assertions=home-search.web.map-and-filter,home-search.location.precision,home-search.images.complete-gallery
  test(`home overview filters cards and markers together at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${searchPath}?${capture(width)}`);
    await waitForComponentPreview(page);
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay').first());
    const grid = page.getByTestId('search-template-grid');
    await expect(grid.getByTestId('embed-preview')).toHaveCount(3);
    await expect(page.getByTestId('search-results-map').locator('[data-home-location]')).toHaveCount(2);
    await expect(page.getByTestId('home-location-pin')).toHaveCount(1);
    await expect(page.getByTestId('home-location-area')).toHaveAttribute('data-radius-m', '1200');
    const filter = page.getByTestId('search-template-filter');
    await filter.fill('District loft');
    await expect(grid.getByTestId('embed-preview')).toHaveCount(1);
    await expect(grid).not.toContainText('Approximate location');
    await expect(page.getByTestId('search-results-map').locator('[data-home-location]')).toHaveCount(1);
    await page.getByTestId('home-location-area').focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('home-gallery')).toBeVisible();
    await expect(page.getByTestId('home-location-label')).toContainText('Approximate location');
  });
}

// contract-test: direct surface=gui.web assertions=home-search.images.complete-gallery,home-search.location.precision,app-skills.history.renderable
test('home empty photos and partial gallery keep missing media truthful', async ({ page }) => {
  await page.goto(`${listingPath}?${capture(390, 'noPhotos')}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('home-gallery')).toContainText('No listing photos available.');
  await expect(page.getByTestId('home-gallery-image')).toHaveCount(0);
  await expect(page.getByTestId('embed-leaflet-map')).toHaveCount(0);
  await expect(page.getByTestId('home-location-info')).toHaveCount(0);
  await openHomeInfo(page, 'home-amenity-balcony');
  await expect(page.getByRole('tooltip')).toContainText('Unavailable');
  await page.goto(`${listingPath}?${capture(390, 'partialGallery')}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('home-gallery').getByRole('group').getByRole('button')).toHaveCount(1);
  await expect(page.getByTestId('home-gallery')).toContainText('Additional listing photos may be unavailable.');
  await expect(page.getByTestId('home-gallery-counter')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=home-search.images.complete-gallery,home-search.web.map-and-filter
test('home serialized gallery deduplicates and missing-coordinate listings remain discoverable', async ({ page }) => {
  await page.goto(`${listingPath}?${capture(390, 'serializedGallery')}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('home-gallery').getByRole('group').getByRole('button')).toHaveCount(3);
  await openHomeInfo(page, 'home-amenity-balcony');
  await expect(page.getByRole('tooltip')).toContainText('Uncertain');
  await page.goto(`${searchPath}?${capture(390)}`);
  await waitForComponentPreview(page);
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay').first());
  await page.getByTestId('search-template-filter').fill('Garden apartment without coordinates');
  await expect(page.getByTestId('search-template-grid').getByTestId('embed-preview')).toHaveCount(1);
  await expect(page.getByTestId('search-results-map').locator('[data-home-location]')).toHaveCount(0);
  await page.getByTestId('search-template-grid').getByTestId('embed-preview').click();
  await expect(page.getByTestId('home-gallery')).toBeVisible();
  await expect(page.getByTestId('home-location-info')).toHaveCount(0);
  await expect(page.getByTestId('result-map')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=home-search.images.complete-gallery,app-skills.history.renderable
test('home retains all eighteen supplied photos beyond the visual assessment limit', async ({ page }) => {
  await page.goto(`${listingPath}?${capture(390, 'longGallery')}`);
  await waitForComponentPreview(page);
  const thumbnails = page.getByTestId('home-gallery').getByRole('group').getByRole('button');
  await expect(thumbnails).toHaveCount(18);
  await thumbnails.first().focus();
  await page.keyboard.press('End');
  await expect(thumbnails.last()).toHaveAttribute('aria-pressed', 'true');
  await expect(thumbnails.last()).toBeFocused();
  await expect(page.getByTestId('home-gallery-image')).toHaveAttribute('src', '/store-examples/home-3.webp?photo=18');
  await openHomeInfo(page, 'home-amenity-balcony');
  await expect(page.getByRole('tooltip')).toContainText('2 / 18 photos assessed');
});

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=home-search.filters.explicit-and-unknown,home-search.web.map-and-filter
  test(`home numeric and amenity filters require known matching facts at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({width, height: 900});
    await page.goto(`${searchPath}?${capture(width)}`);
    await waitForComponentPreview(page);
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay').first());
    const cards = page.getByTestId('search-template-grid').getByTestId('embed-preview');
    const maxPrice = page.getByTestId('home-filter-max-price');
    const basis = page.getByTestId('home-filter-price-basis');
    const rooms = page.getByTestId('home-filter-min-rooms');
    const size = page.getByTestId('home-filter-min-size');
    const amenity = page.getByTestId('home-filter-amenity');
    const reset = page.getByTestId('search-template-clear-filters');
    await expect(cards).toHaveCount(3);
    const launcher = page.getByTestId('search-template-filter-button');
    const panel = page.getByTestId('search-template-filter-menu');
    await expect(launcher).toHaveAttribute('aria-expanded', 'false');
    await expect(maxPrice).toHaveCount(0);
    await expect(panel).toHaveCount(0);
    await testInfo.attach(`home-filters-${width}-closed`, {body: await page.screenshot(), contentType: 'image/png'});
    await launcher.hover();
    await launcher.click();
    await expect(launcher).toHaveAttribute('aria-expanded', 'true');
    await expect(panel).toBeVisible();
    await expect(launcher.locator('.close-icon')).toHaveCount(1);
    const panelBox = await panel.boundingBox();
    expect(panelBox!.x).toBeGreaterThanOrEqual(0);
    expect(panelBox!.x + panelBox!.width).toBeLessThanOrEqual(width);
    expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(900);
    const composerBox = await page.getByTestId('embed-fixed-bottom').boundingBox();
    expect(panelBox!.y + panelBox!.height).toBeLessThanOrEqual(composerBox!.y);
    await expect(panel.locator('fieldset')).toHaveCount(0);
    await testInfo.attach(`home-filters-${width}-open`, {body: await page.screenshot(), contentType: 'image/png'});
    for (const control of [maxPrice, basis, rooms, size, amenity, reset]) {
      await control.scrollIntoViewIfNeeded();
      await expect(control).toBeInViewport();
      const box = await control.boundingBox();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    }
    await maxPrice.fill('1000');
    await expect(cards).toHaveCount(1);
    await expect(cards).toContainText('Garden apartment without coordinates');
    await expect(page.getByTestId('search-results-map').locator('[data-home-location]')).toHaveCount(0);
    await basis.selectOption('cold');
    await expect(cards).toHaveCount(2);
    await expect(page.getByTestId('search-results-map').locator('[data-home-location]')).toHaveCount(1);
    await basis.selectOption('warm');
    await expect(cards).toHaveCount(1);
    await expect(cards).toContainText('Garden apartment without coordinates');
    await reset.click();
    await rooms.fill('2');
    await expect(cards).toHaveCount(2);
    await size.fill('70');
    await expect(cards).toHaveCount(1);
    await expect(cards).toContainText('District loft');
    await amenity.selectOption('balcony');
    await expect(cards).toHaveCount(0);
    await expect(page.getByTestId('search-results-map').locator('[data-home-location]')).toHaveCount(0);
    await reset.click();
    await amenity.selectOption('balcony');
    await expect(cards).toHaveCount(1);
    await expect(cards).toContainText('Canal apartment with balcony');
    await expect(page.getByTestId('search-results-map').locator('[data-home-location]')).toHaveCount(1);
    await amenity.selectOption('garden');
    await expect(cards).toHaveCount(1);
    await expect(cards).toContainText('Garden apartment without coordinates');
    await expect(page.getByTestId('search-results-map').locator('[data-home-location]')).toHaveCount(0);
    await amenity.selectOption('terrace');
    await expect(cards).toHaveCount(1);
    await expect(cards).toContainText('District loft');
    await expect(page.getByTestId('search-results-map').locator('[data-home-location]')).toHaveCount(1);
    await reset.click();
    await expect(cards).toHaveCount(3);
    await expect(page.getByTestId('search-results-map').locator('[data-home-location]')).toHaveCount(2);
    await page.keyboard.press('Escape');
    await expect(panel).toHaveCount(0);
    await expect(page.getByTestId('embed-fullscreen-overlay').first()).toBeVisible();
    await expect(launcher).toBeFocused();
    await expect(launcher).toHaveAttribute('aria-expanded', 'false');
    await launcher.click();
    await expect(panel).toBeVisible();
    await page.getByTestId('search-template-filter').click();
    await expect(panel).toHaveCount(0);
    await expect(page.getByTestId('search-template-filter')).toBeFocused();
  });
}

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable
test('home precise location does not add neighborhood evidence disclosures or infer routes', async ({ page }) => {
  await page.goto(`${listingPath}?${capture(390, 'nearbyEvidence')}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('home-location-label')).toContainText('Building location');
  await expect(page.getByTestId('home-location-pin')).toBeVisible();
  await expect(page.getByTestId('home-neighborhood-info')).toHaveCount(0);
  await expect(page.getByTestId('home-nearby-place')).toHaveCount(0);
  await expect(page.getByTestId('result-embed-content')).not.toContainText('700 m');
  await expect(page.getByTestId('result-embed-content')).not.toContainText('5 minutes');
});

// contract-test: direct surface=gui.web assertions=home-search.filters.explicit-and-unknown,home-search.output.safe-and-truthful
test('home zero confirmed matches retains search warnings and visible controls', async ({ page }) => {
  await page.goto(`${searchPath}?${capture(390, 'noConfirmedMatches')}`);
  await waitForComponentPreview(page);
  const warnings = page.getByTestId('home-search-warnings');
  await expect(warnings).toBeVisible();
  await expect(warnings).toContainText('No confirmed matches: balcony and warm rent below 1500 EUR could not both be established.');
  await expect(warnings).toContainText('Some listing photos could not be assessed.');
  await expect(page.getByTestId('home-filter-amenity')).toHaveCount(0);
  await page.getByTestId('search-template-filter-button').click();
  await expect(page.getByTestId('home-filter-amenity')).toBeVisible();
  await expect(page.getByTestId('home-filter-price-basis')).toBeVisible();
  await expect(page.getByTestId('search-template-grid').getByTestId('embed-preview')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=home-search.images.complete-gallery,app-skills.history.renderable,home-search.filters.explicit-and-unknown
test('home persisted flattened TOON fields hydrate compact evidence and the complete gallery', async ({ page }) => {
  await page.goto(`${listingPath}?${capture(390, 'persistedFlattened')}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('home-gallery').getByRole('group').getByRole('button')).toHaveCount(3);
  await page.getByRole('button', {name: 'Next photo', exact: true}).click();
  await expect(page.getByTestId('home-gallery-image')).toHaveAttribute('src', '/store-examples/home-2.webp');
  await openHomeInfo(page, 'home-amenity-balcony');
  await expect(page.getByRole('tooltip')).toContainText('2 / 3 photos assessed');
  await expect(page.getByRole('tooltip')).toContainText('Uncertain');
  await expect(page.getByTestId('home-advertised-evidence')).toContainText('Yes');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('home-location-area-label')).toContainText('650 m radius');
  await expect(page.getByTestId('home-amenity-pets_allowed')).toHaveAttribute('data-state', 'no');
  await page.goto(`${searchPath}?${capture(390, 'persistedFlattened')}`);
  await waitForComponentPreview(page);
  await page.getByTestId('search-template-filter-button').click();
  await page.getByTestId('home-filter-amenity').selectOption('balcony');
  await page.getByTestId('search-template-filter-button').click();
  const cards = page.getByTestId('search-template-grid').getByTestId('embed-preview');
  await expect(cards).toHaveCount(1);
  await expect(cards).toContainText('Persisted canal apartment');
  await cards.getByTestId('result-card-title').click();
  await expect(page.getByTestId('home-gallery').getByRole('group').getByRole('button')).toHaveCount(3);
  await openHomeInfo(page, 'home-amenity-balcony');
  await expect(page.getByRole('tooltip')).toContainText('Confirmed');
  await expect(page.getByRole('tooltip')).toContainText('2 / 3 photos assessed');
});

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=home-search.web.map-and-filter,home-search.output.safe-and-truthful
  test(`saved Home search preview preserves parent metadata at ${width}px`, async ({page}, testInfo) => {
    await page.setViewportSize({width, height: 900});
    const path = '/dev/preview/embeds/home/HomeSearchEmbedPreview';
    await page.goto(`${path}?${capture(width, 'savedParentMetadata')}`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('home-search-result-count')).toHaveText('6 listings found');
    const thumbnails = page.locator('img.listing-thumbnail');
    await expect(thumbnails).toHaveCount(3);
    await expect.poll(() => thumbnails.evaluateAll((images: HTMLImageElement[]) => images.every(image => image.complete && image.naturalWidth > 0))).toBe(true);
    const preview = page.getByTestId('embed-preview').first();
    const bounds = await preview.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.y).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(900);
    await expect(page.getByTestId('search-no-results-message')).toHaveCount(0);
    await testInfo.attach(`home-preview-${width}-savedParentMetadata`, {body: await page.screenshot(), contentType: 'image/png'});
    await page.goto(`${path}?${capture(width, 'metadataOnly')}`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('home-search-result-count')).toHaveText('6 listings found');
    await expect(page.getByTestId('search-no-results-message')).toHaveCount(0);
    await testInfo.attach(`home-preview-${width}-metadataOnly`, {body: await page.screenshot(), contentType: 'image/png'});
    await page.goto(`${path}?${capture(width, 'knownZero')}`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('search-no-results-message')).toBeVisible();
    await testInfo.attach(`home-preview-${width}-knownZero`, {body: await page.screenshot(), contentType: 'image/png'});
    await page.goto(`${path}?${capture(width, 'unknownResults')}`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('search-no-results-message')).toHaveCount(0);
    await expect(page.getByTestId('search-preview-metadata-missing-message')).toBeVisible();
    await testInfo.attach(`home-preview-${width}-unknownResults`, {body: await page.screenshot(), contentType: 'image/png'});
  });
}

// contract-test: direct surface=gui.web assertions=home-search.location.precision,home-search.web.map-and-filter
test('home area extent is geographic and legacy centers never become apartment pins', async ({page}) => {
  for (const [variant, basis, radius] of [['cityArea', 'city', '18000'], ['persistedFlattened', 'description', '650']] as const) {
    await page.goto(`${listingPath}?${capture(390, variant)}`);
    await waitForComponentPreview(page);
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay').first());
    const area = page.getByTestId('home-location-area');
    await expect(area).toBeVisible();
    await expect(area).toHaveAttribute('data-radius-m', radius);
    await expect(area).toHaveAttribute('data-area-basis', basis);
    await expect(page.locator('.leaflet-marker-icon')).toHaveCount(0);
    // Sample both rectangles in one frame after the fullscreen slide-in settles.
    // Separate protocol calls can otherwise compare different animation positions.
    const {mapBox, areaBox} = await area.evaluate(element => {
      const map = element.closest('[data-testid="embed-leaflet-map"]');
      if (!map) throw new Error('Home area must belong to its Leaflet map');
      return {mapBox: map.getBoundingClientRect().toJSON(), areaBox: element.getBoundingClientRect().toJSON()};
    });
    expect(mapBox).not.toBeNull(); expect(areaBox).not.toBeNull();
    expect(Math.min(areaBox!.width, areaBox!.height)).toBeGreaterThanOrEqual(Math.min(mapBox!.width, mapBox!.height) * 0.35);
    expect(areaBox!.x).toBeGreaterThanOrEqual(mapBox!.x);
    expect(areaBox!.x + areaBox!.width).toBeLessThanOrEqual(mapBox!.x + mapBox!.width);
    expect(areaBox!.y).toBeGreaterThanOrEqual(mapBox!.y);
    expect(areaBox!.y + areaBox!.height).toBeLessThanOrEqual(mapBox!.y + mapBox!.height);
    await expect(page.getByTestId('home-location-area-label')).toContainText(`${radius} m radius`);
    await page.locator('.leaflet-control-zoom-out').click();
    await expect.poll(async () => (await area.boundingBox())!.width).toBeLessThan(areaBox!.width);
    await expect(area).toHaveAttribute('data-radius-m', radius);
  }
  await page.goto(`${listingPath}?${capture(390, 'legacyApproximate')}`);
  await waitForComponentPreview(page);
  await expect(page.locator('[data-home-location]')).toHaveCount(0);
  await expect(page.getByTestId('home-location-label')).toContainText('Approximate location');
  await expect(page.getByTestId('home-location-area-label')).toHaveCount(0);
  await page.goto(`${listingPath}?${capture(390, 'precise')}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('home-location-pin')).toBeVisible();
  await expect(page.getByTestId('home-location-area')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=home-search.web.map-and-filter,home-search.location.precision
test('shared home map keeps overlapping area selections and provider filters linked to cards', async ({page}) => {
  await page.setViewportSize({width: 1280, height: 900});
  await page.goto(`/dev/preview/embeds/EmbedsMapView?${capture(1100, 'homes')}`);
  await waitForComponentPreview(page);
  const cards = page.getByTestId('embeds-map-view-card');
  await expect(cards).toHaveCount(3);
  await expect(page.getByTestId('home-location-area')).toHaveCount(2);
  await expect(page.getByTestId('home-location-pin')).toHaveCount(1);
  const area = page.locator('[data-home-location="area"][data-area-basis="description"]');
  await area.focus();
  await page.keyboard.press('Enter');
  await expect(cards).toHaveCount(1);
  await expect(cards).toContainText('Description home');
  await page.getByTestId('embeds-map-view-show-all-results').click();
  await expect(cards).toHaveCount(3);
  await page.getByTestId('embeds-map-view-filter-button').click();
  const provider = page.getByTestId('embeds-map-view-option-provider-ExampleHousingA');
  await provider.click();
  await expect(provider).toHaveAttribute('aria-checked', 'false');
  await expect(page.getByTestId('home-location-pin')).toHaveCount(0);
  await expect(page.getByTestId('home-location-area')).toHaveCount(2);
  await expect(cards).toHaveCount(2);
});

// contract-test: direct surface=gui.web assertions=home-search.web.map-and-filter,home-search.location.precision
test('filtering between homes with identical city geometry updates area activation identity', async ({page}) => {
  await page.setViewportSize({width: 390, height: 900});
  await page.goto(`${searchPath}?${capture(390, 'sameCityArea')}`);
  await waitForComponentPreview(page);
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay').first());
  const filter = page.getByTestId('search-template-filter');
  const area = page.getByTestId('home-location-area');
  await filter.fill('Same city home A');
  await expect(area).toHaveCount(1);
  await expect(area).toHaveAttribute('aria-label', /Same city home A/);
  const firstRef = await area.getAttribute('data-marker-ref');
  const fittedDiameter = (await area.boundingBox())!.width;
  await page.getByTestId('search-results-map').locator('.leaflet-control-zoom-out').click();
  await expect.poll(async () => (await area.boundingBox())!.width).toBeLessThan(fittedDiameter);
  await expect(page.locator('.leaflet-zoom-anim')).toHaveCount(0);
  const zoomedDiameter = (await area.boundingBox())!.width;
  // Both filtered arrays have one circle with equal center and meter radius.
  await filter.fill('Same city home B');
  await expect(area).toHaveCount(1);
  await expect(area).toHaveAttribute('aria-label', /Same city home B/);
  await expect(area).not.toHaveAttribute('data-marker-ref', firstRef!);
  expect((await area.boundingBox())!.width).toBeCloseTo(zoomedDiameter, 0);
  await area.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('home-gallery')).toBeVisible();
  await expect(page.getByTestId('embed-header-title').last()).toHaveText('Same city home B');
});

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=home-search.location.precision,home-search.web.map-and-filter,home-search.images.complete-gallery
  test(`Home cards show the photo alone and fall back to factual maps at ${width}px`, async ({page}, testInfo) => {
    await page.setViewportSize({width, height: 900});
    await page.goto(`/dev/preview/embeds/home/HomeListingEmbedPreview?${capture(width, 'chat')}&context=chat`);
    await waitForComponentPreview(page);
    const card = page.getByTestId('home-listing-result-card');
    await expect(card.getByTestId('result-card-title')).toContainText('2-Zimmer');
    await expect(card.locator('.listing-price')).toHaveText('850 EUR/month');
    await expect(card.locator('.home-preview-image')).toBeVisible();
    await expect.poll(() => card.locator('.home-preview-image').evaluate(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0)).toBe(true);
    await expect(card.getByTestId('home-preview-map')).toHaveCount(0);
    await expect(card.locator('.home-preview-image')).toHaveCSS('object-fit', 'contain');
    await expect(card).not.toContainText('Approximate location');
    await expect(card.locator('.leaflet-control-attribution')).toHaveCount(0);
    await expect(card.locator('.card-source')).toHaveCount(0);
    if (width === 390) {
      await expect(card.locator('.listing-extra')).toBeHidden();
      await expect(card.locator('.listing-location')).toBeHidden();
      const title = await card.getByTestId('result-card-title').innerText();
      const visibleCopy = await card.locator('.card-copy').evaluate(element => (element as HTMLElement).innerText.replace(/\s+/g, ' ').trim());
      expect(visibleCopy).toBe(`${title} 850 EUR/month`.replace(/\s+/g, ' ').trim());
    } else {
      await expect(card.locator('.listing-extra')).toBeVisible();
      await expect(card.locator('.listing-location')).toContainText('Bergmannstr. 12');
      await expect(card.locator('.listing-extra')).toContainText('55 m²');
    }
    await testInfo.attach(`home-photo-only-${width}`, {body: await page.screenshot(), contentType: 'image/png'});
    const queries: string[] = [];
    await page.route('**/v1/geocode/search?**', route => {
      const query = new URL(route.request().url()).searchParams.get('q')!;
      queries.push(query);
      return route.fulfill({json: [{name: query, addresstype: 'city', address: {city: query}, boundingbox: query === 'Hamburg' ? ['53.39', '53.74', '9.73', '10.33'] : ['52.34', '52.68', '13.09', '13.76']}]});
    });
    for (const [variant, city] of [['noLocation', 'Berlin'], ['cityOnly', 'Hamburg']]) {
      await page.goto(`/dev/preview/embeds/home/HomeListingEmbedPreview?${capture(width, variant)}&context=chat`);
      await waitForComponentPreview(page);
      const area = page.getByTestId('home-preview-location-area');
      await expect(area).toBeVisible();
      await expect(area).toHaveAttribute('data-area-basis', 'city');
      expect(Number(await area.getAttribute('data-radius-m'))).toBeGreaterThan(10000);
      await expect(page.getByTestId('home-listing-result-card')).not.toContainText('Approximate location');
      await expect(page.locator('.leaflet-control-attribution')).toHaveCount(0);
      await expect(page.locator('.leaflet-marker-icon')).toHaveCount(0);
      await expect(page.locator('.home-preview-image')).toHaveCount(0);
      expect(queries).toContain(city);
      await testInfo.attach(`home-city-map-${variant}-${width}`, {body: await page.screenshot(), contentType: 'image/png'});
    }
    expect(queries.every(query => ['Berlin', 'Hamburg'].includes(query))).toBe(true);
    const queryCount = queries.length;
    await page.goto(`/dev/preview/embeds/home/HomeListingEmbedPreview?${capture(width, 'photoWithoutGeometry')}&context=chat`);
    await waitForComponentPreview(page);
    await expect(page.locator('.home-preview-image')).toBeVisible();
    await expect.poll(() => page.locator('.home-preview-image').evaluate(image => (image as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
    await expect(page.getByTestId('home-preview-map')).toHaveCount(0);
    expect(queries).toHaveLength(queryCount);
    await page.goto(`/dev/preview/embeds/home/HomeListingEmbedPreview?${capture(width, 'preciseNoImage')}&context=chat`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('home-preview-location-pin')).toBeVisible();
    await expect(page.locator('.home-preview-image')).toHaveCount(0);
    await expect(page.locator('.leaflet-control-attribution')).toHaveCount(0);
    await expect(page.getByTestId('home-preview-location-area')).toHaveCount(0);
    expect(queries).toHaveLength(queryCount);
    await page.goto(`/dev/preview/embeds/home/HomeListingEmbedPreview?${capture(width, 'unknownCity')}&context=chat`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('home-preview-map-status')).toHaveText('Location unavailable');
    await expect(page.locator('[data-home-location]')).toHaveCount(0);
    expect(queries.every(query => ['Berlin', 'Hamburg'].includes(query))).toBe(true);
  });
}
