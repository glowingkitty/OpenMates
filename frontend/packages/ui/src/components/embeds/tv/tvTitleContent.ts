/** Presentation-only TV metadata. Never enrich titles or read/write TV memories. */
import type { AuthoredResultMetadata } from '../../../types/authoredResult';

export interface TVScore {
  value: number;
  scale: number;
  sourceUrl: string;
  sourceLabel?: string;
  votes?: number;
  observedAt?: string;
}
export interface TVSeason {
  number: number;
  title?: string;
  synopsis?: string;
  firstAirDate?: string;
  episodeCount?: number;
  posterUrl?: string;
}
export interface TVTitle {
  kind: 'movie' | 'series';
  title?: string;
  synopsis?: string;
  posterUrl?: string;
  sourceUrl?: string;
  year?: number;
  endYear?: number;
  releaseDate?: string;
  firstAirDate?: string;
  lastAirDate?: string;
  runtimeMinutes?: number;
  genres: string[];
  directors: string[];
  creators: string[];
  cast: string[];
  language?: string;
  countries: string[];
  contentRating?: string;
  seriesStatus?: string;
  seasonCount?: number;
  episodeCount?: number;
  seasons: TVSeason[];
  score?: TVScore;
  authoring?: AuthoredResultMetadata;
}

export function tvText(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}
function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function count(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
}
function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.flatMap(entry => tvText(entry) ? [tvText(entry)!] : []) : [];
}
function unsafeUrlCharacters(value: string): boolean {
  return [...value].some(character => character.charCodeAt(0) <= 32
    || character.charCodeAt(0) === 127 || character === "\\");
}
export function tvSourceUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value || unsafeUrlCharacters(value)) return;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? value : undefined;
  } catch { return; }
}
function poster(value: unknown, allowDecryptedMedia = false): string | undefined {
  if (typeof value !== 'string' || !value || unsafeUrlCharacters(value)) return;
  if (allowDecryptedMedia && value.startsWith('blob:')) return value;
  if (value.startsWith('/') && !value.startsWith('//')) return value;
  const url = tvSourceUrl(value);
  return url?.startsWith('https:') ? url : undefined;
}
function date(value: unknown): string | undefined {
  const text = tvText(value);
  if (!text || !/^\d{4}-\d{2}-\d{2}$/.test(text)) return;
  const parsed = new Date(`${text}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === text ? text : undefined;
}
function year(value: unknown): number | undefined {
  const supplied = count(value);
  return supplied !== undefined && supplied > 0 && supplied <= 9999 ? supplied : undefined;
}
function score(value: unknown): TVScore | undefined {
  const raw = record(value);
  const sourceUrl = tvSourceUrl(raw.source_url);
  if (typeof raw.value !== 'number' || !Number.isFinite(raw.value) || raw.value < 0
    || typeof raw.scale !== 'number' || !Number.isFinite(raw.scale) || raw.scale <= 0
    || raw.value > raw.scale || !sourceUrl) return;
  return { value: raw.value, scale: raw.scale, sourceUrl,
    sourceLabel: tvText(raw.source_label), votes: count(raw.votes), observedAt: tvText(raw.observed_at) };
}

/** Keep missing totals absent and supplied season order, including season zero. */
export function readTVTitle(content: Record<string, unknown>, options: { allowDecryptedMedia?: boolean } = {}): TVTitle {
  const rawAuthoring = record(content.authoring);
  const authoring = rawAuthoring.schema_version === 1
    && ['researched', 'user_provided', 'draft'].includes(String(rawAuthoring.origin))
    && ['tv.movie', 'tv.series'].includes(String(rawAuthoring.kind))
    && Array.isArray(rawAuthoring.sources) ? rawAuthoring as unknown as AuthoredResultMetadata : undefined;
  const kind = authoring ? (authoring.kind === 'tv.series' ? 'series' : 'movie')
    : content.type === 'tv_series' ? 'series' : 'movie';
  const seasonRows = Array.isArray(content.seasons) ? content.seasons.slice(0, 100).map(record) : [];
  const seasons = seasonRows.flatMap(raw => {
    const number = count(raw.season_number);
    if (number === undefined || seasonRows.filter(row => row.season_number === number).length !== 1) return [];
    return [{ number, title: tvText(raw.title), synopsis: tvText(raw.synopsis), firstAirDate: date(raw.first_air_date),
      episodeCount: count(raw.episode_count), posterUrl: poster(raw.poster_url) }];
  });
  return {
    kind, title: tvText(content.title), synopsis: tvText(content.synopsis),
    posterUrl: poster(content.poster_url, options.allowDecryptedMedia) ?? poster(content.image_url, options.allowDecryptedMedia), sourceUrl: tvSourceUrl(content.source_url),
    year: year(kind === 'series' ? content.start_year : content.year), endYear: year(content.end_year),
    releaseDate: date(content.release_date), firstAirDate: date(content.first_air_date), lastAirDate: date(content.last_air_date),
    runtimeMinutes: count(kind === 'series' ? content.episode_runtime_minutes : content.runtime_minutes),
    genres: texts(content.genres), directors: texts(content.directors), creators: texts(content.creators),
    cast: texts(content.cast), language: tvText(content.original_language), countries: texts(content.country_codes),
    contentRating: tvText(content.content_rating), seriesStatus: tvText(content.series_status),
    seasonCount: count(content.season_count), episodeCount: count(content.episode_count), seasons,
    score: score(content.score), authoring,
  };
}

/** Only visible title facts enter the shared follow-up composer. */
export function tvFollowupContext(title: TVTitle): Record<string, unknown> {
  return Object.fromEntries(Object.entries({
    title: title.title, kind: `tv.${title.kind}`, origin: title.authoring?.origin, synopsis: title.synopsis, year: title.year,
    end_year: title.endYear, release_date: title.releaseDate, first_air_date: title.firstAirDate,
    last_air_date: title.lastAirDate, runtime_minutes: title.runtimeMinutes, genres: title.genres,
    directors: title.directors, creators: title.creators, cast: title.cast, source_url: title.sourceUrl,
    season_count: title.seasonCount, episode_count: title.episodeCount,
    seasons: title.seasons.map(season => ({ season_number: season.number, title: season.title,
      first_air_date: season.firstAirDate, episode_count: season.episodeCount })),
    score: title.score ? { value: title.score.value, scale: title.score.scale,
      source_url: title.score.sourceUrl, source_label: title.score.sourceLabel } : undefined,
  }).filter(([, value]) => value !== undefined));
}
