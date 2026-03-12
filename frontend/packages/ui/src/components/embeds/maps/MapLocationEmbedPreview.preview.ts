/**
 * Preview mock data for MapLocationEmbedPreview.
 *
 * Shows a single place result card as rendered in the MapsSearchEmbedFullscreen list.
 * Access at: /dev/preview/embeds/maps/MapLocationEmbedPreview
 */

/** Default props — shows a finished place card with full data */
const defaultProps = {
  id: "preview-map-place-1",
  displayName: "Man vs. Machine Coffee Roasters",
  formattedAddress: "Müllerstraße 23, 80469 Munich",
  rating: 4.7,
  userRatingCount: 1832,
  placeType: "Coffee Shop",
  isSelected: false,
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Selected / highlighted state */
  selected: {
    ...defaultProps,
    id: "preview-map-place-selected",
    isSelected: true,
  },

  /** Place without optional fields */
  minimal: {
    id: "preview-map-place-minimal",
    displayName: "Café Frischhut",
    formattedAddress: "Prälat-Zistl-Straße 8, 80331 Munich",
    status: "finished" as const,
    isMobile: false,
    onFullscreen: () => {},
  },

  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-map-place-mobile",
    isMobile: true,
  },
};
