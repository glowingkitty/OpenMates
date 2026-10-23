<script lang="ts">
  import { onMount } from "svelte";
  import type { MapMarker, MapPathPoint, MapRoutePath } from "./EmbedLeafletMap.svelte";

  let {
    center,
    markers = [],
    zoom = 13,
    paused = false,
    interactive = false,
    showAttribution = false,
    path = [],
    paths = [],
  }: {
    center?: { lat: number; lon: number };
    markers?: MapMarker[];
    zoom?: number;
    paused?: boolean;
    interactive?: boolean;
    showAttribution?: boolean;
    path?: MapPathPoint[];
    paths?: MapRoutePath[];
  } = $props();
  let host = $state<HTMLDivElement>();
  let visible = $state(false);
  let Map = $state<typeof import("./EmbedLeafletMap.svelte").default>();
  onMount(() => {
    if (!host || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
    });
    observer.observe(host);
    return () => observer.disconnect();
  });
  // Merely importing a result card must not initialize the map dependency tree.
  // Conditional rendering also destroys Leaflet observers/layers when offscreen.
  $effect(() => {
    if (visible && center && !paused && !Map)
      void import("./EmbedLeafletMap.svelte").then((module) => {
        Map = module.default;
      });
  });
</script>

<div bind:this={host} class="map-preview" data-testid="result-map-preview" aria-hidden={!interactive} inert={!interactive}>
  {#if visible && center && !paused && Map}<Map
      {center}
      {markers}
      {zoom}
      {showAttribution}
      {path}
      {paths}
      fitBounds={true}
      height="100%"
      minHeight="120px"
      scrollWheelZoom={false}
      controlStyle="hidden"
    />{/if}
</div>

<style>
  .map-preview {
    width: 100%;
    height: 100%;
    background: var(--color-grey-20);
  }
</style>
