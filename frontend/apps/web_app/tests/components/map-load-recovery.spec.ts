import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/embeds/EmbedLeafletMap?chrome=0&theme=light&background=%23dbeafe&width=800';
test.setTimeout(120_000);

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('cold map renders and recovers interrupted initialization without a page reload', async ({ page }) => {
  // Interrupt after Leaflet claims its DOM container, which also verifies that
  // retry disposes the partial map rather than hitting "already initialized".
  await page.addInitScript(() => {
    const observe = ResizeObserver.prototype.observe;
    let interrupt = true;
    ResizeObserver.prototype.observe = function (element, options) {
      if (interrupt && element.matches('[data-testid="embed-leaflet-map"]')) {
        interrupt = false;
        throw new Error('Test: interrupted map initialization');
      }
      return observe.call(this, element, options);
    };
  });
  await page.goto(PREVIEW);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('embed-map-load-error')).toBeVisible();
  await expect(page.getByTestId('embed-leaflet-map')).toHaveAttribute('data-map-ready', 'false');
  const timeOrigin = await page.evaluate(() => performance.timeOrigin);
  await page.getByTestId('embed-map-retry').click();
  await expect(page.getByTestId('embed-leaflet-map')).toHaveAttribute('data-map-ready', 'true');
  await expect(page.getByTestId('embed-map-load-error')).toHaveCount(0);
  await expect(page.locator('.leaflet-marker-icon').first()).toBeVisible();
  await expect(page.getByTestId('embed-map-zoom-controls')).toBeVisible();
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(timeOrigin);
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('a failed fullscreen chunk preserves the current page', async ({ page }) => {
  let mapSourceUrl = '';
  page.on('request', (request) => {
    if (request.url().includes('/src/components/embeds/EmbedLeafletMap.svelte')) {
      mapSourceUrl = request.url();
    }
  });
  await page.goto(PREVIEW);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('embed-leaflet-map')).toHaveAttribute('data-map-ready', 'true');
  const timeOrigin = await page.evaluate(() => performance.timeOrigin);
  await page.route('**/maps/MapLocationEmbedFullscreen.svelte*', (route) => route.abort());
  // Exercise the production resolver on the runner-local Vite preview. There
  // is no ActiveChat host in a bare component preview to perform this import.
  expect(mapSourceUrl).not.toBe('');
  const result = await page.evaluate(async (mapModule) => {
    const resolverUrl = mapModule.split('/src/components/')[0] + '/src/services/embedFullscreenResolver.ts';
    const resolver = await import(/* @vite-ignore */ resolverUrl);
    return await resolver.loadFullscreenComponent('maps-place');
  }, mapSourceUrl);
  expect(result).toBeNull();
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(timeOrigin);
  await expect(page.getByTestId('embed-leaflet-map')).toHaveAttribute('data-map-ready', 'true');
});
