/** The public catalog can be older than the backend's live tariff. Keep stale
 * or unverified proposals from appearing as active cache prices. */
export interface CachePricingAvailability {
  enabled?: boolean;
  status?: string;
  source_url?: string;
  reviewed_on?: string;
  effective_from?: string;
  expires_on?: string;
  eligible_hosts?: string[];
  write_billing?: 'included_in_input' | 'separate';
  requires_cache_retention_metric?: boolean;
  cache_write_1h_hosts?: string[];
}

/** A proposed 1h rate is only public on a route that actually requests 1h retention. */
export function supportsOneHourCacheWrites(
  policy: CachePricingAvailability | null | undefined,
  defaultHost?: string,
): boolean {
  return Boolean(defaultHost && policy?.cache_write_1h_hosts?.includes(defaultHost));
}

export interface CachePricingRates {
  cache_read?: number;
  cache_write?: number;
  cache_write_1h?: number;
}

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(5, 7));
  const day = Number(value.slice(8, 10));
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

export function isCachePricingDisplayActive(
  policy: CachePricingAvailability | null | undefined,
  defaultHost?: string,
  rates?: CachePricingRates,
  today = new Date().toISOString().slice(0, 10),
): boolean {
  if (!policy?.enabled || policy.status !== 'verified_for_activation') return false;
  if (!['included_in_input', 'separate'].includes(policy.write_billing ?? '') || !rates) return false;
  if (!policy.source_url || !policy.reviewed_on || !policy.expires_on || !policy.eligible_hosts?.length) return false;
  if (!validDate(policy.reviewed_on) || !validDate(policy.expires_on) ||
    (policy.effective_from && !validDate(policy.effective_from))) return false;
  if (policy.reviewed_on > today || policy.expires_on < today) return false;
  if (policy.effective_from && policy.effective_from > today) return false;
  if (!rates.cache_read || rates.cache_read <= 0) return false;
  if (policy.write_billing === 'separate' && (!rates.cache_write || rates.cache_write <= 0)) return false;
  if (policy.requires_cache_retention_metric && (!rates.cache_write_1h || rates.cache_write_1h <= 0)) return false;
  return Boolean(defaultHost && policy.eligible_hosts.includes(defaultHost));
}
