/** Synthetic fixtures for the investor search embed; no real investors or directories. */
export const investorData = {
  app_id: 'business', skill_id: 'search_investors', status: 'finished', success: true,
  query: 'climate software seed', regions: ['DE', 'AT'], provider: 'my_provider', providers: ['my_provider'],
  result_count: 4, partial: false,
  limitation: 'Public self-descriptions of investors, not a recommendation. Portfolios and ticket sizes are not verified.',
  investors: [
    { name: 'Alex Sample', investor_type: 'angel', organization: 'Sample Ventures', regions: ['DE', 'AT'], city: 'Berlin',
      stages: ['pre_seed', 'seed'], sectors: ['climate', 'software', 'energy'], ticket_min: 25000, ticket_max: 100000, currency: 'EUR',
      thesis: 'Backs early software teams that cut emissions in industry and buildings. Prefers founders with a working prototype and first pilot customers, and stays involved through introductions to utilities and industrial buyers across the region.',
      example_investments: ['Example Grid GmbH', 'Sample Heat AG'], profile_url: 'https://example.org/investors/alex-sample',
      website_url: 'https://example.org/alex', contact_route: 'Via the profile contact form', source_updated_at: '2026-09-01', provider: 'my_provider' },
    { name: 'Northlight Angels', investor_type: 'angel_network', organization: 'Northlight', regions: ['DE'], city: 'Hamburg',
      stages: ['seed', 'series_a'], sectors: ['climate'], ticket_min: 50000, currency: 'EUR', thesis: 'Syndicated angel rounds for climate teams.',
      profile_url: 'https://example.org/northlight', provider: 'my_provider' },
    { name: 'Sample Capital Partners', investor_type: 'vc', regions: ['AT'], stages: ['series_a'], ticket_max: 2000000, currency: 'EUR', provider: 'my_provider' },
    { name: 'Example Founders Lab', investor_type: 'accelerator', organization: 'Example Lab', city: 'Vienna', provider: 'my_provider' },
  ],
  warnings: [],
};
export const warningData = { ...investorData, partial: true, warnings: ['Example Directory was not searched: it does not cover US.'] };
export const emptyData = { ...investorData, result_count: 0, investors: [] };
export const errorData = { ...investorData, status: 'error', success: false, result_count: 0, investors: [], error: 'Investor search is unavailable.', error_code: 'provider_unavailable' };
const props = { id: 'preview-investor-search', data: investorData, status: 'finished' as const, presentationOnly: true, onFullscreen: () => {} };
export default props;
export const variants = {
  processing: { ...props, data: { query: 'climate software seed' }, status: 'processing' as const },
  error: { ...props, data: errorData, status: 'error' as const },
  cancelled: { ...props, data: { query: 'climate software seed' }, status: 'cancelled' as const },
  empty: { ...props, data: emptyData },
  warning: { ...props, data: warningData },
  mobile: { ...props, isMobile: true },
  long: { ...props, data: { ...investorData, query: 'A long investor search topic with many words to verify that narrow preview wrapping stays tidy', investors: [{ name: 'An Investor With An Extremely Long Display Name That Should Be Truncated Cleanly', investor_type: 'family_office' }] } },
};
