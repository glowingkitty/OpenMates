/**
 * Plain-text renderers for Business app embeds.
 *
 * Used by copy/export/CLI surfaces so SEC company financial embeds remain
 * readable without mounting Svelte components.
 */

import { resolveResultCount, str } from '../../../data/embedTextRenderers';

function formatMoney(value: unknown, currency: unknown): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: str(currency) ?? 'USD',
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(value);
}

export function renderCompanyFinancials(content: Record<string, unknown>): string {
  const query = str(content.query) ?? 'Company financials';
  const provider = str(content.provider) ?? 'SEC EDGAR';
  const count = resolveResultCount(content);
  const lines = [`**Business | Get company financials**`, `query: ${query}`, `provider: ${provider}`];
  if (count !== null) lines.push(`companies: ${count}`);
  return lines.join('\n');
}

export function renderCompanyFinancialResult(content: Record<string, unknown>): string {
  const company = str(content.company) ?? str(content.ticker) ?? 'Company financial result';
  const currency = str(content.currency) ?? 'USD';
  const lines = [`**${company}**`];
  if (str(content.ticker)) lines.push(`ticker: ${str(content.ticker)}`);
  if (typeof content.fiscal_year === 'number') lines.push(`fiscal year: ${content.fiscal_year}`);
  const revenue = formatMoney(content.revenue, currency);
  const netIncome = formatMoney(content.net_income, currency);
  if (revenue) lines.push(`revenue: ${revenue}`);
  if (netIncome) lines.push(`net income: ${netIncome}`);
  if (str(content.source_url)) lines.push(str(content.source_url) as string);
  return lines.join('\n');
}
