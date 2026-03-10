/**
 * Preview mock data for PDFEmbedPreview (user-uploaded PDF).
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/pdf
 *
 * Note: PDFEmbedPreview is a direct-type embed (not app-skill-use).
 * The 'finished' state without a screenshot shows a centered PDF icon.
 */

/** Default props — shows a finished PDF upload embed */
const defaultProps = {
  id: "preview-pdf-upload-1",
  filename: "Q4-2025-Annual-Report.pdf",
  status: "finished" as const,
  pageCount: 42,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Uploading state — shows spinner */
  uploading: {
    id: "preview-pdf-uploading",
    filename: "Q4-2025-Annual-Report.pdf",
    status: "uploading" as const,
    isMobile: false,
  },

  /** Processing state — OCR running */
  processing: {
    id: "preview-pdf-processing",
    filename: "architecture-whitepaper.pdf",
    status: "processing" as const,
    pageCount: 12,
    isMobile: false,
  },

  /** Error state */
  error: {
    id: "preview-pdf-error",
    filename: "corrupted-file.pdf",
    status: "error" as const,
    uploadError: "Upload failed: file may be corrupted",
    isMobile: false,
  },

  /** Single page PDF */
  singlePage: {
    id: "preview-pdf-single",
    filename: "invoice.pdf",
    status: "finished" as const,
    pageCount: 1,
    isMobile: false,
  },

  /** Mobile view */
  mobile: {
    ...defaultProps,
    id: "preview-pdf-mobile",
    isMobile: true,
  },
};
