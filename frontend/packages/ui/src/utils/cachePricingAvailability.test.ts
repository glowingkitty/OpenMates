import { describe, expect, it } from 'vitest';
import { isCachePricingDisplayActive, supportsOneHourCacheWrites } from './cachePricingAvailability';

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
});
