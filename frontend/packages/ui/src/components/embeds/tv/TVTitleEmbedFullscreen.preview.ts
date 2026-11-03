import { movieContent, seriesContent, unknownMovieContent, unknownSeriesContent } from './tvTitleFixtures';

const defaultProps = { embedId: 'tv-movie-fullscreen', data: { decodedContent: movieContent }, onClose: () => {} };
export default defaultProps;
export const variants = {
  movie: { ...defaultProps },
  series: { ...defaultProps, embedId: 'tv-series-fullscreen', data: { decodedContent: seriesContent } },
  unknown: { ...defaultProps, data: { decodedContent: unknownMovieContent } },
  unknownMovie: { ...defaultProps, data: { decodedContent: unknownMovieContent } },
  unknownSeries: { ...defaultProps, data: { decodedContent: unknownSeriesContent } },
  brokenPoster: { ...defaultProps, data: { decodedContent: { ...movieContent, poster_url: '/missing-tv-poster.jpg' } } },
  processing: { ...defaultProps, data: { decodedContent: { type: 'tv_movie', status: 'processing' } } },
  cancelled: { ...defaultProps, data: { decodedContent: { ...movieContent, status: 'cancelled' } } },
  error: { ...defaultProps, data: { decodedContent: { ...movieContent, status: 'error' } } },
  mobile: { ...defaultProps },
  seriesMobile: { ...defaultProps, data: { decodedContent: seriesContent } },
};
