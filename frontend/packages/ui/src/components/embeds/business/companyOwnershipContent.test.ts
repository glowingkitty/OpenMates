import { describe, expect, it } from 'vitest';
import { formatShare, normalizeCompanyOwnership, renderCompanyOwnershipText } from './companyOwnershipContent';

describe('formatShare', () => {
  // contract-test: supporting surface=gui.web assertions=ownership.results
  it('prefers the exact percentage over the band', () => {
    expect(formatShare(42, '25-50%')).toBe('42%');
    expect(formatShare(12.5, null)).toBe('12.5%');
  });
  // contract-test: supporting surface=gui.web assertions=ownership.results
  it('falls back to the band and then to nothing', () => {
    expect(formatShare(null, '25-50%')).toBe('25-50%');
    expect(formatShare(undefined, undefined)).toBe('');
  });
});

describe('normalizeCompanyOwnership', () => {
  // contract-test: supporting surface=gui.web assertions=ownership.results
  it('keeps named records with missing fields and drops unnamed ones', () => {
    const data = normalizeCompanyOwnership({
      records: [{ subject: { name: 'Example Robotics GmbH' }, owners: [{ name: 'Jane Example', share_percent: 60 }, { share_percent: 5 }] }, { subject: {} }],
      errors: [{ query: 'Example', country: 'GB', code: 'ambiguous', candidates: [{ name: 'Example Ltd', register_id: '01234567' }, {}] }],
    });
    expect(data.records).toHaveLength(1);
    expect(data.records[0].owners).toEqual([expect.objectContaining({ name: 'Jane Example', share: '60%' })]);
    expect(data.count).toBe(1);
    expect(data.errors[0].candidates).toHaveLength(1);
  });
  // contract-test: supporting surface=gui.web assertions=ownership.results
  it('marks holdings with an end date as ended and drops unsafe links', () => {
    const data = normalizeCompanyOwnership({ records: [{ subject: { name: 'Jane Example', source_url: 'javascript:x' },
      holdings: [{ name: 'Example Holding SAS', until: '2024-01-01' }, { name: 'Example Robotics GmbH' }] }] });
    expect(data.records[0].holdings.map((h) => h.ended)).toEqual([true, false]);
    expect(data.records[0].subject.sourceUrl).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=ownership.results
  it('treats a missing records list as no data and renders text', () => {
    expect(normalizeCompanyOwnership({ error: 'x' }).hasData).toBe(false);
    expect(renderCompanyOwnershipText({ query: 'q', records: [{ subject: { name: 'A GmbH', country: 'DE' } }] })).toContain('A GmbH — DE');
  });
});
