import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Page } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview
const ROOT = '/dev/preview/embeds/maps/';
test.setTimeout(120_000);

async function preview(page: Page, component: string, variant = '', width = 1100) {
  await page.setViewportSize({ width, height: width < 600 ? 844 : 900 });
  await page.goto(`${ROOT}${component}?chrome=0&theme=light&background=%23dbeafe&width=${width}${variant ? `&variant=${variant}` : ''}`);
  await waitForComponentPreview(page);
}

for (const width of [390, 1100]) {
  for (const variant of ['', 'discovery']) {
    // contract-test: supporting surface=gui.web assertions=maps-search.gui.place-rendering,maps-search.compatibility.regular-search
    test(`${variant || 'regular'} search renders place cards and markers at ${width}px`, async ({ page }, testInfo) => {
      await preview(page, 'MapsSearchEmbedFullscreen', variant, width);
      const cards = page.getByTestId('embeds-map-view-card');
      await expect(cards).toHaveCount(2);
      await expect(cards.first()).toBeVisible();
      await expect(page.getByTestId('maps-place-card')).toHaveCount(2);
      await expect(page.getByTestId('embed-leaflet-map')).toHaveAttribute('data-map-ready', 'true');
      await expect(page.locator('.leaflet-marker-icon')).toHaveCount(2);
      if (variant) {
        await expect(cards.first()).toContainText('Historic ruins');
        await expect(cards.first()).toContainText('Ruins');
        await expect(cards.first()).toContainText('1.2 km');
        await expect(page.getByTestId('maps-place-source')).toHaveCount(2);
        await expect(page.locator('.rating-star')).toHaveCount(0);
      } else {
        await expect(cards.first()).toContainText('Man vs. Machine');
        await expect(cards.first()).toContainText('4.7');
      }
      await cards.nth(1).click();
      await expect(cards.nth(1)).toHaveAttribute('data-selected', 'true');
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
      await testInfo.attach('maps-search-' + (variant || 'regular') + '-' + width, {
        body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png',
      });
    });
  }
}

// contract-test: supporting surface=gui.web assertions=maps-search.gui.place-rendering,maps-search.output.source-and-identity
test('discovery preview uses parent result_count and identifies its provider', async ({ page }) => {
  await preview(page, 'MapsSearchEmbedPreview', 'discovery', 390);
  const canvas = page.getByTestId('component-preview-canvas');
  await expect(canvas).toContainText('Geoapify');
  await expect(canvas).toContainText('2 places');
});

// contract-test: supporting surface=gui.web assertions=maps-search.gui.place-rendering,maps-search.output.source-and-identity
test('place fullscreen uses coordinates rather than a Geoapify ID for Google links', async ({ page }) => {
  await preview(page, 'MapLocationEmbedFullscreen', 'discovery');
  await expect(page.getByTestId('maps-place-source')).toHaveAttribute('href', /openstreetmap\.org/);
  await expect(page.getByTestId('map-location-fullscreen')).toContainText('1.2 km');
  const [popup] = await Promise.all([
    page.waitForEvent('popup'), page.getByRole('button', { name: /Open.*Google Maps/i }).click(),
  ]);
  await popup.waitForURL(/google\.com\/maps\/search/);
  expect(popup.url()).toContain('query=52.52,13.405');
  expect(popup.url()).not.toContain('geoapify');
  await popup.close();
});

// contract-test: supporting surface=gui.web assertions=maps-search.gui.place-rendering,maps-search.provider.budget-and-cache
test('empty, quota and unverified amenity states stay readable', async ({ page }) => {
  await preview(page, 'MapsSearchEmbedFullscreen', 'noResults');
  await expect(page.getByTestId('maps-no-results')).toBeVisible();
  await preview(page, 'MapsSearchEmbedFullscreen', 'quotaExhausted');
  await expect(page.getByTestId('maps-search-error')).toContainText('daily search allowance is exhausted');
  await preview(page, 'MapsSearchEmbedFullscreen', 'noVerifiedAmenityMatches');
  await expect(page.getByTestId('maps-no-verified-results-title')).toBeVisible();
  await expect(page.getByTestId('maps-enrichment-warning')).toContainText('No Geoapify/OSM-verified matches');
});

// contract-test: supporting surface=gui.web assertions=maps-search.gui.place-rendering,maps-search.compatibility.regular-search
test('a broken pinned map image keeps its name and address visible', async ({ page }) => {
  await preview(page, 'MapsLocationEmbedPreview', 'brokenImage', 390);
  await expect(page.locator('.map-preview-image')).toHaveCount(0);
  await expect(page.getByTestId('component-preview-canvas')).toContainText('Berlin Hauptbahnhof');
  await expect(page.getByTestId('component-preview-canvas')).toContainText('Europaplatz 1');
});
