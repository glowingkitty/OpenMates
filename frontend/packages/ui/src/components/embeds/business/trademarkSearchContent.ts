/** Read both direct skill responses and saved TOON app-skill payloads. */
export type TrademarkRow = Record<string, unknown>;

export function record(value: unknown): value is TrademarkRow {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

export function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean)
    : typeof value === 'string' ? value.split('|').filter(Boolean) : [];
}

export function string(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function rows(value: unknown): TrademarkRow[] {
  return Array.isArray(value) ? value.filter(record).slice(0, 60) : [];
}

export function normalizeTrademarkSearch(content: unknown) {
  const root = record(content) ? content : {};
  const saved = rows(root.results).find(row => Array.isArray(row.matches) || Array.isArray(row.coverage));
  const data = saved ?? root;
  const matches = rows(data.matches);
  const coverage = rows(data.coverage);
  const count = typeof data.result_count === 'number' && Number.isInteger(data.result_count) && data.result_count >= 0
    ? data.result_count : matches.length;
  return {
    query: string(data.query) || string(root.query),
    regions: strings(data.regions),
    niceClasses: strings(data.nice_classes),
    statusFilter: string(data.status_filter),
    match: string(data.match),
    provider: string(data.provider),
    matches, coverage, count,
    partial: data.partial === true || data.partial === 'true',
    limitation: string(data.limitation),
    error: string(data.error),
    status: string(data.status) || string(root.status),
    hasData: Array.isArray(data.matches) || Array.isArray(data.coverage),
  };
}

/** Saved external links are limited to the official sources used by this skill. */
export function trademarkSourceUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || (url.port && url.port !== '443')) return null;
    if (!['www.tmdn.org', 'register.dpma.de', 'www.wipo.int'].includes(url.hostname)) return null;
    return url.href;
  } catch { return null; }
}
