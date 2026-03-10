/**
 * Preview mock data for ImageResultEmbedPreview.
 *
 * Single image result card (child embed inside ImagesSearchEmbedFullscreen).
 * Images reference external URLs — may not load in dev preview without proxying.
 * Access at: /dev/preview/embeds/images/ImageResultEmbedPreview
 */

/** Default props — single image result with thumbnail */
const defaultProps = {
  id: "preview-image-result-1",
  title: "Golden Gate Bridge at sunset",
  sourceDomain: "flickr.com",
  thumbnailUrl:
    "https://live.staticflickr.com/7272/7228523136_67c89cd2a0_m.jpg",
  imageUrl: "https://live.staticflickr.com/7272/7228523136_67c89cd2a0_b.jpg",
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => console.log("[Preview] Fullscreen clicked"),
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Image from Unsplash */
  unsplash: {
    ...defaultProps,
    id: "preview-image-result-unsplash",
    title: "Golden Gate Bridge morning fog",
    sourceDomain: "unsplash.com",
    thumbnailUrl:
      "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200",
    imageUrl: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29",
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
