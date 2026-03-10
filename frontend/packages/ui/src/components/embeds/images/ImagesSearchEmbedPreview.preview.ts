/**
 * Preview mock data for ImagesSearchEmbedPreview.
 *
 * All thumbnail URLs use Unsplash/Wikimedia which reliably serve through the image proxy.
 * Flickr URLs were removed because they return 403 when proxied.
 * Access at: /dev/preview/embeds/images/ImagesSearchEmbedPreview
 */

const sampleResults = [
  {
    title: "Golden Gate Bridge at dusk",
    source: "unsplash.com",
    thumbnail_url:
      "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200",
    image_url: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29",
    source_page_url: "https://unsplash.com/photos/Cs99I6PYLlk",
  },
  {
    title: "Aerial view of Golden Gate",
    source: "wikimedia.org",
    thumbnail_url:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0c/GoldenGateBridge-001.jpg/200px-GoldenGateBridge-001.jpg",
    image_url:
      "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg",
    source_page_url:
      "https://commons.wikimedia.org/wiki/File:GoldenGateBridge-001.jpg",
  },
  {
    title: "Golden Gate Bridge towers in fog",
    source: "unsplash.com",
    thumbnail_url:
      "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=200",
    image_url: "https://images.unsplash.com/photo-1558618666-fcd25c85cd64",
    source_page_url: "https://unsplash.com/photos/golden-gate-bridge",
  },
];

/** Default props — finished image search */
const defaultProps = {
  id: "preview-images-search-1",
  query: "Golden Gate Bridge",
  provider: "Brave",
  status: "finished" as const,
  results: sampleResults,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Processing state */
  processing: {
    ...defaultProps,
    id: "preview-images-search-processing",
    status: "processing" as const,
    results: [],
  },

  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-images-search-mobile",
    isMobile: true,
  },
};
