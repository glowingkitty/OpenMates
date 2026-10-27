/* eslint-disable @typescript-eslint/no-require-imports -- Existing isolated-stack helpers use CommonJS. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, createSignupLogger, createStepScreenshotter } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { execFileSync } = require('node:child_process');
const { existsSync, readFileSync } = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../../..');
const COMPOSE = path.join(ROOT, 'test-results/ci-private/compose.json');
const API_URL = process.env.PLAYWRIGHT_TEST_API_URL?.replace(/\/$/, '');

// contract-test: direct surface=rest_api assertions=billing.usage.receipt-token-breakdown,billing.credits.idempotent-charge,billing.access.authenticated-first-party
test('parent, child and grandchild cache receipts debit once and remain owner-readable under one root', async ({ page, playwright }) => {
  test.setTimeout(240_000);
  if (process.env.OPENMATES_CI_ISOLATED !== '1' || !existsSync(COMPOSE) || !API_URL) {
    throw new Error('Fresh isolated product stack required for nested cache billing proof.');
  }
  const profile = JSON.parse(readFileSync(COMPOSE, 'utf8'));
  expect(profile.services?.api?.environment?.SERVER_ENVIRONMENT).toBe('development');
  const credentials = getTestAccount(1);
  if (!credentials.email) throw new Error('Fresh isolated account required.');
  const log = createSignupLogger('nested-cache-billing');
  const screenshot = createStepScreenshotter(log);
  await loginToTestAccount(page, log, screenshot, { credentials });
  const output = execFileSync('docker', ['compose', '-f', COMPOSE, 'exec', '-T', 'api',
    'python', '/app/backend/scripts/test_nested_chat_cache_billing_contract.py'], {
    cwd: ROOT, input: JSON.stringify({ email: credentials.email }), encoding: 'utf8', timeout: 180_000,
  });
  const result = JSON.parse(output.trim());
  expect(result).toMatchObject({ passed: true, depths: [0, 1, 2], total_credits: 9,
    maximum_depth_enforced: true, saved_descendant_admission_separated: true,
    charges: 3, replay_debits: 0, balance_restored: true, root_spent_credits: 9, root_reserved_credits: 0 });
  const params = { type: 'chat', identifier: result.root_chat_id, year_month: result.year_month };
  const anonymous = await playwright.request.newContext();
  try {
    const denied = await anonymous.get(`${API_URL}/v1/settings/usage/details`, { params });
    expect([401, 403]).toContain(denied.status());
  } finally { await anonymous.dispose(); }
  const response = await page.request.get(`${API_URL}/v1/settings/usage/details`, { params });
  expect(response.status()).toBe(200);
  const entries = (await response.json()).entries.filter((entry) => entry.llm_usage_breakdown);
  expect(entries).toHaveLength(3);
  for (const entry of entries) {
    expect(entry.llm_usage_breakdown.credits_charged).toBe(3);
    expect(entry.llm_usage_breakdown.cache_read_input_tokens).toBe(8000);
    expect(entry.llm_usage_breakdown.entries[0].billing_mode).toBe('cache_aware');
    expect(entry).not.toHaveProperty('encrypted_llm_usage_breakdown');
  }
  await test.info().attach('nested-cache-ledger-receipt', { body: JSON.stringify(result, null, 2), contentType: 'application/json' });
  await screenshot(page, 'nested-cache-receipts-verified');
});
