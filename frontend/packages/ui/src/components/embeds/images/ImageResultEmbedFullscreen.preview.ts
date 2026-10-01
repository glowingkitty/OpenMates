/**
 * Preview mock data for ImageResultEmbedFullscreen.
 *
 * Single image result fullscreen (drill-down from ImagesSearchEmbedFullscreen).
 * The fullscreen component proxies external image bytes while retaining the
 * original image and source links for explicit user navigation.
 * Access at: /dev/preview/embeds/images/ImageResultEmbedFullscreen
 */

/** Default props — single image result fullscreen */
const defaultProps = {
  title: "Golden Gate Bridge at dusk",
  source_domain: "unsplash.com",
  source_page_url: "https://unsplash.com/photos/Cs99I6PYLlk",
  image_url: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29",
  thumbnail_url:
    "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200",
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
  failedImage: {
    ...defaultProps,
    image_url: 'data:image/png;base64,invalid-image',
    thumbnail_url: 'data:image/png;base64,invalid-thumbnail',
  },
};
