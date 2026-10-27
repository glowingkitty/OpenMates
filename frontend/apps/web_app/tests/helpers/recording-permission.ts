import type { Page } from '@playwright/test';

/** Allow a fake microphone in an explicitly scoped browser-test document. */
export async function allowFixtureMicrophone(page: Page, documentUrl: string | RegExp): Promise<void> {
  // The runner's SvelteKit server denies device permissions by default. Keep
  // every other policy directive while allowing the test's synthetic microphone.
  await page.route(documentUrl, async route => {
    if (route.request().resourceType() !== 'document') return route.fallback();
    const response = await route.fetch();
    const headers = response.headers();
    await route.fulfill({ response, headers: {
      ...headers,
      'permissions-policy': (headers['permissions-policy'] ?? '').replace('microphone=()', 'microphone=(self)'),
    } });
  });
}
