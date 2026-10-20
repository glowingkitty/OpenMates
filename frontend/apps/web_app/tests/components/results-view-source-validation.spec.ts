import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
test.setTimeout(120_000);

// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
test('a copied example source never requests an embed and a real short parent renders map and calendar', async ({ page }) => {
  const copiedRef = 'events-search-12ab34';
  const realRef = 'berlin-bangkok-flight-search-preview';
  const invalidRequests: string[] = [];
  const invalidResolverWarnings: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/v1/embeds/') && request.url().includes(copiedRef)) {
      invalidRequests.push(request.url());
    }
  });
  page.on('console', (message) => {
    const text = message.text();
    if (text.includes('[embedResolver]') && text.includes(copiedRef)) invalidResolverWarnings.push(text);
  });
  const preview = (sourceRefs: string[]) => '/dev/preview/embeds/EmbedsMapView?chrome=0&theme=light&width=1000&props='
    + encodeURIComponent(JSON.stringify({ sourceRefs, highlightRefs: [] }));

  // The original broken source can arrive during streaming. Wait for local
  // resolution to finish, then check the product stays free of error notices.
  await page.goto(preview([copiedRef]));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('embeds-map-view-resolution')).toHaveAttribute('data-loading', 'false');
  await expect(page.getByTestId('embeds-map-view')).toHaveCount(0);
  await expect(page.getByText('Server error: Embed not found', { exact: true })).toHaveCount(0);

  // After finalization supplies the real source, its registered short alias
  // expands the complete parent result set. A stray unknown alias stays local.
  await page.goto(preview([realRef, copiedRef]));
  await waitForComponentPreview(page);
  const view = page.getByTestId('embeds-map-view');
  await expect(view).toBeVisible();
  await expect(view.getByTestId('embeds-map-view-card')).toHaveCount(5);
  await expect(view.getByTestId('embeds-map-view-map')).toHaveAttribute('data-map-hydrated', 'true');
  await expect(view.locator('.leaflet-marker-icon').first()).toBeVisible();
  await view.getByTestId('embeds-results-view-tab-calendar').click();
  await expect(view.getByTestId('embeds-results-view-calendar')).toBeVisible();
  // Each fixture itinerary contributes departure and arrival calendar entries.
  await expect(view.getByTestId('embeds-results-view-calendar-item')).toHaveCount(10);
  await expect(page.getByText('Server error: Embed not found', { exact: true })).toHaveCount(0);
  expect(invalidRequests).toEqual([]);
  expect(invalidResolverWarnings).toEqual([]);
});
