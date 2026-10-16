// playwright-account: not_required reason=public_logged_out_example_admission
// contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
/* eslint-disable @typescript-eslint/no-require-imports -- The shared browser helper uses CommonJS. */
import type { Page, APIRequestContext, TestInfo } from '@playwright/test';
import { airFryersAmazonGermanyChat } from '../../../packages/ui/src/demo_chats/data/example_chats/air-fryers-amazon-germany';
import {
  admitLandingExample, type FixtureImageProxyObservation, type LandingViewport
} from './landing-app-example-admission';

const { test, expect } = require('./helpers/cookie-audit');

const fixtureProductImageUrls = new Set(
  airFryersAmazonGermanyChat.embeds
    .filter(embed => embed.type === 'product')
    .map(embed => embed.content.match(/^image_url: "([^"]+)"$/m)?.[1])
    .filter((url): url is string => Boolean(url))
);

for (const viewport of ['phone', 'laptop'] as LandingViewport[]) {
  // contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  test(`shopping replacement example admits its real Amazon Germany chat on ${viewport}`, async (
    { page, request }: { page: Page; request: APIRequestContext }, testInfo: TestInfo
  ) => {
    test.setTimeout(150_000);
    expect(airFryersAmazonGermanyChat.metadata.app_skill_examples).toContain('shopping.search_products');
    expect(airFryersAmazonGermanyChat.follow_up_suggestions.length).toBeGreaterThan(0);
    expect(fixtureProductImageUrls.size).toBeGreaterThan(0);

    // Shared admission supplies the declared app Referer for fixture images
    // requested from localhost CI while checking actual public proxy pixels.
    const routeObservations: FixtureImageProxyObservation[] = [];
    const imageNetwork: Array<Record<string, unknown>> = [];
    const proxyImageRequest = (url: string): boolean => {
      try { return new URL(url).pathname === '/api/v1/image'; }
      catch { return false; }
    };
    page.on('request', request => {
      if (proxyImageRequest(request.url())) imageNetwork.push({
        event: 'request', url: request.url(), resourceType: request.resourceType(),
        referer: request.headers().referer ?? null,
      });
    });
    page.on('response', response => {
      if (proxyImageRequest(response.url())) imageNetwork.push({
        event: 'response', url: response.url(), status: response.status(),
        contentType: response.headers()['content-type'] ?? null,
      });
    });
    page.on('requestfailed', request => {
      if (proxyImageRequest(request.url())) imageNetwork.push({
        event: 'requestfailed', url: request.url(), failure: request.failure(),
      });
    });
    try {
      await admitLandingExample(page, request, testInfo, 'shopping', airFryersAmazonGermanyChat,
        viewport, routeObservations);
    } finally {
      const renderedImages = await page.locator('[data-testid="embed-preview"] img, .product-fullscreen img.product-image')
        .evaluateAll((images: HTMLImageElement[]) => images.map(image => ({
          src: image.src, currentSrc: image.currentSrc, complete: image.complete,
          naturalWidth: image.naturalWidth,
        }))).catch(() => []);
      await testInfo.attach(`shopping-image-network-${viewport}.json`, {
        body: Buffer.from(JSON.stringify({
          fixtureProductImageUrls: [...fixtureProductImageUrls],
          routeObservations, imageNetwork, renderedImages,
        }, null, 2)), contentType: 'application/json'
      });
    }
  });
}
