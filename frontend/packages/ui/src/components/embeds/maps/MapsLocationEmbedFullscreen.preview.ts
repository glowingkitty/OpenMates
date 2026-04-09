/**
 * frontend/packages/ui/src/components/embeds/maps/MapsLocationEmbedFullscreen.preview.ts
 *
 * Mock props for MapsLocationEmbedFullscreen used by dev component previews.
 * Architecture context: docs/architecture/embeds.md (EntryWithMapTemplate flow).
 * Verification reference: frontend/apps/web_app/tests/embed-showcase.spec.ts.
 * Access path: /dev/preview/embeds/maps/MapsLocationEmbedFullscreen.
 *
 * Map image is an inline SVG data URI — no third-party request, no cookies.
 * (Previously fetched from upload.wikimedia.org, which set the WMF-Uniq cookie
 * and contaminated the legal cookie inventory. See docs/architecture/compliance/cookies.yml.)
 */

const PLACEHOLDER_MAP_IMAGE =
  'data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%20640%20360%22%3E%3Crect%20width%3D%22640%22%20height%3D%22360%22%20fill%3D%22%23e5e7eb%22%2F%3E%3Ctext%20x%3D%22320%22%20y%3D%22180%22%20text-anchor%3D%22middle%22%20dominant-baseline%3D%22middle%22%20font-family%3D%22sans-serif%22%20font-size%3D%2232%22%20fill%3D%22%236b7280%22%3EMap%20preview%3C%2Ftext%3E%3C%2Fsvg%3E';

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
    mapImageUrl: PLACEHOLDER_MAP_IMAGE,
  },
  noCoordinates: {
    ...defaultProps,
    lat: undefined,
    lon: undefined,
    mapImageUrl: PLACEHOLDER_MAP_IMAGE,
  },
  withNavigation: {
    ...defaultProps,
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },
};
