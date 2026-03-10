/**
 * Preview mock data for ImageEmbedPreview.
 *
 * User-uploaded image embed. In dev preview mode, the image will not display
 * because there is no S3 data to decrypt. The component UI states are still testable.
 * Access at: /dev/preview/embeds/images/ImageEmbedPreview
 */

/** Default props — finished upload state (no image visible without S3 data) */
const defaultProps = {
  id: "preview-image-embed-1",
  filename: "golden-gate-sunset.jpg",
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Uploading state */
  uploading: {
    ...defaultProps,
    id: "preview-image-embed-uploading",
    status: "uploading" as const,
  },

  /** Upload error */
  error: {
    ...defaultProps,
    id: "preview-image-embed-error",
    status: "error" as const,
    uploadError: "Upload failed: file too large (max 10 MB)",
  },

  /** Long filename */
  longFilename: {
    ...defaultProps,
    id: "preview-image-embed-long-name",
    filename: "my-very-long-vacation-photo-at-the-golden-gate-bridge-2026.jpg",
  },

  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-image-embed-mobile",
    isMobile: true,
  },
};
