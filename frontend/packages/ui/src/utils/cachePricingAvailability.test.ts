import { describe, expect, it } from 'vitest';
import { isCachePricingDisplayActive, isLongContextPricingDisplayActive, supportsOneHourCacheWrites } from './cachePricingAvailability';

const verified = {
  enabled: true,
  status: 'verified_for_activation',
  write_billing: 'separate' as const,
  source_url: 'https://provider.example/pricing',
  reviewed_on: '2026-10-06',
  expires_on: '2026-11-06',
  eligible_hosts: ['anthropic'],
};
const rates = { cache_read: 1000, cache_write: 80, cache_write_1h: 50 };

describe('cache pricing catalog admission', () => {
  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  it('shows rates only on the verified, current default host', () => {
    expect(isCachePricingDisplayActive(verified, 'anthropic', rates, '2026-10-07')).toBe(true);
    expect(isCachePricingDisplayActive(verified, 'aws_bedrock', rates, '2026-10-07')).toBe(false);
    expect(isCachePricingDisplayActive(verified, undefined, rates, '2026-10-07')).toBe(false);
    expect(isCachePricingDisplayActive({ ...verified, status: 'proposed_pending_provider_evidence' }, 'anthropic', rates, '2026-10-07')).toBe(false);
    expect(isCachePricingDisplayActive({ ...verified, write_billing: 'unknown' } as unknown as typeof verified, 'anthropic', rates, '2026-10-07')).toBe(false);
    expect(isCachePricingDisplayActive(verified, 'anthropic', { ...rates, cache_read: undefined }, '2026-10-07')).toBe(false);
    expect(isCachePricingDisplayActive(verified, 'anthropic', { ...rates, cache_write: undefined }, '2026-10-07')).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  it('does not publish one-hour writes on a five-minute-only route', () => {
    expect(supportsOneHourCacheWrites({ ...verified, cache_write_1h_hosts: [] }, 'aws_bedrock')).toBe(false);
    expect(supportsOneHourCacheWrites({ ...verified, cache_write_1h_hosts: ['anthropic'] }, 'aws_bedrock')).toBe(false);
    expect(supportsOneHourCacheWrites({ ...verified, cache_write_1h_hosts: ['anthropic'] }, 'anthropic')).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  it('hides expired, future, and invalid calendar dates', () => {
    expect(isCachePricingDisplayActive(verified, 'anthropic', rates, '2026-11-07')).toBe(false);
    expect(isCachePricingDisplayActive({ ...verified, reviewed_on: '2026-10-08' }, 'anthropic', rates, '2026-10-07')).toBe(false);
    expect(isCachePricingDisplayActive({ ...verified, effective_from: '2026-10-08' }, 'anthropic', rates, '2026-10-07')).toBe(false);
    expect(isCachePricingDisplayActive({ ...verified, expires_on: '2026-11-31' }, 'anthropic', rates, '2026-10-07')).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  it('shows a complete long-context tier only on its eligible active host', () => {
    const openaiPolicy = { ...verified, eligible_hosts: ['openai'] };
    const standardRates = { ...rates, input: 100, output: 20 };
    const band = {
      min_input_tokens: 272001,
      eligible_hosts: ['openai'],
      input_tokens_per_credit: 50,
      cache_read_tokens_per_credit: 500,
      cache_write_tokens_per_credit: 40,
      output_tokens_per_credit: 10,
    };
    expect(isLongContextPricingDisplayActive(openaiPolicy, 'openai', standardRates, band, '2026-10-07')).toBe(true);
    expect(isLongContextPricingDisplayActive(openaiPolicy, 'aws_bedrock', standardRates, band, '2026-10-07')).toBe(false);
    expect(isLongContextPricingDisplayActive({ ...openaiPolicy, enabled: false }, 'openai', standardRates, band, '2026-10-07')).toBe(false);
    expect(isLongContextPricingDisplayActive(openaiPolicy, 'openai', standardRates, { ...band, min_input_tokens: 272000 }, '2026-10-07')).toBe(false);
    expect(isLongContextPricingDisplayActive(openaiPolicy, 'openai', standardRates, { ...band, cache_write_tokens_per_credit: undefined }, '2026-10-07')).toBe(false);
    expect(isLongContextPricingDisplayActive(openaiPolicy, 'openai', { ...standardRates, input: undefined }, band, '2026-10-07')).toBe(false);
  });
});
