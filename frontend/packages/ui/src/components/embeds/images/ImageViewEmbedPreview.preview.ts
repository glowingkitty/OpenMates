/**
 * Preview mock data for ImageViewEmbedPreview.
 *
 * AI skill result when the images/view skill runs on a user-uploaded image.
 * Synthetic encryption metadata exercises the production media reader in CI.
 * Access at: /dev/preview/embeds/images/ImageViewEmbedPreview
 */

const previewFile = { s3_key: 'e2e/image-view/v2.png', width: 64, height: 64, size_bytes: 0, format: 'png', encryption: 'aes-gcm-nonce-prefixed-v1' };

/** Default props — finished view skill result using nonce-prefixed media. */
const defaultProps = {
  id: "preview-image-view-1",
  filename: "golden-gate-sunset.jpg",
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
  s3BaseUrl: 'https://fixture.invalid',
  s3Files: { preview: previewFile },
  aesKey: 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=',
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  legacyEncrypted: {
    ...defaultProps,
    s3Files: { preview: { ...previewFile, s3_key: 'e2e/image-view/legacy.png', encryption: undefined } },
    aesNonce: 'AAECAwQFBgcICQoL',
  },
  variantNonce: {
    ...defaultProps,
    s3Files: { preview: { ...previewFile, s3_key: 'e2e/image-view/variant-nonce.png', encryption: undefined, aes_nonce: 'AAECAwQFBgcICQoL' } },
  },
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
