/**
 * Preview mock data for ImageEmbedFullscreen.
 *
 * Fullscreen viewer for user-uploaded image embeds.
 * Without S3 credentials and AES keys, the image cannot be decrypted in dev preview.
 * The component's loading state and UI structure are still testable.
 * Access at: /dev/preview/embeds/images/ImageEmbedFullscreen
 */

/** Default props — shows fullscreen structure without image (no S3 data in dev preview) */
const defaultProps = {
  filename: "golden-gate-sunset.jpg",
  fileSize: 2411520,
  fileType: "image/jpeg",
  isAuthenticated: true,
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** With navigation arrows */
  withNavigation: {
    ...defaultProps,
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },

  /** PNG image */
  png: {
    ...defaultProps,
    filename: "screenshot-2026-03-10.png",
    fileSize: 856320,
    fileType: "image/png",
  },
};
