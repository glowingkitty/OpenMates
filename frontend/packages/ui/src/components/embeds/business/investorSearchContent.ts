/**
 * Normalises business.search_investors embed content (direct skill response or
 * saved payload) and formats investor fields. Every investor field except the
 * name may be missing; helpers return empty values so the UI renders nothing.
 */
import { record, string, strings } from './trademarkSearchContent';

export const INVESTOR_TYPES = ['angel', 'angel_network', 'vc', 'family_office', 'accelerator', 'public_funding'] as const;
export const INVESTOR_STAGES = ['pre_seed', 'seed', 'series_a', 'later'] as const;

export interface InvestorRow {
  name: string;
  investorType: string;
  organization: string;
  regions: string[];
  city: string;
  stages: string[];
  sectors: string[];
  ticket: string;
  thesis: string;
  exampleInvestments: string[];
  profileUrl: string | null;
  websiteUrl: string | null;
  contactRoute: string;
  sourceUpdatedAt: string;
  provider: string;
}

/** Only absolute http(s) links without credentials are rendered as links. */
export function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== 'string' || !value) return null;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    return url.href;
  } catch { return null; }
}

function amount(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

/** Formats a ticket range such as "€25k – €100k"; handles only min or only max. */
export function formatTicketRange(min: unknown, max: unknown, currency: unknown, locale?: string): string {
  const low = amount(min);
  const high = amount(max);
  if (low === null && high === null) return '';
  const code = typeof currency === 'string' && /^[A-Za-z]{3}$/.test(currency) ? currency.toUpperCase() : '';
  const fmt = (value: number): string => {
    try {
      return new Intl.NumberFormat(locale ?? 'en', {
        ...(code ? { style: 'currency', currency: code } : {}),
        notation: 'compact', maximumFractionDigits: 1,
      }).format(value);
    } catch { return String(value); }
  };
  if (low !== null && high !== null) return low === high ? fmt(low) : `${fmt(low)} – ${fmt(high)}`;
  return low !== null ? `≥ ${fmt(low)}` : `≤ ${fmt(high as number)}`;
}

function toInvestor(row: Record<string, unknown>): InvestorRow | null {
  const name = string(row.name).trim();
  if (!name) return null;
  return {
    name,
    investorType: string(row.investor_type),
    organization: string(row.organization),
    regions: strings(row.regions),
    city: string(row.city),
    stages: strings(row.stages),
    sectors: strings(row.sectors),
    ticket: formatTicketRange(row.ticket_min, row.ticket_max, row.currency),
    thesis: string(row.thesis),
    exampleInvestments: strings(row.example_investments),
    profileUrl: safeHttpUrl(row.profile_url),
    websiteUrl: safeHttpUrl(row.website_url),
    contactRoute: string(row.contact_route),
    sourceUpdatedAt: string(row.source_updated_at),
    provider: string(row.provider),
  };
}

export function normalizeInvestorSearch(content: unknown) {
  const root = record(content) ? content : {};
  const investors = (Array.isArray(root.investors) ? root.investors : [])
    .filter(record).slice(0, 100).map(toInvestor).filter((row): row is InvestorRow => row !== null);
  const count = typeof root.result_count === 'number' && Number.isInteger(root.result_count) && root.result_count >= 0
    ? root.result_count : investors.length;
  return {
    query: string(root.query),
    regions: strings(root.regions),
    provider: string(root.provider),
    investors, count,
    warnings: strings(root.warnings),
    partial: root.partial === true || root.partial === 'true',
    limitation: string(root.limitation),
    error: string(root.error),
    errorCode: string(root.error_code),
    status: string(root.status),
    hasData: Array.isArray(root.investors),
  };
}

/** Plain-text rendering for copy/CLI parity. */
export function renderInvestorSearchText(content: Record<string, unknown>): string {
  const data = normalizeInvestorSearch(content);
  const lines = ['**Business | Search investors**', data.query];
  if (data.regions.length) lines.push(data.regions.join(', '));
  if (data.hasData) lines.push(`${data.count} investors`);
  for (const row of data.investors) {
    lines.push([row.name, row.investorType, row.organization, row.ticket].filter(Boolean).join(' — '));
    if (row.profileUrl) lines.push(row.profileUrl);
  }
  lines.push(...data.warnings);
  if (data.error) lines.push(data.error);
  if (data.limitation) lines.push(data.limitation);
  return lines.filter(Boolean).join('\n');
}
