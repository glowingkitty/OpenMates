// playwright-account: not_required reason=public_guest_example_catalog
import { expect, test } from './helpers/cookie-audit';
import expectations from '../../../packages/ui/src/demo_chats/__tests__/fixtures/curatedExampleExpectations.json';

// contract-test: direct surface=gui.web assertions=public-example-chats.catalog.discoverable,public-example-chats.seo.crawlable,marketing-landing.example-catalog-alignment
test('retired examples have no catalog, landing link or direct public route', async ({ request }) => {
  test.setTimeout(120_000);
  const listing = await request.get('/example');
  expect(listing.status()).toBe(200);
  const landing = await request.get('/');
  expect(landing.status()).toBe(200);
  const catalogHtml = await listing.text();
  const landingHtml = await landing.text();
  for (const example of [...expectations.qualityRetiredExamples, ...expectations.unsupportedProviderExamples]) {
    expect(catalogHtml, example.chatId).not.toContain(`/example/${example.slug}`);
    expect(landingHtml, example.chatId).not.toContain(`chat-id=${example.chatId}`);
    expect(landingHtml, example.slug).not.toContain(`/example/${example.slug}`);
    const response = await request.get(`/example/${example.slug}`);
    expect(response.status(), example.slug).toBe(404);
  }
  const admitted = await request.get('/example/gigantic-airplanes-transporting-rocket-parts');
  expect(admitted.status()).toBe(200);
  const admittedHtml = await admitted.text();
  expect(admittedHtml).toMatch(/<h1\b[^>]*>[^<]*Gigantic airplanes for transporting rocket and airplane parts/i);
  expect(admittedHtml).toContain('Antonov An-225');
});

// contract-test: direct surface=gui.web assertions=public-example-chats.catalog.discoverable,public-example-chats.navigation.static-public-link,marketing-landing.example-catalog-alignment
test('unsupported-provider chat IDs cannot reopen through direct hash navigation', async ({ page }) => {
  test.setTimeout(180_000);
  for (const example of expectations.unsupportedProviderExamples) {
    await page.goto(`/#chat-id=${example.chatId}`, { waitUntil: 'domcontentloaded' });
    const chat = page.getByTestId('active-chat-container');
    await expect(chat).toBeVisible();
    await expect(page.getByTestId('login-wrapper')).toBeVisible();
    await expect(page.getByTestId('example-chat-badge')).toHaveCount(0);
    await expect(chat).not.toHaveAttribute('data-current-chat-id', example.chatId);
    await expect(page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${example.chatId}"]`)).toHaveCount(0);
  }
});
