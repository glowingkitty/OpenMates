/** Synthetic app-store examples for business.search_investors; no real investors or directories. */
const germanSeed = {
  query: 'climate software seed', regions: ['DE'], provider: 'my_provider', result_count: 2,
  limitation: 'Public self-descriptions of investors, not a recommendation. Portfolios and ticket sizes are not verified.',
  investors: [
    { name: 'Alex Sample', investor_type: 'angel', organization: 'Sample Ventures', regions: ['DE'], city: 'Berlin', stages: ['seed'],
      sectors: ['climate', 'software'], ticket_min: 25000, ticket_max: 100000, currency: 'EUR',
      thesis: 'Backs early software teams that reduce emissions in industry.', profile_url: 'https://example.org/investors/alex-sample', provider: 'my_provider' },
    { name: 'Northlight Angels', investor_type: 'angel_network', regions: ['DE'], city: 'Hamburg', stages: ['seed', 'series_a'],
      ticket_min: 50000, currency: 'EUR', profile_url: 'https://example.org/northlight', provider: 'my_provider' },
  ],
  warnings: [],
};
const austriaHealth = {
  query: 'health startups', regions: ['AT'], provider: 'my_provider', result_count: 2,
  limitation: 'Public self-descriptions of investors, not a recommendation. Portfolios and ticket sizes are not verified.',
  investors: [
    { name: 'Sample Care Angels', investor_type: 'angel_network', regions: ['AT'], city: 'Vienna', stages: ['pre_seed', 'seed'],
      sectors: ['health'], ticket_max: 150000, currency: 'EUR', profile_url: 'https://example.org/care-angels', provider: 'my_provider' },
    { name: 'Example Health Accelerator', investor_type: 'accelerator', regions: ['AT'], city: 'Graz', stages: ['pre_seed'],
      sectors: ['health', 'medtech'], website_url: 'https://example.org/health-accelerator', provider: 'my_provider' },
  ],
  warnings: [],
};
const examples = [
  { id: 'store-example-business-search-investors-1', query_translation_key: 'settings.app_store_examples.business.search_investors.1',
    status: 'finished' as const, ...germanSeed, content: germanSeed },
  { id: 'store-example-business-search-investors-2', query_translation_key: 'settings.app_store_examples.business.search_investors.2',
    status: 'finished' as const, ...austriaHealth, content: austriaHealth },
];
export default examples;
