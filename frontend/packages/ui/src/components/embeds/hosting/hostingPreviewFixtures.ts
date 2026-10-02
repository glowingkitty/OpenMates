import { normalizeDomain, type DomainResult, type DomainSearchContent, type DomainTier } from './hostingDomainData';

const registration = (amount: number, minimum = 1, discount = false): DomainTier => ({
  unit: 'y', duration_range: { minimum, maximum: minimum === 1 ? 10 : 9 }, minimum_term: `${minimum} y`,
  price_including_tax: amount, price_excluding_tax: +(amount / 1.19).toFixed(2),
  discount, normal_price: discount ? +(amount + 7.45).toFixed(2) : null,
  product_taxes: [{ name: 'VAT', rate: 19 }],
});

function child(id: string, ascii: string, unicode: string, availability: DomainResult['availability'], registrationTiers: DomainTier[], renewalTiers: DomainTier[], extra: Record<string, unknown> = {}): DomainResult {
  return normalizeDomain(id, {
    domain_ascii: ascii, domain_unicode: unicode, availability, provider: 'Gandi',
    provider_url: `https://shop.gandi.net/en/domain/suggest?search=${encodeURIComponent(ascii)}`,
    country: 'DE', currency: 'EUR', checked_at: '2026-10-01T13:09:00Z',
    registration_tiers: registrationTiers, renewal_tiers: renewalTiers, restrictions: [], ...extra,
  });
}

export const domainFixtures = {
  com: child('preview-hosting-com', 'cedarcomet.com', 'cedarcomet.com', 'available', [registration(13.09), registration(30.91, 2, true)], [registration(38.06), registration(34.25, 2, true)]),
  net: child('preview-hosting-net', 'cedarcomet.net', 'cedarcomet.net', 'available', [registration(14.27, 1, true)], [registration(47.60)]),
  idn: child('preview-hosting-idn', 'xn--bcher-beispiel-wob.de', 'bücher-beispiel.de', 'available', [registration(18.40)], [registration(24.80)]),
  org: child('preview-hosting-org', 'cedarcomet.org', 'cedarcomet.org', 'unavailable', [], []),
  co: child('preview-hosting-co', 'cedarcomet.co', 'cedarcomet.co', 'unavailable', [], []),
  unknown: child('preview-hosting-unknown', 'cedarcomet.et', 'cedarcomet.et', 'unknown', [], []),
  premium: child('preview-hosting-premium', 'rarecedar.com', 'rarecedar.com', 'available', [registration(900)], [registration(1100)], { premium: true, restrictions: ['Registration requires identity verification'] }),
  minTwoYears: child('preview-hosting-min-two', 'cedarcomet.dev', 'cedarcomet.dev', 'available', [registration(29.40, 2)], [registration(38.20, 2)]),
  missingPrice: child('preview-hosting-missing', 'cedarcomet.info', 'cedarcomet.info', 'available', [], []),
  longIdn: child('preview-hosting-long-idn', 'xn--berlange-domainkennung-6zb.cedarcomet-example.test', 'überlange-domainkennung-mit-vielen-zeichen.cedarcomet-example.test', 'available', [registration(21.90)], [registration(29.90)]),
} satisfies Record<string, DomainResult>;

export const checkedChildren: DomainResult[] = [domainFixtures.com, domainFixtures.net, domainFixtures.idn, domainFixtures.org, domainFixtures.co, domainFixtures.unknown];

export const parentContent: DomainSearchContent = {
  query: 'cedarcomet', provider: 'Gandi', country: 'DE', currency: 'EUR', checked_at: '2026-10-01T13:09:00Z',
  status: 'finished', partial: false, warnings: [], error: null, availability: 'prefer_available', max_results: 2,
  result_count: 2, checked_count: 6, available_count: 3, unavailable_count: 2, unknown_count: 1,
  embed_ids: checkedChildren.map((item) => item.embed_id),
  selected_embed_ids: [domainFixtures.com.embed_id, domainFixtures.net.embed_id],
  preview_starting_registration: { amount: 13.09, currency: 'EUR', tax_basis: 'including', unit: 'year', duration: 1 },
};
