import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const preview = (path: string, width: number, variant = '') =>
  `/dev/preview/embeds/${path}?chrome=0&width=${width}${variant ? `&variant=${variant}` : ''}`;

for (const width of [390, 1280]) {
  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity
  test(`route overview synchronizes highlights, filtering and drilldown at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(preview('travel/TravelSearchEmbedFullscreen', width, 'routeOverview'));
    await waitForComponentPreview(page);
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
    const map = page.getByTestId('search-results-map');
    const routes = map.getByTestId('search-result-route-path');
    const cards = page.locator('.search-result-card');
    await expect(map).toHaveAttribute('data-route-count', '2');
    await expect(routes).toHaveCount(2);
    await expect(cards).toHaveCount(2);
    await expect.poll(() => cards.locator('img').evaluateAll(images => images.every(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true);
    for (const card of await cards.all()) {
      const bounds = (await card.getByTestId('embed-preview').boundingBox())!;
      for (const fact of await card.locator('.journey-date, .journey-times, [data-testid="connection-price"], [data-testid="connection-meta"]').all()) {
        const factBounds = (await fact.boundingBox())!;
        expect(factBounds.y).toBeGreaterThanOrEqual(bounds.y);
        expect(factBounds.y + factBounds.height).toBeLessThanOrEqual(bounds.y + bounds.height - 5);
      }
      await expect(card.getByTestId('connection-meta')).not.toContainText('Sun, Oct');
    }
    for (const route of await routes.all()) {
      await expect(route).toBeVisible();
      await expect(route).toHaveAttribute('d', /M.+L/);
      await expect(route).toHaveAttribute('stroke-opacity', '0.8');
    }
    await expect(page.getByTestId('search-template-query')).toHaveCount(1);
    await testInfo.attach(`route-overview-${width}`, { body: await page.screenshot(), contentType: 'image/png' });

    const geometry = await routes.evaluateAll(nodes => nodes.map(node => node.getAttribute('d')));
    await cards.first().hover();
    await expect(map.locator('[data-route-ref="legacy-0"]')).toHaveAttribute('stroke-opacity', '0.8');
    await expect(map.locator('[data-route-ref="legacy-1"]')).toHaveAttribute('stroke-opacity', '0.5');
    expect(await routes.evaluateAll(nodes => nodes.map(node => node.getAttribute('d')))).toEqual(geometry);
    await page.mouse.move(0, 0);
    await cards.last().getByTestId('embed-preview').focus();
    await expect(map.locator('[data-route-ref="legacy-0"]')).toHaveAttribute('stroke-opacity', '0.5');
    await expect(map.locator('[data-route-ref="legacy-1"]')).toHaveAttribute('stroke-opacity', '0.8');
    expect(await routes.evaluateAll(nodes => nodes.map(node => node.getAttribute('d')))).toEqual(geometry);
    await testInfo.attach(`route-cards-${width}`, { body: await page.screenshot(), contentType: 'image/png' });

    await page.getByTestId('search-template-filter-button').click();
    const filter = page.getByTestId('search-template-filter');
    await filter.fill('Hamburg');
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toHaveAttribute('data-result-ref', 'legacy-0');
    await expect(routes).toHaveCount(1);
    await expect(routes.first()).toHaveAttribute('data-route-ref', 'legacy-0');
    await filter.fill('');
    await page.getByTestId('search-template-filter-button').click();
    await expect(cards).toHaveCount(2);
    await expect(routes).toHaveCount(2);

    // Select the physical SVG stroke, which may not cross its bounding-box center.
    await map.scrollIntoViewIfNeeded();
    const point = await map.locator('[data-route-ref="legacy-0"]').evaluate(node => {
      const path = node as SVGPathElement;
      const local = path.getPointAtLength(path.getTotalLength() * 0.6);
      const screen = local.matrixTransform(path.getScreenCTM()!);
      return { x: screen.x, y: screen.y };
    });
    await page.mouse.click(point.x, point.y);
    const child = page.locator('.child-embed-overlay');
    await expect(child.getByTestId('flight-details-card')).toContainText('Hamburg Central Station');
    await child.getByTestId('embed-minimize').click();
    await expect(child).toHaveCount(0);
    await map.locator('[data-marker-label="Leipzig Central Station"]').click();
    await expect(child.getByTestId('flight-details-card')).toContainText('Leipzig Central Station');
    await child.getByTestId('embed-minimize').click();
    await expect(child).toHaveCount(0);

    const composer = page.getByTestId('apps-request-textarea');
    await composer.click();
    await composer.pressSequentially('Find an earlier train');
    await expect(composer).toHaveValue('Find an earlier train');
    await expect(composer).toBeFocused();
    await testInfo.attach(`route-followup-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
  });

  // contract-test: supporting surface=gui.web assertions=web-search.surface-parity
  test(`website overview retains one query, actions and child navigation at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(preview('web/WebSearchEmbedFullscreen', width));
    await waitForComponentPreview(page);
    await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
    await expect(page.getByTestId('search-template-query')).toHaveCount(1);
    await expect(page.getByTestId('search-template-query')).toHaveText('best restaurants in Berlin');
    await expect(page.getByTestId('search-results-map')).toHaveCount(0);
    await expect(page.getByTestId('search-template-summary').locator('h2')).toHaveCount(0);
    await expect(page.getByTestId('search-template-save-search')).toBeVisible();
    await expect(page.getByTestId('search-template-create-workflow')).toBeVisible();
    await expect(page.locator('.search-result-card')).toHaveCount(4);
    const composer = page.getByTestId('apps-request-textarea');
    await composer.click();
    await composer.pressSequentially('Find vegetarian options');
    await expect(composer).toHaveValue('Find vegetarian options');
    await expect(composer).toBeFocused();
    await testInfo.attach(`website-overview-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    await page.locator('.search-result-card').first().getByTestId('embed-preview').click();
    const child = page.locator('.child-embed-overlay');
    await expect(child.getByTestId('embed-header-title')).toContainText('Top 10 Restaurants');
    await child.getByRole('button', { name: 'Next embed', exact: true }).click();
    await expect(child.getByTestId('embed-header-title')).toContainText('Berlin Food Scene');
    await child.getByRole('button', { name: 'Previous embed', exact: true }).click();
    await expect(child.getByTestId('embed-header-title')).toContainText('Top 10 Restaurants');
    await child.getByTestId('embed-minimize').click();
    await expect(child).toHaveCount(0);
    await expect(composer).toHaveValue('Find vegetarian options');
  });
}
