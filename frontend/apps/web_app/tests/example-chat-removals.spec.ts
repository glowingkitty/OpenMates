// playwright-account: not_required reason=public_guest_example_catalog
import { expect, test } from './helpers/cookie-audit';
import expectations from '../../../packages/ui/src/demo_chats/__tests__/fixtures/curatedExampleExpectations.json';
const RETIRED_LOW_QUALITY_EXAMPLES = expectations.qualityRetiredExamples;

// contract-test: direct surface=gui.web assertions=public-example-chats.catalog.discoverable,public-example-chats.seo.crawlable,marketing-landing.example-catalog-alignment
  test('retired low-quality examples have no public listing or direct route', async ({ request }: { request: any }) => {
    test.setTimeout(120000);
    const listing = await request.get('/example');
    expect(listing.status()).toBe(200);
    const html = await listing.text();
    for (const example of RETIRED_LOW_QUALITY_EXAMPLES) {
      expect(html, example.chatId).not.toContain(`/example/${example.slug}`);
      const response = await request.get(`/example/${example.slug}`);
      expect(response.status(), example.slug).toBe(404);
    }
  });
