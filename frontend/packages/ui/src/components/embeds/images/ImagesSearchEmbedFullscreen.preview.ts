/**
 * Preview mock data for ImagesSearchEmbedFullscreen.
 *
 * Fullscreen image search results grid. Images reference external URLs
 * which are proxied in production — may not load in dev preview.
 * Access at: /dev/preview/embeds/images/ImagesSearchEmbedFullscreen
 */

/** Default props — finished image search with 3 results */
const defaultProps = {
  query: "Golden Gate Bridge",
  provider: "Brave",
  status: "finished" as const,
  onClose: () => console.log("[Preview] Close clicked"),
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** With navigation */
  withNavigation: {
    ...defaultProps,
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => console.log("[Preview] Navigate previous"),
    onNavigateNext: () => console.log("[Preview] Navigate next"),
  },
};
