import realExamples from './JobsSearchEmbedPreview.examples';

const jobs = [
  { id: 'preview-1', title: 'Climate Data Analyst', company: 'Example Organization', location: 'Berlin', country: 'DE', provider: 'Arbeitnow', url: 'https://example.com/jobs/climate-data', remote: null, description: 'Analyse public climate datasets.' },
  { id: 'preview-2', title: 'Energy Researcher', company: 'Example Institute', location: 'Stockholm', country: 'SE', provider: 'JobTech', url: 'https://example.com/jobs/energy', apply_url: 'https://example.com/jobs/energy/apply', remote: true, description: 'Research energy systems.' },
];
const defaultProps = {
  embedId: 'preview-jobs-search',
  data: { decodedContent: { query: 'climate analyst', providers: ['Arbeitnow', 'JobTech'], result_count: 2, results: [{ id: 'query-1', results: jobs }] }, embedData: { status: 'finished' } },
  onClose: () => {},
};
export default defaultProps;
export const variants = {
  empty: { ...defaultProps, data: { decodedContent: { query: 'climate analyst', result_count: 0, results: [] }, embedData: { status: 'finished' } } },
  processing: { ...defaultProps, data: { decodedContent: { query: 'climate analyst' }, embedData: { status: 'processing' } } },
  cancelled: { ...defaultProps, data: { decodedContent: { query: 'climate analyst' }, embedData: { status: 'cancelled' } } },
  error: { ...defaultProps, data: { decodedContent: { query: 'climate analyst', error: 'Search source unavailable' }, embedData: { status: 'error' } } },
  partial: { ...defaultProps, data: { decodedContent: { ...defaultProps.data.decodedContent, warnings: [{ provider: 'JobTech', code: 'unavailable' }] }, embedData: { status: 'finished' } } },
  mobile: { ...defaultProps },
  realStockholm: { ...defaultProps, data: { decodedContent: realExamples[0], embedData: { status: 'finished' } } },
  multiCountry: { ...defaultProps, data: { decodedContent: { ...defaultProps.data.decodedContent, location: 'Berlin', countries: 'DE|SE', provider: 'auto', providers: 'arbeitsagentur|arbeitnow|eighty_thousand_hours|hard_problems|jobtech' }, embedData: { status: 'finished' } } },
};
