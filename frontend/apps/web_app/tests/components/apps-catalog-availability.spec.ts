// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (component: string, width: number, variant = 'catalogAvailability') =>
  `/dev/preview/${component}?${new URLSearchParams({ chrome: '0', width: String(width), theme: 'light', variant })}`;

for (const width of [390, 1180]) {
  // contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,apps.presentation.shared-detail-and-recency,settings-ui.navigation.contextual-availability
  test(`Apps and Settings share available catalog and card constraints at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.route('**/v1/features/availability', route => route.fulfill({ json: { disabled: [] } }));
    await page.route('**/v1/apps/workspace/public/**', route => route.fulfill({ json: { recommendations: [], cta: null } }));
    let settingsWidth = 0;
    let settingsIds: string[] = [];
    for (const component of ['settings/SettingsAllApps', 'apps/AppsWorkspace']) {
      await page.goto(preview(component, width), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const cards = page.locator('[data-app-id].app-store-card');
      const web = cards.filter({ has: page.getByTestId('app-card-name').getByText('Web', { exact: true }) });
      await expect(web).toBeVisible();
      for (const id of ['openmates', 'plans', 'projects', 'tasks', 'workflows', 'home', 'models3d', 'ai']) {
        await expect(page.locator(`.app-store-card[data-app-id="${id}"]`)).toHaveCount(0);
      }
      for (const id of ['docs', 'mindmaps', 'diagrams', 'electronics']) {
        await expect(page.locator(`.app-store-card[data-app-id="${id}"]`)).toHaveCount(1);
      }
      const ids = await cards.evaluateAll(elements => elements.map(element => element.getAttribute('data-app-id')!).sort());
      const bounds = await web.boundingBox();
      expect(bounds!.width).toBeLessThanOrEqual(223.5);
      if (component.startsWith('settings')) { settingsWidth = bounds!.width; settingsIds = ids; }
      else { expect(bounds!.width).toBeCloseTo(settingsWidth, 0); expect(ids).toEqual(settingsIds); }
      if (component.startsWith('apps')) await page.getByTestId('apps-search').click();
      const search = page.locator('input.search-input');
      await search.fill('no-catalog-app-7295');
      await expect(cards).toHaveCount(0);
      await search.fill('');
      const filter = page.getByRole('combobox', { name: 'Filter', exact: true });
      await filter.selectOption('focus_modes');
      await expect(cards.filter({ has: page.getByTestId('app-card-name').getByText('Politics', { exact: true }) })).toBeVisible();
      await filter.selectOption('all');
      await expect(web).toBeVisible();
      if (component.startsWith('apps')) {
        const destination = page.evaluate(() => new Promise<string>(resolve => window.addEventListener('apps-preview-navigate', event => resolve((event as CustomEvent<string>).detail), { once: true })));
        await web.click();
        expect(await destination).toBe('#apps/web');
      }
      await page.evaluate(() => window.dispatchEvent(new Event('catalog-preview-hide-web')));
      await expect(web).toHaveCount(0);
      await expect(cards.filter({ has: page.getByTestId('app-card-name').getByText('Politics', { exact: true }) })).toBeVisible();
      const overflow = await page.getByTestId('component-preview-viewport').evaluate(element => element.scrollWidth > element.clientWidth + 1);
      expect(overflow).toBe(false);
    }
  });
}

// contract-test: direct surface=gui.web assertions=apps.discovery.public-catalog,apps.navigation.hash-and-forwarding,settings-ui.navigation.contextual-availability
test('direct app discovery closes when runtime availability removes it and excludes internal routes', async ({ page }) => {
  await page.route('**/v1/features/availability', route => route.fulfill({ json: { disabled: [] } }));
  await page.route('**/v1/apps/workspace/public/**', route => route.fulfill({ json: { recommendations: [], cta: null } }));
  await page.goto(preview('apps/AppsWorkspace', 1180, 'catalogWeb'), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.getByTestId('apps-settings-open')).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event('catalog-preview-hide-web')));
  await expect(page.getByTestId('apps-settings-open')).toHaveCount(0);
  await expect(page.getByTestId('apps-detail-fullscreen').getByRole('alert')).toBeVisible();
  await page.goto(preview('apps/AppsWorkspace', 1180, 'catalogBlockedApp'), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.getByTestId('apps-settings-open')).toHaveCount(0);
  await expect(page.getByTestId('apps-detail-fullscreen').getByRole('alert')).toBeVisible();
  await page.goto(preview('settings/AppDetailsWrapper', 1180, 'catalogWeb'), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.getByTestId('app-discovery-unavailable')).toHaveCount(0);
  const skills = page.getByTestId('settings-skill-cards-scroll');
  await expect(skills.getByRole('menuitem', { name: 'Search', exact: true })).toBeVisible();
  await expect(skills.getByRole('menuitem', { name: 'Read', exact: true })).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event('catalog-preview-hide-web')));
  await expect(page.getByTestId('app-discovery-unavailable')).toBeVisible();
  await expect(skills).toHaveCount(0);
  await page.goto(preview('settings/AppDetailsWrapper', 1180, 'catalogBlockedApp'), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.getByTestId('app-discovery-unavailable')).toBeVisible();
});
