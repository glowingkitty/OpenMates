/* eslint-disable @typescript-eslint/no-require-imports */
/** Real regional input, USPTO execution and encrypted saved-result rendering. */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

// contract-test: direct surface=gui.web assertions=trademarks.request,trademarks.coverage,trademarks.evidence,trademarks.parity
test('region selectors execute a live search and preserve coverage after reload', async ({ page }: { page: any }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await loginToTestAccount(page, () => {}, async () => {}, { waitForEditor: false });
  await page.goto(getE2EDebugUrl('/#apps/business/search-trademarks'), { waitUntil: 'domcontentloaded' });
  const form = page.getByTestId('apps-skill-form');
  await expect(form).toBeVisible({ timeout: 30_000 });
  const queries = form.getByRole('group', { name: /^Queries/ });
  await queries.getByRole('button', { name: /Add item/i }).click({ timeout: 10_000 });
  await queries.getByRole('textbox').fill('ADIDAS');
  const regions = form.getByRole('group', { name: /^Regions/ });
  await regions.getByRole('button', { name: /Add item/i }).click({ timeout: 10_000 });
  const firstRegion = regions.getByRole('combobox').first();
  expect(await firstRegion.locator('option').evaluateAll((options: HTMLOptionElement[]) => options.map(option => option.value).filter(Boolean)))
    .toEqual(['US', 'EU', 'DE', 'WORLDWIDE']);
  await firstRegion.selectOption('US');
  await regions.getByRole('button', { name: /Add item/i }).click();
  await regions.getByRole('combobox').nth(1).selectOption('DE');
  await form.getByTestId('apps-skill-settings-toggle').click();
  await form.getByRole('combobox', { name: 'Match', exact: true }).selectOption('exact');
  const executed = page.waitForResponse((response: any) => response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/v1/apps/business/skills/search_trademarks');
  await form.getByTestId('apps-skill-submit').click();
  const response = await executed;
  expect(response.ok()).toBe(true);
  expect(response.request().postDataJSON()).toMatchObject({ queries: ['ADIDAS'], regions: ['US', 'DE'], match: 'exact' });
  const inline = page.getByTestId('apps-inline-results-grid');
  await expect(inline.getByTestId('embed-preview')).toHaveCount(1, { timeout: 60_000 });
  await expect(inline).toContainText('ADIDAS');
  await expect(inline).toContainText('US · Checked');
  await expect(inline).toContainText('DE · Not searched');
  await inline.getByTestId('embed-preview').click();
  const fullscreen = page.getByTestId('apps-result-fullscreen');
  await expect(fullscreen.getByTestId('trademark-record').first()).toContainText(/ADIDAS/i);
  await expect(fullscreen.getByTestId('trademark-search-coverage')).toContainText('Not searched');
  await expect(fullscreen.getByTestId('trademark-record-source').first()).toHaveAttribute('href', /^https:\/\/tsdr\.uspto\.gov\/#caseNumber=/);
  await expect(fullscreen.getByTestId('trademark-fullscreen-limitation')).toContainText('legal availability');
  await page.setViewportSize({ width: 1280, height: 950 });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(fullscreen.getByTestId('trademark-record').first()).toContainText(/ADIDAS/i, { timeout: 30_000 });
  await expect(fullscreen.getByTestId('trademark-search-coverage')).toContainText('DE');
  await fullscreen.getByTestId('embed-minimize').click();
  await expect(fullscreen).toHaveCount(0);
});
