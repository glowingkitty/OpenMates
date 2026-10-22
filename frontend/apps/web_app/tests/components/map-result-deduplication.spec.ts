import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('overlapping event searches render one card per occurrence throughout the map view', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/embeds/EmbedsMapView?chrome=0&theme=light&background=%23dbeafe&width=366&variant=duplicateEvents');
  await waitForComponentPreview(page);
  const map = page.getByTestId('embeds-map-view');
  const cards = map.getByTestId('embeds-map-view-card');

  await test.step('one highlighted card survives repeated search results and reference aliases', async () => {
    await expect(cards).toHaveCount(3);
    await expect(map.locator('[data-testid="embeds-map-view-card"][data-entry-status="ready"]')).toHaveCount(3);
    await expect(cards.first()).toHaveAttribute('aria-label', 'Community AI evening');
    await expect(cards.first()).toHaveAttribute('data-highlighted', 'true');
    await expect(map.getByTestId('embeds-map-view-count')).toHaveText('3 shown');
    const firstPreview = cards.first().getByRole('button');
    await firstPreview.focus();
    await expect(cards.first()).toHaveAttribute('data-hovered', 'true');
    await firstPreview.click();
    await expect(cards.first()).toHaveAttribute('data-selected', 'true');
  });

  await test.step('scrolling to the end reveals unique events after the duplicate batch', async () => {
    const carousel = map.getByTestId('embeds-map-view-carousel');
    await expect.poll(() => carousel.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
    await carousel.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
    await expect(cards.last()).toBeInViewport();
    await expect(cards.last()).toHaveAttribute('aria-label', 'Community AI evening (next day)');
    await expect(cards).toHaveCount(3);
  });

  await test.step('calendar occurrences and filter counts use the same unique results', async () => {
    await map.getByTestId('embeds-results-view-tab-calendar').click();
    await expect(map.getByTestId('embeds-results-view-calendar-item')).toHaveCount(3);
    await map.getByTestId('embeds-map-view-filter-button').click();
    await expect(map.getByTestId('embeds-map-view-filter-summary')).toHaveText(/3 of 3\s*results remain/);
    await map.getByTestId('embeds-map-view-filter-button').click();
    await map.getByTestId('embeds-results-view-tab-map').click();
    await expect(cards).toHaveCount(3);
  });
});
