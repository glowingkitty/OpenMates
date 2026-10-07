import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const now = Math.floor(Date.now() / 1000);
const today = new Date().toISOString().slice(0, 10);

const settledReceipt = {
  schema_version: 1,
  settlement_state: 'settled',
  input_tokens: 100,
  uncached_input_tokens: 60,
  cache_read_input_tokens: 30,
  cache_creation_input_tokens: 10,
  output_tokens: 5,
  usage_source: 'provider_reported',
  entries: [{
    model_id: 'cache-fixture-model',
    inference_host: 'cache-fixture-host',
    pricing_version: 'cache-v1',
    write_billing: 'separate',
    billing_mode: 'cache_aware',
    billed_input_tokens: 60,
    input_tokens: 100,
    uncached_input_tokens: 60,
    cache_read_input_tokens: 30,
    cache_creation_input_tokens: 10,
    cache_creation_5m_input_tokens: 10,
    cache_creation_1h_input_tokens: 0,
    output_tokens: 5,
    rates: { input: '100', cache_read: '1000', cache_write: '80', cache_write_1h: null, output: '20' },
    category_credits: { input: '0.6', cache_read: '0.03', cache_write: '0.125', cache_write_1h: '0', output: '0.25' },
    raw_credits: '1.005'
  }],
  raw_credits: '1.005',
  rounding_adjustment: '-0.005',
  credits_charged: 1
};

const pendingReceipt = {
  ...settledReceipt,
  settlement_state: 'pending',
  requested_credits: 1,
  rounding_adjustment: '-1.005',
  credits_charged: 0,
};

const ordinaryInputReceipt = {
  ...settledReceipt,
  input_tokens: 150,
  uncached_input_tokens: 100,
  cache_read_input_tokens: 50,
  cache_creation_input_tokens: null,
  entries: [{
    ...settledReceipt.entries[0],
    billing_mode: 'ordinary_input',
    billed_input_tokens: 150,
    input_tokens: 150,
    uncached_input_tokens: 100,
    cache_read_input_tokens: 50,
    cache_creation_input_tokens: null,
    cache_creation_5m_input_tokens: null,
    cache_creation_1h_input_tokens: null,
    rates: { input: '100', cache_read: null, cache_write: null, cache_write_1h: null, output: '20' },
    category_credits: { input: '1.5', cache_read: '0', cache_write: '0', cache_write_1h: '0', output: '0.25' },
    raw_credits: '1.75'
  }],
  raw_credits: '1.75',
  rounding_adjustment: '-0.75',
  credits_charged: 1
};

const ordinaryAllKnownReceipt = {
  ...settledReceipt,
  entries: [{
    ...settledReceipt.entries[0],
    billing_mode: 'ordinary_input',
    billed_input_tokens: 100,
    rates: { input: '100', cache_read: null, cache_write: null, cache_write_1h: null, output: '20' },
    category_credits: { input: '1', cache_read: '0', cache_write: '0', cache_write_1h: '0', output: '0.25' },
    raw_credits: '1.25'
  }],
  raw_credits: '1.25',
  rounding_adjustment: '-0.25',
  credits_charged: 1
};

const longContextReceipt = {
  ...settledReceipt,
  input_tokens: 272001,
  uncached_input_tokens: 200000,
  cache_read_input_tokens: 70000,
  cache_creation_input_tokens: 2001,
  entries: [{
    ...settledReceipt.entries[0],
    context_band: 'over_272k',
    billed_input_tokens: 200000,
    input_tokens: 272001,
    uncached_input_tokens: 200000,
    cache_read_input_tokens: 70000,
    cache_creation_input_tokens: 2001,
    cache_creation_5m_input_tokens: 2001,
    rates: { input: '50', cache_read: '500', cache_write: '40', cache_write_1h: null, output: '10' },
    category_credits: { input: '4000', cache_read: '140', cache_write: '50.025', cache_write_1h: '0', output: '0.5' },
    raw_credits: '4190.525'
  }],
  raw_credits: '4190.525',
  rounding_adjustment: '-0.525',
  credits_charged: 4190
};

const automaticSummaryReceipt = {
  schema_version: 1,
  settlement_state: 'settled',
  input_tokens: 1100,
  uncached_input_tokens: 1100,
  cache_read_input_tokens: 0,
  cache_creation_input_tokens: 0,
  output_tokens: 130,
  usage_source: 'provider_reported',
  entries: [{
    model_id: 'gemini-3.5-flash-lite', purpose: 'summary', inference_host: 'google_ai_studio',
    pricing_version: 'summary-standard-v1', billing_mode: 'ordinary_input', billed_input_tokens: 1100,
    input_tokens: 1100, uncached_input_tokens: 1100, cache_read_input_tokens: 0,
    cache_creation_input_tokens: 0, cache_creation_5m_input_tokens: 0, cache_creation_1h_input_tokens: 0,
    output_tokens: 130,
    rates: { input: '1100', cache_read: null, cache_write: null, cache_write_1h: null, output: '130' },
    category_credits: { input: '1', cache_read: '0', cache_write: '0', cache_write_1h: '0', output: '1' },
    raw_credits: '2'
  }],
  raw_credits: '2', rounding_adjustment: '0', credits_charged: 2
};

function decimalCredits(text: string | null): number {
  const match = (text ?? '').match(/([0-9.eE+-]+)\s+credits/i);
  expect(match, 'Expected a decimal credit amount').toBeTruthy();
  return Number(match![1]);
}

test.describe('Usage cache receipt component preview', () => {
  // contract-test: direct surface=gui.web assertions=billing.usage.receipt-token-breakdown,billing.surface.semantic-parity
  test('shows immutable cache rates and reconciles a settled debit', async ({ page }) => {
    await page.route('**/v1/settings/usage/daily-overview**', async route => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        days: [{ date: today, total_credits: 4195, items: [{
          type: 'chat', chat_id: 'cache-receipt-chat', api_key_hash: null,
          total_credits: 4195, entry_count: 6, updated_at: now
        }] }],
        requested_days: 7, total_days: 1, has_more_days: false
      }) });
    });
    await page.route('**/v1/settings/usage/chat-entries**', async route => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entries: [
        { id: 'settled', type: 'ai.ask', source: 'chat', chat_id: 'cache-receipt-chat', app_id: 'ai', skill_id: 'ask', model_used: 'cache-fixture-model', created_at: now, credits: 1, input_tokens: 100, output_tokens: 5, llm_usage_breakdown: settledReceipt },
        { id: 'pending', type: 'ai.ask', source: 'chat', chat_id: 'cache-receipt-chat', app_id: 'ai', skill_id: 'ask', model_used: 'cache-fixture-model', created_at: now - 1, credits: 0, input_tokens: 100, output_tokens: 5, llm_usage_breakdown: pendingReceipt },
        { id: 'ordinary-partial', type: 'ai.ask', source: 'chat', chat_id: 'cache-receipt-chat', app_id: 'ai', skill_id: 'ask', model_used: 'cache-fixture-model', created_at: now - 2, credits: 1, input_tokens: 150, output_tokens: 5, llm_usage_breakdown: ordinaryInputReceipt },
        { id: 'ordinary-all-known', type: 'ai.ask', source: 'chat', chat_id: 'cache-receipt-chat', app_id: 'ai', skill_id: 'ask', model_used: 'cache-fixture-model', created_at: now - 3, credits: 1, input_tokens: 100, output_tokens: 5, llm_usage_breakdown: ordinaryAllKnownReceipt },
        { id: 'long-context', type: 'ai.ask', source: 'chat', chat_id: 'cache-receipt-chat', app_id: 'ai', skill_id: 'ask', model_used: 'cache-fixture-model', created_at: now - 4, credits: 4190, input_tokens: 272001, output_tokens: 5, llm_usage_breakdown: longContextReceipt },
        { id: 'summary', type: 'ai.ask', source: 'chat', chat_id: 'cache-receipt-chat', app_id: 'ai', skill_id: 'ask', model_used: 'gemini-3.5-flash-lite', created_at: now - 5, credits: 2, input_tokens: 1100, output_tokens: 130, llm_usage_breakdown: automaticSummaryReceipt }
      ] }) });
    });

    await page.goto('/dev/preview/settings/SettingsUsage?theme=light&background=%23dbeafe&width=768&chrome=0');
    await waitForComponentPreview(page);
    await page.getByTestId('usage-overview-chat-row').click();
    await expect(page.getByTestId('usage-chat-entry')).toHaveCount(6);
    await expect(page.getByTestId('usage-chat-entry').last()).toContainText('Automatic long-chat summary');
    await page.getByTestId('usage-chat-entry').first().click();

    await expect(page.getByTestId('usage-llm-receipt')).toBeVisible();
    await expect(page.getByTestId('usage-llm-context-band')).toHaveCount(0);
    await expect(page.getByTestId('usage-entry-total-credits')).toBeVisible();
    await expect(page.getByTestId('usage-llm-input-categories')).toContainText('100 = 60 + 30 + 10');
    await expect(page.getByTestId('usage-llm-category-cache_read')).toContainText('1000');
    await expect(page.getByTestId('usage-llm-category-cache_write')).toContainText('80');
    await expect(page.getByTestId('usage-llm-entry')).toContainText('cache-v1');

    let categoryTotal = 0;
    const categories = page.locator('[data-testid^="usage-llm-category-"]');
    await expect(categories).toHaveCount(5);
    for (const row of await categories.all()) {
      const parts = (await row.textContent() ?? '').split('·');
      expect(parts.length).toBeGreaterThanOrEqual(3);
      categoryTotal += decimalCredits(parts[1]);
    }
    const raw = decimalCredits(await page.getByTestId('usage-llm-raw-credits').textContent());
    const adjustment = decimalCredits(await page.getByTestId('usage-llm-rounding-adjustment').textContent());
    const charged = decimalCredits(await page.getByTestId('usage-llm-credits-charged').textContent());
    expect(Math.abs(categoryTotal - raw)).toBeLessThan(0.000001);
    expect(Math.abs(raw + adjustment - charged)).toBeLessThan(0.000001);

    await page.getByTestId('usage-entry-detail-back-button').click();
    await page.getByTestId('usage-chat-entry').nth(1).click();
    await expect(page.getByTestId('usage-llm-settlement-pending')).toContainText('1 credits');
    await expect(page.getByTestId('usage-llm-credits-charged')).toHaveCount(0);
    await expect(page.getByTestId('usage-entry-total-credits')).toHaveCount(0);

    await page.getByTestId('usage-entry-detail-back-button').click();
    await page.getByTestId('usage-chat-entry').nth(2).click();
    await expect(page.getByTestId('usage-llm-ordinary-input-explanation')).toContainText('all known input tokens');
    await expect(page.getByTestId('usage-llm-input-categories')).toContainText('Uncached input: 100');
    await expect(page.getByTestId('usage-llm-input-categories')).toContainText('Cache read: 50');
    const ordinaryInput = page.getByTestId('usage-llm-category-input');
    await expect(ordinaryInput.getByText('Input', { exact: true })).toBeVisible();
    await expect(ordinaryInput).toContainText('150 tokens · 1.5 credits');
    await expect(page.getByTestId('usage-llm-category-cache_read')).toContainText('50 tokens · 0 credits · Included in ordinary input');
    await expect(page.getByTestId('usage-llm-category-cache_read')).not.toContainText('1000');
    await expect(page.getByTestId('usage-llm-category-cache_write')).toContainText('0 credits · Included in ordinary input');
    const ordinaryRaw = decimalCredits(await page.getByTestId('usage-llm-raw-credits').textContent());
    const ordinaryAdjustment = decimalCredits(await page.getByTestId('usage-llm-rounding-adjustment').textContent());
    const ordinaryCharged = decimalCredits(await page.getByTestId('usage-llm-credits-charged').textContent());
    expect(Math.abs(ordinaryRaw + ordinaryAdjustment - ordinaryCharged)).toBeLessThan(0.000001);

    await page.getByTestId('usage-entry-detail-back-button').click();
    await page.getByTestId('usage-chat-entry').nth(3).click();
    await expect(page.getByTestId('usage-llm-ordinary-input-explanation')).toContainText('all known input tokens');
    await expect(page.getByTestId('usage-llm-input-categories')).toContainText('100 = 60 + 30 + 10');
    const allKnownInput = page.getByTestId('usage-llm-category-input');
    await expect(allKnownInput.getByText('Input', { exact: true })).toBeVisible();
    await expect(allKnownInput).toContainText('100 tokens · 1 credits');
    await expect(allKnownInput).not.toContainText('60 tokens · 1 credits');
    await expect(page.getByTestId('usage-llm-category-cache_read')).toContainText('30 tokens · 0 credits · Included in ordinary input');
    await expect(page.getByTestId('usage-llm-category-cache_write')).toContainText('10 tokens · 0 credits · Included in ordinary input');
    expect(decimalCredits(await page.getByTestId('usage-llm-raw-credits').textContent())).toBe(1.25);
    expect(decimalCredits(await page.getByTestId('usage-llm-rounding-adjustment').textContent())).toBe(-0.25);
    expect(decimalCredits(await page.getByTestId('usage-llm-credits-charged').textContent())).toBe(1);

    await page.getByTestId('usage-entry-detail-back-button').click();
    await page.getByTestId('usage-chat-entry').nth(4).click();
    await expect(page.getByTestId('usage-llm-context-band')).toContainText('Pricing tier');
    await expect(page.getByTestId('usage-llm-context-band')).toContainText('Over 272,000 input tokens');
    await expect(page.getByTestId('usage-llm-input-categories')).toContainText('272,001 = 200,000 + 70,000 + 2,001');
    await expect(page.getByTestId('usage-llm-category-input')).toContainText('50');
    await expect(page.getByTestId('usage-llm-category-cache_read')).toContainText('500');
    expect(decimalCredits(await page.getByTestId('usage-llm-raw-credits').textContent())).toBe(4190.525);
    expect(decimalCredits(await page.getByTestId('usage-llm-rounding-adjustment').textContent())).toBe(-0.525);
    expect(decimalCredits(await page.getByTestId('usage-llm-credits-charged').textContent())).toBe(4190);

    await page.getByTestId('usage-entry-detail-back-button').click();
    await page.getByTestId('usage-chat-entry').last().click();
    await expect(page.getByTestId('usage-detail-view')).toContainText('Automatic long-chat summary');
    await expect(page.getByTestId('usage-llm-entry')).toContainText('Automatic long-chat summary · gemini-3.5-flash-lite');
    await expect(page.getByTestId('usage-llm-category-input')).toContainText('1,100 tokens · 1 credits · 1 credits per 1100');
    await expect(page.getByTestId('usage-llm-category-output')).toContainText('130 tokens · 1 credits · 1 credits per 130');
    expect(decimalCredits(await page.getByTestId('usage-llm-raw-credits').textContent())).toBe(2);
    expect(decimalCredits(await page.getByTestId('usage-llm-rounding-adjustment').textContent())).toBe(0);
    expect(decimalCredits(await page.getByTestId('usage-llm-credits-charged').textContent())).toBe(2);
  });
});
