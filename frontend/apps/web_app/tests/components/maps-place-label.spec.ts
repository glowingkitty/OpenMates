import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

for (const variant of ['mapsPlace', 'mapsPlaceUnknown']) {
  // contract-test: supporting surface=gui.web assertions=maps-search.gui.place-rendering,maps-search.output.source-and-identity
  test(`place preview resolves a readable category for ${variant}`, async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 900 });
    await page.goto(`/dev/preview/apps/AppsEmbedPreview?chrome=0&theme=light&background=%23dbeafe&width=390&variant=${variant}`);
    await waitForComponentPreview(page);
    const card = page.getByTestId('maps-place-card');
    await expect(card).toBeVisible();
    await expect(card).toContainText('Evening Coffee');
    await expect(card).toContainText('Example Street 1, Berlin');
    await expect(card).not.toContainText('place_result');
    if (variant === 'mapsPlace') await expect(card).toContainText('Cafe');
    else await expect(card).not.toContainText('establishment');
    const action = page.getByTestId('embed-preview');
    await card.hover();
    await action.focus();
    await expect(action).toBeFocused();
    await page.evaluate(() => window.addEventListener('apps-embed-preview-open', () => {
      document.documentElement.dataset.placeExpanded = 'true';
    }, { once: true }));
    await action.press('Enter');
    await expect(page.locator('html')).toHaveAttribute('data-place-expanded', 'true');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1100);
  });
}
