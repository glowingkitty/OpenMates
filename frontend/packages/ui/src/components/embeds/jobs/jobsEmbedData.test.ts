import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { URL } from 'node:url';
import { jobSalary, normalizeJob } from './jobsEmbedData';

// contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
describe('authored job salary presentation', () => {
  it('retains supplied salary and zero amounts without inventing a currency', () => {
    const job = normalizeJob('authored-job', { title: 'Example role', salary_min: 0, salary_max: 1250,
      salary_period: 'month', remote: false, authoring: { schema_version: 1, kind: 'jobs.job_result', origin: 'draft', sources: [] } });
    expect(jobSalary(job)).toBe(`${new Intl.NumberFormat().format(0)}–${new Intl.NumberFormat().format(1250)} / month`);
    expect(job.remote).toBe(false);
    expect(job.salary_currency).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts
  it('keeps an omitted salary absent and preserves ordinary provider currency requirements', () => {
    expect(jobSalary(normalizeJob('authored-job', { authoring: { kind: 'jobs.job_result' } }))).toBeUndefined();
    expect(jobSalary(normalizeJob('provider-job', { salary_min: 1250 }))).toBeUndefined();
    expect(jobSalary(normalizeJob('provider-job', { salary_min: 1250, salary_currency: 'USD' })))
      .toBe(new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(1250));
  });
});

// contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
it('shows the admitted EUR 60–80k fixture with its supplied annual basis', () => {
  const fixture = JSON.parse(readFileSync(new URL('../../../../../../../backend/apps/ai/testing/fixtures/authored_results.json', import.meta.url), 'utf8')) as {
    embeds: Record<string, { document: { items: Array<{ kind: string; details: Record<string, unknown> }> } }>;
  };
  const item = Object.values(fixture.embeds)[0].document.items.find((entry) => entry.kind === 'jobs.job_result')!;
  const job = normalizeJob('fixture-job', { ...item.details, authoring: { kind: item.kind, origin: 'user_provided' } });
  const euro = (amount: number) => new Intl.NumberFormat(undefined, { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(amount);
  expect(job).toMatchObject({ salary_min: 60000, salary_max: 80000, salary_currency: 'EUR', salary_period: 'annual' });
  expect(jobSalary(job)).toBe(`${euro(60000)}–${euro(80000)} / annual`);
});

// contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts
it('preserves authored zero and one-sided amounts without adding currency or period', () => {
  const zero = normalizeJob('zero', { salary: { min: 0, max: 0 }, authoring: { kind: 'jobs.job_result' } });
  expect(jobSalary(zero)).toBe(new Intl.NumberFormat().format(0));
  expect(zero.salary_currency).toBeUndefined();
  expect(zero.salary_period).toBeUndefined();
  const maximumOnly = normalizeJob('max', { salary: { max: 80000, currency: 'EUR' }, authoring: { kind: 'jobs.job_result' } });
  expect(maximumOnly.salary_min).toBeUndefined();
  expect(maximumOnly.salary_max).toBe(80000);
  expect(jobSalary(maximumOnly)).not.toContain('/');
  const amount = normalizeJob('amount', { salary: { amount: 0 }, authoring: { kind: 'jobs.job_result' } });
  expect(jobSalary(amount)).toBe(new Intl.NumberFormat().format(0));
});

// contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
it('retains supplied salary text and preserves legacy flat salary precedence including zero', () => {
  expect(jobSalary(normalizeJob('text', { salary: 'By collective agreement', authoring: { kind: 'jobs.job_result' } })))
    .toBe('By collective agreement');
  const legacy = normalizeJob('legacy', {
    salary_min: 0, salary_max: 70000, salary_currency: 'USD', salary_period: 'month',
    salary: { min: 60000, max: 80000, currency: 'EUR', basis: 'annual' },
  });
  expect(legacy).toMatchObject({ salary_min: 0, salary_max: 70000, salary_currency: 'USD', salary_period: 'month' });
});
