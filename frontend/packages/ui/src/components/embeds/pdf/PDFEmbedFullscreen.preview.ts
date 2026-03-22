/**
 * Preview mock data for PDFEmbedFullscreen (user-uploaded PDF viewer).
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/pdf
 *
 * Note: PDFEmbedFullscreen normally loads encrypted screenshots from S3 via embedId.
 * In the preview context, no embedId is provided so it renders the fallback UI
 * (filename + page count + hint to use AI to view the PDF).
 */

/** Default props — shows the fallback UI (no screenshots available) */
const defaultProps = {
  filename: "Q4-2025-Annual-Report.pdf",
  pageCount: 42,
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

  /** Single page */
  singlePage: {
    filename: "invoice-2025-Q4.pdf",
    pageCount: 1,
    onClose: () => {},
  },
};
