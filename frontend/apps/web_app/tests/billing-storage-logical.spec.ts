/* eslint-disable @typescript-eslint/no-require-imports */
/** Real PG/S3 page and upload metering under the isolated logical-S3 profile. */
export {};

const { test, expect } = require('./console-monitor');
const { getTestAccount, createSignupLogger, createStepScreenshotter } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

// Two independent password/TOTP logins include crypto and window-boundary waits.
test.setTimeout(90_000);

const API_URL = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
const LEGACY_BYTES = Number(process.env.E2E_STORAGE_BILLING_EXPECTED_LEGACY_BYTES || 0);
const PAGE_BYTES = Number(process.env.E2E_STORAGE_BILLING_EXPECTED_PAGE_BYTES || 0);
const TOTAL_BYTES = Number(process.env.E2E_STORAGE_BILLING_EXPECTED_TOTAL_BYTES || 0);

// contract-test: direct surface=rest_api assertions=billing.storage.logical-usage,billing.storage.weekly-quote,billing.storage.disclosures
// contract-test: supporting surface=rest_api assertions=billing.storage.team-policy-gate
test('storage overview bills one real logical page once alongside the small upload',
  async ({ page, playwright, browser }: { page: any; playwright: any; browser: any }) => {
    if (process.env.E2E_STORAGE_BILLING_LOGICAL_PROFILE !== '1') throw new Error('Isolated logical-S3 storage billing profile required.');
    if (!getTestAccount().email || !getTestAccount(2).email) {
      throw new Error('Two disposable test accounts are required for owner isolation.');
    }
    expect(getTestAccount(2).email).not.toBe(getTestAccount().email);
    expect(process.env.E2E_STORAGE_BILLING_TEAM_UNRATED).toBe('1');
    expect(process.env.E2E_STORAGE_BILLING_CONFLICT_REJECTED).toBe('1');
    expect(process.env.E2E_STORAGE_BILLING_EXPIRY_VERIFIED).toBe('1');
    expect(LEGACY_BYTES).toBeGreaterThan(0);
    expect(PAGE_BYTES).toBeGreaterThan(0);
    expect(TOTAL_BYTES).toBe(LEGACY_BYTES + PAGE_BYTES);

    const log = createSignupLogger('billing-storage-logical');
    const screenshot = createStepScreenshotter(log);
    await loginToTestAccount(page, log, screenshot);
    const url = `${API_URL}/v1/settings/storage`;
    const anonymous = await playwright.request.newContext();
    try {
      const denied = await anonymous.get(url);
      expect([401, 403]).toContain(denied.status());
      const noticeDenied = await anonymous.get(`${url}/notice?limit=50`);
      expect([401, 403]).toContain(noticeDenied.status());
    } finally {
      await anonymous.dispose();
    }

    const quoteRequestStarted = Math.floor(Date.now() / 1000);
    const response = await page.request.get(url);
    const quoteResponseFinished = Math.ceil(Date.now() / 1000);
    expect(response.ok()).toBe(true);
    const overview = await response.json();
    const noticeResponse = await page.request.get(`${url}/notice?limit=50`);
    expect(noticeResponse.ok()).toBe(true);
    const ownerNotice = await noticeResponse.json();
    expect(ownerNotice).toMatchObject({ episode_id: null, warning_count: 0, units: [], has_more: false });
    expect(overview.measurement_at).toBeGreaterThanOrEqual(quoteRequestStarted - 1);
    expect(overview.measurement_at).toBeLessThanOrEqual(quoteResponseFinished + 1);
    expect(overview.metering_source_version).toBe('logical-s3-v1');
    expect(overview.metering_policy_version).toBe('personal-storage-1gb-3credits-week-v1');
    expect(overview.total_bytes).toBe(TOTAL_BYTES);
    expect(overview.logical_s3_bytes).toBe(PAGE_BYTES);
    expect(overview.metering_categories).toEqual({ chat_pages: PAGE_BYTES });
    expect(overview.total_files).toBe(1);
    expect(overview.breakdown).toContainEqual({
      category: 'other', bytes_used: LEGACY_BYTES, file_count: 1
    });
    expect(overview.breakdown.reduce((sum: number, row: any) => sum + row.bytes_used, 0))
      .toBe(LEGACY_BYTES);

    // A second fresh owner has no access to the first owner's upload or archive.
    const otherContext = await browser.newContext();
    try {
      const otherPage = await otherContext.newPage();
      await loginToTestAccount(otherPage, log, screenshot, { credentials: getTestAccount(2) });
      const otherResponse = await otherPage.request.get(url);
      expect(otherResponse.ok()).toBe(true);
      const otherOverview = await otherResponse.json();
      expect(otherOverview.total_bytes).toBe(0);
      expect(otherOverview.total_files).toBe(0);
      expect(otherOverview.logical_s3_bytes).toBe(0);
      const otherNoticeResponse = await otherPage.request.get(`${url}/notice?limit=50`);
      expect(otherNoticeResponse.ok()).toBe(true);
      const otherNotice = await otherNoticeResponse.json();
      expect(otherNotice).toMatchObject({ episode_id: null, warning_count: 0, units: [], has_more: false });
    } finally {
      await otherContext.close();
    }
    const free = 1_073_741_824;
    const expectedBillableGb = Math.max(0, Math.ceil((TOTAL_BYTES - free) / free));
    expect(overview.billable_gb).toBe(expectedBillableGb);
    expect(overview.weekly_cost_credits).toBe(expectedBillableGb * 3);
  });
