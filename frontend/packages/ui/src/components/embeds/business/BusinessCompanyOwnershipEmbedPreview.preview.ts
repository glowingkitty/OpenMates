/** Synthetic fixtures for the company ownership embed; no real companies or people. */
const limitation = 'Official register data only; ownership may be incomplete, and registers can lag behind recent changes.';
export const germanRecord = {
  subject: { name: 'Example Robotics GmbH', type: 'company', country: 'DE', register_id: 'HRB 123456', legal_form: 'GmbH', status: 'active', city: 'Berlin', source_url: 'https://example.org/register/de/hrb-123456' },
  owners: [
    { name: 'Jane Example', type: 'person', relation: 'shareholder', share_percent: 42, nominal_amount: 10500, currency: 'EUR', since: '2021-03-01' },
    { name: 'Example Holding SAS', type: 'company', relation: 'shareholder', share_percent: 33, nominal_amount: 8250, currency: 'EUR', since: '2022-06-15', register_id: '123456789' },
    { name: 'Sample Ventures GmbH', type: 'company', relation: 'shareholder', share_percent: 25, nominal_amount: 6250, currency: 'EUR', since: '2022-06-15' },
  ],
  holdings: [],
  officers: [
    { name: 'Jane Example', type: 'person', role: 'Managing director', since: '2021-03-01' },
    { name: 'Sam Sample', type: 'person', role: 'Authorised signatory', since: '2022-01-10' },
  ],
  provider: 'my_provider', warnings: [], limitation,
};
export const ukRecord = {
  subject: { name: 'Example Analytics Ltd', type: 'company', country: 'GB', register_id: '01234567', legal_form: 'Private limited company', status: 'active', city: 'London', source_url: 'https://example.org/register/gb/01234567' },
  owners: [
    { name: 'Jane Example', type: 'person', relation: 'significant_control', share_band: '50-75%', since: '2019-05-02' },
    { name: 'Example Holding SAS', type: 'company', relation: 'significant_control', share_band: '25-50%', since: '2020-11-20' },
  ],
  holdings: [],
  officers: [{ name: 'Pat Placeholder', type: 'person', role: 'Director', since: '2019-05-02' }],
  provider: 'my_provider', warnings: [], limitation,
};
export const personRecord = {
  subject: { name: 'Jane Example', type: 'person', country: 'GB', register_id: '', legal_form: '', status: '', city: '', source_url: 'https://example.org/register/gb/officers/jane-example' },
  owners: [],
  holdings: [
    { name: 'Example Analytics Ltd', register_id: '01234567', country: 'GB', relation: 'significant_control', share_band: '50-75%', since: '2019-05-02', status: 'active', source_url: 'https://example.org/register/gb/01234567' },
    { name: 'Sample Labs Ltd', register_id: '07654321', country: 'GB', relation: 'director', since: '2017-02-01', until: '2023-09-30', status: 'dissolved', source_url: 'https://example.org/register/gb/07654321' },
  ],
  officers: [],
  provider: 'my_provider', warnings: [], limitation,
};
export const ambiguousError = {
  query: 'Example Holding', country: 'FR', code: 'ambiguous', message: 'Several companies are named "Example Holding"',
  candidates: [
    { name: 'Example Holding SAS', register_id: '123456789', city: 'Paris', status: 'active' },
    { name: 'Example Holding Lyon SARL', register_id: '987654321', city: 'Lyon', status: 'active' },
    { name: 'Example Holding Services SAS', register_id: '111222333', city: 'Lille', status: 'closed' },
  ],
};
export const coverageGapError = { query: 'Example Oy', country: 'FI', code: 'coverage_gap', message: 'Finland is not covered by an installed register provider', candidates: [] };
const base = { app_id: 'business', skill_id: 'company_ownership', status: 'finished', success: true, providers: ['my_provider'], warnings: [], limitation, errors: [] };
export const ownershipData = { ...base, query: 'Example Robotics GmbH', result_count: 2, records: [germanRecord, ukRecord] };
export const ukData = { ...base, query: 'Example Analytics Ltd', result_count: 1, records: [ukRecord] };
export const personData = { ...base, query: 'Jane Example', result_count: 1, records: [personRecord] };
export const ambiguousData = { ...base, query: 'Example Holding', result_count: 0, records: [], errors: [ambiguousError] };
export const coverageGapData = { ...base, query: 'Example Oy', result_count: 0, records: [], errors: [coverageGapError] };
export const mixedData = { ...ownershipData, query: 'Example Robotics GmbH, Example Oy', errors: [coverageGapError], warnings: ['Example Oy was not looked up: Finland is not covered.'] };
export const emptyData = { ...base, query: 'Example Robotics GmbH', result_count: 0, records: [] };
export const errorData = { ...base, status: 'error', success: false, query: 'Example Robotics GmbH', result_count: 0, records: [], error: 'Company ownership lookup is unavailable.', error_code: 'provider_error' };
const props = { id: 'preview-company-ownership', data: ownershipData, status: 'finished' as const, presentationOnly: true, onFullscreen: () => {} };
export default props;
export const variants = {
  processing: { ...props, data: { query: 'Example Robotics GmbH' }, status: 'processing' as const },
  error: { ...props, data: errorData, status: 'error' as const },
  cancelled: { ...props, data: { query: 'Example Robotics GmbH' }, status: 'cancelled' as const },
  empty: { ...props, data: emptyData },
  uk: { ...props, data: ukData },
  person: { ...props, data: personData },
  ambiguous: { ...props, data: ambiguousData },
  coverage_gap: { ...props, data: coverageGapData },
  mobile: { ...props, isMobile: true },
  long: { ...props, data: { ...ownershipData, query: 'A long ownership lookup with many words to verify that narrow preview wrapping stays tidy',
    records: [{ ...germanRecord, subject: { ...germanRecord.subject, name: 'Example Robotics And Autonomous Systems Verwaltungsgesellschaft Mit Beschränkter Haftung' },
      owners: [{ name: 'Jane Maria Example-Placeholder Of The Very Long Family Name Holding Company', share_percent: 42.5 }] }] } },
};
