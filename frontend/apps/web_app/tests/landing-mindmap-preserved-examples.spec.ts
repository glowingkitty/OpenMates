// playwright-account: not_required reason=public_logged_out_example_admission
/* eslint-disable @typescript-eslint/no-require-imports -- The browser helper uses CommonJS. */
import { ALL_EXAMPLE_CHATS, INTERNAL_EXAMPLE_CHATS } from '../../../packages/ui/src/demo_chats/exampleChatData';
import { landingAppExamples } from '../../../packages/public-site/src/components/landing/landingPageContent';
import type { Page, APIRequestContext, TestInfo } from '@playwright/test';
import { admitLandingExample, type LandingViewport } from './landing-app-example-admission';
const { test, expect } = require('./helpers/cookie-audit');
import { booksAfterLeftHandOfDarknessChat } from '../../../packages/ui/src/demo_chats/data/example_chats/books-after-left-hand-of-darkness';

const reviewed = [
  { appId: 'books', chat: booksAfterLeftHandOfDarknessChat },
];

for (const viewport of ['phone', 'laptop'] as LandingViewport[]) {
  for (const { appId, chat } of reviewed) {
    // contract-test: direct surface=gui.web assertions=public-example-chats.admission.reviewed-complete,public-example-chats.transcript.safe-rendering,public-example-chats.catalog.discoverable,marketing-landing.interactive-rail,marketing-landing.hero-app-rail
    test(`${appId} example verifies header, transcript and artifacts on ${viewport}`, async (
      { page, request }: { page: Page; request: APIRequestContext }, testInfo: TestInfo
    ) => {
      test.setTimeout(180_000);
      await admitLandingExample(page, request, testInfo, appId, chat, viewport);
    });
  }
}


// Removed public examples must not become hidden direct-hash fixtures.
const unpublished = [
  { slug: 'printable-benchy-phone-stand-models', chatId: 'example-printable-benchy-phone-stand' },
  { slug: 'ai-workshops-meetups-berlin', chatId: 'example-ai-workshops-meetups-berlin' },
  { slug: 'deutschlandticket-train-fare-breakdown', chatId: 'example-deutschlandticket-train-fare-breakdown' },
  { slug: 'beginner-yoga-classes-berlin', chatId: 'example-beginner-yoga-classes-berlin' },
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
