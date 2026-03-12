/**
 * Preview mock data for PdfReadEmbedFullscreen (pdf/read skill fullscreen view).
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/pdf
 */

const sampleTextContent =
  "## Executive Summary\n\n" +
  "Annual revenue increased 23% year-over-year, reaching €48.2M in Q4 2025. " +
  "Growth was driven by the Enterprise tier (up 41%), offset by a 6% decline in the legacy Basic tier. " +
  "Operating margin improved to 18.4% from 14.1% in Q4 2024.\n\n" +
  "## Key Metrics\n\n" +
  "- ARR: €192.8M (+23% YoY)\n" +
  "- NRR: 118%\n" +
  "- Gross margin: 76.3%\n" +
  "- Headcount: 312 (+44 YoY)\n\n" +
  "## Revenue Breakdown\n\n" +
  "Enterprise tier accounted for 68% of total revenue (up from 55% in Q4 2024). " +
  "The Business tier contributed 24%, with the Basic tier at 8%.\n\n" +
  "## Outlook\n\n" +
  "For FY 2026, we project ARR of €240-250M, driven by continued Enterprise expansion " +
  "and three new product launches in H1.";

/** Default props — shows a fullscreen text content view */
const defaultProps = {
  filename: "Q4-2025-Annual-Report.pdf",
  pagesReturned: [1, 2, 3],
  pagesSkipped: [],
  textContent: sampleTextContent,
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

  /** Single page read */
  singlePage: {
    filename: "invoice-2025-Q4.pdf",
    pagesReturned: [1],
    textContent:
      "INVOICE #2025-Q4-0042\n\nBill To: OpenMates GmbH\nDate: December 31, 2025\n\nDescription: Infrastructure Services Q4\nAmount: €12,480.00\n\nTotal Due: €12,480.00",
    onClose: () => {},
  },
};
