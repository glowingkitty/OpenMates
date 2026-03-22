/**
 * Preview mock data for PdfSearchEmbedFullscreen (pdf/search skill fullscreen view).
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/pdf
 */

const sampleMatches = [
  {
    page_num: 3,
    match_text: "authentication",
    context:
      "The microservices architecture requires robust authentication middleware at each service boundary. " +
      "We use JWT-based authentication with a 15-minute expiry window.",
    char_offset: 42,
  },
  {
    page_num: 7,
    match_text: "authentication",
    context:
      "OAuth 2.0 authentication flows are handled by the dedicated auth service, " +
      "which issues short-lived access tokens and long-lived refresh tokens.",
    char_offset: 8,
  },
  {
    page_num: 12,
    match_text: "authentication",
    context:
      "All API endpoints require authentication via the Authorization header. " +
      "Unauthenticated requests receive a 401 Unauthorized response.",
    char_offset: 27,
  },
  {
    page_num: 15,
    match_text: "authentication",
    context:
      "Multi-factor authentication (MFA) is enforced for all admin accounts " +
      "and strongly recommended for regular users.",
    char_offset: 18,
  },
];

/** Default props — shows a fullscreen search results view */
const defaultProps = {
  filename: "architecture-whitepaper.pdf",
  query: "authentication",
  totalMatches: 7,
  truncated: false,
  matches: sampleMatches,
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

  /** No matches */
  noMatches: {
    filename: "Q4-2025-Annual-Report.pdf",
    query: "blockchain",
    totalMatches: 0,
    matches: [],
    onClose: () => {},
  },

  /** Truncated results */
  truncated: {
    filename: "system-architecture.pdf",
    query: "API",
    totalMatches: 83,
    truncated: true,
    matches: sampleMatches,
    onClose: () => {},
  },
};
