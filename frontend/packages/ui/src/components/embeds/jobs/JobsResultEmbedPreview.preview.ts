const job = {
  embed_id: 'preview-job-result', id: 'preview-1', title: 'Climate Data Analyst',
  company: 'Example Organization', location: 'Berlin', country: 'DE',
  provider: 'Arbeitnow', url: 'https://example.com/jobs/climate-data',
  remote: null, published_at: '2026-10-01',
};
const defaultProps = { id: job.embed_id, job, presentationOnly: true, onFullscreen: () => {} };
export default defaultProps;
export const variants = {
  missingData: { ...defaultProps, job: { ...job, company: undefined, location: undefined, remote: null, published_at: undefined } },
  chat: { ...defaultProps, resultContext: 'chat' as const },
  remote: { ...defaultProps, job: { ...job, remote: true } },
  mobile: { ...defaultProps, isMobile: true },
  longTitle: { ...defaultProps, job: { ...job, title: 'Senior Climate Policy and Data Analysis Researcher for Regional Energy Transition Programs' } },
};
