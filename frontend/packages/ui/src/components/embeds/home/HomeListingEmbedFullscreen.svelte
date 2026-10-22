<!--
  frontend/packages/ui/src/components/embeds/home/HomeListingEmbedFullscreen.svelte

  Fullscreen view for a single Home listing embed (child of search results).
  Uses ResultEmbedFullscreen for the shared centered result layout — same
  pattern as EventEmbedFullscreen and HealthAppointmentEmbedFullscreen.

  Shows an interactive map when the listing has latitude/longitude coordinates
  (geocoded by the backend search skill). Falls back to details-only layout
  when no coordinates are available.

  Layout:
  - Map background with detail card overlay (wide) or stacked (narrow)
  - Listing photo, price, address
  - Metadata: size, rooms, listing type, provider, available from, deposit
  - "Open on {provider}" CTA button
-->

<script lang="ts">
  import ResultEmbedFullscreen from "../ResultEmbedFullscreen.svelte";
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
  let latitude = $derived(homeNumber(dc.latitude));
  let longitude = $derived(homeNumber(dc.longitude));

  let imageIndex = $state(0);
  let failedImages = $state<string[]>([]);
  let images = $derived(homeImages(dc.image_urls, image_url));
  let activeImage = $derived(images[imageIndex]);
  let displayTitle = $derived(title || $text("home_listing.listing"));
  let approximate = $derived(homeApproximate(dc));
  let amenities = $derived(homeObject(dc.amenities));
  let evidence = $derived(homeObject(dc.match_evidence));
  let visual = $derived(homeObject(dc.visual_assessment));
  let neighborhood = $derived(homeObject(dc.neighborhood));
  let matchAmenities = $derived(Object.entries(homeObject(evidence.amenities)));
  let photoFeatures = $derived(Object.entries(homeObject(visual.features)));
  let neighborhoodCategories = $derived(
    Object.entries(homeObject(neighborhood.features)),
  );
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
  function neighborhoodPlaces(value: unknown): Record<string, unknown>[] {
    return (Array.isArray(value) ? value : []).map(homeObject);
  }
  function checkedDate(value: unknown): string {
    return typeof value === "string" && !Number.isNaN(Date.parse(value))
      ? value.slice(0, 10)
      : $text("home_listing.unknown");
  }
  function distanceValue(place: Record<string, unknown>): number | undefined {
    const distance = homeNumber(place.distance_m);
    return !approximate &&
      [
        "shoreline_geometry",
        "feature_geometry",
        "representative_point",
      ].includes(String(place.distance_method)) &&
      place.location_precision === "building" &&
      distance !== undefined &&
      distance >= 0
      ? distance
      : undefined;
  }
  function distanceLabel(
    place: Record<string, unknown>,
    category: string,
  ): string {
    if (distanceValue(place) === undefined)
      return $text(
        category === "water"
          ? "home_listing.shoreline_unknown"
          : "home_listing.distance_unknown",
      );
    if (place.distance_method === "shoreline_geometry" && category === "water")
      return $text("home_listing.shoreline_distance");
    return $text(
      place.distance_method === "representative_point"
        ? "home_listing.point_distance"
        : "home_listing.geometry_distance",
    );
  }
  function walkingMinutes(place: Record<string, unknown>): number | undefined {
    const minutes = homeNumber(place.walk_minutes);
    return !approximate &&
      place.location_precision === "building" &&
      place.walk_status === "routed" &&
      minutes !== undefined &&
      minutes >= 0
      ? minutes
      : undefined;
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
  const detailKeys = [
    "price",
    "price_type",
    "cold_rent_eur",
    "warm_rent_eur",
    "utilities_eur",
    "heating_costs_eur",
    "floor",
    "available_from",
    "available_to",
    "deposit",
  ];
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
    ["price_type", "cold_rent_eur", "warm_rent_eur"].filter(
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
      : price_label || $text("home_listing.unknown");
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
  let locationArea = $derived(homeObject(homeObject(dc.location).area));

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

<ResultEmbedFullscreen
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
          variant={savedMemoryEntry ? "destructive" : "secondary"}
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
    <ResultEmbedInfo
      icon="euro"
      label={price_label || $text("home_listing.price")}
      value={summaryPrice}
      caption={priceBasis}
    />
    {#if available_from}<ResultEmbedInfo
        icon="calendar-days"
        label={`${$text("home_listing.available_from")}: ${available_from}`}
        value={availability}
        caption={$text("home_listing.available_from")}
      />{/if}
    {#if sizeDisplay}<ResultEmbedInfo
        icon="house"
        label={sizeDisplay}
        value={sizeDisplay}
      />{/if}
  {/snippet}

  {#snippet media()}
    <section
      class="gallery"
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
              alt={`${displayTitle} — ${imageIndex + 1} / ${images.length}`}
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
            aria-label={$text("home_listing.previous_photo")}>←</button
          >
          <span aria-live="polite" data-testid="home-gallery-counter"
            >{imageIndex + 1} / {images.length}</span
          >
          <button
            type="button"
            onclick={() => navigateImage(1)}
            aria-label={$text("home_listing.next_photo")}>→</button
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
              <img src={proxyImage(image, 160)} alt="" loading="lazy" />
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

  {#snippet detailContent()}
    {#if address}
      <div class="result-location">
        <MapPin
          size={28}
          color="var(--color-app-home-start)"
          aria-hidden="true"
        />
        <div>
          <strong>{address}</strong><small
            >{approximate
              ? $text("home_listing.approximate")
              : $text("home_listing.building")}</small
          >
        </div>
        <ResultEmbedInfo
          icon="info"
          label={$text("home_listing.location")}
          testId="home-location-info"
        >
          <section class="listing-section" data-testid="home-location-evidence">
            <h3>{$text("home_listing.location")}</h3>
            <p>
              {geometry
                ? geometry.radiusM
                  ? $text("home_listing.approximate")
                  : $text("home_listing.building")
                : latitude !== undefined && longitude !== undefined
                  ? $text("home_listing.approximate")
                  : $text("home_listing.no_location")}
            </p>
            <p>
              {homeEvidence(dc.location_precision)} · {homeEvidence(
                dc.location_source,
              )}
            </p>
            {#if geometry?.radiusM}
              <p data-testid="home-location-area-label">
                {homeMapLabel(geometry, $text)}
              </p>
              <p>{homeEvidence(locationArea.source)}</p>
              {#if locationArea.anchor_name}<p>
                  {homeEvidence(locationArea.anchor_name)}
                </p>{/if}
              {#if locationArea.evidence_quote}<blockquote>
                  {homeEvidence(locationArea.evidence_quote)}
                </blockquote>{/if}
            {:else if approximate && latitude !== undefined && longitude !== undefined}
              <p>{$text("home_listing.area_unavailable")}</p>
            {/if}
            {#if approximate}<p class="uncertainty">
                {$text("home_listing.location_warning")}
              </p>{/if}
          </section>
        </ResultEmbedInfo>
      </div>
    {/if}
    {#if typeof dc.description === "string" && dc.description}<p
        class="result-description"
      >
        {dc.description}
      </p>{/if}
    <div class="result-icon-row" data-testid="home-amenities">
      {#each amenityKeys as key}
        <ResultEmbedInfo
          icon={amenityIcons[key]}
          label={`${featureLabel(key)}: ${yesNo(amenityValue(key))}`}
          state={amenityValue(key) === true
            ? "yes"
            : amenityValue(key) === false
              ? "no"
              : "unknown"}
          testId={`home-amenity-${key}`}
        />
      {/each}
    </div>
    {#if priceRows.length}
      <dl class="price-card" data-testid="home-price-summary">
        {#each priceRows as key}<div>
            <dt>{$text(`home_listing.${key}`)}</dt>
            <dd>{homeEvidence(dc[key])}{key.endsWith("_eur") ? " EUR" : ""}</dd>
          </div>{/each}
      </dl>
    {/if}
    <div class="result-icon-row" data-testid="home-evidence-icons">
      <ResultEmbedInfo
        icon="list"
        label={$text("home_listing.details")}
        testId="home-details-info"
      >
        <section class="listing-section" data-testid="home-listing-facts">
          <h3>{$text("home_listing.details")}</h3>
          <dl>
            {#each detailKeys as key}<div>
                <dt>{$text(`home_listing.${key}`)}</dt>
                <dd>
                  {homeEvidence(dc[key])}{key.endsWith("_eur") &&
                  homeNumber(dc[key]) !== undefined
                    ? " EUR"
                    : ""}
                </dd>
              </div>{/each}
          </dl>
        </section>
        {#if roomsDisplay}<p>{roomsDisplay}</p>{/if}{#if typeDisplay}<p>
            {typeDisplay}
          </p>{/if}
      </ResultEmbedInfo>
      <ResultEmbedInfo
        icon="badge-check"
        label={$text("home_listing.match_evidence")}
        testId="home-match-info"
      >
        <section class="listing-section" data-testid="home-match-evidence">
          <h3>{$text("home_listing.match_evidence")}</h3>
          {#if provider}<p class="uncertainty">
              {provider} · {$text("home_listing.advertised_evidence")}
            </p>{/if}
          <p>{statusLabel(evidence.status)}</p>
          {#each matchAmenities as [key, rawMatch]}
            {@const match = homeObject(rawMatch)}
            <article class="evidence-card">
              <h4>{featureLabel(key)}</h4>
              <dl>
                <div>
                  <dt>{$text("home_listing.match_status")}</dt>
                  <dd>{statusLabel(match.status)}</dd>
                </div>
                {#if match.expectation === "absent"}<div>
                    <dt>{$text("home_listing.requirement")}</dt>
                    <dd>{$text("home_listing.status_absent")}</dd>
                  </div>{/if}
                <div data-testid="home-advertised-evidence">
                  <dt>{$text("home_listing.advertised_fact")}</dt>
                  <dd>{yesNo(match.advertised)}</dd>
                </div>
                <div>
                  <dt>{$text("home_listing.listing_text")}</dt>
                  <dd>{statusLabel(match.text_status)}</dd>
                </div>
                <div>
                  <dt>{$text("home_listing.photo_evidence")}</dt>
                  <dd>{statusLabel(match.visual_status)}</dd>
                </div>
              </dl>
            </article>
          {/each}
        </section>
      </ResultEmbedInfo>
      <ResultEmbedInfo
        icon="scan-eye"
        label={$text("home_listing.visual_evidence")}
        testId="home-visual-info"
      >
        <section class="listing-section" data-testid="home-visual-evidence">
          <h3>{$text("home_listing.visual_evidence")}</h3>
          <p class="uncertainty">{$text("home_listing.assessment_warning")}</p>
          <p>
            {statusLabel(visual.status)} · {homeNumber(visual.photo_count) ?? 0} /
            {homeNumber(visual.total_photo_count) ?? images.length}
            {$text("home_listing.photos_assessed")}
          </p>
          <dl>
            {#each photoFeatures as [key, rawFeature]}{@const feature =
                homeObject(rawFeature)}
              <div>
                <dt>{featureLabel(key)}</dt>
                <dd>{statusLabel(feature.status)}</dd>
              </div>{/each}
          </dl>
        </section>
      </ResultEmbedInfo>
      <ResultEmbedInfo
        icon="trees"
        label={$text("home_listing.neighborhood")}
        testId="home-neighborhood-info"
      >
        <section
          class="listing-section"
          data-testid="home-neighborhood-evidence"
        >
          <h3>{$text("home_listing.neighborhood")}</h3>
          <p>{statusLabel(neighborhood.status)}</p>
          <p class="uncertainty">
            {$text("home_listing.source")}: {typeof neighborhood.source ===
            "string"
              ? neighborhood.source
              : $text("home_listing.unknown")} · {$text(
              "home_listing.checked",
            )}: {checkedDate(neighborhood.checked_at)}
          </p>
          {#each neighborhoodCategories as [category, rawPlaces]}
            {@const places = neighborhoodPlaces(rawPlaces)}
            {@const coverage = homeObject(
              homeObject(neighborhood.coverage)[category],
            )}
            <div
              class="neighborhood-category"
              data-testid="home-neighborhood-category"
            >
              <h4>{featureLabel(category)}</h4>
              <p class="uncertainty">
                {statusLabel(coverage.status)} · {$text(
                  "home_listing.limited_coverage",
                )}
              </p>
              {#each places as place}
                <article class="evidence-card" data-testid="home-nearby-place">
                  <h5>
                    {typeof place.name === "string"
                      ? place.name
                      : featureLabel(category)}
                  </h5>
                  <p data-testid="home-place-distance">
                    {distanceLabel(place, category)}{distanceValue(place) !==
                    undefined
                      ? `: ${distanceValue(place)} m`
                      : ""}
                  </p>
                  <p data-testid="home-place-walking">
                    {walkingMinutes(place) !== undefined
                      ? `${$text("home_listing.routed_walk")}: ${walkingMinutes(place)} ${$text("home_listing.minutes")}`
                      : $text("home_listing.walking_unknown")}
                  </p>
                  <p class="uncertainty">
                    {$text("home_listing.source")}: {typeof place.source ===
                    "string"
                      ? place.source
                      : typeof neighborhood.source === "string"
                        ? neighborhood.source
                        : $text("home_listing.unknown")} · {$text(
                      "home_listing.checked",
                    )}: {checkedDate(
                      place.checked_at ?? neighborhood.checked_at,
                    )}
                  </p>
                </article>
              {:else}
                <p>{$text("home_listing.no_nearby_evidence")}</p>
              {/each}
            </div>
          {/each}
        </section>
      </ResultEmbedInfo>
      {#if dc.enrichment_warnings || dc.warnings}<ResultEmbedInfo
          icon="triangle-alert"
          label={homeEvidence(dc.enrichment_warnings ?? dc.warnings)}
        />{/if}
    </div>
  {/snippet}
</ResultEmbedFullscreen>

<style>
  .gallery {
    position: relative;
    min-width: 0;
  }
  .gallery-stage {
    height: clamp(13rem, 28vh, 19rem);
    background: var(--color-grey-25);
    display: grid;
    place-items: center;
    overflow: hidden;
  }
  .listing-image {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .gallery-controls {
    position: absolute;
    inset-inline: var(--spacing-3);
    top: 40%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    pointer-events: none;
  }
  .gallery-controls button {
    all: unset;
    box-sizing: border-box;
    display: grid;
    place-items: center;
    pointer-events: auto;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 0;
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: var(--shadow-sm);
    cursor: pointer;
  }
  .gallery-controls span {
    position: absolute;
    right: var(--spacing-2);
    top: -5rem;
    font-size: 0.75rem;
    border-radius: var(--radius-3);
    padding: var(--spacing-2) var(--spacing-3);
    background: var(--color-grey-0);
  }
  .gallery button:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 2px;
  }
  .gallery-thumbnails {
    display: flex;
    justify-content: flex-start;
    gap: var(--spacing-2);
    overflow-x: auto;
    padding: var(--spacing-3);
    background: var(--color-grey-0);
  }
  .gallery-thumbnails button {
    all: unset;
    box-sizing: border-box;
    flex: 0 0 44px;
    width: 44px;
    height: 32px;
    padding: 0;
    border: 2px solid transparent;
    border-radius: var(--radius-3);
    overflow: hidden;
    cursor: pointer;
  }
  .gallery-thumbnails .selected {
    border-color: var(--color-button-primary);
  }
  .gallery-thumbnails img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .gallery > p {
    padding: var(--spacing-6);
    margin: 0;
    font-size: 0.75rem;
  }
  .result-location small {
    display: block;
    color: var(--color-font-tertiary);
    font-size: 0.75rem;
    margin-top: var(--spacing-2);
  }
  .price-card {
    box-sizing: border-box;
    width: min(100%, 30rem);
    margin: 0;
    padding: var(--spacing-10) var(--spacing-12);
    border-radius: var(--radius-6);
    background: var(--color-grey-0);
    display: grid;
    gap: var(--spacing-5);
    font-size: 0.875rem;
  }
  .price-card > div {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--spacing-8);
  }
  .price-card dt {
    color: var(--color-font-tertiary);
  }
  .price-card dd {
    margin: 0;
  }
</style>
