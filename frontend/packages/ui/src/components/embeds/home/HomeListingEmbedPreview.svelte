<!-- Home result card: uncropped photo or factual location-map fallback in the shared result shell. -->

<script lang="ts">
  import House from '@lucide/svelte/icons/house';
  import EmbedCalendarDate from "../EmbedCalendarDate.svelte";
  import ExternalLink from '@lucide/svelte/icons/external-link';
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
    url,
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

  let geometry = $derived(homeMapGeometry({ latitude: lat, longitude: lon, location_precision, location_approximate, location: { area: homeObject(location_area) } }));
  let mapCenter = $derived(geometry ? { lat: geometry.lat, lon: geometry.lon } : typeof lat === "number" && typeof lon === "number" && Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? { lat, lon } : undefined);
  // A center without a known extent is useful for the map, but is never an exact home pin.
  let mapMarkers = $derived(geometry ? [{ ...geometry, homeLocation: true, testId: "home-preview-location-area", label: `${address || title || ""} · ${$text("home_listing.approximate")}` }] : []);
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
  {#snippet resultPrimaryAction()}
    {#if url}<a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={$text("embeds.open_on_provider").replace(
          "{provider}",
          provider || "listing",
        )}
        onclick={(event) => event.stopPropagation()}
        ><ExternalLink size={18} aria-hidden="true" /></a
      >{/if}
  {/snippet}
  {#snippet listingMedia()}
    {#if proxiedImageUrl}<img class="home-preview-image" src={proxiedImageUrl} alt={title || $text("home_listing.listing")} loading="lazy" onerror={() => imageError = true} />
    {:else if mapCenter}<ResultEmbedMapPreview center={mapCenter} markers={mapMarkers} zoom={location_precision === "city" ? 10 : 12} />{/if}
  {/snippet}
  {#snippet details()}
    <div class="listing-card" data-testid="home-listing-result-card">
      <ResultEmbedCard title={title || $text("home_listing.listing")} sourceLabel={address ? `${address}${location_approximate || location_precision !== "building" ? ` · ${$text("home_listing.approximate")}` : ""}` : provider} media={proxiedImageUrl || mapCenter ? listingMedia : undefined} mediaFit="contain">
        {#snippet badge()}{#if available_from}<EmbedCalendarDate date={available_from} />{/if}{/snippet}
        {#snippet facts()}
          {#if price_label}<span class="listing-price">{price_label}</span>{/if}
          <div class="listing-extra">
            {#if sizeDisplay}<span title={sizeDisplay}><House size={14} aria-hidden="true" />{sizeDisplay}</span>{/if}
            {#if roomsDisplay}<span class="sr-only">{roomsDisplay}</span>{/if}
          </div>
        {/snippet}
      </ResultEmbedCard>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
.listing-card {width:100%;height:100%;min-width:0;} .home-preview-image {display:block;width:100%;height:100%;object-fit:contain;background:var(--color-grey-25);} .listing-price {width:100%;font-size:var(--font-size-small);font-weight:600;color:var(--color-font-primary);} .listing-extra {display:flex;flex-wrap:wrap;gap:var(--spacing-4);font-size:var(--font-size-small);color:var(--color-font-secondary);} .listing-extra>span {display:inline-flex;align-items:center;gap:var(--spacing-2);} .sr-only {position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;}
</style>
