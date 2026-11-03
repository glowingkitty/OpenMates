import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { URL } from 'node:url';
import { boundedView, formatMoney, formatTierMoney, headlineTier, isFirstYearOffer, normalRegistration, quote, normalizeDomain, safeProviderUrl, years } from '../hostingDomainData';
import { checkedChildren, domainFixtures } from '../hostingPreviewFixtures';

describe('Hosting checked-domain presentation', () => {
  // contract-test: supporting surface=gui.web assertions=hosting-domains.embeds.parent-child
  it('keeps the backend selection and bounds local views without losing checked evidence', () => {
    const selected = boundedView(checkedChildren, [domainFixtures.net.embed_id, domainFixtures.com.embed_id], 'selected', 2);
    expect(selected.map((item) => item.domain_ascii)).toEqual(['cedarcomet.net', 'cedarcomet.com']);
    expect(boundedView(checkedChildren, [], 'in-use', 2).map((item) => item.domain_ascii)).toEqual(['cedarcomet.org', 'cedarcomet.co']);
    expect(boundedView(checkedChildren, [], 'unknown', 2).map((item) => item.domain_ascii)).toEqual(['cedarcomet.et']);
    expect(boundedView(checkedChildren, [], 'available', 2)).toHaveLength(2);
  });

  // contract-test: supporting surface=gui.web assertions=hosting-domains.embeds.parent-child,hosting-domains.quotes.truthful
  it('does not label a cheaper multiyear renewal as a one-year offer', () => {
    const oneYear = headlineTier(domainFixtures.com.renewal_tiers);
    expect(quote(oneYear)?.amount).toBe(38.06);
    expect(isFirstYearOffer(oneYear)).toBe(false);
    expect(isFirstYearOffer(domainFixtures.com.renewal_tiers[1])).toBe(false);
    expect(formatTierMoney(domainFixtures.com.renewal_tiers[1], 'EUR', 'year')).toContain('/ year');
  });

  // contract-test: supporting surface=gui.web assertions=hosting-domains.embeds.parent-child,hosting-domains.quotes.truthful
  it('compares normal and discounted registration on the same tax basis', () => {
    const excluding = {
      unit: 'y', duration_range: { minimum: 1 }, discount: true,
      price_excluding_tax: 10, normal_price: 20,
    };
    expect(isFirstYearOffer(excluding)).toBe(false);
    expect(normalRegistration(excluding)).toBeUndefined();
    expect(isFirstYearOffer({ ...excluding, normal_price_before_taxes: 15 })).toBe(true);
    expect(normalRegistration({ ...excluding, normal_price_before_taxes: 15 })).toBe(15);
    expect(formatTierMoney(domainFixtures.minTwoYears.registration_tiers[0], 'EUR', 'year')).toContain('/ year');
  });
  // contract-test: supporting surface=gui.web assertions=hosting-domains.results.partial-and-safe,app-skills.history.renderable
  it('keeps stored attribution and accepts only HTTPS source links without embedded credentials', () => {
    expect(normalizeDomain('saved-domain', { provider_name: 'Example Registrar', domain_ascii: 'example.com' }).provider).toBe('Example Registrar');
    expect(normalizeDomain('saved-domain', { domain_ascii: 'example.com' }).provider).toBe('');
    expect(safeProviderUrl('https://example.com/domain')).toBe('https://example.com/domain');
    for (const value of ['http://example.com/domain', 'javascript:alert(1)', 'https://user:secret@example.com/domain']) {
      expect(safeProviderUrl(value)).toBeNull();
    }
  });

});

// contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
it('retains the admitted registered-domain fixture and its exact supplied tier currency and term', () => {
  const fixture = JSON.parse(readFileSync(new URL('../../../../../../../../backend/apps/ai/testing/fixtures/authored_results.json', import.meta.url), 'utf8')) as {
    embeds: Record<string, { document: { items: Array<{ kind: string; details: Record<string, unknown> }> } }>;
  };
  const details = Object.values(fixture.embeds)[0].document.items.find((entry) => entry.kind === 'hosting.hosting_domain')!.details;
  const result = normalizeDomain('fixture-domain', details);
  const tier = headlineTier(result.registration_tiers)!;
  expect(result.availability).toBe('unavailable');
  expect(years(tier)).toBe(1);
  expect(quote(tier)).toEqual({ amount: 12, basis: 'unknown' });
  expect(formatTierMoney(tier, 'USD', 'year')).toBe(formatMoney(12, 'EUR'));
  expect(tier.unit).toBeUndefined();
  expect(tier.duration_range).toBeUndefined();
  expect(result.currency).toBe('');
  expect(isFirstYearOffer(tier)).toBe(false);
  expect(boundedView([result], [], 'in-use', 10)).toEqual([result]);
  expect(boundedView([result], [], 'available', 10)).toEqual([]);
});

// contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,hosting-domains.quotes.truthful
it('keeps authored zero prices and multiyear totals without annual, currency or tax guesses', () => {
  const result = normalizeDomain('zero-domain', { registration_tiers: [{ years: 3, price: 0 }] });
  const tier = headlineTier(result.registration_tiers)!;
  expect(years(tier)).toBe(3);
  expect(quote(tier)).toEqual({ amount: 0, basis: 'unknown' });
  expect(formatTierMoney(tier, 'EUR', 'year')).toBe(formatMoney(0, ''));
  expect(formatTierMoney(tier, 'EUR', 'year')).not.toMatch(/EUR|€|year/);
  expect(tier.currency).toBeUndefined();
  expect(isFirstYearOffer({ ...tier, discount: true, normal_price: 20 })).toBe(false);
  expect(normalRegistration(tier)).toBeUndefined();
  expect(result.availability).toBe('unknown');
});

// contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,hosting-domains.quotes.truthful
it('uses only supplied record currency as fallback while retaining per-tier currency and partial unknowns', () => {
  const result = normalizeDomain('partial', { currency: 'USD', registration_tiers: [
    { price: 9 }, { years: 2, amount: 14, currency: 'EUR' }, { years: 4 },
  ] });
  expect(result.registration_tiers[0].currency).toBe('USD');
  expect(years(result.registration_tiers[0])).toBeUndefined();
  expect(formatTierMoney(result.registration_tiers[0], 'GBP', 'year')).toBe(formatMoney(9, 'USD'));
  expect(formatTierMoney(result.registration_tiers[1], 'GBP', 'year')).toBe(formatMoney(14, 'EUR'));
  expect(quote(result.registration_tiers[2])).toBeNull();
  expect(formatTierMoney(result.registration_tiers[2], 'GBP', 'year')).toBeNull();
});

// contract-test: supporting surface=gui.web assertions=hosting-domains.quotes.truthful,hosting-domains.embeds.parent-child
it('preserves legacy provider annual unit, duration, tax basis and price semantics', () => {
  const legacy = { unit: 'y', duration_range: { minimum: 3, maximum: 5 }, price_excluding_tax: 8, discount: false };
  const result = normalizeDomain('legacy', { availability: 'available', currency: 'EUR', registration_tiers: [legacy] });
  expect(result.registration_tiers).toEqual([legacy]);
  expect(years(result.registration_tiers[0])).toBe(3);
  expect(quote(result.registration_tiers[0])).toEqual({ amount: 8, basis: 'excluding' });
  expect(formatTierMoney(result.registration_tiers[0], result.currency!, 'year')).toBe(`${formatMoney(8, 'EUR')} / year`);
});
