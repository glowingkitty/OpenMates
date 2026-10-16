import { describe, expect, it, vi } from 'vitest';
import { bindTemporaryModelPricing, resolveTemporaryModelPrice } from './temporaryModelPricing';

const model = {
  default_server: 'google_ai_studio', servers: [{ id: 'google_ai_studio', region: 'US' }],
  pricing: { input_tokens_per_credit: 80, output_tokens_per_credit: 15 },
  temporary_prices: [{ id: 'intro', effective_from: '2026-10-13', expires_on: '2026-11-30',
    source_url: 'https://example.test/pricing', reviewed_on: '2026-10-14',
    eligible_hosts: ['google_ai_studio'], processing_tier: 'standard',
    pricing: { input_tokens_per_credit: 160, output_tokens_per_credit: 30 } }],
};
describe('current public temporary prices', () => {
  // contract-test: supporting surface=gui.web assertions=billing.models.active-price-consistency
  it('resolves inclusive dates and excludes another host, region and processing tier', () => {
    expect(resolveTemporaryModelPrice(model, '2026-11-30').pricing?.input_tokens_per_credit).toBe(160);
    expect(resolveTemporaryModelPrice(model, '2026-12-01').pricing?.input_tokens_per_credit).toBe(80);
    expect(resolveTemporaryModelPrice({ ...model, default_server: 'google' }, '2026-10-14').active_temporary_price).toBeUndefined();
    for (const override of [{ regions: ['EU'] }, { processing_tier: 'batch' }]) {
      expect(resolveTemporaryModelPrice({ ...model, temporary_prices: [{ ...model.temporary_prices[0], ...override }] }, '2026-10-14').active_temporary_price).toBeUndefined();
    }
  });
  // contract-test: supporting surface=gui.web assertions=billing.models.verified-host-prices
  it('never guesses a discount from incomplete or overlapping customer tariffs', () => {
    const incomplete = { ...model.temporary_prices[0], pricing: { input_tokens_per_credit: 160 } } as unknown as typeof model.temporary_prices[0];
    expect(resolveTemporaryModelPrice({ ...model, temporary_prices: [incomplete] }, '2026-10-14').active_temporary_price).toBeUndefined();
    const overlap = { ...model.temporary_prices[0], id: 'overlap' };
    expect(resolveTemporaryModelPrice({ ...model, temporary_prices: [...model.temporary_prices, overlap] }, '2026-10-14').active_temporary_price).toBeUndefined();
  });
  // contract-test: supporting surface=gui.web assertions=billing.models.active-price-consistency
  it('changes existing catalog getters without rebuilding or replacing a model object', () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date('2026-11-30T23:59:59Z'));
      const current = bindTemporaryModelPricing(structuredClone(model));
      expect(current.pricing?.input_tokens_per_credit).toBe(160);
      vi.setSystemTime(new Date('2026-12-01T00:00:00Z'));
      expect(current.pricing?.input_tokens_per_credit).toBe(80);
      expect(current.active_temporary_price).toBeUndefined();
    } finally { vi.useRealTimers(); }
  });
  // contract-test: supporting surface=gui.web assertions=billing.models.active-price-consistency
  it('does not treat a minimum duration as an end date', () => {
    const { expires_on: _, ...offer } = model.temporary_prices[0];
    expect(resolveTemporaryModelPrice({ ...model, temporary_prices: [{ ...offer, guaranteed_through: '2026-11-30' }] }, '2026-12-01').pricing?.input_tokens_per_credit).toBe(160);
  });
});
