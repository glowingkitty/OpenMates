/**
 * Preview mock data for PDFEmbedFullscreen (user-uploaded PDF viewer).
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/pdf
 *
 * PDFEmbedFullscreen normally loads encrypted screenshots from S3 via embedId.
 * The default fixture has no embedId, so it renders the fallback UI. The guest
 * fixture uses the reviewed static PDF and its generated page image.
 */

/** Default props — shows the fallback UI (no screenshots available) */
const defaultProps = {
  data: {
    decodedContent: {
      filename: "Q4-2025-Annual-Report.pdf",
      page_count: 42,
    },
  },
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Native browser viewer shows the actual reviewed PDF pages. */
  guest: {
    ...defaultProps,
    data: {
      decodedContent: {
        filename: "community-garden-budget.pdf",
        page_count: 1,
        previewPdfUrl: "/store-examples/community-garden-budget.pdf",
      },
    },
  },

  /** An untrusted URL cannot be embedded. */
  untrustedUrl: {
    ...defaultProps,
    data: {
      decodedContent: {
        filename: "private.pdf",
        previewPdfUrl: "https://example.com/private.pdf",
      },
    },
  },

  /** Encrypted upload credentials retain the private screenshot flow. */
  encrypted: {
    ...defaultProps,
    data: {
      decodedContent: {
        filename: "private.pdf",
        previewPdfUrl: "/store-examples/community-garden-budget.pdf",
        screenshot_s3_keys: { "1": "private/page-one.png" },
        aes_key: "private-key",
        aes_nonce: "",
      },
    },
  },

  /** With navigation arrows */
  withNavigation: {
    ...defaultProps,
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },

  /** Single page */
  singlePage: {
    ...defaultProps,
    data: {
      decodedContent: {
        filename: "invoice-2025-Q4.pdf",
        page_count: 1,
      },
    },
  },
};
