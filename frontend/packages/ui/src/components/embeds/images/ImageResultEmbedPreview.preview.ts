/**
 * Preview mock data for ImageResultEmbedPreview.
 *
 * Single image result card (child embed inside ImagesSearchEmbedFullscreen).
 * Uses Unsplash URLs which reliably proxy through preview.openmates.org.
 * Note: thumbnailUrl must already be proxied by the caller (AppSkillUseRenderer).
 * In this preview file we pass the raw URL; the component itself calls proxyImage internally.
 *
 * Wikimedia URLs are intentionally NOT used here: upload.wikimedia.org sets the
 * WMF-Uniq cookie which contaminates the legal cookie inventory run via the
 * embed-showcase Playwright suite. See docs/architecture/compliance/cookies.yml.
 *
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
  /** Alternate image from Unsplash */
  alternate: {
    ...defaultProps,
    id: "preview-image-result-alternate",
    title: "Golden Gate Bridge from Baker Beach",
    sourceDomain: "unsplash.com",
    thumbnailUrl:
      "https://images.unsplash.com/photo-1449034446853-66c86144b0ad?w=200",
    imageUrl: "https://images.unsplash.com/photo-1449034446853-66c86144b0ad",
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
