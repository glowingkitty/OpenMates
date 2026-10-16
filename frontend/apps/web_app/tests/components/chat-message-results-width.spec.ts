// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { expectChatResultsFullWidth } from '../helpers/chat-results-width';

for (const width of [390, 820, 1000]) {
  for (const variant of ['resultsOnly', 'shortResults', 'workflowResults']) {
    // contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history
    test(`${variant} fills the map and calendar message lane at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width: Math.max(1280, width + 80), height: 1100 });
      const params = new URLSearchParams({
        theme: width === 820 ? 'dark' : 'light', background: '#dbeafe',
        width: String(width), chrome: '0', variant,
        props: JSON.stringify({ containerWidth: width, ...(variant === 'shortResults' ? { status: 'streaming' } : {}) }),
      });
      await page.goto(`/dev/preview/ChatMessage?${params}`);
      await waitForComponentPreview(page);
      const results = page.getByTestId('embeds-map-view');
      const map = results.getByTestId('embed-leaflet-map');
      async function expectVisibleMap() {
        await expect(map).toHaveAttribute('data-map-ready', 'true');
        await expect(map).toBeVisible();
        const mapBounds = await map.boundingBox();
        const bodyBounds = await results.locator('.map-view-body').boundingBox();
        expect(mapBounds!.height).toBeGreaterThanOrEqual(278);
        expect(mapBounds!.y + mapBounds!.height, 'the map must not be clipped below its results body')
          .toBeLessThanOrEqual(bodyBounds!.y + bodyBounds!.height + 1);
      }
      await expect(results).toBeVisible();
      await expect(results.getByTestId('embeds-map-view-card')).toHaveCount(1);
      await expect(results.getByTestId('embeds-map-view-map')).toHaveAttribute('data-map-hydrated', 'true');
      await expectVisibleMap();
      await expectChatResultsFullWidth(results);
      if (width === 820 && variant === 'workflowResults') {
        await testInfo.attach('tablet-map', { body: await page.screenshot(), contentType: 'image/png' });
      }

      await results.getByTestId('embeds-results-view-tab-calendar').click();
      await expect(results.getByTestId('embeds-results-view-pane')).toHaveAttribute('data-active-tab', 'calendar');
      await expect(results.getByTestId('embeds-results-view-calendar-item')).toHaveCount(1);
      await expectChatResultsFullWidth(results);
      if (width === 820 && variant === 'workflowResults') {
        await testInfo.attach('tablet-calendar', { body: await page.screenshot(), contentType: 'image/png' });
      }

      await results.getByTestId('embeds-results-view-tab-map').click();
      await expect(results.getByTestId('embeds-map-view-map')).toHaveAttribute('data-map-hydrated', 'true');
      await expectVisibleMap();
      await expectChatResultsFullWidth(results);
    });
  }
}
