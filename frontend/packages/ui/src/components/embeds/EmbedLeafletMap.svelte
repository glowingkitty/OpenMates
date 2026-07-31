<!--
  frontend/packages/ui/src/components/embeds/EmbedLeafletMap.svelte

  Shared interactive Leaflet map component for embed fullscreen views.
  Extracted from MapsLocationEmbedFullscreen + TravelConnectionEmbedFullscreen
  to avoid duplicating Leaflet initialization, dark mode, and resize handling.

  Features:
  - Dynamic Leaflet import (SSR-safe)
  - OpenStreetMap tiles with automatic dark mode support
  - Custom pin markers via CSS mask-image
  - ResizeObserver for animation-safe invalidateSize()
  - Configurable center, zoom, markers, and optional polyline path
  - Exposes the Leaflet map instance via onMapReady callback for advanced use

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Embeds/Renderers/EventEmbedRenderer.swift

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { isDarkThemeActive, watchDarkThemeActive } from '../../utils/themeDetection';

  /** A single marker on the map */
  export interface MapMarker {
    lat: number;
    lon: number;
    /** Optional label (used as tooltip) */
    label?: string;
    /** Optional custom CSS class for the marker icon */
    iconClass?: string;
    /** Visual opacity, used for list-hover focus without refitting the map */
    opacity?: number;
  }

  /** A point in a polyline path */
  export interface MapPathPoint {
    lat: number;
    lon: number;
  }

  /** A route polyline rendered on the map */
  export interface MapRoutePath {
    points: MapPathPoint[];
    color?: string;
    weight?: number;
    opacity?: number;
    ref?: string;
    testId?: string;
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
    /** Callback with the raw Leaflet map + L module for advanced customization */
    onMapReady?: (map: unknown, L: unknown) => void;
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
    onMapReady,
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
  let lastFitGeometrySignature = '';
  let lastLayerSignature = '';

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
      markers: markers.map((marker) => [marker.lat, marker.lon, marker.iconClass, marker.opacity, marker.label]),
      paths: normalizedPaths.map((routePath) => [
        routePath.color,
        routePath.weight,
        routePath.opacity,
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
        html: '<div class="marker-icon"></div>',
        iconSize: [40, 40],
        iconAnchor: [20, 40],
      });

      const m = L.marker([marker.lat, marker.lon], { icon: customIcon }).addTo(markerLayerGroup);
      m.setOpacity(marker.opacity ?? 1);
      if (marker.label) {
        m.bindTooltip(marker.label, { permanent: false });
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
        }
      ).addTo(pathLayerGroup);
      const element = line.getElement();
      if (routePath.testId) element?.setAttribute('data-testid', routePath.testId);
      if (routePath.ref) element?.setAttribute('data-route-ref', routePath.ref);
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
    lastLayerSignature = layerSignature();
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
        html: '<div class="marker-icon"></div>',
        iconSize: [40, 40],
        iconAnchor: [20, 40],
      }));
    });
    normalizedPaths.forEach((routePath, index) => {
      pathLayers[index]?.setStyle?.({
        color: routePath.color || pathColor,
        weight: routePath.weight || pathWeight,
        opacity: routePath.opacity ?? 0.8,
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

      // Add zoom control on the right side
      L.control.zoom({ position: 'topright' }).addTo(leafletMap);

      tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        className: isDarkMode ? 'dark-tiles' : '',
      });
      tileLayer.addTo(leafletMap);
      stopWatchingMapTheme = watchDarkThemeActive(applyTileTheme);
      renderLeafletLayers({ fitBoundsToGeometry: true });
      lastFitGeometrySignature = geometrySignature();
      leafletReady = true;

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

  :global(.embed-leaflet-map .default-map-marker .marker-icon) {
    width: 40px;
    height: 40px;
    background-color: var(--color-primary, #6c63ff);
    -webkit-mask-image: url('@openmates/ui/static/icons/pin.svg');
    mask-image: url('@openmates/ui/static/icons/pin.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    transition: opacity var(--duration-fast, 0.15s) ease;
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
</style>
