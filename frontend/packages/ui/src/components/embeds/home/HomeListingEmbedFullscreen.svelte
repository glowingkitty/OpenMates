<!-- Home listing details: shared facts/media layout, uncropped gallery and provider-backed location precision. -->

<script lang="ts">
  import ResultEmbedFullscreen from "../ResultEmbedFullscreen.svelte";
  import EmbedChevron from "../EmbedChevron.svelte";
  import ResultEmbedInfo from "../ResultEmbedInfo.svelte";
  import { getLucideIcon } from "../../../utils/categoryUtils";
  const MapPin = getLucideIcon("map-pin");
  import EmbedHeaderCtaButton from "../EmbedHeaderCtaButton.svelte";
  import {
    proxyImage,
    MAX_WIDTH_HEADER_IMAGE,
  } from "../../../utils/imageProxy";
  import { text } from "../../../i18n/translations";
  import {
    homeListingContent,
    homeNumber,
    homeObject,
    homeImages,
    homeBoolean,
    homeApproximate,
    homeMapGeometry,
    homeMapLabel,
    homeEvidence,
  } from "./homeListingData";
  import { handleImageError } from "../../../utils/offlineImageHandler";
  import { authStore } from "../../../stores/authStore";
  import { appSettingsMemoriesStore } from "../../../stores/appSettingsMemoriesStore";
  import {
    findSavedEmbedMemoryEntry,
    forgetEmbedMemory,
    getEmbedIdFromContentRef,
    promptToSaveEmbedMemory,
    saveEmbedMemory,
  } from "../../../services/savedEmbedMemoryService";
  import type { EmbedFullscreenRawData } from "../../../types/embedFullscreen";

  /**
   * Props for listing fullscreen view.
   * Receives raw embed data via `data` prop and extracts fields internally.
   */
  interface Props {
    /** Raw embed data containing decodedContent */
    data: EmbedFullscreenRawData;
    /** Close handler */
    onClose: () => void;
    /** Embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Direction of navigation */
    navigateDirection?: "previous" | "next";
    /** Whether to show the chat button (ultra-wide mode) */
    showChatButton?: boolean;
    /** Callback for chat button */
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  // Extract fields from data.decodedContent.
  // Must be $derived so it updates when navigating between results (prev/next).
  // Handles both direct fields and flat TOON format from _flatten_for_toon_tabular.
  let dc = $derived(homeListingContent(data.decodedContent));
  let url = $derived(typeof dc.url === "string" ? dc.url : "");
  let title = $derived(typeof dc.title === "string" ? dc.title : undefined);
  let price_label = $derived(
    typeof dc.price_label === "string" ? dc.price_label : undefined,
  );
  let size_sqm = $derived(homeNumber(dc.size_sqm));
  let rooms = $derived(homeNumber(dc.rooms));
  let address = $derived(
    typeof dc.address === "string" ? dc.address : undefined,
  );
  let image_url = $derived(
    typeof dc.image_url === "string" ? dc.image_url : undefined,
  );
  let provider = $derived(
    typeof dc.provider === "string" ? dc.provider : undefined,
  );
  let listing_type = $derived(
    typeof dc.listing_type === "string" ? dc.listing_type : undefined,
  );
  let available_from = $derived(
    typeof dc.available_from === "string" ? dc.available_from : undefined,
  );

  let imageIndex = $state(0);
  let failedImages = $state<string[]>([]);
  let images = $derived(homeImages(dc.image_urls, image_url));
  let activeImage = $derived(images[imageIndex]);
  let displayTitle = $derived(title || $text("home_listing.listing"));
  let approximate = $derived(homeApproximate(dc));
  let amenities = $derived(homeObject(dc.amenities));
  let evidence = $derived(homeObject(dc.match_evidence));
  let visual = $derived(homeObject(dc.visual_assessment));
  function featureLabel(key: string): string {
    return [
      ...amenityKeys,
      "water",
      "park",
      "transit",
      "groceries",
      "school",
    ].includes(key)
      ? $text(`home_listing.${key}`)
      : key.replaceAll("_", " ");
  }
  const readableStatuses = [
    "confirmed",
    "possible",
    "conflicting",
    "unknown",
    "unavailable",
    "unconfirmed",
    "partial",
    "evaluated",
    "visible",
    "not_visible",
    "uncertain",
    "present",
    "absent",
    "no_features_returned",
    "not_checked",
    "ok",
  ];
  function statusLabel(value: unknown): string {
    return typeof value === "string" && readableStatuses.includes(value)
      ? $text(`home_listing.status_${value}`)
      : $text("home_listing.unknown");
  }
  function yesNo(value: unknown): string {
    return homeBoolean(value) === true
      ? $text("home_listing.yes")
      : homeBoolean(value) === false
        ? $text("home_listing.no")
        : $text("home_listing.unknown");
  }
  function amenityValue(key: string): boolean | undefined {
    return homeBoolean(dc[key]) ?? homeBoolean(amenities[key]);
  }
  const amenityKeys = [
    "balcony",
    "furnished",
    "elevator",
    "garden",
    "terrace",
    "parking",
    "pets_allowed",
  ];
  const priceKeys = ["price", "price_type", "cold_rent_eur", "warm_rent_eur", "utilities_eur", "heating_costs_eur", "deposit"];
  const amenityIcons: Record<string, string> = {
    balcony: "fence",
    furnished: "armchair",
    elevator: "arrow-up-down",
    garden: "trees",
    terrace: "sun",
    parking: "car",
    pets_allowed: "paw-print",
  };
  let priceRows = $derived(
    priceKeys.filter(
      (key) => dc[key] !== null && dc[key] !== undefined && dc[key] !== "",
    ),
  );
  let summaryPrice = $derived.by(() => {
    const amount =
      homeNumber(dc.price) ??
      homeNumber(
        dc.price_type === "cold" ? dc.cold_rent_eur : dc.warm_rent_eur,
      );
    return amount !== undefined
      ? new Intl.NumberFormat().format(amount)
      : price_label || undefined;
  });
  let priceBasis = $derived(
    dc.price_type === "warm"
      ? $text("home_listing.warm_rent_eur")
      : dc.price_type === "cold"
        ? $text("home_listing.cold_rent_eur")
        : undefined,
  );
  let availability = $derived.by(() => {
    const parsed = parseAvailableFromDate(available_from);
    return parsed
      ? new Date(parsed).toLocaleDateString([], {
          month: "short",
          year: "numeric",
        })
      : available_from || "";
  });
  $effect(() => {
    void dc;
    imageIndex = 0;
    failedImages = [];
  });
  function navigateImage(offset: number) {
    imageIndex = (imageIndex + offset + images.length) % images.length;
  }
  function galleryKey(event: KeyboardEvent) {
    const handled = ["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key);
    if (event.key === "ArrowRight") {
      event.preventDefault();
      navigateImage(1);
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      navigateImage(-1);
    }
    if (event.key === "Home") {
      event.preventDefault();
      imageIndex = 0;
    }
    if (event.key === "End") {
      event.preventDefault();
      imageIndex = images.length - 1;
    }
    if (handled) {
      const selected = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLButtonElement>("button")[imageIndex];
      selected?.focus({ preventScroll: true });
      selected?.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }
  /** Extract hostname for CTA button label */
  let hostname = $derived.by(() => {
    try {
      return new URL(url).hostname.replace("www.", "");
    } catch {
      return provider || "listing";
    }
  });

  let geometry = $derived(homeMapGeometry(dc));
  let mapCenter = $derived(
    geometry ? { lat: geometry.lat, lon: geometry.lon } : undefined,
  );
  let mapMarkers = $derived(
    geometry
      ? [
          {
            ...geometry,
            homeLocation: true,
            testId: geometry.radiusM
              ? "home-location-area"
              : "home-location-pin",
            label: `${title || address || ""} · ${homeMapLabel(geometry, $text)}`,
          },
        ]
      : [],
  );

  /** Format size with unit */
  let sizeDisplay = $derived(size_sqm ? `${size_sqm} m\u00B2` : undefined);

  /** Format rooms count */
  let roomsDisplay = $derived(
    rooms ? `${rooms} ${rooms === 1 ? "room" : "rooms"}` : undefined,
  );

  /** Capitalize listing type */
  let typeDisplay = $derived(
    listing_type
      ? listing_type.charAt(0).toUpperCase() + listing_type.slice(1)
      : undefined,
  );

  /** Open listing on original platform */
  function handleOpenOnPlatform() {
    if (url) {
      window.open(url, "_blank", "noopener,noreferrer");
    }
    promptToSaveEmbedMemory(buildSaveConfig());
  }

  function parseAvailableFromDate(value: string | undefined): string | null {
    if (!value) return null;
    const germanDateMatch = value.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
    if (germanDateMatch) {
      const [, day, month, year] = germanDateMatch;
      return `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}T09:00:00`;
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
  }

  function buildSaveConfig() {
    const saveTitle = displayTitle || "Listing";
    return {
      kind: "home_listing" as const,
      appId: "home",
      itemType: "saved_listings",
      itemKey: `saved_listings.${url || saveTitle}`,
      title: saveTitle,
      reminderDateTime: parseAvailableFromDate(available_from),
      reminderPromptTitle: saveTitle,
      itemValue: {
        embed_id:
          embedId ||
          data.focusChildEmbedId ||
          getEmbedIdFromContentRef(data.attrs?.contentRef),
        title: saveTitle,
        url,
        provider: provider || hostname,
        price_label: price_label || "",
        address: address || "",
        available_from: available_from || "",
        notes: [sizeDisplay, roomsDisplay, typeDisplay]
          .filter(Boolean)
          .join(" · "),
      },
    };
  }

  let saveConfig = $derived(buildSaveConfig());
  let savedMemoryEntry = $derived(
    findSavedEmbedMemoryEntry($appSettingsMemoriesStore, saveConfig),
  );

  function handleToggleSavedListing() {
    if (savedMemoryEntry) {
      forgetEmbedMemory(saveConfig);
      return;
    }
    saveEmbedMemory(saveConfig);
  }
</script>

  {#snippet listingGallery()}
    <section
      class="gallery"
      class:partial-gallery={dc.gallery_status !== "complete" && images.length > 0}
      aria-label={$text("home_listing.photos")}
      data-testid="home-gallery"
    >
      {#if images.length}
        <div class="gallery-stage">
          {#if failedImages.includes(activeImage)}
            <p role="status">{$text("home_listing.photo_unavailable")}</p>
          {:else}
            <img
              src={proxyImage(activeImage, MAX_WIDTH_HEADER_IMAGE)}
              alt={displayTitle}
              class="listing-image"
              data-testid="home-gallery-image"
              onerror={(event) => {
                failedImages = [...failedImages, activeImage];
                handleImageError(event.currentTarget);
              }}
            />
          {/if}
        </div>
        <div class="gallery-controls">
          <button
            type="button"
            onclick={() => navigateImage(-1)}
            aria-label={$text("home_listing.previous_photo")}><EmbedChevron direction="previous" /></button
          >
          <button
            type="button"
            onclick={() => navigateImage(1)}
            aria-label={$text("home_listing.next_photo")}><EmbedChevron direction="next" /></button
          >
        </div>
        <div
          class="gallery-thumbnails"
          role="group"
          aria-label={$text("home_listing.photos")}
        >
          {#each images as image, index}
            <button
              type="button"
              class:selected={imageIndex === index}
              aria-label={`${$text("home_listing.photo")} ${index + 1}`}
              aria-pressed={imageIndex === index}
              onkeydown={galleryKey}
              onclick={() => (imageIndex = index)}
            >
              <img src={proxyImage(image, 160)} alt="" loading="lazy" onerror={(event) => handleImageError(event.currentTarget)} />
            </button>
          {/each}
        </div>
      {:else}
        <p>{$text("home_listing.no_photos")}</p>
      {/if}
      {#if dc.gallery_status !== "complete"}<p class="uncertainty">
          {$text("home_listing.partial_gallery")}
        </p>{/if}
    </section>
  {/snippet}


<ResultEmbedFullscreen
  media={images.length || !mapCenter ? listingGallery : undefined}
  appId="home"
  skillId="listing"
  embedHeaderTitle={displayTitle}
  skillIconName="home"
  result={dc}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  {mapCenter}
  mapZoom={dc.location_precision === "city"
    ? 10
    : dc.location_precision === "district"
      ? 12
      : 14}
  {mapMarkers}
>
  {#snippet embedHeaderCta()}
    <div class="embed-header-cta-group">
      {#if $authStore.isAuthenticated}
        <EmbedHeaderCtaButton
          label={savedMemoryEntry ? "Forget" : "Add memory"}
          variant="secondary" iconName="heart" iconOnly pressed={!!savedMemoryEntry}
          onclick={handleToggleSavedListing}
          testId="save-embed-cta"
        />
      {/if}
      {#if url}
        <EmbedHeaderCtaButton
          label="Open on {hostname}"
          onclick={handleOpenOnPlatform}
          testId="external-provider-cta"
        />
      {/if}
    </div>
  {/snippet}

  {#snippet summary()}
    {#if price_label || priceRows.length}<ResultEmbedInfo
      icon="euro" label={price_label || $text("home_listing.price")} value={summaryPrice} caption={priceBasis} testId="home-price-info"
    >
      {#snippet children()}
        {#if price_label}<p>{price_label}</p>{/if}
        <dl data-testid="home-price-summary">
          {#each priceRows as key}<div><dt>{$text(`home_listing.${key}`)}</dt><dd>{key === "price_type" ? priceBasis || homeEvidence(dc[key]) : homeEvidence(dc[key])}{key.endsWith("_eur") ? " EUR" : ""}</dd></div>{/each}
        </dl>
        {#if provider}<p>{provider} · {$text("home_listing.advertised_evidence")}</p>{/if}
      {/snippet}
    </ResultEmbedInfo>{/if}
    {#if available_from || dc.available_to}<ResultEmbedInfo
      icon="calendar-days" label={$text(available_from ? "home_listing.available_from" : "home_listing.available_to")} value={availability || homeEvidence(dc.available_to)} caption={$text(available_from ? "home_listing.available_from" : "home_listing.available_to")} testId="home-availability-info"
    >
      {#snippet children()}
        {#if available_from}<p>{$text("home_listing.available_from")}: {available_from}</p>{/if}
        {#if dc.available_to}<p>{$text("home_listing.available_to")}: {homeEvidence(dc.available_to)}</p>{/if}
      {/snippet}
    </ResultEmbedInfo>{/if}
    {#if sizeDisplay || roomsDisplay || typeDisplay || (dc.floor !== undefined && dc.floor !== null && dc.floor !== "")}<ResultEmbedInfo
      icon="house" label={sizeDisplay || roomsDisplay || $text("home_listing.floor")} value={sizeDisplay || roomsDisplay || typeDisplay} testId="home-size-info"
    >
      {#snippet children()}
        {#if sizeDisplay}<p>{sizeDisplay}</p>{/if}{#if roomsDisplay}<p>{roomsDisplay}</p>{/if}
        {#if dc.floor !== undefined && dc.floor !== null && dc.floor !== ''}<p>{$text("home_listing.floor")}: {homeEvidence(dc.floor)}</p>{/if}
        {#if typeDisplay}<p>{typeDisplay}</p>{/if}
      {/snippet}
    </ResultEmbedInfo>{/if}
  {/snippet}

  {#snippet detailContent()}
    {#if address}
      <div class="result-location">
        <MapPin
          size={28}
          color="var(--color-app-home-start)"
          aria-hidden="true"
        />
        <div>
          <strong>{address}</strong><small data-testid="home-location-label">{approximate ? $text("home_listing.approximate") : $text("home_listing.building")}</small>
          {#if geometry?.radiusM}<small data-testid="home-location-area-label">{homeMapLabel(geometry, $text)}</small>{/if}
        </div>
      </div>
    {/if}
    {#if typeof dc.description === "string" && dc.description}<p
        class="result-description"
      >
        {dc.description}
      </p>{/if}
    <div class="result-icon-row" data-testid="home-amenities">
      {#each amenityKeys as key}
        {@const match = homeObject(homeObject(evidence.amenities)[key])}
        {@const feature = homeObject(homeObject(visual.features)[key])}
        <ResultEmbedInfo icon={amenityIcons[key]} label={`${featureLabel(key)}: ${yesNo(amenityValue(key))}`} state={amenityValue(key) === true ? "yes" : amenityValue(key) === false ? "no" : "unknown"} testId={`home-amenity-${key}`}>
          {#snippet children()}
            <p>{featureLabel(key)}: {yesNo(amenityValue(key))}</p>
            {#if provider}<p>{provider} · {$text("home_listing.advertised_evidence")}</p>{/if}
            {#if match.status}<p>{$text("home_listing.match_status")}: {statusLabel(match.status)}</p>{/if}
            {#if match.advertised !== undefined}<p data-testid="home-advertised-evidence">{$text("home_listing.advertised_fact")}: {yesNo(match.advertised)}</p>{/if}
            {#if match.text_status}<p>{$text("home_listing.listing_text")}: {statusLabel(match.text_status)}</p>{/if}
            {#if match.visual_status || feature.status}<p>{$text("home_listing.photo_evidence")}: {statusLabel(match.visual_status ?? feature.status)}</p>{/if}
            {#if homeBoolean(match.source_conflict) === true}<p>{$text("home_listing.status_conflicting")}</p>{/if}
            {#if visual.status}<p>{$text("home_listing.visual_evidence")}: {statusLabel(visual.status)}{#if homeNumber(visual.photo_count) !== undefined} · {homeNumber(visual.photo_count)} / {homeNumber(visual.total_photo_count) ?? images.length} {$text("home_listing.photos_assessed")}{/if}</p>{/if}
          {/snippet}
        </ResultEmbedInfo>
      {/each}
    </div>
  {/snippet}
</ResultEmbedFullscreen>

<style>
  .gallery {position:relative;min-width:0;height:var(--result-media-height, clamp(16rem, 35vh, 26rem));margin-bottom:1.5rem;overflow:visible;}
  .partial-gallery {margin-bottom:3.5rem;}
  .gallery>.uncertainty {position:absolute;top:calc(100% + 1.5rem);padding:0;}
  .gallery-stage {height:100%;background:var(--color-grey-25);display:grid;place-items:center;overflow:hidden;border-radius:var(--radius-6);}
  .listing-image {display:block;width:100%;height:100%;object-fit:contain;}
  .gallery-controls {position:absolute;inset-inline:var(--spacing-3);top:50%;transform:translateY(-50%);display:flex;align-items:center;justify-content:space-between;pointer-events:none;}
  .gallery-controls button {all:unset;box-sizing:border-box;display:grid;place-items:center;pointer-events:auto;width:36px;height:44px;cursor:pointer;color:white;}
  .gallery button:focus-visible {outline:2px solid var(--color-button-primary);outline-offset:2px;}
  .gallery-thumbnails {position:absolute;bottom:-22px;left:var(--spacing-4);right:var(--spacing-4);display:flex;justify-content:safe center;gap:var(--spacing-2);overflow-x:auto;padding:var(--spacing-1);z-index:2;}
  .gallery-thumbnails button {all:unset;box-sizing:border-box;position:relative;flex:0 0 44px;width:44px;height:44px;aspect-ratio:1;border-radius:var(--radius-4);overflow:hidden;cursor:pointer;}
  .gallery-thumbnails button::after {content:"";position:absolute;inset:0;background:rgb(255 255 255 / 60%);opacity:1;transition:opacity var(--duration-fast) var(--easing-default);pointer-events:none;}
  .gallery-thumbnails button.selected::after,.gallery-thumbnails button:hover::after,.gallery-thumbnails button:focus-visible::after {opacity:0;}
  .gallery-thumbnails img {width:100%;height:100%;object-fit:cover;display:block;}
  .gallery > p {padding:var(--spacing-4);margin:0;font-size:var(--font-size-small);}
  .result-location small {display:block;color:var(--color-font-tertiary);font-size:var(--font-size-small);margin-top:var(--spacing-2);}
  dl {margin:var(--spacing-3) 0;} dl>div {display:flex;justify-content:space-between;gap:var(--spacing-4);padding-block:var(--spacing-1);} dd {margin:0;}
</style>
