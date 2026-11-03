import { describe, expect, it } from 'vitest';
import { readTVTitle, tvFollowupContext, tvSourceUrl } from './tvTitleContent';
import { renderTVTitle } from './tvEmbedText';
import { movieContent, seriesContent, unknownMovieContent, unknownSeriesContent } from './tvTitleFixtures';

describe('TV supplied result presentation', () => {
  // contract-test: supporting surface=gui.web assertions=tv-titles.presentation.posters-and-details,tv-titles.lifecycle.groups-and-actions
  it('retains source score, scale, credits and supplied dates without personal ratings', () => {
    const movie = readTVTitle({ ...movieContent, personal_rating: 1, watchlist: true });
    expect(movie.score).toEqual({ value: 8.2, scale: 10, sourceUrl: 'https://example.org/movie-score',
      sourceLabel: 'Example source', votes: 1200, observedAt: '2026-10-26T10:00:00Z' });
    expect(movie.directors).toEqual(['Alex Example']);
    expect(movie.cast).toEqual(['Sam Example', 'Robin Sample']);
    expect(movie.releaseDate).toBe('2025-09-12');
    expect(movie.year).toBe(2025);
    expect(movie).not.toHaveProperty('watchlist');
    expect(movie).not.toHaveProperty('personal_rating');
  });

  // contract-test: supporting surface=gui.web assertions=tv-titles.presentation.posters-and-details,tv-titles.series.supplied-seasons
  it('leaves unknown facts absent, including runtime, totals, year and score', () => {
    for (const content of [unknownMovieContent, unknownSeriesContent]) {
      const title = readTVTitle(content);
      for (const field of ['year', 'runtimeMinutes', 'score', 'seasonCount', 'episodeCount', 'posterUrl'])
        expect(title[field as keyof typeof title]).toBeUndefined();
      expect(title.seasons).toEqual([]);
    }
    expect(readTVTitle({ type: 'tv_movie', release_date: '2025-09-12' }).year).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=tv-titles.series.supplied-seasons
  it('preserves partial season rows and specials zero without inventing missing rows', () => {
    const series = readTVTitle(seriesContent);
    expect(series.seasonCount).toBe(4);
    expect(series.episodeCount).toBe(30);
    expect(series.seasons.map(season => season.number)).toEqual([0, 1]);
    expect(series.seasons.map(season => season.episodeCount)).toEqual([2, 8]);
    const partial = readTVTitle({ type: 'tv_series', seasons: [{ season_number: 2 }, { season_number: 0, episode_count: 0 }] });
    expect(partial.seasons.map(season => season.number)).toEqual([2, 0]);
    expect(partial.seasons[0].episodeCount).toBeUndefined();
    expect(partial.seasons[1].episodeCount).toBe(0);
    expect(partial.seasonCount).toBeUndefined();
    expect(partial.episodeCount).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=tv-titles.series.supplied-seasons,tv-titles.presentation.posters-and-details
  it('does not display malformed dates, numbers, duplicate rows or unsupported source scores', () => {
    expect(readTVTitle({ runtime_minutes: -1, year: '2025', release_date: '2025-02-30' })).toMatchObject({
      runtimeMinutes: undefined, year: undefined, releaseDate: undefined,
    });
    expect(readTVTitle({ seasons: [{ season_number: 1 }, { season_number: 1 }, { season_number: -1 }] }).seasons).toEqual([]);
    for (const score of [{ value: 8.2, scale: 10 }, { value: 11, scale: 10, source_url: 'https://example.org' },
      { value: 1, scale: 0, source_url: 'https://example.org' }, { value: NaN, scale: 10, source_url: 'https://example.org' },
      { value: 1, scale: 10, source_url: 'javascript:alert(1)' }])
      expect(readTVTitle({ score }).score).toBeUndefined();
    expect(readTVTitle({ score: { value: 0, scale: 100, source_url: 'https://example.org', votes: 0 } }).score?.value).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=tv-titles.presentation.posters-and-details,authored-results.media.safe-and-attributed
  it('accepts only supplied safe posters or presentation-owned decrypted URLs', () => {
    expect(readTVTitle({ poster_url: 'https://example.org/poster.jpg' }).posterUrl).toBe('https://example.org/poster.jpg');
    expect(readTVTitle({ poster_url: '/store-examples/generate-1.webp' }).posterUrl).toBe('/store-examples/generate-1.webp');
    for (const poster_url of ['//other.example/poster.jpg', 'javascript:bad', 'data:image/svg+xml,anything', 'blob:https://app.example/owned'])
      expect(readTVTitle({ poster_url }).posterUrl).toBeUndefined();
    expect(readTVTitle({ poster_url: 'blob:https://app.example/owned' }, { allowDecryptedMedia: true }).posterUrl).toBe('blob:https://app.example/owned');
    expect(tvSourceUrl('https://private@example.org/title')).toBeUndefined();
    expect(tvSourceUrl('javascript:alert(1)')).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=tv-titles.lifecycle.groups-and-actions
  it('passes only visible title facts to the follow-up composer', () => {
    const raw = { ...movieContent, aes_key: 'private-key', aes_nonce: 'private-nonce',
      authored_media: [{ aes_key: 'nested-key', s3_base_url: 'private-location' }], watched: true };
    const context = tvFollowupContext(readTVTitle(raw));
    const serialized = JSON.stringify(context);
    for (const secret of ['private-key', 'private-nonce', 'nested-key', 'private-location', 'aes_key', 'authored_media', 'watched'])
      expect(serialized).not.toContain(secret);
    expect(context).toMatchObject({ title: movieContent.title, year: movieContent.year });
  });

  // contract-test: supporting surface=gui.web assertions=tv-titles.authoring.relevant-and-flexible,tv-titles.lifecycle.groups-and-actions
  it('preserves the canonical authoring kind over conflicting legacy type hints', () => {
    expect(readTVTitle({ ...movieContent, type: 'tv_series' }).kind).toBe('movie');
    expect(readTVTitle(seriesContent).kind).toBe('series');
  });

  // contract-test: supporting surface=gui.web assertions=tv-titles.presentation.posters-and-details,tv-titles.series.supplied-seasons
  it('exports sourced scores and supplied season rows without implying a full guide', () => {
    const movie = renderTVTitle(movieContent);
    expect(movie).toContain('[Draft]');
    expect(movie).toContain('8.2 / 10');
    expect(movie).toContain('https://example.org/movie-score');
    expect(movie).toContain('Alex Example');
    const series = renderTVTitle(seriesContent);
    expect(series).toContain('4 seasons');
    expect(series).toContain('Specials (0)');
    expect(series).toContain('Supplied seasons (partial details)');
    expect(series).not.toContain('Season 2');
    expect(series).not.toContain('watchlist');
  });
});
