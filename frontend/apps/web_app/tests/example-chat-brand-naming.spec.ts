/* eslint-disable @typescript-eslint/no-require-imports */
/** Real CLI naming transcript, app-store links and saved trademark evidence. */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');

const slug = 'find-brand-name-and-domain';
const chatId = 'example-find-brand-name-and';

async function expandActivityDetails(page: any) {
  const toggles = page.getByTestId('assistant-activity-toggle');
  for (const toggle of await toggles.all()) {
    if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
  }
}

for (const [viewport, size] of [
  ['phone', { width: 390, height: 844 }],
  ['laptop', { width: 1440, height: 1000 }],
] as const) {
  // contract-test: direct surface=gui.web assertions=brand-naming.flow,trademarks.parity,public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  test(`real brand naming example and trademark fullscreen render on ${viewport}`, async ({ page, request }: any, testInfo: any) => {
    test.setTimeout(120_000);
    const response = await request.get(`/example/${slug}`);
    expect(response.status()).toBe(200);
    const html = await response.text();
    for (const name of ['Equafy', 'Cadenceo']) expect(html).toContain(name);
    for (const marker of ['vault:v1:', 'vault_key_id', 'aes_key', 'aes_nonce', 'example_chats.find_brand_name_and_domain']) {
      expect(html).not.toContain(marker);
    }
    await page.setViewportSize(size);
    await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('user-message-content').filter({ hasText: 'Help me find a name for my new product.' }).first())
      .toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('focus-pill-label')).toContainText(/brand name/i);
    const activation = page.getByTestId('assistant-activity-toggle').filter({ hasText: "Activated 'Find a brand name'" }).first();
    await expect(activation).toBeVisible();
    await expandActivityDetails(page);
    await expect(page.locator('[data-testid="focus-mode-bar"][data-focus-id="business-find_brand_name"]').first()).toBeVisible();
    const parent = page.getByTestId('embed-preview').filter({ has: page.getByTestId('trademark-search-preview') }).first();
    await parent.scrollIntoViewIfNeeded();
    await expect(parent).toContainText('ExampleTrademarks');
    await expect(parent).toContainText('US · Checked');
    await testInfo.attach(`brand-naming-${viewport}-preview`, { body: await parent.screenshot(), contentType: 'image/png' });
    const fullscreen = await openFullscreen(page, parent);
    const coverage = fullscreen.getByTestId('trademark-search-coverage');
    await expect(coverage).toContainText('Equafy');
    await expect(coverage).toContainText('Cadenceo');
    await expect(fullscreen.getByTestId('trademark-fullscreen-limitation')).toContainText('legal availability');
    await expect(fullscreen.getByTestId('trademark-record-source').first()).toHaveAttribute('href', /^https:\/\/tsdr\.ExampleTrademarks\.gov\/#caseNumber=/);
    await testInfo.attach(`brand-naming-${viewport}-fullscreen`, { body: await page.screenshot({ animations: 'disabled' }), contentType: 'image/png' });
    await closeFullscreen(page, fullscreen);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(activation).toBeVisible({ timeout: 30_000 });
    await expandActivityDetails(page);
    await expect(parent).toBeVisible({ timeout: 30_000 });

    for (const [path, section] of [
      ['skill/search_trademarks', 'app-store-example-chats'],
      ['focus/find_brand_name', 'app-store-focus-mode-example-chats'],
    ]) {
      await page.goto(getE2EDebugUrl(`/#settings/apps/business/${path}`), { waitUntil: 'domcontentloaded' });
      if (path.startsWith('skill/')) await page.getByTestId('apps-skill-context-toggle').click();
      const card = page.getByTestId(section).getByTestId('app-store-example-chat-card').filter({ hasText: 'Find a brand name and domain' });
      await expect(card).toBeVisible({ timeout: 30_000 });
    }
  });
}
