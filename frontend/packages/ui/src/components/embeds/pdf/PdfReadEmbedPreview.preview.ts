/**
 * Preview mock data for PdfReadEmbedPreview (pdf/read skill result).
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/pdf
 */

/** Default props — shows a finished pdf.read embed with extracted text */
const defaultProps = {
  id: "preview-pdf-read-1",
  filename: "Q4-2025-Annual-Report.pdf",
  pagesReturned: [1, 2, 3],
  pagesSkipped: [],
  pageCount: 42,
  textContent:
    "## Executive Summary\n\nAnnual revenue increased 23% year-over-year, reaching €48.2M in Q4 2025. " +
    "Growth was driven by the Enterprise tier (up 41%), offset by a 6% decline in the legacy Basic tier. " +
    "Operating margin improved to 18.4% from 14.1% in Q4 2024.\n\n" +
    "## Key Metrics\n\n" +
    "- ARR: €192.8M (+23% YoY)\n" +
    "- NRR: 118%\n" +
    "- Gross margin: 76.3%\n" +
    "- Headcount: 312 (+44 YoY)",
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Processing state — reading in progress */
  processing: {
    id: "preview-pdf-read-processing",
    filename: "architecture-whitepaper.pdf",
    status: "processing" as const,
    isMobile: false,
  },

  /** Error state */
  error: {
    id: "preview-pdf-read-error",
    filename: "corrupted.pdf",
    status: "error" as const,
    error: "Failed to extract text from page 5",
    isMobile: false,
  },

  /** Single page read */
  singlePage: {
    id: "preview-pdf-read-single",
    filename: "invoice-2025-Q4.pdf",
    pagesReturned: [1],
    pageCount: 1,
    textContent:
      "INVOICE #2025-Q4-0042\n\nBill To: OpenMates GmbH\nDate: December 31, 2025\n\nDescription: Infrastructure Services Q4\nAmount: €12,480.00\n\nTotal Due: €12,480.00",
    status: "finished" as const,
    isMobile: false,
  },

  /** Mobile view */
  mobile: {
    ...defaultProps,
    id: "preview-pdf-read-mobile",
    isMobile: true,
  },
};
