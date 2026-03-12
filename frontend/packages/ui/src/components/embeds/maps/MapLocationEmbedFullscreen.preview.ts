/**
 * Preview mock data for MapLocationEmbedFullscreen.
 *
 * Shows location details with an interactive Leaflet map.
 * Note: The Leaflet map requires network access to load OpenStreetMap tiles.
 * Access at: /dev/preview/embeds/maps/MapLocationEmbedFullscreen
 */

/** Default props — shows a finished place with full location data */
const defaultProps = {
  displayName: "Man vs. Machine Coffee Roasters",
  formattedAddress: "Müllerstraße 23, 80469 Munich, Germany",
  lat: 48.1321,
  lon: 11.5718,
  zoom: 16,
  rating: 4.7,
  userRatingCount: 1832,
  placeType: "Coffee Shop",
  websiteUri: "https://www.mvsm.coffee",
  placeId: "ChIJabc123",
  onClose: () => {},
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

  /** No map coordinates (address-only) */
  noCoords: {
    displayName: "Lost Weekend",
    formattedAddress: "Schellingstraße 3, 80799 Munich",
    rating: 4.5,
    userRatingCount: 2456,
    placeType: "Coffee Shop & Bookstore",
    onClose: () => {},
  },

  /** Minimal — just name and close */
  minimal: {
    displayName: "Café Frischhut",
    lat: 48.1354,
    lon: 11.5762,
    onClose: () => {},
  },
};
