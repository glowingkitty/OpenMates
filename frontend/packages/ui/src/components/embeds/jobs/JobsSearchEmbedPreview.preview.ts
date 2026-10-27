// Synthetic component-preview data. Public app-store examples use recorded CLI output separately.
const previewResults = [
  { title: 'Climate Data Analyst', company: 'Example Organization', location: 'Berlin', country: 'DE', provider: 'ExampleJobsD', url: 'https://example.com/jobs/climate-data', remote: null, published_at: '2026-10-01' },
  { title: 'Energy Researcher', company: 'Example Institute', location: 'Stockholm', country: 'SE', provider: 'JobTech', url: 'https://example.com/jobs/energy', remote: true, published_at: '2026-10-02' },
];
const defaultProps = {
  id: 'preview-jobs-search',
  status: 'finished' as const,
  content: { query: 'climate analyst', result_count: 2, providers: ['ExampleJobsD', 'JobTech'], preview_results: previewResults },
  presentationOnly: true,
  onFullscreen: () => {},
};
export default defaultProps;
export const variants = {
  processing: { ...defaultProps, status: 'processing' as const, content: { query: 'climate analyst', result_count: 0, preview_results: [] } },
  empty: { ...defaultProps, content: { query: 'climate analyst', result_count: 0, preview_results: [] } },
  error: { ...defaultProps, status: 'error' as const, content: { query: 'climate analyst', error: 'Search source unavailable', result_count: 0, preview_results: [] } },
  cancelled: { ...defaultProps, status: 'cancelled' as const, content: { query: 'climate analyst', result_count: 0, preview_results: [] } },
  partial: { ...defaultProps, content: { ...defaultProps.content, warnings: [{ provider: 'JobTech', code: 'unavailable' }] } },
  located: { ...defaultProps, content: { ...defaultProps.content, location: 'Stockholm', country: 'SE' } },
  multiCountry: { ...defaultProps, content: { ...defaultProps.content, location: 'Berlin', countries: 'DE|SE', provider: 'auto', providers: 'ExampleJobsA|ExampleJobsD|ExampleJobsB|ExampleJobsC|jobtech' } },
  mobile: { ...defaultProps, isMobile: true },
};
