/**
 * frontend/packages/ui/src/components/embeds/maps/MapsLocationEmbedFullscreen.preview.ts
 *
 * Mock props for MapsLocationEmbedFullscreen used by dev component previews.
 * Architecture context: docs/architecture/embeds.md (EntryWithMapTemplate flow).
 * Verification reference: frontend/apps/web_app/tests/embed-showcase.spec.ts.
 * Access path: /dev/preview/embeds/maps/MapsLocationEmbedFullscreen.
 */

const defaultProps = {
  lat: 52.5251,
  lon: 13.3694,
  zoom: 16,
  name: "Berlin Hauptbahnhof",
  address: "Europaplatz 1, 10557 Berlin",
  locationType: "precise_location",
  mapImageUrl: undefined,
  status: "finished" as const,
  onClose: () => {},
};

export default defaultProps;

export const variants = {
  nearbyArea: {
    ...defaultProps,
    locationType: "area",
    address: "Near Potsdamer Platz, Berlin",
  },
  staticImage: {
    ...defaultProps,
    mapImageUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/OpenStreetMap_logo.svg/640px-OpenStreetMap_logo.svg.png",
  },
  noCoordinates: {
    ...defaultProps,
    lat: undefined,
    lon: undefined,
    mapImageUrl:
      "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/OpenStreetMap_logo.svg/640px-OpenStreetMap_logo.svg.png",
  },
  withNavigation: {
    ...defaultProps,
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },
};
