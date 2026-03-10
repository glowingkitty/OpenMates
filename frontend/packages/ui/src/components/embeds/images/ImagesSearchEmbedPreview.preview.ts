/**
 * Preview mock data for ImagesSearchEmbedPreview.
 *
 * Parent embed for an image search. Inline thumbnails reference
 * example URLs that are proxied in production — images may not load in dev preview.
 * Access at: /dev/preview/embeds/images/ImagesSearchEmbedPreview
 */

const sampleResults = [
  {
    title: "Golden Gate Bridge at sunset",
    source: "flickr.com",
    thumbnail_url:
      "https://live.staticflickr.com/7272/7228523136_67c89cd2a0_m.jpg",
    image_url: "https://live.staticflickr.com/7272/7228523136_67c89cd2a0_b.jpg",
    source_page_url:
      "https://www.flickr.com/photos/nicholasfalletta/7228523136/",
  },
  {
    title: "Golden Gate Bridge morning fog",
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
];

/** Default props — finished image search */
const defaultProps = {
  id: "preview-images-search-1",
  query: "Golden Gate Bridge",
  provider: "Brave",
  status: "finished" as const,
  results: sampleResults,
  isMobile: false,
  onFullscreen: () => console.log("[Preview] Fullscreen clicked"),
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
