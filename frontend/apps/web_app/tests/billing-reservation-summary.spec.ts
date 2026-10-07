/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers use CommonJS. */
/** Isolated product REST proof for owner-scoped billing reservation aggregates. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, createSignupLogger, createStepScreenshotter } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const API_URL = process.env.PLAYWRIGHT_TEST_API_URL?.replace(/\/$/, '');
const BILLING_PATH = '/v1/settings/billing';

// contract-test: direct surface=rest_api assertions=billing.access.authenticated-first-party,billing.credits.idempotent-charge
test('billing reservation totals require a session and contain no private hold identifiers',
  async ({ page, playwright }: { page: any; playwright: any }) => {
    test.setTimeout(120_000);
    if (!API_URL) throw new Error('Isolated PLAYWRIGHT_TEST_API_URL is required.');
    if (!getTestAccount().email) throw new Error('Fresh isolated test account is required.');
    const url = `${API_URL}${BILLING_PATH}`;

    const anonymous = await playwright.request.newContext();
    try {
      const denied = await anonymous.get(url);
      expect([401, 403]).toContain(denied.status());
      const invalidKey = await anonymous.get(url, {
        headers: { Authorization: 'Bearer sk-api-invalid-key' },
      });
      expect([401, 403]).toContain(invalidKey.status());
    } finally {
      await anonymous.dispose();
    }

    const log = createSignupLogger('billing-reservation-summary');
    const screenshot = createStepScreenshotter(log);
    await loginToTestAccount(page, log, screenshot);
    const response = await page.request.get(url);
    expect(response.ok()).toBe(true);
    const overview = await response.json();
    expect(Number.isInteger(overview.held_credits)).toBe(true);
    expect(Number.isInteger(overview.review_required_credits)).toBe(true);
    expect(overview.held_credits).toBe(0);
    expect(overview.review_required_credits).toBe(0);
    expect(overview).not.toHaveProperty('billing_reservations');
    expect(overview).not.toHaveProperty('charge_id');
    expect(overview).not.toHaveProperty('subject_hash');
  });
