import { expect, test } from '../helpers/cookie-audit';
import type { Page, TestInfo } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path fill="currentColor" d="M3 10 12 2l9 8v12H3z"/></svg>';
async function iconRoute(page: Page) {
  await page.route('**/v1/apps/design/icons/iconify/**', route => route.fulfill({
    status: 200, contentType: 'image/svg+xml', headers: { 'Access-Control-Allow-Origin': '*' }, body: svg,
  }));
}
async function open(page: Page, app: string, component: string, width: number, variant?: string) {
  await page.setViewportSize({ width, height: 900 });
  await page.goto(`/dev/preview/embeds/${app}/${component}?chrome=0&theme=light&width=${width}${variant ? `&variant=${variant}` : ''}`);
  await waitForComponentPreview(page);
}
async function capture(page: Page, testInfo: TestInfo, name: string) {
  await testInfo.attach(name, { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
}
for (const width of [390, 1100]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`weather result preview retains supplied values and unknown fallback at ${width}px`, async ({ page }, testInfo) => {
    await open(page, 'weather', 'WeatherDayEmbedPreview', width);
    await expect(page.getByTestId('weather-day-preview')).toBeVisible();
    await expect(page.getByTestId('weather-day-temperature')).toHaveText('14° / 19°');
    await expect(page.getByTestId('weather-day-metrics')).toContainText('67%');
    await expect(page.getByTestId('result-card-title')).toBeVisible();
    await capture(page, testInfo, `weather-preview-default-${width}px`);
    await open(page, 'weather', 'WeatherDayEmbedPreview', width, 'missing');
    await expect(page.getByTestId('weather-day-temperature')).toHaveText('—');
    await expect(page.getByTestId('weather-day-metrics')).toHaveText('— · — · —');
    await expect(page.getByTestId('result-card-media')).toHaveCount(0);
    await capture(page, testInfo, `weather-preview-missing-${width}px`);
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`weather fullscreen keeps hourly detail and compact factual controls at ${width}px`, async ({ page }, testInfo) => {
    await open(page, 'weather', 'WeatherDayEmbedFullscreen', width);
    await expect(page.getByTestId('weather-day-fullscreen')).toBeVisible();
    await expect(page.getByTestId('result-facts')).toContainText('14° / 19°');
    await expect(page.getByTestId('result-facts')).toContainText('67%');
    await expect(page.getByTestId('weather-hourly-row')).toHaveCount(5);
    const rain = page.getByTestId('result-facts').getByRole('button').filter({ hasText: '67%' });
    await rain.click();
    await expect(page.getByRole('tooltip')).toContainText('5.8 mm');
    await expect(page.getByRole('tooltip')).toContainText('13h');
    await page.keyboard.press('Escape');
    await capture(page, testInfo, `weather-fullscreen-default-${width}px`);
    await open(page, 'weather', 'WeatherDayEmbedFullscreen', width, 'missing');
    await expect(page.getByTestId('weather-hourly-row')).toHaveCount(0);
    await expect(page.getByTestId('result-facts')).not.toContainText('0%');
    await expect(page.getByTestId('weather-hourly-table').locator('.empty-hourly')).toHaveText('Hourly forecast unavailable');
    await capture(page, testInfo, `weather-fullscreen-missing-${width}px`);
    await open(page, 'weather', 'WeatherDayEmbedFullscreen', width, 'zero');
    await expect(page.getByTestId('result-facts')).toContainText('0° / 0°');
    await expect(page.getByTestId('result-facts')).toContainText('0%');
    await expect(page.getByTestId('weather-hourly-row')).toContainText('0 mm');
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`design icon preview loads entire sanitized asset and missing fallback at ${width}px`, async ({ page }, testInfo) => {
    await iconRoute(page);
    await open(page, 'design', 'DesignIconResultEmbedPreview', width);
    const image = page.getByTestId('result-card-media').locator('img');
    await expect(image).toBeVisible();
    await expect(image).toHaveCSS('object-fit', 'contain');
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    await expect(image).toHaveAttribute('src', /\/v1\/apps\/design\/icons\/iconify\/tabler\/home\.svg/);
    await expect(page.getByTestId('result-card-title')).toHaveText('Home');
    await capture(page, testInfo, `design-icon-preview-default-${width}px`);
    await open(page, 'design', 'DesignIconResultEmbedPreview', width, 'missing');
    await expect(page.getByTestId('result-card-title')).toHaveText('Home');
    await expect(page.getByTestId('result-card-media')).toHaveCount(0);
    await capture(page, testInfo, `design-icon-preview-missing-${width}px`);
  });
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`design icon fullscreen retains attribution, recoloring and exports at ${width}px`, async ({ page }, testInfo) => {
    await iconRoute(page);
    await open(page, 'design', 'DesignIconResultEmbedFullscreen', width);
    const fullscreen = page.getByTestId('design-icon-result-fullscreen');
    await expect(fullscreen).toBeVisible();
    await expect(fullscreen).toContainText('MIT');
    const artwork = fullscreen.locator('.icon-stage svg');
    await expect(artwork).toBeVisible();
    await expect(artwork).toHaveAttribute('viewBox', '0 0 24 24');
    await expect(fullscreen.getByRole('button', { name: 'Copy SVG', exact: true })).toBeEnabled();
    const svgExport = fullscreen.getByRole('button', { name: 'Download SVG', exact: true });
    const pngExport = fullscreen.getByRole('button', { name: 'Download PNG', exact: true });
    await expect(svgExport).toHaveAttribute('href', /^data:image\/svg\+xml/);
    await expect(pngExport).toHaveAttribute('href', /^data:image\/png/);
    await expect(page.getByTestId('design-icon-provider-cta')).toHaveAttribute('href', 'https://icon-sets.iconify.design/tabler/home/');
    await capture(page, testInfo, `design-icon-fullscreen-default-${width}px`);
    await page.getByTestId('design-icon-color-input').fill('#2563eb');
    await expect(artwork).toHaveAttribute('color', '#2563eb');
    await expect(svgExport).toHaveAttribute('href', /%232563eb/);
    const download = page.waitForEvent('download');
    await svgExport.click();
    expect((await download).suggestedFilename()).toBe('tabler-home.svg');
    await open(page, 'design', 'DesignIconResultEmbedFullscreen', width, 'missing');
    await expect(page.getByTestId('design-icon-result-fullscreen').locator('.placeholder-icon')).toBeVisible();
    await expect(page.getByTestId('result-facts')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Copy SVG', exact: true })).toBeDisabled();
    await expect(page.getByTestId('design-icon-provider-cta')).toHaveCount(0);
    await capture(page, testInfo, `design-icon-fullscreen-missing-${width}px`);
  });
}

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('result followups allow only visible metadata from supplied and decoded result records', async ({ page }) => {
  test.setTimeout(120_000);
  const sentinel = 'private-result-storage-sentinel';
  const hidden = {
    aes_key: sentinel, aesKey: sentinel, aes_nonce: sentinel, aesNonce: sentinel,
    files: { original: { encryption: sentinel } }, storage: { private_path: sentinel },
    unrecognized_payload: { nested: sentinel },
  };
  const cases = [
    {
      component: 'shopping/ShoppingResultEmbedFullscreen',
      props: { product: { ...hidden, embed_id: 'safe-product', title: 'Visible product', provider: 'REWE', stock: 0, attributes: { ...hidden, is_organic: true } } },
      expected: { title: 'Visible product', stock: 0, organic: true },
    },
    {
      component: 'nutrition/NutritionRecipeEmbedFullscreen',
      props: { recipe: { ...hidden, embed_id: 'safe-recipe', title: 'Visible recipe', servings: 4,
        ingredients: [{ ...hidden, amount: '1', unit: 'g', name: 'Visible ingredient' }],
        instructions: [{ ...hidden, text: 'Visible instruction' }], nutrition: { ...hidden, protein_g: 0 } } },
      expected: { title: 'Visible recipe', ingredients: [{ amount: '1', unit: 'g', name: 'Visible ingredient' }], instructions: [{ text: 'Visible instruction' }], nutrition: { protein_g: 0 } },
    },
    {
      component: 'fitness/FitnessResultEmbedFullscreen',
      props: { data: { ...hidden, decodedContent: { ...hidden, name: 'Visible class', date: '2026-10-26', time_range: '07:30 - 08:30', distance_km: 0 } } },
      expected: { title: 'Visible class', date: '2026-10-26', distance_km: 0 },
    },
    {
      component: 'design/DesignIconResultEmbedFullscreen',
      props: { data: { embedData: hidden, attrs: hidden, decodedContent: { ...hidden, display_name: 'Visible icon', license_title: 'MIT' } } },
      expected: { title: 'Visible icon', license: 'MIT' },
    },
    {
      component: 'weather/WeatherDayEmbedFullscreen',
      props: { data: { ...hidden, decodedContent: { ...hidden, location_name: 'Berlin', temperature_min_c: 0, hourly: [{ ...hidden, time: '00:00', temperature_c: 0 }] } } },
      expected: { location_name: 'Berlin', temperature_min_c: 0, hourly: [{ time: '00:00', temperature_c: 0 }] },
    },
  ];
  await page.route('**/v1/apps/workspace/interpret', route => route.fulfill({ status: 503, json: { detail: 'isolated component request' } }));
  for (const entry of cases) {
    const props = encodeURIComponent(JSON.stringify(entry.props));
    await page.goto(`/dev/preview/embeds/${entry.component}?chrome=0&width=700&props=${props}`);
    await waitForComponentPreview(page);
    await page.getByTestId('apps-request-textarea').fill('Explain this visible result');
    const pending = page.waitForRequest('**/v1/apps/workspace/interpret');
    await page.getByTestId('apps-request-submit').click();
    const request = await pending;
    const body = request.postDataJSON();
    expect(body.context.result).toMatchObject(entry.expected);
    expect(JSON.stringify(body.context.result)).not.toContain(sentinel);
    for (const key of Object.keys(hidden)) expect(body.context.result).not.toHaveProperty(key);
  }
});
