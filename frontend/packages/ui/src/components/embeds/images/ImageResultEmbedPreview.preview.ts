/**
 * Preview mock data for ImageResultEmbedPreview.
 *
 * Single image result card (child embed inside ImagesSearchEmbedFullscreen).
 * Uses Unsplash/Wikimedia URLs which reliably proxy through preview.openmates.org.
 * Note: thumbnailUrl must already be proxied by the caller (AppSkillUseRenderer).
 * In this preview file we pass the raw URL; the component itself calls proxyImage internally.
 * Access at: /dev/preview/embeds/images/ImageResultEmbedPreview
 */

/** Default props — single image result with thumbnail */
const defaultProps = {
  id: "preview-image-result-1",
  title: "Golden Gate Bridge at dusk",
  sourceDomain: "unsplash.com",
  thumbnailUrl:
    "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200",
  imageUrl: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29",
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Image from Wikimedia */
  wikimedia: {
    ...defaultProps,
    id: "preview-image-result-wikimedia",
    title: "Aerial view of Golden Gate Bridge",
    sourceDomain: "wikimedia.org",
    thumbnailUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0c/GoldenGateBridge-001.jpg/200px-GoldenGateBridge-001.jpg",
    imageUrl:
      "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg",
  },

  /** Processing state */
  processing: {
    ...defaultProps,
    id: "preview-image-result-processing",
    status: "processing" as const,
    thumbnailUrl: undefined,
    imageUrl: undefined,
  },

  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-image-result-mobile",
    isMobile: true,
  },
};
