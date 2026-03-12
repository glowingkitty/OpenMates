/**
 * Preview mock data for PdfSearchEmbedPreview (pdf/search skill result).
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/pdf
 */

/** Default props — shows a finished pdf.search embed with matches found */
const defaultProps = {
  id: "preview-pdf-search-1",
  filename: "Q4-2025-Annual-Report.pdf",
  query: "authentication",
  totalMatches: 7,
  truncated: false,
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Processing state — search in progress */
  processing: {
    id: "preview-pdf-search-processing",
    filename: "architecture-whitepaper.pdf",
    query: "microservices",
    status: "processing" as const,
    isMobile: false,
  },

  /** No matches found */
  noResults: {
    id: "preview-pdf-search-no-results",
    filename: "Q4-2025-Annual-Report.pdf",
    query: "blockchain",
    totalMatches: 0,
    status: "finished" as const,
    isMobile: false,
  },

  /** Truncated results (>50 matches) */
  truncated: {
    id: "preview-pdf-search-truncated",
    filename: "system-architecture.pdf",
    query: "API",
    totalMatches: 83,
    truncated: true,
    status: "finished" as const,
    isMobile: false,
  },

  /** Error state */
  error: {
    id: "preview-pdf-search-error",
    filename: "large-document.pdf",
    query: "revenue",
    status: "error" as const,
    error: "Search index unavailable for this document",
    isMobile: false,
  },

  /** Mobile view */
  mobile: {
    ...defaultProps,
    id: "preview-pdf-search-mobile",
    isMobile: true,
  },
};
