/**
 * Preview mock data for ImageResultEmbedFullscreen.
 *
 * Single image result fullscreen (drill-down from ImagesSearchEmbedFullscreen).
 * Images reference external URLs — may not load in dev preview without proxying.
 * Access at: /dev/preview/embeds/images/ImageResultEmbedFullscreen
 */

/** Default props — single image result fullscreen */
const defaultProps = {
  title: "Golden Gate Bridge at sunset",
  sourceDomain: "flickr.com",
  sourcePageUrl: "https://www.flickr.com/photos/nicholasfalletta/7228523136/",
  imageUrl: "https://live.staticflickr.com/7272/7228523136_67c89cd2a0_b.jpg",
  thumbnailUrl:
    "https://live.staticflickr.com/7272/7228523136_67c89cd2a0_m.jpg",
  onClose: () => console.log("[Preview] Close clicked"),
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
    onNavigatePrevious: () => console.log("[Preview] Navigate previous"),
    onNavigateNext: () => console.log("[Preview] Navigate next"),
  },
};
