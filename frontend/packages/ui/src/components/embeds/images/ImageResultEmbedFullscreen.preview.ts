/**
 * Preview mock data for ImageResultEmbedFullscreen.
 *
 * Single image result fullscreen (drill-down from ImagesSearchEmbedFullscreen).
 * Uses Unsplash/Wikimedia which load without needing the image proxy.
 * Note: ImageResultEmbedFullscreen renders imageUrl directly (no re-proxying).
 * Access at: /dev/preview/embeds/images/ImageResultEmbedFullscreen
 */

/** Default props — single image result fullscreen */
const defaultProps = {
  title: "Golden Gate Bridge at dusk",
  sourceDomain: "unsplash.com",
  sourcePageUrl: "https://unsplash.com/photos/Cs99I6PYLlk",
  imageUrl: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29",
  thumbnailUrl:
    "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=400",
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** With sibling navigation */
  withNavigation: {
    ...defaultProps,
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },
};
