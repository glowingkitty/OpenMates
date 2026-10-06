/* eslint-disable @typescript-eslint/no-require-imports */
/** Authenticated REST check for the default-off storage billing measurement. */
export {};

const { test, expect } = require('./console-monitor');
const { getTestAccount, createSignupLogger, createStepScreenshotter } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

// Two independent password/TOTP logins include crypto and window-boundary waits.
test.setTimeout(90_000);

const EXPECTED_LEGACY_BYTES = Number(process.env.E2E_STORAGE_BILLING_EXPECTED_LEGACY_BYTES || 0);
const API_URL = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';

// contract-test: direct surface=rest_api assertions=billing.storage.weekly-quote,billing.storage.disclosures
// contract-test: supporting surface=rest_api assertions=billing.storage.team-policy-gate
// The logical-S3 enabled profile requires an authenticated canonical S3-page fixture;
// this case verifies only the default-off policy on an isolated account.
test('storage overview uses the legacy upload quote while logical S3 billing is off',
  async ({ page, playwright, browser }: { page: any; playwright: any; browser: any }) => {
    if (process.env.E2E_STORAGE_BILLING_LEGACY_PROFILE !== '1') throw new Error('Isolated default-off storage billing profile required.');
    if (!getTestAccount().email || !getTestAccount(2).email) {
      throw new Error('Two disposable test accounts are required for owner isolation.');
    }
    expect(getTestAccount(2).email).not.toBe(getTestAccount().email);
    // This proves only the isolated CMS financial guard; API remains self-hosted.
    expect(process.env.E2E_STORAGE_BILLING_TEAM_RATED).toBeUndefined();
    expect(process.env.E2E_STORAGE_BILLING_CMS_TEAM_DISABLED_CLAIM_REJECTED).toBe('1');
    expect(process.env.E2E_STORAGE_BILLING_CONFLICT_REJECTED).toBe('1');
    expect(EXPECTED_LEGACY_BYTES).toBeGreaterThan(0);
    const log = createSignupLogger('billing-storage-quote');
    const screenshot = createStepScreenshotter(log);
    await loginToTestAccount(page, log, screenshot);

    const url = `${API_URL}/v1/settings/storage`;
    const anonymous = await playwright.request.newContext();
    try {
      const denied = await anonymous.get(url);
      expect([401, 403]).toContain(denied.status());
    } finally {
      await anonymous.dispose();
    }

    const quoteRequestStarted = Math.floor(Date.now() / 1000);
    const response = await page.request.get(url);
    const quoteResponseFinished = Math.ceil(Date.now() / 1000);
    expect(response.ok()).toBe(true);
    const overview = await response.json();
    expect(overview.measurement_at).toBeGreaterThanOrEqual(quoteRequestStarted - 1);
    expect(overview.measurement_at).toBeLessThanOrEqual(quoteResponseFinished + 1);
    expect(overview.metering_source_version).toBe('legacy-upload-files-v1');
    expect(overview.metering_policy_version).toBe('legacy-upload-storage-1gb-3credits-week-v1');
    expect(overview.logical_s3_bytes).toBe(0);
    expect(overview.metering_categories).toEqual({});
    expect(overview.total_bytes).toBe(EXPECTED_LEGACY_BYTES);
    expect(overview.total_files).toBe(1);
    expect(overview.breakdown).toContainEqual({
      category: 'other', bytes_used: EXPECTED_LEGACY_BYTES, file_count: 1
    });
    expect(overview.total_bytes).toBe(
      overview.breakdown.reduce((sum: number, row: any) => sum + row.bytes_used, 0)
    );
    expect(overview.total_files).toBe(
      overview.breakdown.reduce((sum: number, row: any) => sum + row.file_count, 0)
    );

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
    } finally {
      await otherContext.close();
    }
    const free = 1_073_741_824;
    const expectedBillableGb = Math.max(0, Math.ceil((overview.total_bytes - free) / free));
    expect(overview.billable_gb).toBe(expectedBillableGb);
    expect(overview.weekly_cost_credits).toBe(expectedBillableGb * 3);
  });
