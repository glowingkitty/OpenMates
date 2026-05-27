/**
 * Preview mock data for WikipediaEmbedPreview.
 * Access at: /dev/preview/embeds/wiki/WikipediaEmbedPreview
 */

const defaultProps = {
  id: 'preview-wiki-murmuration',
  title: 'Murmuration',
  wikiTitle: 'Murmuration',
  description: 'Coordinated flock movement that creates living patterns in the sky.',
  thumbnailUrl: 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/0c/Brandenburger_Tor_abends.jpg/640px-Brandenburger_Tor_abends.jpg',
  wikidataId: null,
  status: 'finished' as const,
  isMobile: false,
  onFullscreen: () => console.log('[Preview] Wikipedia fullscreen clicked'),
};

export default defaultProps;

export const variants = {
  processing: {
    ...defaultProps,
    id: 'preview-wiki-processing',
    status: 'processing' as const,
  },
  error: {
    ...defaultProps,
    id: 'preview-wiki-error',
    status: 'error' as const,
  },
  cancelled: {
    ...defaultProps,
    id: 'preview-wiki-cancelled',
    status: 'cancelled' as const,
  },
  mobile: {
    ...defaultProps,
    id: 'preview-wiki-mobile',
    isMobile: true,
  },
  noImage: {
    ...defaultProps,
    id: 'preview-wiki-no-image',
    thumbnailUrl: null,
  },
};
