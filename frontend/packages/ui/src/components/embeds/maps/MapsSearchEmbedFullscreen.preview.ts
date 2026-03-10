/**
 * Preview mock data for MapsSearchEmbedFullscreen.
 *
 * Note: The Leaflet map requires network access to load tiles from OpenStreetMap.
 * In preview mode the map may not render, but the component layout/controls can be tested.
 * Access at: /dev/preview/embeds/maps/MapsSearchEmbedFullscreen
 */

// Results use PlaceSearchResult format: location is nested as { latitude, longitude }
// to match transformLegacyResults() in MapsSearchEmbedFullscreen.svelte which reads
// r.location.latitude and r.location.longitude.
const sampleResults = [
  {
    embed_id: "preview-maps-place-1",
    displayName: "Man vs. Machine Coffee Roasters",
    formattedAddress: "Müllerstraße 23, 80469 Munich",
    rating: 4.7,
    userRatingCount: 1832,
    location: { latitude: 48.1321, longitude: 11.5718 },
  },
  {
    embed_id: "preview-maps-place-2",
    displayName: "Lost Weekend",
    formattedAddress: "Schellingstraße 3, 80799 Munich",
    rating: 4.5,
    userRatingCount: 2456,
    location: { latitude: 48.1523, longitude: 11.5784 },
  },
  {
    embed_id: "preview-maps-place-3",
    displayName: "Café Frischhut",
    formattedAddress: "Prälat-Zistl-Straße 8, 80331 Munich",
    rating: 4.6,
    userRatingCount: 3210,
    location: { latitude: 48.1354, longitude: 11.5762 },
  },
];

/** Default props — shows a fullscreen maps search results view with Leaflet map */
const defaultProps = {
  query: "coffee shops near Marienplatz Munich",
  provider: "Google",
  results: sampleResults,
  onClose: () => console.log("[Preview] Close clicked"),
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
    onNavigatePrevious: () => console.log("[Preview] Navigate previous"),
    onNavigateNext: () => console.log("[Preview] Navigate next"),
  },

  /** Empty results */
  noResults: {
    query: "unicorn cafes in Antarctica",
    provider: "Google",
    results: [],
    onClose: () => console.log("[Preview] Close clicked"),
  },
};
