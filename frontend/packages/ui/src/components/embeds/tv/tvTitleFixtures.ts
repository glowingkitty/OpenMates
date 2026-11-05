/** Synthetic supplied facts for account-free TV component previews. */
export const movieContent = {
  type: 'tv_movie', title: 'The Last Observatory', status: 'finished',
  synopsis: 'An astronomer and a village mechanic restore a remote observatory before its final winter.\nA fictional film concept supplied for this component preview.',
  year: 2025, release_date: '2025-09-12', runtime_minutes: 112,
  genres: ['Drama', 'Science fiction'], directors: ['Alex Example'], cast: ['Sam Example', 'Robin Sample'],
  original_language: 'en', country_codes: ['GB', 'IE'], content_rating: '12A',
  poster_url: '/store-examples/generate-1.webp', source_url: 'https://example.org/movie',
  score: { value: 8.2, scale: 10, source_url: 'https://example.org/movie-score', source_label: 'Example source', votes: 1200, observed_at: '2026-10-26T10:00:00Z' },
  authoring: { schema_version: 1 as const, kind: 'tv.movie', origin: 'draft' as const,
    sources: [{ url: 'https://example.org/movie', label: 'Supplied example catalogue' }], observed_at: '2026-10-26T10:00:00Z' },
};
export const seriesContent = {
  type: 'tv_series', title: 'Harbour Signals', status: 'finished',
  synopsis: 'Neighbours in a coastal town solve the mystery of a silent radio station. A fictional series supplied for this preview.',
  start_year: 2023, end_year: 2026, first_air_date: '2023-03-01', last_air_date: '2026-10-01',
  episode_runtime_minutes: 25, genres: ['Mystery', 'Comedy'], creators: ['Jordan Example'],
  cast: ['Taylor Example', 'Casey Sample'], original_language: 'en', content_rating: 'TV-14', series_status: 'Ended',
  season_count: 4, episode_count: 30, poster_url: '/store-examples/generate-1.webp', source_url: 'https://example.org/series',
  seasons: [
    { season_number: 0, title: 'Winter special', episode_count: 2 },
    { season_number: 1, title: 'The first signal', first_air_date: '2023-03-01', episode_count: 8,
      synopsis: 'The first supplied season introduces the town.', poster_url: '/store-examples/generate-1.webp' },
  ],
  authoring: { schema_version: 1 as const, kind: 'tv.series', origin: 'draft' as const,
    sources: [{ url: 'https://example.org/series', label: 'Supplied example catalogue' }] },
};
export const unknownMovieContent = { type: 'tv_movie', title: 'A supplied movie title',
  authoring: { schema_version: 1 as const, kind: 'tv.movie', origin: 'user_provided' as const, sources: [] } };
export const unknownSeriesContent = { type: 'tv_series', title: 'A supplied series title', synopsis: 'Only this synopsis was supplied.',
  authoring: { schema_version: 1 as const, kind: 'tv.series', origin: 'user_provided' as const, sources: [] } };
