// frontend/packages/ui/src/components/embeds/fitness/fitnessEmbedData.ts
//
// Shared normalization helpers for Fitness Urban Sports embeds. Runtime skill
// embeds can arrive either as modern parent embeds with child embed IDs or as
// legacy TOON-decoded top-level result tables from example chats. Keeping this
// normalization in one place prevents preview/fullscreen renderers from drifting.

export type FitnessSkillId = 'search_locations' | 'search_classes';
export type FitnessStatus = 'processing' | 'finished' | 'error' | 'cancelled';

export interface FitnessResult {
  embed_id?: string;
  id?: string;
  provider?: string;
  appointment_id?: string;
  venue_id?: string;
  name?: string;
  category?: string;
  class_type?: string;
  attendance_mode?: string;
  date?: string;
  time_range?: string | null;
  venue_name?: string;
  venue_url?: string;
  venue_address?: string;
  venue_postal_code?: string;
  venue_city?: string;
  venue_lat?: number | string;
  venue_lon?: number | string;
  address?: string;
  street?: string;
  postal_code?: string;
  city?: string;
  country?: string;
  lat?: number | string;
  lon?: number | string;
  distance_km?: number | string;
  disciplines?: string[] | string;
  spots_left?: number | string;
  spots_display?: string;
  plans_required?: string[] | string;
  detail_url?: string;
  url?: string;
  image_url?: string | null;
  [key: string]: unknown;
}

export interface FitnessSearchData {
  skillId: FitnessSkillId;
  provider: string;
  query: string;
  filters: Record<string, unknown>;
  summary: string;
  results: FitnessResult[];
  resultCount: number;
  embedIds?: string | string[];
  status: FitnessStatus;
}

export function normalizeFitnessStatus(value: unknown): FitnessStatus {
  if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
  return 'finished';
}

export function normalizeFitnessSkillId(value: unknown, fallback: FitnessSkillId = 'search_classes'): FitnessSkillId {
  return value === 'search_locations' ? 'search_locations' : value === 'search_classes' ? 'search_classes' : fallback;
}

export function asText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.filter(Boolean).join(', ');
  return String(value);
}

export function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

export function normalizePipedList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(asText).filter(Boolean);
  if (typeof value === 'string') return value.split('|').map((part) => part.trim()).filter(Boolean);
  return [];
}

export function getFitnessResultTitle(result: FitnessResult): string {
  return asText(result.name || result.venue_name || result.id || 'Urban Sports result');
}

export function getFitnessResultAddress(result: FitnessResult): string {
  return asText(result.address || result.venue_address || [result.street, result.postal_code, result.city].filter(Boolean).join(', '));
}

export function getFitnessResultUrl(result: FitnessResult): string {
  return asText(result.detail_url || result.url || result.venue_url);
}

export function normalizeFitnessSearchContent(
  content: Record<string, unknown> | null | undefined,
  fallbackSkillId: FitnessSkillId = 'search_classes',
): FitnessSearchData {
  const safeContent = content ?? {};
  const skillId = normalizeFitnessSkillId(safeContent.skill_id, fallbackSkillId);
  const rawResults = Array.isArray(safeContent.results) ? safeContent.results as Record<string, unknown>[] : [];
  const firstGroup = rawResults[0];
  const hasGroupedResults = Boolean(firstGroup && Array.isArray(firstGroup.results));
  const groupedResults = hasGroupedResults ? firstGroup.results as FitnessResult[] : [];
  const legacyResults = hasGroupedResults ? [] : rawResults as FitnessResult[];
  const results = hasGroupedResults ? groupedResults : legacyResults;
  const filters = hasGroupedResults && firstGroup?.filters && typeof firstGroup.filters === 'object'
    ? firstGroup.filters as Record<string, unknown>
    : safeContent.filters && typeof safeContent.filters === 'object'
      ? safeContent.filters as Record<string, unknown>
      : {
          query: safeContent.query,
          address: safeContent.address || safeContent.location,
          city: safeContent.city,
          radius_km: safeContent.radius_km,
          plan: safeContent.plan,
          attendance_mode: safeContent.attendance_mode,
          start_date: safeContent.start_date || safeContent.date,
          days: safeContent.days,
        };

  const explicitCount = hasGroupedResults ? firstGroup?.result_count : safeContent.result_count;
  const resultCount = typeof explicitCount === 'number' ? explicitCount : results.length;

  return {
    skillId,
    provider: asText((hasGroupedResults ? firstGroup?.provider : safeContent.provider) || 'Urban Sports Club'),
    query: asText(safeContent.query || filters.query || filters.address || filters.city || safeContent.location),
    filters: Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== undefined && value !== null && value !== '')),
    summary: asText((hasGroupedResults ? firstGroup?.summary : safeContent.summary) || ''),
    results,
    resultCount,
    embedIds: safeContent.embed_ids as string | string[] | undefined,
    status: normalizeFitnessStatus(safeContent.status),
  };
}
