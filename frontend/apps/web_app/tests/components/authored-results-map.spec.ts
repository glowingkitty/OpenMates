import { expect, test } from '../helpers/cookie-audit';
import {
  authoredChild, openAuthoredComponent, isolateAuthoredImages, authoredCapture,
} from '../helpers/authored-result-fixtures';

// playwright-account: not_required reason=isolated_component_preview

for (const width of [390, 1100]) for (const theme of ['light', 'dark'] as const) {
  // contract-test: supporting surface=gui.web assertions=authored-results.groups.same-response-and-reuse,authored-results.maps.source-faithful-geometry,authored-results.content.typed-and-useful
  test(`mixed authored map retains unmappable records, supplied area extent and schematic endpoints at ${width}px ${theme}`, async ({ page }, testInfo) => {
    await isolateAuthoredImages(page);
    await openAuthoredComponent(page, 'AuthoredResultsPreviewFixture', { width, theme, variant: 'mixedmap',
      props: { isMobile: width === 390 } });
    const carrier = page.getByTestId('authored-results-preview');
    const cards = carrier.getByTestId('embeds-map-view-card');
    await expect(cards).toHaveCount(4);
    const sourceOrder = ['home.listing', 'health.appointment', 'travel.connection', 'tv.movie'].map(kind => authoredChild(kind).embed_id);
    expect(await cards.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-entry-ref')))).toEqual(sourceOrder);
    await expect(carrier.getByTestId('results-view-unmapped')).toHaveCount(2);
    for (const kind of ['home.listing', 'health.appointment', 'tv.movie', 'travel.connection']) {
      const card = cards.filter({ has: page.locator(`[data-embed-id="${authoredChild(kind).embed_id}"]`) });
      await expect(card).toHaveCount(1);
      await expect(card).toHaveAttribute('data-entry-mapped', ['home.listing', 'travel.connection'].includes(kind) ? 'true' : 'false');
    }
    const pane = carrier.getByTestId('embeds-map-view-map');
    await pane.scrollIntoViewIfNeeded();
    await expect(pane).toHaveAttribute('data-route-count', '1');
    await expect(pane).toHaveAttribute('data-endpoint-marker-count', '2');
    await expect(pane).toHaveAttribute('data-marker-count', '3');
    await expect(pane.getByTestId('embed-leaflet-map')).toHaveAttribute('data-map-ready', 'true');
    const area = pane.getByTestId('home-location-area');
    await expect(area).toBeVisible();
    await expect(area).toHaveAttribute('data-radius-m', '500');
    await expect(area).toHaveAttribute('data-area-basis', 'description');
    await expect(pane.getByTestId('home-location-pin')).toHaveCount(0);
    // Two actual connection endpoints plus a radius area; online care and a
    // movie remain list members rather than receiving fabricated coordinates.
    await expect(pane.locator('.leaflet-marker-icon')).toHaveCount(2);
    const route = pane.getByTestId('embeds-map-view-route-path');
    await expect(route).toHaveCount(1);
    await expect(route).toHaveAttribute('data-route-ref', authoredChild('travel.connection').embed_id);
    await expect(route).toHaveAttribute('stroke-dasharray', /10[, ]+10/);
    await expect(carrier.getByTestId('results-view-route-note')).toContainText(/schematic/i);
    const geometry = await route.getAttribute('d');
    expect(geometry).toMatch(/M.+L/);
    const point = await route.evaluate(element => {
      const path = element as SVGGeometryElement;
      const matrix = path.getScreenCTM();
      if (!matrix) throw new Error('Rendered route has no screen transform');
      const length = path.getTotalLength();
      // A dashed route's geometric midpoint may be an unpainted gap. Pick
      // an actual hit-tested interior stroke, then send a genuine mouse click.
      // An occluded/noninteractive route still fails rather than bypassing it.
      for (let index = 0; index <= 64; index += 1) {
        const position = path.getPointAtLength(length * (0.25 + index / 128));
        const screen = new DOMPoint(position.x, position.y).matrixTransform(matrix);
        if (screen.x < 0 || screen.y < 0 || screen.x >= innerWidth || screen.y >= innerHeight) continue;
        if (document.elementFromPoint(screen.x, screen.y) === path) return { x: screen.x, y: screen.y };
      }
      throw new Error('Supplied route has no visible, painted, interactive interior point');
    });
    await page.mouse.click(point.x, point.y);
    const travel = cards.filter({ has: page.locator(`[data-embed-id="${authoredChild('travel.connection').embed_id}"]`) });
    await expect(travel).toHaveAttribute('data-selected', 'true');
    expect(await route.getAttribute('d')).toEqual(geometry);
    expect(await cards.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-entry-ref')))).toEqual(sourceOrder);
    await authoredCapture(page, testInfo, `mixed-truthful-map-${width}-${theme}`);
    const travelPreview = travel.getByTestId('embed-preview');
    await expect(travelPreview).toHaveAttribute('role', 'button');
    await expect(travelPreview.getByTestId('preview-tools')).toHaveCount(0);
    await expect(travelPreview.getByTestId('result-preview-expand')).toHaveCount(0);
    await travelPreview.scrollIntoViewIfNeeded();
    await travelPreview.focus();
    await travelPreview.press('Enter');
    await expect(page.getByTestId('authored-fixture-fullscreen')).toHaveAttribute('data-embed-id', authoredChild('travel.connection').embed_id);
    await expect(page.getByTestId('authored-fixture-fullscreen').getByTestId('embed-header-title')).toHaveText('Supplied: travel.connection');
    await expect(page.getByTestId('authored-fixture-error')).toHaveCount(0);
  });
}
