const job = {
  id: 'preview-1', title: 'Climate Data Analyst', company: 'Example Organization',
  location: 'Berlin', country: 'DE', provider: 'Arbeitnow',
  url: 'https://example.com/jobs/climate-data', apply_url: 'https://example.com/jobs/climate-data/apply',
  remote: null, description: 'Analyse public climate datasets.', published_at: '2026-10-01',
};
const defaultProps = { embedId: 'preview-job-result', data: { decodedContent: job }, onClose: () => {} };
export default defaultProps;
export const variants = {
  remote: { ...defaultProps, data: { decodedContent: { ...job, remote: true } } },
  salaried: { ...defaultProps, data: { decodedContent: { ...job, salary_min: 50000, salary_max: 65000, salary_currency: 'EUR', salary_period: 'year' } } },
  unsafeUrl: { ...defaultProps, data: { decodedContent: { ...job, url: 'javascript:alert(1)', apply_url: 'data:text/html,bad' } } },
  credentialUrl: { ...defaultProps, data: { decodedContent: { ...job, url: 'https://user:secret@example.com/jobs/climate-data', apply_url: 'https://user:secret@example.com/jobs/climate-data/apply' } } },
  mobile: { ...defaultProps },
};
