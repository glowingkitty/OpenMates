<!--
  frontend/packages/ui/src/components/embeds/EmbedLeafletMap.svelte

  Shared interactive Leaflet map component for embed fullscreen views.
  Extracted from MapsLocationEmbedFullscreen + TravelConnectionEmbedFullscreen
  to avoid duplicating Leaflet initialization, dark mode, and resize handling.

  Features:
  - Dynamic Leaflet import (SSR-safe)
  - OpenStreetMap tiles with automatic dark mode support
  - Custom pin markers using the bundled shared Maps SVG asset
  - ResizeObserver for animation-safe invalidateSize()
  - Configurable center, zoom, markers, and optional polyline path
  - Exposes the Leaflet map instance via onMapReady callback for advanced use

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Embeds/Renderers/EventEmbedRenderer.swift

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import mapsMarkerIconSvg from '../../../static/icons/maps.svg?raw';
  import { isDarkThemeActive, watchDarkThemeActive } from '../../utils/themeDetection';

  /** A single marker on the map */
  export interface MapMarker {
    lat: number;
    lon: number;
    /** Optional ref for selection callbacks */
    ref?: string;
    /** Optional label (used as tooltip) */
    label?: string;
    /** Optional custom CSS class for the marker icon */
    iconClass?: string;
    /** Optional test ID for the marker element */
    testId?: string;
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

  interface Props {
    /** Map center latitude and longitude */
    center: { lat: number; lon: number };
    /** Map zoom level (default 15) */
    zoom?: number;
    /** Array of markers to display */
    markers?: MapMarker[];
    /** Optional polyline path (e.g. for routes) */
    path?: MapPathPoint[];
    /** Optional multiple route polylines */
    paths?: MapRoutePath[];
    /** Path color (default: primary color) */
    pathColor?: string;
    /** Path weight in pixels (default: 3) */
    pathWeight?: number;
    /** Whether to auto-fit bounds to markers/path (default: true when >1 marker or path) */
    fitBounds?: boolean;
    /** Fit bounds padding in pixels (default: 50) */
    fitBoundsPadding?: number;
    /** Height CSS value (default: '100%') */
    height?: string;
    /** Min height CSS value (default: '220px') */
    minHeight?: string;
    /** Whether scroll wheel zoom is enabled (default: true) */
    scrollWheelZoom?: boolean;
    /** Leaflet corner used for the zoom control (default: top-right) */
    zoomControlPosition?: 'topleft' | 'topright' | 'bottomleft' | 'bottomright';
    /** Callback with the raw Leaflet map + L module for advanced customization */
    onMapReady?: (map: unknown, L: unknown) => void;
    /** Called when a marker with a ref is clicked */
    onMarkerSelect?: (ref: string, relatedRefs?: string[], selectionKey?: string) => void;
    /** Called when a route path with a ref is clicked */
    onRouteSelect?: (ref: string) => void;
    /** Called after Leaflet settles its current viewport */
    onBoundsChange?: (bounds: MapBounds) => void;
    /** Horizontal visual offset in pixels for center/fit (used when a left detail panel overlaps map) */
    centerOffsetX?: number;
  }

  let {
    center,
    zoom = 15,
    markers = [],
    path = [],
    paths = [],
    pathColor = '#6c63ff',
    pathWeight = 3,
    fitBounds: fitBoundsProp,
    fitBoundsPadding = 50,
    height = '100%',
    minHeight = '220px',
    scrollWheelZoom = true,
    zoomControlPosition = 'topright',
    onMapReady,
    onMarkerSelect,
    onRouteSelect,
    onBoundsChange,
    centerOffsetX = 0,
  }: Props = $props();

  let shouldFitBounds = $derived(
    fitBoundsProp ?? (markers.length > 1 || path.length > 0 || paths.length > 0)
  );
  let normalizedPaths = $derived(
    [
      ...(path.length > 1 ? [{ points: path, color: pathColor, weight: pathWeight }] : []),
      ...paths,
    ].filter((routePath) => routePath.points.length > 1)
  );

  let mapContainer = $state<HTMLDivElement | null>(null);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let leafletMap: any = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let leafletModule: any = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let tileLayer: any = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let markerLayerGroup: any = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let pathLayerGroup: any = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let markerLayers: any[] = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let pathLayers: any[] = [];
  let mapResizeObserver: ResizeObserver | null = null;
  let stopWatchingMapTheme: (() => void) | null = null;
  let resizeAnimationFrame: number | null = null;
  let appliedCenterPanX = 0;
  let leafletReady = $state(false);
  let tilesLoaded = $state(false);
  let lastFitGeometrySignature = '';
  let lastLayerSignature = '';
  const markerIconHtml = mapsMarkerIconSvg
    .replace('<svg ', '<svg class="marker-icon" aria-hidden="true" ')
    .replace('fill="#000"', 'fill="currentColor"');

  function applyTileTheme(isDarkMode: boolean) {
    const container = tileLayer?.getContainer?.();
    container?.classList.toggle('dark-tiles', isDarkMode);
  }

  function geometrySignature(): string {
    return JSON.stringify({
      center,
      markers: markers.map((marker) => [marker.lat, marker.lon]),
      paths: normalizedPaths.map((routePath) => routePath.points.map((point) => [point.lat, point.lon])),
      shouldFitBounds,
      fitBoundsPadding,
    });
  }

  function layerSignature(): string {
    return JSON.stringify({
      markers: markers.map((marker) => [
        marker.lat,
        marker.lon,
        marker.ref,
        marker.relatedRefs,
        marker.selectionKey,
        marker.selected,
        marker.testId,
        marker.iconClass,
        marker.opacity,
        marker.label,
      ]),
      paths: normalizedPaths.map((routePath) => [
        routePath.color,
        routePath.weight,
        routePath.opacity,
        routePath.dashArray,
        routePath.ref,
        routePath.testId,
        routePath.points.map((point) => [point.lat, point.lon]),
      ]),
      pathColor,
      pathWeight,
    });
  }

  function renderLeafletLayers({ fitBoundsToGeometry = false } = {}) {
    if (!leafletMap || !leafletModule) return;
    const L = leafletModule;

    markerLayerGroup?.remove?.();
    pathLayerGroup?.remove?.();
    markerLayerGroup = L.layerGroup().addTo(leafletMap);
    pathLayerGroup = L.layerGroup().addTo(leafletMap);
    markerLayers = [];
    pathLayers = [];

    for (const marker of markers) {
      const customIcon = L.divIcon({
        className: marker.iconClass || 'default-map-marker',
        html: markerIconHtml,
        iconSize: [40, 40],
        iconAnchor: [20, 40],
      });

      const m = L.marker([marker.lat, marker.lon], { icon: customIcon }).addTo(markerLayerGroup);
      m.setOpacity(marker.opacity ?? 1);
      const element = m.getElement?.();
      if (marker.testId) element?.setAttribute('data-testid', marker.testId);
      if (marker.label) element?.setAttribute('data-marker-label', marker.label);
      if (marker.selectionKey) element?.setAttribute('data-marker-selection-key', marker.selectionKey);
      if (marker.ref) {
        element?.setAttribute('data-marker-ref', marker.ref);
        m.on('click', () => onMarkerSelect?.(marker.ref!, marker.relatedRefs, marker.selectionKey));
      }
      if (marker.label) {
        m.bindTooltip(marker.label, {
          permanent: marker.selected === true,
          direction: 'top',
          offset: [0, -34],
          className: 'embed-map-marker-label',
        });
      }
      markerLayers.push(m);
    }

    for (const routePath of normalizedPaths) {
      const line = L.polyline(
        routePath.points.map(p => [p.lat, p.lon] as [number, number]),
        {
          color: routePath.color || pathColor,
          weight: routePath.weight || pathWeight,
          opacity: routePath.opacity ?? 0.8,
          dashArray: routePath.dashArray,
        }
      ).addTo(pathLayerGroup);
      const element = line.getElement();
      if (routePath.testId) element?.setAttribute('data-testid', routePath.testId);
      if (routePath.ref) {
        element?.setAttribute('data-route-ref', routePath.ref);
        line.on('click', () => onRouteSelect?.(routePath.ref!));
      }
      pathLayers.push(line);
    }

    if (fitBoundsToGeometry) {
      if (shouldFitBounds) {
        const allPoints: [number, number][] = [
          ...markers.map(m => [m.lat, m.lon] as [number, number]),
          ...normalizedPaths.flatMap(routePath => routePath.points.map(p => [p.lat, p.lon] as [number, number])),
        ];
        if (allPoints.length > 1) {
          leafletMap.fitBounds(L.latLngBounds(allPoints), { padding: [fitBoundsPadding, fitBoundsPadding] });
        } else {
          leafletMap.setView([center.lat, center.lon], zoom, { animate: false });
        }
      } else {
        leafletMap.setView([center.lat, center.lon], zoom, { animate: false });
      }
    }
    applyCenterOffset();
    emitBoundsChange();
    lastLayerSignature = layerSignature();
  }

  function emitBoundsChange() {
    if (!leafletMap || !onBoundsChange) return;
    const bounds = leafletMap.getBounds?.();
    if (!bounds) return;
    onBoundsChange({
      north: bounds.getNorth(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      west: bounds.getWest(),
    });
  }

  function updateLeafletLayerStyles() {
    if (!leafletModule) return;
    const L = leafletModule;
    markers.forEach((marker, index) => {
      const markerLayer = markerLayers[index];
      if (!markerLayer) return;
      markerLayer.setOpacity?.(marker.opacity ?? 1);
      markerLayer.setIcon?.(L.divIcon({
        className: marker.iconClass || 'default-map-marker',
        html: markerIconHtml,
        iconSize: [40, 40],
        iconAnchor: [20, 40],
      }));
      const element = markerLayer.getElement?.();
      if (marker.testId) element?.setAttribute('data-testid', marker.testId);
      if (marker.label) element?.setAttribute('data-marker-label', marker.label);
      if (marker.selectionKey) element?.setAttribute('data-marker-selection-key', marker.selectionKey);
      markerLayer.unbindTooltip?.();
      if (marker.label) {
        markerLayer.bindTooltip?.(marker.label, {
          permanent: marker.selected === true,
          direction: 'top',
          offset: [0, -34],
          className: 'embed-map-marker-label',
        });
      }
    });
    normalizedPaths.forEach((routePath, index) => {
      pathLayers[index]?.setStyle?.({
        color: routePath.color || pathColor,
        weight: routePath.weight || pathWeight,
        opacity: routePath.opacity ?? 0.8,
        dashArray: routePath.dashArray,
      });
    });
    lastLayerSignature = layerSignature();
  }

  function scheduleResizeInvalidation() {
    if (!leafletMap || resizeAnimationFrame != null) return;
    resizeAnimationFrame = requestAnimationFrame(() => {
      resizeAnimationFrame = null;
      if (!leafletMap) return;
      leafletMap.invalidateSize();
      applyCenterOffset();
    });
  }

  function getEffectiveCenterOffsetX(): number {
    if (!mapContainer) return 0;
    const WIDE_LAYOUT_MIN_WIDTH_PX = 601;
    if (mapContainer.clientWidth < WIDE_LAYOUT_MIN_WIDTH_PX) return 0;
    return centerOffsetX;
  }

  function applyCenterOffset() {
    if (!leafletMap) return;
    const effectiveOffsetX = getEffectiveCenterOffsetX();
    const targetPanX = -effectiveOffsetX;
    const deltaPanX = targetPanX - appliedCenterPanX;
    if (deltaPanX === 0) return;
    leafletMap.panBy([deltaPanX, 0], { animate: false });
    appliedCenterPanX = targetPanX;
  }

  async function initLeafletMap() {
    if (!mapContainer) return;

    try {
      const L = (await import('leaflet')).default;
      await import('leaflet/dist/leaflet.css');
      leafletModule = L;

      const isDarkMode = isDarkThemeActive();

      leafletMap = L.map(mapContainer, {
        center: [center.lat, center.lon],
        zoom,
        zoomControl: false,
        attributionControl: true,
        scrollWheelZoom,
      });
      leafletMap.on('moveend zoomend', emitBoundsChange);

      const zoomControl = L.control.zoom({ position: zoomControlPosition });
      zoomControl.addTo(leafletMap);
      zoomControl.getContainer?.()?.setAttribute('data-testid', 'embed-map-zoom-controls');

      tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        className: isDarkMode ? 'dark-tiles' : '',
      });
      tileLayer.on('loading', () => {
        tilesLoaded = false;
      });
      tileLayer.on('load', () => {
        tilesLoaded = true;
      });
      tileLayer.addTo(leafletMap);
      stopWatchingMapTheme = watchDarkThemeActive(applyTileTheme);
      renderLeafletLayers({ fitBoundsToGeometry: true });
      lastFitGeometrySignature = geometrySignature();
      leafletReady = true;
      emitBoundsChange();

      if (typeof ResizeObserver !== 'undefined') {
        mapResizeObserver = new ResizeObserver(() => {
          scheduleResizeInvalidation();
        });
        mapResizeObserver.observe(mapContainer);
      }

      if (onMapReady) {
        onMapReady(leafletMap, L);
      }

    } catch (err) {
      console.error('[EmbedLeafletMap] Failed to init Leaflet map:', err);
    }
  }

  onMount(() => {
    initLeafletMap();
  });

  onDestroy(() => {
    if (mapResizeObserver) {
      mapResizeObserver.disconnect();
      mapResizeObserver = null;
    }
    if (leafletMap) {
      try { leafletMap.remove(); } catch { /* ignore */ }
      leafletMap = null;
      appliedCenterPanX = 0;
    }
    if (resizeAnimationFrame != null) {
      cancelAnimationFrame(resizeAnimationFrame);
      resizeAnimationFrame = null;
    }
    markerLayerGroup = null;
    pathLayerGroup = null;
    markerLayers = [];
    pathLayers = [];
    stopWatchingMapTheme?.();
    stopWatchingMapTheme = null;
    tileLayer = null;
    leafletModule = null;
    leafletReady = false;
    tilesLoaded = false;
    lastFitGeometrySignature = '';
    lastLayerSignature = '';
  });

  $effect(() => {
    const nextLayerSignature = layerSignature();
    const nextGeometrySignature = geometrySignature();
    if (!leafletReady) return;
    if (nextLayerSignature === lastLayerSignature && nextGeometrySignature === lastFitGeometrySignature) return;
    const shouldRefit = nextGeometrySignature !== lastFitGeometrySignature;
    if (shouldRefit) {
      renderLeafletLayers({ fitBoundsToGeometry: true });
      lastFitGeometrySignature = nextGeometrySignature;
      return;
    }
    updateLeafletLayerStyles();
  });
</script>

<div
  class="embed-leaflet-map"
  data-testid="embed-leaflet-map"
  data-tiles-loaded={tilesLoaded ? 'true' : 'false'}
  style="height: {height}; min-height: {minHeight};"
  bind:this={mapContainer}
></div>

<style>
  .embed-leaflet-map {
    width: 100%;
    isolation: isolate;
  }

  :global(.embed-leaflet-map .default-map-marker) {
    background: none;
    border: none;
  }

  :global(.embed-leaflet-map .marker-icon) {
    display: block;
    width: 40px;
    height: 40px;
    transition: opacity var(--duration-fast, 0.15s) ease;
  }

  :global(.embed-leaflet-map .embed-map-marker-label) {
    border: 0;
    border-radius: var(--radius-3, 8px);
    background: var(--color-grey-0, #ffffff);
    color: var(--color-font-primary, #222222);
    box-shadow: var(--shadow-md, 0 4px 12px rgba(0, 0, 0, 0.15));
    font-family: inherit;
    font-weight: 650;
  }

  :global(.embed-leaflet-map .embeds-map-view-marker-active) {
    background: none;
    border: none;
  }

  :global(.embed-leaflet-map .dark-tiles) {
    filter: invert(1) hue-rotate(180deg) brightness(0.85) saturate(0.8);
  }

  :global(.embed-leaflet-map .leaflet-top.leaflet-right) {
    top: 12px !important;
    right: 12px !important;
    left: auto !important;
    bottom: auto !important;
    transform: none;
  }

  :global(.embed-leaflet-map .leaflet-top.leaflet-left) {
    top: 50% !important;
    left: 14px !important;
    right: auto !important;
    bottom: auto !important;
    transform: translateY(-50%);
  }

  @media (min-width: 601px) {
    :global(.embed-leaflet-map .leaflet-top.leaflet-right) {
      top: 50% !important;
      right: 24px !important;
      transform: translateY(-50%);
    }
  }

  :global(.embed-leaflet-map .leaflet-top.leaflet-right .leaflet-control-zoom) {
    margin-top: 0 !important;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    border-radius: var(--radius-3);
    overflow: hidden;
  }

  :global(.embed-leaflet-map .leaflet-top.leaflet-left .leaflet-control-zoom) {
    margin: 0 !important;
    box-shadow: var(--shadow-md, 0 4px 12px rgba(0, 0, 0, 0.15));
    border: 0;
    border-radius: var(--radius-full, 9999px);
    overflow: hidden;
  }

  :global(.embed-leaflet-map .leaflet-top.leaflet-left .leaflet-control-zoom a) {
    display: grid;
    width: 57px;
    height: 50px;
    place-items: center;
    border-color: var(--color-grey-25);
    background: var(--color-grey-0);
    color: var(--color-primary);
    font-size: 1.75rem;
    line-height: 1;
  }
</style>
