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

const MEDIA_TEST_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=";
const MEDIA_TEST_NONCE = "AAECAwQFBgcICQoL";
const mediaFile = {
  width: 64,
  height: 64,
  size_bytes: 0,
  format: "png",
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Frozen legacy external-nonce reader contract for deployed E2E coverage. */
  legacyEncrypted: {
    ...defaultProps,
    id: "preview-image-embed-legacy-encrypted",
    filename: "legacy-encrypted.png",
    s3BaseUrl: "https://fixture.invalid",
    s3Files: {
      preview: {
        ...mediaFile,
        s3_key: "e2e/media-encryption/legacy.png",
      },
    },
    aesKey: MEDIA_TEST_KEY,
    aesNonce: MEDIA_TEST_NONCE,
  },

  /** Explicit nonce-prefixed v2 reader contract for deployed E2E coverage. */
  v2Encrypted: {
    ...defaultProps,
    id: "preview-image-embed-v2-encrypted",
    filename: "v2-encrypted.png",
    s3BaseUrl: "https://fixture.invalid",
    s3Files: {
      preview: {
        ...mediaFile,
        s3_key: "e2e/media-encryption/v2.png",
        encryption: "aes-gcm-nonce-prefixed-v1",
      },
    },
    aesKey: MEDIA_TEST_KEY,
  },

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
