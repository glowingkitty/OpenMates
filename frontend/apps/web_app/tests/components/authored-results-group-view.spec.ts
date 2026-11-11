// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
import { expect, test } from '../helpers/cookie-audit';
import type { Locator, Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const WIDTHS = [390, 330, 1100]; // phone, narrow chat column, wide
const THEMES = ['light', 'dark'] as const;
const TITLES = ['Open source conference: opening day', 'Open source conference: workshops'];

function previewUrl(variant: string, theme: 'light' | 'dark', width: number) {
  const background = theme === 'dark' ? '%2318202c' : '%23dbeafe';
  return `/dev/preview/embeds/AuthoredResultsPreviewFixture?theme=${theme}&background=${background}&width=${width}&chrome=0&variant=${variant}`;
}

async function openGroup(page: Page, variant: string, theme: 'light' | 'dark', width: number) {
  await page.setViewportSize({ width: Math.max(width, 390), height: 900 });
  await page.goto(previewUrl(variant, theme, width));
  await waitForComponentPreview(page);
  const host = page.getByTestId('authored-results-preview');
  await expect(host).toBeVisible();
  await expect(host.getByTestId('embeds-map-view')).toBeVisible();
  return host;
}

async function expectInside(inner: Locator, outer: Locator) {
  const innerBox = (await inner.boundingBox())!;
  const outerBox = (await outer.boundingBox())!;
  expect(innerBox.width).toBeGreaterThan(10);
  expect(innerBox.height).toBeGreaterThan(8);
  expect(innerBox.x).toBeGreaterThanOrEqual(outerBox.x - 1);
  expect(innerBox.y).toBeGreaterThanOrEqual(outerBox.y - 1);
  expect(innerBox.x + innerBox.width).toBeLessThanOrEqual(outerBox.x + outerBox.width + 1);
  expect(innerBox.y + innerBox.height).toBeLessThanOrEqual(outerBox.y + outerBox.height + 1);
}

for (const width of WIDTHS) for (const theme of THEMES) {
  // contract-test: direct surface=gui.web assertions=authored-results.presentation.standard-results-view
  test(`authored group is the standard results view with Calendar and Map tabs at ${width}px ${theme}`, async ({ page }, testInfo) => {
    const host = await openGroup(page, 'calendarAndMap', theme, width);
    // No custom layer of its own: no expand button, no extra title row.
    await expect(page.getByTestId('authored-results-expand')).toHaveCount(0);
    const tabs = host.getByTestId('embeds-results-view-tabs');
    await expect(tabs).toBeVisible();
    const calendarTab = host.getByTestId('embeds-results-view-tab-calendar');
    const mapTab = host.getByTestId('embeds-results-view-tab-map');
    await expect(calendarTab).toBeVisible();
    await expect(mapTab).toBeVisible();
    await expectInside(tabs, host);

    // Map is the default; its list shows every member with its title inside its card.
    await expect(mapTab).toHaveAttribute('aria-selected', 'true');
    await expect(host.getByTestId('embeds-map-view-map')).toBeVisible();
    const cards = host.getByTestId('embeds-map-view-card');
    await expect(cards).toHaveCount(2);
    for (const [index, title] of TITLES.entries()) {
      const card = cards.nth(index);
      await card.scrollIntoViewIfNeeded();
      const label = card.getByText(title, { exact: true }).first();
      await expect(label).toBeVisible();
      await expectInside(label, card);
      // A member without an image shows its own venue map, tiles included.
      await expect(card.getByTestId('event-preview-map').locator('.leaflet-tile-loaded').first()).toBeVisible({ timeout: 20000 });
    }
    await testInfo.attach(`group-map-${width}-${theme}`, {
      body: await host.screenshot({ animations: 'disabled' }), contentType: 'image/png' });

    // Switching to Calendar shows the members on the calendar and hides the map.
    await calendarTab.click();
    await expect(calendarTab).toHaveAttribute('aria-selected', 'true');
    await expect(mapTab).toHaveAttribute('aria-selected', 'false');
    const calendar = host.getByRole('tabpanel', { name: 'Calendar results' });
    await expect(calendar).toBeVisible();
    await expect(host.getByTestId('embeds-map-view-map')).toHaveCount(0);
    for (const title of TITLES) await expect(calendar.getByText(title).first()).toBeVisible();
    await testInfo.attach(`group-calendar-${width}-${theme}`, {
      body: await host.screenshot({ animations: 'disabled' }), contentType: 'image/png' });

    // And back.
    await mapTab.click();
    await expect(host.getByTestId('embeds-map-view-map')).toBeVisible();
    await expect(host.getByRole('tabpanel', { name: 'Calendar results' })).toHaveCount(0);
    // The cards rebuild their venue maps when the Map tab returns.
    for (let index = 0; index < TITLES.length; index += 1) {
      const card = host.getByTestId('embeds-map-view-card').nth(index);
      await card.scrollIntoViewIfNeeded();
      await expect(card.getByTestId('event-preview-map').locator('.leaflet-tile-loaded').first()).toBeVisible({ timeout: 20000 });
    }
    await host.getByTestId('embeds-map-view-card').first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`group-map-return-${width}-${theme}.png`), animations: 'disabled' });
  });

  // contract-test: direct surface=gui.web assertions=authored-results.presentation.standard-results-view
  test(`authored group without coordinates offers Calendar only, with no switch, at ${width}px ${theme}`, async ({ page }, testInfo) => {
    const host = await openGroup(page, 'calendarOnly', theme, width);
    await expect(page.getByTestId('authored-results-expand')).toHaveCount(0);
    await expect(host.getByRole('tabpanel', { name: 'Calendar results' })).toBeVisible();
    // The Map tab exists only when a member has coordinates or a route, and the
    // switch only when both views exist.
    await expect(host.getByTestId('embeds-results-view-tab-map')).toHaveCount(0);
    await expect(host.getByTestId('embeds-results-view-tabs')).toHaveCount(0);
    await expect(host.getByTestId('embeds-map-view-map')).toHaveCount(0);
    await testInfo.attach(`group-calendar-only-${width}-${theme}`, {
      body: await host.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
  });

  // contract-test: direct surface=gui.web assertions=authored-results.presentation.standard-results-view
  test(`authored group shows skeleton cards for members that are still pending at ${width}px ${theme}`, async ({ page }, testInfo) => {
    const host = await openGroup(page, 'pending', theme, width);
    await expect(host.getByTestId('embeds-map-view-card')).toHaveCount(2);
    const pending = host.getByTestId('embeds-map-view-pending-card');
    await expect(pending).toHaveCount(2);
    for (let index = 0; index < 2; index += 1) {
      await pending.nth(index).scrollIntoViewIfNeeded();
      await expect(pending.nth(index)).toBeVisible();
      await expect(pending.nth(index)).toHaveAttribute('aria-busy', 'true');
      const box = (await pending.nth(index).boundingBox())!;
      expect(box.width).toBeGreaterThan(100);
      expect(box.height).toBeGreaterThan(100);
    }
    await testInfo.attach(`group-pending-${width}-${theme}`, {
      body: await host.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
  });
}
