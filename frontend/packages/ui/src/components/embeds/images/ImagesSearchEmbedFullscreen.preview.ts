/**
 * Preview mock data for ImagesSearchEmbedFullscreen.
 *
 * Uses the legacyResults prop (added for dev preview) to supply a direct results array
 * instead of relying on child embed store resolution (which has no data in dev preview).
 * All image URLs use Unsplash/Wikimedia which reliably proxy through preview.openmates.org.
 * Access at: /dev/preview/embeds/images/ImagesSearchEmbedFullscreen
 */

const sampleResults = [
  {
    title: "Golden Gate Bridge at dusk",
    source: "unsplash.com",
    source_page_url: "https://unsplash.com/photos/Cs99I6PYLlk",
    thumbnail_url:
      "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=300",
    image_url: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29",
  },
  {
    title: "Aerial view of Golden Gate Bridge",
    source: "wikimedia.org",
    source_page_url:
      "https://commons.wikimedia.org/wiki/File:GoldenGateBridge-001.jpg",
    thumbnail_url:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0c/GoldenGateBridge-001.jpg/300px-GoldenGateBridge-001.jpg",
    image_url:
      "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg",
  },
  {
    title: "Golden Gate Bridge towers in fog",
    source: "unsplash.com",
    source_page_url: "https://unsplash.com/photos/golden-gate-fog",
    thumbnail_url:
      "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=300",
    image_url: "https://images.unsplash.com/photo-1558618666-fcd25c85cd64",
  },
  {
    title: "Golden Gate Bridge from Baker Beach",
    source: "unsplash.com",
    source_page_url: "https://unsplash.com/photos/golden-gate-baker-beach",
    thumbnail_url:
      "https://images.unsplash.com/photo-1449034446853-66c86144b0ad?w=300",
    image_url: "https://images.unsplash.com/photo-1449034446853-66c86144b0ad",
  },
  {
    title: "Golden Gate in evening light",
    source: "unsplash.com",
    source_page_url: "https://unsplash.com/photos/golden-gate-evening",
    thumbnail_url:
      "https://images.unsplash.com/photo-1534430480872-3498386e7856?w=300",
    image_url: "https://images.unsplash.com/photo-1534430480872-3498386e7856",
  },
  {
    title: "Golden Gate Bridge under blue sky",
    source: "wikimedia.org",
    source_page_url:
      "https://commons.wikimedia.org/wiki/File:Golden_Gate_Bridge_seen_from_the_Marin_Headlands_in_March_2019.jpg",
    thumbnail_url:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/New_bridge_at_night.jpg/300px-New_bridge_at_night.jpg",
    image_url:
      "https://upload.wikimedia.org/wikipedia/commons/4/47/New_bridge_at_night.jpg",
  },
];

/** Default props — finished image search with 6 results */
const defaultProps = {
  query: "Golden Gate Bridge",
  provider: "Brave",
  status: "finished" as const,
  results: sampleResults,
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Processing state — no results yet */
  processing: {
    ...defaultProps,
    status: "processing" as const,
    results: [],
  },

  /** With sibling embed navigation */
  withNavigation: {
    ...defaultProps,
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },
};
