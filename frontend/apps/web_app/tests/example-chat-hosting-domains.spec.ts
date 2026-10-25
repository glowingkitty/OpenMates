// playwright-account: not_required reason=public_removed_example_routes
import { waitForComponentPreview } from './helpers/component-preview';
import { expect, test } from './helpers/cookie-audit';
import { ALL_EXAMPLE_CHATS, INTERNAL_EXAMPLE_CHATS } from '../../../packages/ui/src/demo_chats/exampleChatData';
import { landingAppExamples } from '../../../packages/public-site/src/components/landing/landingPageContent';

// Removed public examples must not become hidden direct-hash fixtures.
const unpublished = [
  { slug: 'social-app-name-domain-search', chatId: 'example-social-app-name-domain' },
];

for (const { slug, chatId } of unpublished) {
  // contract-test: direct surface=gui.web assertions=public-example-chats.catalog.discoverable,public-example-chats.seo.crawlable,marketing-landing.example-catalog-alignment
  test(`${slug} has no public route, catalog entry, landing link or hash transcript`, async ({ page, request }) => {
    for (const registry of [ALL_EXAMPLE_CHATS, INTERNAL_EXAMPLE_CHATS]) {
      expect(registry.some(chat => chat.slug === slug || chat.chat_id === chatId)).toBe(false);
    }
    expect(Object.values(landingAppExamples)).not.toContain(chatId);
    const response = await request.get(`/example/${slug}`);
    expect(response.status()).toBe(404);

    const catalog = await request.get('/example');
    expect(catalog.status()).toBe(200);
    const html = await catalog.text();
    expect(html).not.toContain(`/example/${slug}`);
    expect(html).not.toContain(chatId);

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('header-login-signup-btn')).toBeVisible();
    await expect(page.locator(`a[href*="/example/${slug}"], a[href*="chat-id=${chatId}"]`)).toHaveCount(0);

    await page.goto(`/#chat-id=${chatId}`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('header-login-signup-btn')).toBeVisible();
    await expect(page.getByTestId('user-message-content')).toHaveCount(0);
    await expect(page.getByTestId('message-assistant')).toHaveCount(0);
    await expect(page.getByTestId('embed-preview')).toHaveCount(0);
  });
}


for (const width of [390, 1440]) {
  // contract-test: direct surface=gui.web assertions=app-skills.history.renderable
  test(`saved hosting result remains readable at ${width}px without public admission`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    for (const mode of ['Preview', 'Fullscreen']) {
      await page.goto(`/dev/preview/embeds/hosting/HostingDomainEmbed${mode}?chrome=0&width=${width}`);
      const canvas = await waitForComponentPreview(page);
      await expect(canvas).toBeVisible();
      expect((await canvas.innerText()).trim().length).toBeGreaterThan(20);
      await expect(canvas.locator('a[href^="javascript:"]')).toHaveCount(0);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
    }
  });
}
