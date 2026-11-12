/**
 * Normalises business.company_ownership embed content (direct skill response or
 * saved payload). Every register field except a record's subject name may be
 * missing; helpers return empty values so the UI renders nothing for them.
 */
import { record, string, strings } from './trademarkSearchContent';
import { safeHttpUrl } from './investorSearchContent';

export interface OwnershipOwner {
  name: string;
  type: string;
  relation: string;
  share: string;
  nominal: string;
  since: string;
  registerId: string;
}
export interface OwnershipHolding {
  name: string;
  registerId: string;
  country: string;
  relation: string;
  share: string;
  since: string;
  until: string;
  status: string;
  ended: boolean;
  sourceUrl: string | null;
}
export interface OwnershipOfficer { name: string; type: string; role: string; since: string; }
export interface OwnershipSubject {
  name: string;
  type: string;
  country: string;
  registerId: string;
  legalForm: string;
  status: string;
  city: string;
  sourceUrl: string | null;
}
export interface OwnershipRecord {
  subject: OwnershipSubject;
  owners: OwnershipOwner[];
  holdings: OwnershipHolding[];
  officers: OwnershipOfficer[];
  provider: string;
  warnings: string[];
  limitation: string;
}
export interface OwnershipCandidate { name: string; registerId: string; city: string; status: string; }
export interface OwnershipError {
  query: string;
  country: string;
  code: string;
  message: string;
  candidates: OwnershipCandidate[];
}

/** "42%" for an exact share, else the register's band such as "25-50%", else "". */
export function formatShare(percent: unknown, band: unknown): string {
  if (typeof percent === 'number' && Number.isFinite(percent) && percent >= 0) {
    return `${Number(percent.toFixed(2))}%`;
  }
  return typeof band === 'string' ? band.trim() : '';
}

function nominalAmount(value: unknown, currency: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '';
  const code = typeof currency === 'string' && /^[A-Za-z]{3}$/.test(currency) ? currency.toUpperCase() : '';
  try {
    return new Intl.NumberFormat('en', code ? { style: 'currency', currency: code } : {}).format(value);
  } catch { return String(value); }
}

const rows = (value: unknown, limit: number): Record<string, unknown>[] =>
  (Array.isArray(value) ? value : []).filter(record).slice(0, limit) as Record<string, unknown>[];

function toRecord(row: Record<string, unknown>): OwnershipRecord | null {
  const subject = record(row.subject) ? (row.subject as Record<string, unknown>) : {};
  const name = string(subject.name).trim();
  if (!name) return null;
  return {
    subject: {
      name, type: string(subject.type), country: string(subject.country), registerId: string(subject.register_id),
      legalForm: string(subject.legal_form), status: string(subject.status), city: string(subject.city),
      sourceUrl: safeHttpUrl(subject.source_url),
    },
    owners: rows(row.owners, 200).filter((o) => string(o.name).trim()).map((o) => ({
      name: string(o.name).trim(), type: string(o.type), relation: string(o.relation),
      share: formatShare(o.share_percent, o.share_band), nominal: nominalAmount(o.nominal_amount, o.currency),
      since: string(o.since), registerId: string(o.register_id),
    })),
    holdings: rows(row.holdings, 200).filter((h) => string(h.name).trim()).map((h) => ({
      name: string(h.name).trim(), registerId: string(h.register_id), country: string(h.country),
      relation: string(h.relation), share: formatShare(h.share_percent, h.share_band), since: string(h.since),
      until: string(h.until), status: string(h.status), ended: !!string(h.until), sourceUrl: safeHttpUrl(h.source_url),
    })),
    officers: rows(row.officers, 200).filter((o) => string(o.name).trim()).map((o) => ({
      name: string(o.name).trim(), type: string(o.type), role: string(o.role), since: string(o.since),
    })),
    provider: string(row.provider), warnings: strings(row.warnings), limitation: string(row.limitation),
  };
}

function toError(row: Record<string, unknown>): OwnershipError {
  return {
    query: string(row.query), country: string(row.country), code: string(row.code), message: string(row.message),
    candidates: rows(row.candidates, 10).filter((c) => string(c.name).trim()).map((c) => ({
      name: string(c.name).trim(), registerId: string(c.register_id), city: string(c.city), status: string(c.status),
    })),
  };
}

export function normalizeCompanyOwnership(content: unknown) {
  const root = record(content) ? (content as Record<string, unknown>) : {};
  const records = rows(root.records, 20).map(toRecord).filter((r): r is OwnershipRecord => r !== null);
  const errors = rows(root.errors, 20).map(toError);
  const count = typeof root.result_count === 'number' && Number.isInteger(root.result_count) && root.result_count >= 0
    ? root.result_count : records.length;
  return {
    query: string(root.query), providers: strings(root.providers).length ? strings(root.providers) : strings(root.provider),
    records, errors, count, warnings: strings(root.warnings), limitation: string(root.limitation),
    error: string(root.error), errorCode: string(root.error_code), status: string(root.status),
    hasData: Array.isArray(root.records),
  };
}

/** Localised country name for an ISO code; falls back to the code. */
export function countryName(code: string, locale = 'en'): string {
  if (!/^[A-Za-z]{2}$/.test(code)) return code;
  try { return new Intl.DisplayNames([locale], { type: 'region' }).of(code.toUpperCase()) ?? code; } catch { return code; }
}

/** Plain-text rendering for copy parity. */
export function renderCompanyOwnershipText(content: Record<string, unknown>): string {
  const data = normalizeCompanyOwnership(content);
  const lines = ['**Business | Company ownership**', data.query];
  for (const rec of data.records) {
    lines.push([rec.subject.name, rec.subject.country, rec.subject.legalForm, rec.subject.status].filter(Boolean).join(' — '));
    for (const o of rec.owners) lines.push(`  Owner: ${[o.name, o.share].filter(Boolean).join(' — ')}`);
    for (const h of rec.holdings) lines.push(`  Holding: ${[h.name, h.share, h.ended ? 'ended' : ''].filter(Boolean).join(' — ')}`);
    for (const o of rec.officers) lines.push(`  Officer: ${[o.name, o.role].filter(Boolean).join(' — ')}`);
    if (rec.subject.sourceUrl) lines.push(rec.subject.sourceUrl);
    lines.push(...rec.warnings);
  }
  for (const e of data.errors) {
    lines.push(`${e.query} (${e.country}): ${e.code}${e.message ? ' — ' + e.message : ''}`);
    for (const c of e.candidates) lines.push(`  ${[c.name, c.registerId, c.city].filter(Boolean).join(' — ')}`);
  }
  lines.push(...data.warnings);
  if (data.error) lines.push(data.error);
  if (data.limitation) lines.push(data.limitation);
  return lines.filter(Boolean).join('\n');
}
