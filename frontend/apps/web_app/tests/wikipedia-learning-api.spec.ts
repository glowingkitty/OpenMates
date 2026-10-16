/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');

// contract-test: direct surface=rest_api assertions=wikipedia-mentions.learning.public-cache,wikipedia-mentions.provider.bounded-access
test('wiki learning generation requires authentication even with a web Origin', async ({ request }: { request: any }) => {
    const webUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || 'http://localhost:3000';
    const apiUrl = deriveApiUrl(webUrl);
    const endpoint = `${apiUrl}/v1/wikipedia/learning?title=Ada_Lovelace&language=en`;
    const anonymous = await request.get(endpoint);
    expect(anonymous.status()).toBe(401);
    const originOnly = await request.get(endpoint, { headers: { Origin: new URL(webUrl).origin } });
    expect(originOnly.status()).toBe(401);
});
