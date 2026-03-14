/**
 * frontend/packages/ui/src/components/embeds/maps/MapsLocationEmbedPreview.preview.ts
 *
 * Mock props for MapsLocationEmbedPreview used by dev component previews.
 * Architecture context: docs/architecture/embeds.md (app-skill embed rendering).
 * Verification reference: frontend/apps/web_app/tests/embed-showcase.spec.ts.
 * Access path: /dev/preview/embeds/maps/MapsLocationEmbedPreview.
 */

const defaultProps = {
  id: "preview-maps-location-1",
  name: "Berlin Hauptbahnhof",
  address: "Europaplatz 1, 10557 Berlin",
  locationType: "precise_location",
  placeType: "railway",
  mapImageUrl:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/OpenStreetMap_logo.svg/640px-OpenStreetMap_logo.svg.png",
  status: "finished" as const,
  isMobile: false,
  onFullscreen: () => {},
};

export default defaultProps;

export const variants = {
  nearbyArea: {
    ...defaultProps,
    id: "preview-maps-location-area",
    name: "Nearby location",
    address: "Near Potsdamer Platz, Berlin",
    locationType: "area",
    placeType: "",
    mapImageUrl: undefined,
  },
  noImage: {
    ...defaultProps,
    id: "preview-maps-location-no-image",
    mapImageUrl: undefined,
    placeType: "airport",
  },
  processing: {
    ...defaultProps,
    id: "preview-maps-location-processing",
    status: "processing" as const,
    mapImageUrl: undefined,
  },
  mobile: {
    ...defaultProps,
    id: "preview-maps-location-mobile",
    isMobile: true,
  },
};
