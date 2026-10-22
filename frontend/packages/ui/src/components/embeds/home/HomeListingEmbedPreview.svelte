<!--
  frontend/packages/ui/src/components/embeds/home/HomeListingEmbedPreview.svelte

  Child listing preview card for Home Search results.
  Uses UnifiedEmbedPreview as the base card (unified with all other embed previews).
  Renders listing image on the right side when available (matching WebsiteEmbedPreview pattern).

  Shows:
  - Price label (prominent)
  - Title (2 lines, truncated)
  - Address line
  - Metadata: size (m²) + rooms + move-in date
  - Provider badge overlaid on image
  - Listing image on right side (or placeholder)

  Clicking the card calls onSelect() to open the fullscreen listing view.
-->

<script lang="ts">
  import House from '@lucide/svelte/icons/house';
  import Calendar from '@lucide/svelte/icons/calendar-days';
  import ExternalLink from '@lucide/svelte/icons/external-link';
  import { text } from "../../../i18n/translations";
  import UnifiedEmbedPreview from "../UnifiedEmbedPreview.svelte";
  import {
    proxyImage,
    MAX_WIDTH_PREVIEW_THUMBNAIL,
  } from "../../../utils/imageProxy";
  import { handleImageError } from "../../../utils/offlineImageHandler";

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

  let sizeDisplay = $derived(size_sqm ? `${size_sqm} m\u00B2` : undefined);

  let roomsDisplay = $derived(
    rooms ? `${rooms} ${rooms === 1 ? "room" : "rooms"}` : undefined,
  );

  let availableDisplay = $derived(
    available_from ? `from ${available_from}` : undefined,
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
  {#snippet details()}
    <div
      class="listing-card"
      class:without-image={!proxiedImageUrl}
      data-testid="home-listing-result-card"
    >
      {#if proxiedImageUrl}<div class="listing-image">
          <img
            src={proxiedImageUrl}
            alt=""
            loading="lazy"
            onerror={(event) => {
              imageError = true;
              handleImageError(event.currentTarget);
            }}
          />
        </div>{/if}
      <div class="listing-copy">
        <strong class="listing-title"
          >{title || $text("home_listing.listing")}</strong
        >
        {#if price_label}<span class="listing-price">{price_label}</span>{/if}
        <div class="listing-extra">
          {#if sizeDisplay}<span title={sizeDisplay}
              ><House size={14} aria-hidden="true" /> {sizeDisplay}</span
            >{/if}{#if availableDisplay}<span title={availableDisplay}
              ><Calendar size={14} aria-hidden="true" /> {available_from}</span
            >{/if}
        </div>
        {#if address}<span class="sr-only"
            >{address}{location_approximate || location_precision !== "building"
              ? ` · ${$text("home_listing.approximate")}`
              : ""}</span
          >{/if}
        {#if roomsDisplay}<span class="sr-only">{roomsDisplay}</span>{/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .listing-card {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    position: relative;
  }
  .listing-image {
    position: absolute;
    inset: 0 0 3rem;
    overflow: hidden;
  }
  .listing-image img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .listing-image::after {
    content: "";
    position: absolute;
    inset: 40% 0 0;
    background: linear-gradient(transparent, var(--color-grey-0));
  }
  .listing-copy {
    position: relative;
    z-index: 1;
    margin-top: auto;
    padding: var(--spacing-5) var(--spacing-8);
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
  }
  .listing-title {
    font-size: 0.875rem;
    font-weight: 650;
    line-height: 1.3;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
  }
  .listing-price {
    font-size: 0.75rem;
    color: var(--color-font-secondary);
  }
  .listing-extra span {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-2);
  }
  .listing-extra {
    display: none;
    gap: var(--spacing-6);
    color: var(--color-font-secondary);
    font-size: 0.75rem;
  }
  .without-image .listing-copy {
    margin-block: auto;
    padding-top: var(--spacing-20);
  }
  .without-image .listing-extra {
    display: flex;
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  @container result-card (min-width: 400px) {
    .listing-card {
      flex-direction: row;
    }
    .listing-copy {
      width: 34%;
      min-width: 0;
      margin-block: auto;
      box-sizing: border-box;
      padding: var(--spacing-10) var(--spacing-6);
    }
    .listing-image {
      inset: 0 0 0 34%;
    }
    .listing-image::after {
      display: none;
    }
    .listing-extra {
      display: flex;
      flex-wrap: wrap;
    }
  }
</style>
