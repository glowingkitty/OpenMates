import { describe, expect, it } from 'vitest';
import { boundedView, formatTierMoney, headlineTier, isFirstYearOffer, normalRegistration, quote } from '../hostingDomainData';
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
});
