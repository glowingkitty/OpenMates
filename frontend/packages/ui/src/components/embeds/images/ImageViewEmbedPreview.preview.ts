/**
 * Preview mock data for ImageViewEmbedPreview.
 *
 * AI skill result when the images/view skill runs on a user-uploaded image.
 * The decrypted image cannot be shown in dev preview (no S3/AES data available).
 * Access at: /dev/preview/embeds/images/ImageViewEmbedPreview
 */

/** Default props — finished view skill result */
const defaultProps = {
  id: "preview-image-view-1",
  filename: "golden-gate-sunset.jpg",
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => console.log("[Preview] Fullscreen clicked"),
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Processing state */
  processing: {
    ...defaultProps,
    id: "preview-image-view-processing",
    status: "processing" as const,
  },

  /** Error state */
  error: {
    ...defaultProps,
    id: "preview-image-view-error",
    status: "error" as const,
    error: "Could not process the image.",
  },

  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-image-view-mobile",
    isMobile: true,
  },
};
