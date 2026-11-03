/** Copy/export TV facts without implying playback, publication or memory writes. */
import { readTVTitle } from './tvTitleContent';

export function renderTVTitle(content: Record<string, unknown>): string {
  const title = readTVTitle(content);
  const lines = [title.title ? `**${title.title}**` : `**${title.kind === 'series' ? 'TV series' : 'Movie'}**`];
  if (title.authoring?.origin === 'draft') lines.push('[Draft]');
  if (title.year !== undefined) lines.push(String(title.year) + (title.endYear !== undefined ? `–${title.endYear}` : ''));
  if (title.releaseDate) lines.push(title.releaseDate);
  if (title.firstAirDate) lines.push(`First aired: ${title.firstAirDate}`);
  if (title.lastAirDate) lines.push(`Last aired: ${title.lastAirDate}`);
  if (title.runtimeMinutes !== undefined) lines.push(`${title.runtimeMinutes} min`);
  if (title.genres.length) lines.push(title.genres.join(', '));
  if (title.directors.length) lines.push(`Directors: ${title.directors.join(', ')}`);
  if (title.creators.length) lines.push(`Creators: ${title.creators.join(', ')}`);
  if (title.cast.length) lines.push(`Cast: ${title.cast.join(', ')}`);
  if (title.language) lines.push(`Original language: ${title.language}`);
  if (title.countries.length) lines.push(title.countries.join(', '));
  if (title.contentRating) lines.push(`Content rating: ${title.contentRating}`);
  if (title.seriesStatus) lines.push(title.seriesStatus);
  if (title.seasonCount !== undefined) lines.push(`${title.seasonCount} seasons`);
  if (title.episodeCount !== undefined) lines.push(`${title.episodeCount} episodes`);
  if (title.score) {
    lines.push(`Score: ${title.score.value} / ${title.score.scale} — ${title.score.sourceLabel ?? new URL(title.score.sourceUrl).hostname}`);
    if (title.score.votes !== undefined) lines.push(`${title.score.votes} votes`);
    if (title.score.observedAt) lines.push(title.score.observedAt);
    lines.push(title.score.sourceUrl);
  }
  if (title.synopsis) lines.push('', title.synopsis);
  if (title.seasons.length) lines.push('', 'Supplied seasons (partial details):');
  for (const season of title.seasons) {
    const label = season.number === 0 ? 'Specials (0)' : `Season ${season.number}`;
    lines.push([label, season.title, season.firstAirDate,
      season.episodeCount === undefined ? undefined : `${season.episodeCount} episodes`].filter(Boolean).join(' · '));
    if (season.synopsis) lines.push(season.synopsis);
  }
  if (title.sourceUrl) lines.push('', title.sourceUrl);
  for (const source of title.authoring?.sources ?? []) {
    if (source.url && tvLink(source.url)) lines.push(source.label ? `${source.label}: ${source.url}` : source.url);
    else if (source.embed_ref) lines.push(source.label ?? source.embed_ref);
  }
  if (title.authoring?.observed_at) lines.push(title.authoring.observed_at);
  return lines.join('\n');
}
function tvLink(value: string): boolean {
  try { return ['http:', 'https:'].includes(new URL(value).protocol); } catch { return false; }
}
