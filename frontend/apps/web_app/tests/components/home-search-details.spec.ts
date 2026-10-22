import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const listingPath = '/dev/preview/embeds/home/HomeListingEmbedFullscreen';
const searchPath = '/dev/preview/embeds/home/HomeSearchEmbedFullscreen';
const capture = (width: number, variant = '') => `theme=light&background=%23dbeafe&width=${width}&chrome=0${variant ? `&variant=${variant}` : ''}`;

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=home-search.images.complete-gallery,home-search.listings.rich-provider-evidence,home-search.vision.evidence-and-conflicts,home-search.location.precision,home-search.neighborhood.sourced-facts
  test(`home listing gallery and evidence remain usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${listingPath}?${capture(width)}`);
    await waitForComponentPreview(page);
    const gallery = page.getByTestId('home-gallery');
    await expect(gallery).toBeVisible();
    await expect(page.getByTestId('home-gallery-counter')).toHaveText('1 / 3');
    const image = page.getByTestId('home-gallery-image');
    await expect(image).toHaveAttribute('src', '/store-examples/home-1.webp');
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    await page.getByRole('button', {name: 'Next photo', exact: true}).click();
    await expect(image).toHaveAttribute('src', '/store-examples/home-2.webp');
    await page.getByRole('button', {name: 'Photo 2', exact: true}).focus();
    await page.keyboard.press('End');
    await expect(page.getByTestId('home-gallery-counter')).toHaveText('3 / 3');
    await expect(image).toHaveAttribute('src', '/store-examples/home-3.webp');
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId('home-gallery-counter')).toHaveText('1 / 3');
    await page.getByRole('button', {name: 'Previous photo', exact: true}).click();
    await expect(page.getByTestId('home-gallery-counter')).toHaveText('3 / 3');
    await expect(page.getByTestId('home-visual-evidence')).toContainText('2 / 3 photos assessed');
    await expect(page.getByTestId('home-visual-evidence')).toContainText('Uncertain');
    await expect(page.getByTestId('home-match-evidence')).toContainText('Advertised');
    const amenities = page.getByTestId('home-amenities');
    await expect(amenities.locator('dl > div').filter({hasText: 'Balcony'})).toContainText('Yes');
    await expect(amenities.locator('dl > div').filter({hasText: 'Furnished'})).toContainText('No');
    await expect(amenities.locator('dl > div').filter({hasText: 'Pets allowed'})).toContainText('Unknown');
    const facts = page.getByTestId('home-listing-facts');
    await expect(facts.locator('dl > div').filter({hasText: 'Cold rent'})).toContainText('1000 EUR');
    await expect(facts.locator('dl > div').filter({hasText: 'Warm rent'})).toContainText('1250 EUR');
    await expect(page.getByTestId('home-location-evidence')).toContainText('Approximate location');
    if (width === 390) {
      const mapBox = await page.getByTestId('embed-leaflet-map').boundingBox();
      const areaBox = await page.getByTestId('home-location-area').boundingBox();
      expect(mapBox).not.toBeNull(); expect(areaBox).not.toBeNull();
      expect(Math.min(areaBox!.width, areaBox!.height)).toBeGreaterThanOrEqual(Math.min(mapBox!.width, mapBox!.height) * 0.35);
    }
    await expect(page.getByTestId('home-location-evidence')).toContainText('walking access are unknown');
    await expect(page.getByTestId('home-neighborhood-evidence')).toContainText('Geoapify');
    await expect(page.getByTestId('home-neighborhood-evidence')).toContainText('2026-10-21');
    await expect(page.getByTestId('home-neighborhood-evidence')).toContainText('Landwehr Canal');
    await expect(page.getByTestId('home-place-distance')).toHaveText('Apartment-to-shoreline distance unknown');
    await expect(page.getByTestId('home-place-walking')).toContainText('no confirmed route');
    await expect(page.getByTestId('home-neighborhood-evidence')).toContainText('Nearby amenities remain unknown');
    await expect(page.getByTestId('home-advertised-evidence')).toContainText('Yes');
    await gallery.scrollIntoViewIfNeeded();
    const bounds = await gallery.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
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
    await expect(page.locator('[data-home-location]')).toHaveCount(2);
    await expect(page.getByTestId('home-location-pin')).toHaveCount(1);
    await expect(page.getByTestId('home-location-area')).toHaveAttribute('data-radius-m', '1200');
    const filter = page.getByTestId('search-template-filter');
    await filter.fill('District loft');
    await expect(grid.getByTestId('embed-preview')).toHaveCount(1);
    await expect(grid).toContainText('Approximate location');
    await expect(page.locator('[data-home-location]')).toHaveCount(1);
    await page.getByTestId('home-location-area').focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('home-gallery')).toBeVisible();
    await expect(page.getByTestId('home-location-evidence')).toContainText('Approximate location');
  });
}

// contract-test: direct surface=gui.web assertions=home-search.images.complete-gallery,home-search.location.precision,home-search.vision.evidence-and-conflicts
test('home empty photos and partial gallery disclose unavailable evidence', async ({ page }) => {
  await page.goto(`${listingPath}?${capture(390, 'noPhotos')}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('home-gallery')).toContainText('No listing photos available.');
  await expect(page.getByTestId('home-gallery-image')).toHaveCount(0);
  await expect(page.getByTestId('home-visual-evidence')).toContainText('Unavailable');
  await expect(page.getByTestId('home-location-evidence')).toContainText('Location unavailable');
  await expect(page.getByTestId('embed-leaflet-map')).toHaveCount(0);
  await page.goto(`${listingPath}?${capture(390, 'partialGallery')}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('home-gallery-counter')).toHaveText('1 / 1');
  await expect(page.getByTestId('home-gallery')).toContainText('Additional listing photos may be unavailable.');
});

// contract-test: direct surface=gui.web assertions=home-search.images.complete-gallery,home-search.web.map-and-filter
test('home serialized gallery deduplicates and missing-coordinate listings remain discoverable', async ({ page }) => {
  await page.goto(`${listingPath}?${capture(390, 'serializedGallery')}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('home-gallery-counter')).toHaveText('1 / 3');
  await expect(page.getByTestId('home-match-evidence')).toContainText('Unconfirmed');
  await page.goto(`${searchPath}?${capture(390)}`);
  await waitForComponentPreview(page);
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay').first());
  await page.getByTestId('search-template-filter').fill('Garden apartment without coordinates');
  await expect(page.getByTestId('search-template-grid').getByTestId('embed-preview')).toHaveCount(1);
  await expect(page.locator('[data-home-location]')).toHaveCount(0);
  await page.getByTestId('search-template-grid').getByTestId('embed-preview').click();
  await expect(page.getByTestId('home-gallery')).toBeVisible();
  await expect(page.getByTestId('home-location-evidence')).toContainText('Location unavailable');
});

// contract-test: direct surface=gui.web assertions=home-search.images.complete-gallery,home-search.vision.evidence-and-conflicts
test('home retains all eighteen supplied photos beyond the visual assessment limit', async ({ page }) => {
  await page.goto(`${listingPath}?${capture(390, 'longGallery')}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('home-gallery-counter')).toHaveText('1 / 18');
  const thumbnails = page.getByTestId('home-gallery').getByRole('group').getByRole('button');
  await expect(thumbnails).toHaveCount(18);
  await thumbnails.first().focus();
  await page.keyboard.press('End');
  await expect(page.getByTestId('home-gallery-counter')).toHaveText('18 / 18');
  await expect(page.getByTestId('home-gallery-image')).toHaveAttribute('src', '/store-examples/home-3.webp?photo=18');
  await expect(page.getByTestId('home-visual-evidence')).toContainText('2 / 18 photos assessed');
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
    await expect(page.locator('[data-home-location]')).toHaveCount(0);
    await basis.selectOption('cold');
    await expect(cards).toHaveCount(2);
    await expect(page.locator('[data-home-location]')).toHaveCount(1);
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
    await expect(page.locator('[data-home-location]')).toHaveCount(0);
    await reset.click();
    await amenity.selectOption('balcony');
    await expect(cards).toHaveCount(1);
    await expect(cards).toContainText('Canal apartment with balcony');
    await expect(page.locator('[data-home-location]')).toHaveCount(1);
    await amenity.selectOption('garden');
    await expect(cards).toHaveCount(1);
    await expect(cards).toContainText('Garden apartment without coordinates');
    await expect(page.locator('[data-home-location]')).toHaveCount(0);
    await amenity.selectOption('terrace');
    await expect(cards).toHaveCount(1);
    await expect(cards).toContainText('District loft');
    await expect(page.locator('[data-home-location]')).toHaveCount(1);
    await reset.click();
    await expect(cards).toHaveCount(3);
    await expect(page.locator('[data-home-location]')).toHaveCount(2);
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

// contract-test: direct surface=gui.web assertions=home-search.neighborhood.sourced-facts,home-search.water.distance-and-access
test('home neighborhood separates shoreline, map-point distance and confirmed walking routes', async ({ page }) => {
  await page.goto(`${listingPath}?${capture(390, 'nearbyEvidence')}`);
  await waitForComponentPreview(page);
  const shoreline = page.getByTestId('home-nearby-place').filter({hasText: 'Canal shoreline'});
  await expect(shoreline).toContainText('Distance to shoreline: 120 m');
  await expect(shoreline).toContainText('Walking route: 8 minutes');
  await expect(shoreline).toContainText('Geoapify');
  await expect(shoreline).toContainText('2026-10-21');
  const mapPoint = page.getByTestId('home-nearby-place').filter({hasText: 'Lake map point'});
  await expect(mapPoint).toContainText('Distance to map point (not shoreline): 700 m');
  await expect(mapPoint).toContainText('Walking access unknown; no confirmed route');
  await expect(mapPoint).not.toContainText('5 minutes');
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

// contract-test: direct surface=gui.web assertions=home-search.images.complete-gallery,home-search.vision.evidence-and-conflicts,home-search.neighborhood.sourced-facts,home-search.filters.explicit-and-unknown
test('home persisted flattened TOON fields hydrate rich evidence and the complete gallery', async ({ page }) => {
  await page.goto(`${listingPath}?${capture(390, 'persistedFlattened')}`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('home-gallery-counter')).toHaveText('1 / 3');
  await page.getByRole('button', {name: 'Next photo', exact: true}).click();
  await expect(page.getByTestId('home-gallery-image')).toHaveAttribute('src', '/store-examples/home-2.webp');
  await expect(page.getByTestId('home-visual-evidence')).toContainText('2 / 3 photos assessed');
  await expect(page.getByTestId('home-visual-evidence')).toContainText('Uncertain');
  await expect(page.getByTestId('home-match-evidence')).toContainText('Confirmed');
  await expect(page.getByTestId('home-match-evidence')).toContainText('Present');
  await expect(page.getByTestId('home-advertised-evidence')).toContainText('Yes');
  await expect(page.getByTestId('home-amenities').locator('dl > div').filter({hasText: 'Pets allowed'})).toContainText('No');
  await expect(page.getByTestId('home-neighborhood-evidence')).toContainText('Landwehr Canal');
  await expect(page.getByTestId('home-neighborhood-evidence')).toContainText('Geoapify');
  await expect(page.getByTestId('home-neighborhood-evidence')).toContainText('2026-10-21');
  await expect(page.getByTestId('home-place-distance')).toHaveText('Apartment-to-shoreline distance unknown');
  await page.goto(`${searchPath}?${capture(390, 'persistedFlattened')}`);
  await waitForComponentPreview(page);
  await page.getByTestId('search-template-filter-button').click();
  await page.getByTestId('home-filter-amenity').selectOption('balcony');
  await page.getByTestId('search-template-filter-button').click();
  await expect(page.getByTestId('search-template-filter-menu')).toHaveCount(0);
  const cards = page.getByTestId('search-template-grid').getByTestId('embed-preview');
  await expect(cards).toHaveCount(1);
  await expect(cards).toContainText('Persisted canal apartment');
  await cards.click();
  await expect(page.getByTestId('home-gallery-counter')).toHaveText('1 / 3');
  await expect(page.getByTestId('home-match-evidence')).toContainText('Confirmed');
  await expect(page.getByTestId('home-visual-evidence')).toContainText('2 / 3 photos assessed');
  await expect(page.getByTestId('home-neighborhood-evidence')).toContainText('Landwehr Canal');
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
  await expect(page.getByTestId('home-location-evidence')).toContainText('Approximate area extent unavailable');
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
  const provider = page.getByTestId('embeds-map-view-option-provider-immoscout24');
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
  await page.locator('.leaflet-control-zoom-out').click();
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
