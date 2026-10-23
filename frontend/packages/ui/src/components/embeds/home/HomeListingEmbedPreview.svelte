<!-- Home result card: uncropped photo or factual location-map fallback in the shared result shell. -->

<script lang="ts">
  import { onMount } from "svelte";
  import { homePreviewCity, resolveHomePreviewCity } from "./homePreviewLocation";
  import type { HomeMapGeometry } from "./homeListingData";
  import House from '@lucide/svelte/icons/house';
  import EmbedCalendarDate from "../EmbedCalendarDate.svelte";

  import { text } from "../../../i18n/translations";
  import ResultEmbedCard from "../ResultEmbedCard.svelte";
  import ResultEmbedMapPreview from "../ResultEmbedMapPreview.svelte";
  import { homeMapGeometry, homeObject } from "./homeListingData";
  import UnifiedEmbedPreview from "../UnifiedEmbedPreview.svelte";
  import {
    proxyImage,
    MAX_WIDTH_PREVIEW_THUMBNAIL,
  } from "../../../utils/imageProxy";

  interface Props {
    /** Child embed ID */
    embed_id: string;
    /** Listing title */
    title?: string;
    /** Human-readable price (e.g. "850 EUR/month") */
    price_label?: string;
    /** Living area in square meters */
    size_sqm?: number;
    /** Number of rooms */
    rooms?: number;
    /** Address (city + district/street) */
    address?: string;
    city?: string;
    location_exact_address?: boolean;
    location_precision?: string;
    location_approximate?: boolean;
    lat?: number;
    lon?: number;
    location_area?: unknown;
    /** First listing image URL */
    image_url?: string;
    /** Direct link to listing on platform */
    url?: string;
    /** Provider name (ImmoScout24, Kleinanzeigen, WG-Gesucht) */
    provider?: string;
    /** Listing type (rent or buy) */
    listing_type?: string;
    /** Move-in date (DD.MM.YYYY, WG-Gesucht only) */
    available_from?: string;
    /** Click handler to open fullscreen view */
    onSelect: () => void;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    resultContext?: "auto" | "chat" | "results";
  }

  let {
    embed_id,
    title,
    price_label,
    size_sqm,
    rooms,
    address,
    city,
    location_exact_address,
    image_url,
    location_precision,
    location_approximate = true,
    lat,
    lon,
    location_area,
    provider,
    listing_type: _listingType,
    available_from,
    onSelect,
    isMobile = false,
    resultContext = "auto",
  }: Props = $props();

  let imageError = $state(false);
  $effect(() => {
    void image_url;
    imageError = false;
  });

  let proxiedImageUrl = $derived(
    image_url && !imageError
      ? proxyImage(image_url, MAX_WIDTH_PREVIEW_THUMBNAIL)
      : null,
  );

  let host = $state<HTMLDivElement>();
  let visible = $state(false);
  let cityGeometry = $state<HomeMapGeometry>();
  let cityLoading = $state(false);
  const locality = $derived(homePreviewCity(city, address));
  const suppliedGeometry = $derived(homeMapGeometry({ latitude: lat, longitude: lon, address, location_precision, location_approximate, location: { exact_address: location_exact_address, area: homeObject(location_area) } }));
  onMount(() => {
    if (!host) return;
    if (typeof IntersectionObserver === 'undefined') { visible = true; return; }
    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; });
    observer.observe(host);
    return () => observer.disconnect();
  });
  $effect(() => {
    cityGeometry = undefined;
    cityLoading = false;
    if (suppliedGeometry || !locality || !visible) return;
    let active = true;
    cityLoading = true;
    void resolveHomePreviewCity(locality).then(value => {
      if (active) { cityGeometry = value; cityLoading = false; }
    });
    return () => { active = false; };
  });
  const geometry = $derived(suppliedGeometry || cityGeometry);
  const mapCenter = $derived(geometry ? { lat: geometry.lat, lon: geometry.lon } : undefined);
  const mapMarkers = $derived(geometry ? [{ ...geometry, homeLocation: true, testId: geometry.radiusM ? "home-preview-location-area" : "home-preview-location-pin", label: `${geometry.areaBasis === 'city' ? locality || '' : address || title || ''} · ${geometry.radiusM ? $text("home_listing.approximate") : $text("home_listing.building")}` }] : []);
  let sizeDisplay = $derived(size_sqm ? `${size_sqm} m\u00B2` : undefined);

  let roomsDisplay = $derived(
    rooms ? `${rooms} ${rooms === 1 ? "room" : "rooms"}` : undefined,
  );


  function handleStop() {
    // Listing cards are not cancellable
  }
</script>

<UnifiedEmbedPreview
  id={embed_id}
  appId="home"
  skillId="listing"
  skillIconName="home"
  status="finished"
  skillName={title || $text("home_listing.listing")}
  {isMobile}
  onFullscreen={onSelect}
  onStop={handleStop}
  resultPreview={true}
  {resultContext}
>

  {#snippet listingMedia()}
    <div class="listing-media" class:paired={!!proxiedImageUrl} data-testid="home-preview-media">
      {#if proxiedImageUrl}<img class="home-preview-image" src={proxiedImageUrl} alt={title || $text("home_listing.listing")} loading="lazy" onerror={() => imageError = true} />{/if}
      <div class="listing-map" data-testid="home-preview-map">
        {#if mapCenter}<ResultEmbedMapPreview center={mapCenter} markers={mapMarkers} zoom={geometry?.areaBasis === "city" ? 10 : 12} />
        {#if geometry?.radiusM}<span class="map-approximate" data-testid="home-preview-approximate">{$text("home_listing.approximate")}</span>{/if}
        {:else}<span class="map-status" data-testid="home-preview-map-status">{cityLoading ? $text("common.loading") : $text("home_listing.no_location")}</span>{/if}
      </div>
    </div>
  {/snippet}
  {#snippet details()}
    <div bind:this={host} class="listing-card" data-testid="home-listing-result-card">
      <ResultEmbedCard title={title || $text("home_listing.listing")} media={listingMedia} mediaFit="contain">
        {#snippet badge()}{#if available_from}<EmbedCalendarDate date={available_from} />{/if}{/snippet}
        {#snippet facts()}
          {#if price_label}<span class="listing-price">{price_label}</span>{/if}
          <div class="listing-extra">
            {#if address || provider}<span class="listing-location">{address || provider}{geometry?.radiusM ? ` · ${$text("home_listing.approximate")}` : ""}</span>{/if}
            {#if sizeDisplay}<span title={sizeDisplay}><House size={14} aria-hidden="true" />{sizeDisplay}</span>{/if}
            {#if roomsDisplay}<span class="sr-only">{roomsDisplay}</span>{/if}
          </div>
        {/snippet}
      </ResultEmbedCard>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
.listing-card {width:100%;height:100%;min-width:0;} .home-preview-image {display:block;width:100%;height:100%;object-fit:contain;background:#262626;} .listing-price {width:100%;font-size:var(--font-size-small);font-weight:600;color:var(--color-font-primary);} .listing-extra {display:none;flex-wrap:wrap;gap:var(--spacing-4);font-size:var(--font-size-small);color:var(--color-font-secondary);} .listing-extra>span {display:inline-flex;align-items:center;gap:var(--spacing-2);} .sr-only {position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;}
.listing-media {display:grid;grid-template-columns:minmax(0,1fr);width:100%;height:100%;min-height:0;} .listing-media.paired {grid-template-columns:repeat(2,minmax(0,1fr));} .listing-map {position:relative;min-width:0;min-height:0;height:100%;overflow:hidden;background:var(--color-grey-20);} .map-approximate {position:absolute;bottom:5px;left:5px;right:5px;width:fit-content;padding:2px 5px;border-radius:var(--radius-3);background:var(--color-grey-0);color:var(--color-font-secondary);font-size:.625rem;} .map-status {display:flex;align-items:center;justify-content:center;height:100%;padding:8px;box-sizing:border-box;font-size:var(--font-size-xxs);color:var(--color-font-secondary);}
@container result-card (min-width:401px) {.listing-extra {display:flex;} .listing-location {width:100%;}}
</style>
