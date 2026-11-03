import { movieContent, seriesContent, unknownMovieContent, unknownSeriesContent } from './tvTitleFixtures';

const defaultProps = { id: 'tv-movie-preview', content: movieContent,
  status: 'finished' as const, resultContext: 'chat' as const, isMobile: false, onFullscreen: () => {} };
export default defaultProps;
export const variants = {
  movie: { ...defaultProps },
  series: { ...defaultProps, id: 'tv-series-preview', content: seriesContent },
  unknown: { ...defaultProps, content: unknownMovieContent },
  unknownMovie: { ...defaultProps, content: unknownMovieContent },
  unknownSeries: { ...defaultProps, content: unknownSeriesContent },
  error: { ...defaultProps, status: 'error' as const },
  cancelled: { ...defaultProps, status: 'cancelled' as const },
  processing: { ...defaultProps, status: 'processing' as const, content: { type: 'tv_movie' } },
  mobile: { ...defaultProps, isMobile: true },
  seriesMobile: { ...defaultProps, isMobile: true, content: seriesContent },
  longTitle: { ...defaultProps, content: { ...movieContent, title: 'The Last Observatory: a very long supplied film title about a remote village and its mysterious winter skies' } },
};
