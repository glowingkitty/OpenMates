export type EmbedStatus = 'processing' | 'finished' | 'error' | 'cancelled';
export type DomainAvailability = 'available' | 'unavailable' | 'unknown';
export type DomainView = 'selected' | 'available' | 'all' | 'in-use' | 'unknown';

export interface DomainTier {
  unit?: string;
  duration_range?: { minimum?: number | null; maximum?: number | null };
  minimum_term?: string | null;
  price_including_tax?: number | null;
  price_excluding_tax?: number | null;
  normal_price?: number | null;
  normal_price_before_taxes?: number | null;
  discount?: boolean | null;
  tax_rate?: number | null;
  product_taxes?: Array<{ rate?: number | null; name?: string }>;
}

export interface DomainResult {
  embed_id: string;
  domain_ascii: string;
  domain_unicode: string;
  availability: DomainAvailability;
  provider: string;
  provider_url: string;
  premium?: boolean | null;
  reserved?: boolean | null;
  corporate?: boolean | null;
  restrictions: string[];
  registration_tiers: DomainTier[];
  renewal_tiers: DomainTier[];
  checked_at?: string | null;
  country?: string;
  currency?: string;
}

export interface StartingQuote {
  amount: number;
  currency: string;
  tax_basis: 'including' | 'excluding';
  unit: 'year';
  duration: 1;
}

export interface DomainSearchContent {
  query?: string;
  provider?: string;
  country?: string;
  currency?: string;
  checked_at?: string | null;
  status?: EmbedStatus;
  partial?: boolean;
  warnings?: string[];
  error?: string | null;
  availability?: 'prefer_available' | 'available_only' | 'all';
  max_results?: number;
  result_count?: number;
  checked_count?: number;
  available_count?: number;
  unavailable_count?: number;
  unknown_count?: number;
  embed_ids?: string | string[];
  selected_embed_ids?: string | string[];
  preview_starting_registration?: StartingQuote | null;
}

export function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function textValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

export function numberValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

export function idList(value: unknown): string[] {
  const items = Array.isArray(value) ? value : typeof value === 'string' ? value.split('|') : [];
  return [...new Set(items.filter((item): item is string => typeof item === 'string' && !!item.trim()).map((item) => item.trim()))];
}

export function tierList(value: unknown): DomainTier[] {
  return Array.isArray(value) ? value.filter((item): item is DomainTier => !!item && typeof item === 'object' && !Array.isArray(item)) : [];
}

export function normalizeDomain(embedId: string, raw: Record<string, unknown>): DomainResult {
  const availability = raw.availability;
  const ascii = textValue(raw.domain_ascii);
  return {
    embed_id: embedId,
    domain_ascii: ascii,
    domain_unicode: textValue(raw.domain_unicode) || ascii,
    availability: availability === 'available' || availability === 'unavailable' ? availability : 'unknown',
    provider: textValue(raw.provider) || 'Gandi',
    provider_url: textValue(raw.provider_url),
    premium: raw.premium === true,
    reserved: raw.reserved === true,
    corporate: raw.corporate === true,
    restrictions: Array.isArray(raw.restrictions) ? raw.restrictions.filter((item): item is string => typeof item === 'string' && !!item.trim()) : [],
    registration_tiers: tierList(raw.registration_tiers),
    renewal_tiers: tierList(raw.renewal_tiers),
    checked_at: textValue(raw.checked_at) || null,
    country: textValue(raw.country),
    currency: textValue(raw.currency),
  };
}

export function years(tier: DomainTier): number | undefined {
  if (tier.unit !== 'y' && tier.unit !== 'year' && tier.unit !== 'years') return undefined;
  return numberValue(tier.duration_range?.minimum);
}

export function quote(tier: DomainTier | undefined): { amount: number; basis: 'including' | 'excluding' } | null {
  if (!tier) return null;
  const including = numberValue(tier.price_including_tax);
  if (including !== undefined && including >= 0) return { amount: including, basis: 'including' };
  const excluding = numberValue(tier.price_excluding_tax);
  return excluding !== undefined && excluding >= 0 ? { amount: excluding, basis: 'excluding' } : null;
}

export function headlineTier(tiers: DomainTier[]): DomainTier | undefined {
  return tiers.find((tier) => years(tier) === 1 && quote(tier)) ?? tiers.find((tier) => quote(tier));
}

export function isFirstYearOffer(tier: DomainTier | undefined): boolean {
  if (!tier || years(tier) !== 1 || tier.discount !== true) return false;
  const currentQuote = quote(tier);
  const current = currentQuote?.amount;
  const normal = numberValue(currentQuote?.basis === 'including' ? tier.normal_price : tier.normal_price_before_taxes);
  return current !== undefined && normal !== undefined && normal > current;
}

export function normalRegistration(tier: DomainTier | undefined): number | undefined {
  if (!tier || !isFirstYearOffer(tier)) return undefined;
  return numberValue(quote(tier)?.basis === 'including' ? tier.normal_price : tier.normal_price_before_taxes);
}

export function formatMoney(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

/** Gandi quotes are per duration_unit, even when the tier requires several years. */
export function formatTierMoney(tier: DomainTier | undefined, currency: string, localizedYear: string): string | null {
  const value = quote(tier);
  if (!value) return null;
  const amount = formatMoney(value.amount, currency);
  return tier?.unit === 'y' || tier?.unit === 'year' || tier?.unit === 'years'
    ? `${amount} / ${localizedYear}`
    : amount;
}

export function formatChecked(value: string | null | undefined): string {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export function safeGandiUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'shop.gandi.net' ? url.toString() : null;
  } catch {
    return null;
  }
}

export function boundedView(children: DomainResult[], selectedIds: string[], view: DomainView, maxResults: number): DomainResult[] {
  const byId = new Map(children.map((child) => [child.embed_id, child]));
  if (view === 'selected') return selectedIds.map((id) => byId.get(id)).filter((child): child is DomainResult => !!child).slice(0, maxResults);
  const matching = children.filter((child) => view === 'all'
    ? child.availability !== 'unknown'
    : view === 'available' ? child.availability === 'available'
    : view === 'in-use' ? child.availability === 'unavailable'
    : child.availability === 'unknown');
  return matching.slice(0, maxResults);
}
