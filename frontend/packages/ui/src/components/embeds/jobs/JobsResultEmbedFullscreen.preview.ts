const job = {
  id: 'preview-1', title: 'Climate Data Analyst', company: 'Example Organization',
  location: 'Berlin', country: 'DE', provider: 'ExampleJobsD',
  url: 'https://example.com/jobs/climate-data', apply_url: 'https://example.com/jobs/climate-data/apply',
  remote: null, description: 'Analyse public climate datasets.', published_at: '2026-10-01',
};
const defaultProps = { embedId: 'preview-job-result', data: { decodedContent: job }, onClose: () => {} };
export default defaultProps;
export const variants = {
  sourceOnly: { ...defaultProps, data: { decodedContent: { ...job, apply_url: undefined } } },
  richDetails: { ...defaultProps, data: { decodedContent: { ...job,
    provider: 'ExampleJobsC', sector: 'Healthcare', role: 'Product design',
    seniority: 'Senior', organization_type: 'For-profit', work_arrangement: 'Hybrid',
    employment_type: 'full_time', valid_through: '2026-11-14T00:00:00Z', detail_status: 'complete',
    impact: 'Reduce administrative work so healthcare professionals can focus on patients.',
    description: 'About the employer\n\nBuild useful healthcare tools.\n\nThe role\n\nDesign accessible products with a cross-functional team.\n\nRequirements\n\nExperience owning design outcomes.\n\nBenefits\n\n30 days of annual leave and flexible working arrangements.',
  } } },
  sameUrl: { ...defaultProps, data: { decodedContent: { ...job, apply_url: job.url } } },
  summaryOnly: { ...defaultProps, data: { decodedContent: { ...job, detail_status: 'summary' } } },
  remote: { ...defaultProps, data: { decodedContent: { ...job, remote: true } } },
  salaried: { ...defaultProps, data: { decodedContent: { ...job, salary_min: 50000, salary_max: 65000, salary_currency: 'EUR', salary_period: 'year' } } },
  unsafeUrl: { ...defaultProps, data: { decodedContent: { ...job, url: 'javascript:alert(1)', apply_url: 'data:text/html,bad' } } },
  credentialUrl: { ...defaultProps, data: { decodedContent: { ...job, url: 'https://user:secret@example.com/jobs/climate-data', apply_url: 'https://user:secret@example.com/jobs/climate-data/apply' } } },
  mobile: { ...defaultProps },
  longMetadata: { ...defaultProps, data: { decodedContent: { ...job, company: 'Example Organization for Sustainable Digital Infrastructure and Research', location: 'Stockholm, Stockholms län, Sweden', employment_type: 'Full-time permanent employment' } } },
};
