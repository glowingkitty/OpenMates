import { describe, expect, it } from 'vitest';
import { formatTicketRange, normalizeInvestorSearch, safeHttpUrl } from './investorSearchContent';

describe('formatTicketRange', () => {
  // contract-test: supporting surface=gui.web assertions=investors.results,investors.limits
  it('formats min and max with currency', () => {
    expect(formatTicketRange(25000, 100000, 'EUR', 'en')).toBe('€25K – €100K');
  });
  // contract-test: supporting surface=gui.web assertions=investors.results,investors.limits
  it('handles only min or only max', () => {
    expect(formatTicketRange(25000, undefined, 'EUR', 'en')).toBe('≥ €25K');
    expect(formatTicketRange(null, 100000, 'USD', 'en')).toBe('≤ $100K');
  });
  // contract-test: supporting surface=gui.web assertions=investors.results,investors.limits
  it('returns empty for missing or invalid values', () => {
    expect(formatTicketRange(undefined, undefined, 'EUR')).toBe('');
    expect(formatTicketRange('x', -5, 'EUR')).toBe('');
  });
  // contract-test: supporting surface=gui.web assertions=investors.results,investors.limits
  it('falls back to plain numbers without a valid currency', () => {
    expect(formatTicketRange(1000, 2000, 'euro', 'en')).toBe('1K – 2K');
  });
});

describe('normalizeInvestorSearch', () => {
  // contract-test: supporting surface=gui.web assertions=investors.results,investors.limits
  it('keeps named investors with missing fields and drops nameless rows', () => {
    const data = normalizeInvestorSearch({ investors: [{ name: 'Alex Sample' }, { city: 'Berlin' }, 'x'], warnings: ['A was not searched.'] });
    expect(data.investors).toHaveLength(1);
    expect(data.investors[0]).toMatchObject({ name: 'Alex Sample', ticket: '', profileUrl: null, regions: [] });
    expect(data.count).toBe(1);
    expect(data.warnings).toEqual(['A was not searched.']);
  });
  // contract-test: supporting surface=gui.web assertions=investors.results,investors.limits
  it('treats missing investors list as no data', () => {
    expect(normalizeInvestorSearch({ error: 'x' }).hasData).toBe(false);
  });
});

describe('safeHttpUrl', () => {
  // contract-test: supporting surface=gui.web assertions=investors.results,investors.limits
  it('allows http(s) only', () => {
    expect(safeHttpUrl('https://example.org/a')).toBe('https://example.org/a');
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull();
    expect(safeHttpUrl('https://u:p@example.org')).toBeNull();
  });
});
