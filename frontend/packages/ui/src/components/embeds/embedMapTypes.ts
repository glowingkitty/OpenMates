/** Shared map geometry types for result helpers and the Leaflet renderer. */
/** A single marker on the map */
export interface MapMarker {
  lat: number;
  lon: number;
  /** Meter-radius area, rendered as a circle instead of a point pin. */
  radiusM?: number;
  areaBasis?: 'description' | 'district' | 'city';
  homeLocation?: boolean;
  /** Optional ref for selection callbacks */
  ref?: string;
  /** Optional label (used as tooltip) */
  label?: string;
  /** Optional custom CSS class for the marker icon */
  iconClass?: string;
  /** Optional test ID for the marker element */
  testId?: string;
  /** App color, independent of marker selection or hover state */
  color?: string;
  /** Visual opacity, used for list-hover focus without refitting the map */
  opacity?: number;
  /** Every result ref represented by this coordinate (for shared stops) */
  relatedRefs?: string[];
  /** Stable coordinate key used to preserve explicit marker selection */
  selectionKey?: string;
  /** Keep the marker label visible while this marker is selected */
  selected?: boolean;
}

/** A point in a polyline path */
export interface MapPathPoint {
  lat: number;
  lon: number;
  label?: string;
}

/** A route polyline rendered on the map */
export interface MapRoutePath {
  points: MapPathPoint[];
  color?: string;
  weight?: number;
  opacity?: number;
  dashArray?: string;
  ref?: string;
  testId?: string;
}

export interface MapBounds {
  north: number;
  south: number;
  east: number;
  west: number;
}

