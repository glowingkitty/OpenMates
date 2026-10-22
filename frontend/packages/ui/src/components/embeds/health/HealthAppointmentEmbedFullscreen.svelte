<!--
  frontend/packages/ui/src/components/embeds/health/HealthAppointmentEmbedFullscreen.svelte

  Fullscreen detail view for a single appointment slot.
  Uses the shared ResultEmbedFullscreen layout with a wide map and compact facts.

  Shows map when gps_coordinates are available (Doctolib provides gpsPoint).
  Falls back to details-only layout when no coordinates.

  Shows:
  - Appointment slot datetime (prominent)
  - Doctor name, speciality, address
  - Telehealth/insurance badges
  - "Book on Doctolib" CTA linking to the practice_url

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import ResultEmbedFullscreen from "../ResultEmbedFullscreen.svelte";
  import ResultEmbedInfo from "../ResultEmbedInfo.svelte";
  import { getLucideIcon } from "../../../utils/categoryUtils";
  import { tooltip } from "../../../actions/tooltip";
  const MapPin = getLucideIcon("map-pin");
  const Phone = getLucideIcon("phone");
  const Globe = getLucideIcon("globe");
  const MapIcon = getLucideIcon("map");
  import EmbedHeaderCtaButton from "../EmbedHeaderCtaButton.svelte";
  import { text } from "@repo/ui";
  import {
    downloadCalendarFile,
    sanitizeCalendarFilename,
  } from "../../../utils/calendarDownload";
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

  interface GoogleReview {
    author?: string;
    rating?: number;
    text?: string;
    language?: string;
    relative_time?: string;
  }

  interface AppointmentData {
    embed_id: string;
    /** ISO datetime for this specific appointment slot */
    slot_datetime?: string;
    name?: string;
    speciality?: string;
    address?: string;
    gps_coordinates?: { latitude: number; longitude: number };
    insurance?: string;
    telehealth?: boolean;
    practice_url?: string;
    provider?: string;
    provider_platform?: string;
    // Jameda-specific fields (null for Doctolib results)
    booking_url?: string;
    rating?: number;
    rating_count?: number;
    rating_sources?: string[];
    price?: number;
    service_name?: string;
    // Alternate slot times (same doctor, next 5 available)
    additional_slot_datetimes?: string[];
    additional_slot_count?: number;
    // Google Places enrichment
    google_reviews?: GoogleReview[];
    opening_hours?: string[];
    phone?: string;
    website?: string;
    description?: string;
    google_maps_uri?: string;
    business_status?: string;
    accessibility?: string[];
  }

  interface Props {
    /** Raw embed data containing decodedContent */
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  // Build appointment object from data.decodedContent.
  // Must be $derived so it updates when navigating between results (prev/next).
  // Handles both nested gps_coordinates object (from search transformer) and flat TOON
  // fields (gps_coordinates_latitude, gps_coordinates_longitude — from _flatten_for_toon_tabular).
  let dc = $derived(data.decodedContent);

  /** Parse a number from unknown value (handles TOON string→number edge cases). */
  function asNumber(v: unknown): number | undefined {
    if (typeof v === "number" && Number.isFinite(v)) return v;
    if (typeof v === "string") {
      const n = Number(v);
      if (Number.isFinite(n)) return n;
    }
    return undefined;
  }

  function asString(v: unknown): string | undefined {
    return typeof v === "string" ? v : undefined;
  }

  function asStringArray(v: unknown): string[] | undefined {
    if (!Array.isArray(v)) return undefined;
    const out: string[] = [];
    for (const s of v)
      if (typeof s === "string" && s.trim().length > 0) out.push(s);
    return out.length > 0 ? out : undefined;
  }

  function parseGoogleReviews(v: unknown): GoogleReview[] | undefined {
    if (!Array.isArray(v)) return undefined;
    const out: GoogleReview[] = [];
    for (const entry of v) {
      if (entry && typeof entry === "object") {
        const r = entry as Record<string, unknown>;
        out.push({
          author: asString(r.author),
          rating: asNumber(r.rating),
          text: asString(r.text),
          language: asString(r.language),
          relative_time: asString(r.relative_time),
        });
      }
    }
    return out.length > 0 ? out : undefined;
  }

  function parseGps(
    content: Record<string, unknown>,
  ): AppointmentData["gps_coordinates"] {
    // Nested: gps_coordinates: { latitude, longitude }
    const gps = content.gps_coordinates;
    if (gps && typeof gps === "object") {
      const g = gps as Record<string, unknown>;
      const lat = asNumber(g.latitude) ?? asNumber(g.lat);
      const lon = asNumber(g.longitude) ?? asNumber(g.lon);
      if (lat != null && lon != null) return { latitude: lat, longitude: lon };
    }
    // Flat TOON: gps_coordinates_latitude, gps_coordinates_longitude
    const flatLat = asNumber(content.gps_coordinates_latitude);
    const flatLon = asNumber(content.gps_coordinates_longitude);
    if (flatLat != null && flatLon != null)
      return { latitude: flatLat, longitude: flatLon };
    return undefined;
  }

  let appointment: AppointmentData = $derived.by(() => ({
    embed_id: asString(dc.embed_id) || embedId || "",
    slot_datetime: asString(dc.slot_datetime),
    name: asString(dc.name),
    speciality: asString(dc.speciality),
    address: asString(dc.address),
    gps_coordinates: parseGps(dc),
    insurance: asString(dc.insurance),
    telehealth: typeof dc.telehealth === "boolean" ? dc.telehealth : undefined,
    practice_url: asString(dc.practice_url),
    provider: asString(dc.provider),
    provider_platform: asString(dc.provider_platform),
    booking_url: asString(dc.booking_url),
    rating: asNumber(dc.rating),
    rating_count: asNumber(dc.rating_count),
    rating_sources: asStringArray(dc.rating_sources),
    price: asNumber(dc.price),
    service_name: asString(dc.service_name),
    additional_slot_datetimes: asStringArray(dc.additional_slot_datetimes),
    additional_slot_count: asNumber(dc.additional_slot_count),
    google_reviews: parseGoogleReviews(dc.google_reviews),
    opening_hours: asStringArray(dc.opening_hours),
    phone: asString(dc.phone),
    website: asString(dc.website),
    description: asString(dc.description),
    google_maps_uri: asString(dc.google_maps_uri),
    business_status: asString(dc.business_status),
    accessibility: asStringArray(dc.accessibility),
  }));

  /** Format an ISO slot as a short "Sat, 14:00" label for the alternate-times list. */
  function formatAlternateSlot(iso: string): string {
    try {
      const dt = new Date(iso);
      return (
        dt.toLocaleDateString([], {
          weekday: "short",
          day: "numeric",
          month: "short",
        }) +
        " · " +
        dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      );
    } catch {
      return iso;
    }
  }

  /** Map accessibility flag keys to translated labels. */
  function accessibilityLabel(flag: string): string {
    const key = `embeds.health.${flag}`;
    const translated = $text(key);
    // If the key isn't found, $text returns the key itself — fall back to the raw flag
    return translated !== key ? translated : flag;
  }

  function getAddressLines(value: unknown): string[] {
    if (typeof value !== "string" || !value.trim()) return [];
    return value
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }

  // appointment is always an object (from $derived.by above), so alias directly
  let activeAppointment = $derived(appointment);

  function formatSlot(iso: string): string {
    try {
      const dt = new Date(iso);
      return (
        dt.toLocaleDateString([], {
          weekday: "long",
          month: "long",
          day: "numeric",
        }) +
        " \u00b7 " +
        dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      );
    } catch {
      return iso;
    }
  }

  let effectiveSlotDatetime = $derived(
    activeAppointment?.slot_datetime || null,
  );

  // Map data from gps_coordinates
  let mapCenter = $derived(
    activeAppointment?.gps_coordinates?.latitude != null &&
      activeAppointment?.gps_coordinates?.longitude != null
      ? {
          lat: activeAppointment.gps_coordinates.latitude,
          lon: activeAppointment.gps_coordinates.longitude,
        }
      : undefined,
  );

  let mapMarkers = $derived(
    mapCenter
      ? [
          {
            lat: mapCenter.lat,
            lon: mapCenter.lon,
            label: activeAppointment?.name || activeAppointment?.speciality,
          },
        ]
      : [],
  );

  let addressLines = $derived(getAddressLines(activeAppointment?.address));

  /** Booking platform name for labels/disclaimer — falls back to a generic word. */
  let providerName = $derived(
    activeAppointment?.provider_platform?.trim() || "the provider",
  );

  let insuranceValue = $derived(
    activeAppointment.insurance === "public"
      ? $text("embeds.search_domain.insurance_public")
      : activeAppointment.insurance === "private"
        ? $text("embeds.search_domain.insurance_private")
        : "?",
  );
  let insuranceLabel = $derived(
    activeAppointment.insurance === "unknown"
      ? $text("embeds.health.insurance_verify_tooltip").replace(
          "{provider}",
          providerName,
        )
      : `${$text("result_embed.insurance")}: ${insuranceValue}`,
  );

  /** Header title: formatted appointment date/time (most important info at a glance) */
  let headerTitle = $derived.by(() => {
    if (effectiveSlotDatetime) return formatSlot(effectiveSlotDatetime);
    return (
      activeAppointment?.name ||
      activeAppointment?.speciality ||
      $text("embeds.health.appointment")
    );
  });

  /** Header subtitle: doctor name + speciality (secondary context) */
  let headerSubtitle = $derived.by(() => {
    const parts: string[] = [];
    if (effectiveSlotDatetime && activeAppointment?.name)
      parts.push(activeAppointment.name);
    if (activeAppointment?.speciality) parts.push(activeAppointment.speciality);
    return parts.join(" · ") || undefined;
  });

  let bookingUrl = $derived(
    activeAppointment?.booking_url || activeAppointment?.practice_url || "",
  );

  function getSlotDate(iso: string | null | undefined): string {
    if (!iso) return "";
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) return iso.split("T")[0] || iso;
    return parsed.toISOString().split("T")[0];
  }

  function buildSaveConfig() {
    const title =
      activeAppointment?.name || activeAppointment?.speciality || "Appointment";
    const date = getSlotDate(effectiveSlotDatetime);
    return {
      kind: "health_appointment" as const,
      appId: "health",
      itemType: "appointments",
      itemKey: `appointments.${bookingUrl || title}.${effectiveSlotDatetime || ""}`,
      title,
      reminderDateTime: effectiveSlotDatetime,
      reminderPromptTitle: `${title}${effectiveSlotDatetime ? ` at ${formatSlot(effectiveSlotDatetime)}` : ""}`,
      itemValue: {
        embed_id:
          embedId ||
          data.focusChildEmbedId ||
          activeAppointment?.embed_id ||
          getEmbedIdFromContentRef(data.attrs?.contentRef),
        title: headerTitle,
        appointment_type: "doctor_visit",
        where: [activeAppointment?.name, activeAppointment?.speciality]
          .filter(Boolean)
          .join(" · "),
        date,
        appointment_time: effectiveSlotDatetime || "",
        notes: [activeAppointment?.address, bookingUrl]
          .filter(Boolean)
          .join("\n"),
      },
    };
  }

  let saveConfig = $derived(buildSaveConfig());
  let savedMemoryEntry = $derived(
    findSavedEmbedMemoryEntry($appSettingsMemoriesStore, saveConfig),
  );

  function handleToggleSavedAppointment() {
    if (savedMemoryEntry) {
      forgetEmbedMemory(saveConfig);
      return;
    }
    saveEmbedMemory(saveConfig);
  }

  function handleOpenAppointment() {
    if (bookingUrl) window.open(bookingUrl, "_blank", "noopener,noreferrer");
    promptToSaveEmbedMemory(buildSaveConfig());
  }

  function buildCalendarDescription(): string {
    return [
      activeAppointment?.speciality
        ? `Speciality: ${activeAppointment.speciality}`
        : "",
      activeAppointment?.service_name
        ? `Service: ${activeAppointment.service_name}`
        : "",
      activeAppointment?.provider_platform
        ? `Provider: ${activeAppointment.provider_platform}`
        : "",
      activeAppointment?.price != null
        ? `Price: ${activeAppointment.price} EUR`
        : "",
      bookingUrl,
    ]
      .filter(Boolean)
      .join("\n");
  }

  function handleAddToCalendar() {
    const calendarTitle =
      [activeAppointment?.name, activeAppointment?.speciality]
        .filter(Boolean)
        .join(" - ") || "Health appointment";
    downloadCalendarFile({
      title: calendarTitle,
      start: effectiveSlotDatetime || "",
      location: activeAppointment?.address,
      description: buildCalendarDescription(),
      url: bookingUrl,
      filename: sanitizeCalendarFilename(
        [calendarTitle, effectiveSlotDatetime?.slice(0, 10) || ""]
          .filter(Boolean)
          .join("-"),
      ),
    });
  }
</script>

{#if activeAppointment}
  <ResultEmbedFullscreen
    appId="health"
    decorationIconName="calendar"
    skillId="appointment"
    result={dc}
    {onClose}
    skillIconName="health"
    embedHeaderTitle={headerTitle}
    embedHeaderSubtitle={headerSubtitle}
    currentEmbedId={embedId}
    {hasPreviousEmbed}
    {hasNextEmbed}
    {onNavigatePrevious}
    {onNavigateNext}
    {mapCenter}
    mapZoom={16}
    {mapMarkers}
    onCalendar={effectiveSlotDatetime ? handleAddToCalendar : undefined}
  >
    {#snippet summary()}
      {#if activeAppointment.rating != null}<ResultEmbedInfo
          icon="star"
          label={`${activeAppointment.rating.toFixed(1)} · ${activeAppointment.rating_count ?? 0} ${$text("embeds.health.reviews")}`}
          value={activeAppointment.rating.toFixed(1)}
        />{/if}
      {#if activeAppointment.price != null}<ResultEmbedInfo
          icon="euro"
          label={`${activeAppointment.price} EUR`}
          value={`${activeAppointment.price} EUR`}
        />{/if}
      {#if activeAppointment.insurance}<ResultEmbedInfo
          icon="users"
          label={insuranceLabel}
          value={insuranceValue}
          caption={$text("result_embed.insurance")}
          state={activeAppointment.insurance === "unknown"
            ? "unknown"
            : undefined}
        />{/if}
    {/snippet}
    {#snippet detailContent()}
      <div class="result-location">
        <MapPin
          size={28}
          color="var(--color-app-health-start)"
          aria-hidden="true"
        />
        <div>
          {#if activeAppointment.name}<strong>{activeAppointment.name}</strong
            >{/if}
          {#each addressLines as line}<span>{line}</span>{/each}
        </div>
      </div>
      {#if activeAppointment.description}<p class="result-description">
          {activeAppointment.description}
        </p>{/if}
      <div class="result-icon-row" data-testid="health-detail-icons">
        <ResultEmbedInfo
          icon="stethoscope"
          label={$text("embeds.health.appointment")}
          testId="health-appointment-info"
        >
          {#if effectiveSlotDatetime}<p>
              {formatSlot(effectiveSlotDatetime)}
            </p>{/if}
          {#if activeAppointment.name}<p>{activeAppointment.name}</p>{/if}
          {#if activeAppointment.speciality}<p>
              {activeAppointment.speciality}
            </p>{/if}
          {#if activeAppointment.service_name}<p>
              {activeAppointment.service_name}
            </p>{/if}
        </ResultEmbedInfo>
        {#if activeAppointment.telehealth}<ResultEmbedInfo
            icon="video"
            label={$text("embeds.health.telehealth")}
            state="yes"
          />{/if}
        {#each activeAppointment.accessibility ?? [] as flag}<ResultEmbedInfo
            icon="accessibility"
            label={accessibilityLabel(flag)}
            state="yes"
          />{/each}
        {#if activeAppointment.additional_slot_datetimes?.length}
          <ResultEmbedInfo
            icon="calendar-days"
            label={$text("embeds.health.also_available")}
            testId="health-alternate-info"
          >
            <!-- Alternate slot times for the same doctor (from _group_slots_by_doctor) -->
            {#if activeAppointment.additional_slot_datetimes && activeAppointment.additional_slot_datetimes.length > 0}
              <div class="alternate-slots">
                <div class="section-title">
                  {$text("embeds.health.also_available")}
                </div>
                <div class="alternate-slots-list">
                  {#each activeAppointment.additional_slot_datetimes as altIso}
                    <span class="alternate-slot"
                      >{formatAlternateSlot(altIso)}</span
                    >
                  {/each}
                </div>
              </div>
            {/if}
          </ResultEmbedInfo>
        {/if}
        {#if activeAppointment.opening_hours?.length}
          <ResultEmbedInfo
            icon="clock"
            label={$text("embeds.health.opening_hours")}
            testId="health-hours-info"
          >
            <!-- Opening hours from Google Places -->
            {#if activeAppointment.opening_hours && activeAppointment.opening_hours.length > 0}
              <div class="opening-hours">
                <div class="section-title">
                  {$text("embeds.health.opening_hours")}
                </div>
                <ul class="opening-hours-list">
                  {#each activeAppointment.opening_hours as line}
                    <li>{line}</li>
                  {/each}
                </ul>
              </div>
            {/if}
          </ResultEmbedInfo>
        {/if}
        {#if activeAppointment.google_reviews?.length}
          <ResultEmbedInfo
            icon="messages-square"
            label={$text("embeds.health.patient_reviews")}
            testId="health-reviews-info"
          >
            <!-- Patient reviews from Google Places (up to 5) -->
            {#if activeAppointment.google_reviews && activeAppointment.google_reviews.length > 0}
              <div class="reviews">
                <div class="section-title">
                  {$text("embeds.health.patient_reviews")}
                </div>
                {#each activeAppointment.google_reviews as review}
                  <div class="review-card">
                    <div class="review-header">
                      {#if review.rating != null}
                        <span class="review-rating"
                          >{review.rating.toFixed(1)} ★</span
                        >
                      {/if}
                      {#if review.author}
                        <span class="review-author">{review.author}</span>
                      {/if}
                      {#if review.relative_time}
                        <span class="review-time">· {review.relative_time}</span
                        >
                      {/if}
                    </div>
                    {#if review.text}
                      <p class="review-text">{review.text}</p>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}
          </ResultEmbedInfo>
        {/if}
        {#if activeAppointment.phone}<a
            class="health-link"
            use:tooltip
            aria-label={activeAppointment.phone}
            href={`tel:${activeAppointment.phone}`}
            ><Phone size={21} aria-hidden="true" /></a
          >{/if}
        {#if activeAppointment.website}<a
            class="health-link"
            use:tooltip
            aria-label={$text("embeds.health.website")}
            href={activeAppointment.website}
            target="_blank"
            rel="noopener noreferrer"><Globe size={21} aria-hidden="true" /></a
          >{/if}
        {#if activeAppointment.google_maps_uri}<a
            class="health-link"
            use:tooltip
            aria-label={$text("embeds.health.view_on_google_maps")}
            href={activeAppointment.google_maps_uri}
            target="_blank"
            rel="noopener noreferrer"
            ><MapIcon size={21} aria-hidden="true" /></a
          >{/if}
        {#if effectiveSlotDatetime}<ResultEmbedInfo
            icon="triangle-alert"
            label={$text("embeds.health.slots_may_be_outdated").replace(
              "{provider}",
              providerName,
            )}
            testId="health-availability-info"
          />{/if}
      </div>
    {/snippet}

    {#snippet embedHeaderCta()}
      <div class="embed-header-cta-group">
        {#if $authStore.isAuthenticated}
          <EmbedHeaderCtaButton
            label={savedMemoryEntry ? "Forget" : "Add memory"}
            variant={savedMemoryEntry ? "destructive" : "secondary"}
            onclick={handleToggleSavedAppointment}
            testId="save-embed-cta"
          />
        {/if}
        {#if bookingUrl}
          <EmbedHeaderCtaButton
            label={$text("embeds.open_on_provider").replace(
              "{provider}",
              providerName,
            )}
            onclick={handleOpenAppointment}
            testId="external-provider-cta"
          />
        {/if}
      </div>
    {/snippet}
  </ResultEmbedFullscreen>
{/if}

<style>
  .result-location span {
    display: block;
  }
  .health-link {
    display: inline-flex;
    justify-content: center;
    align-items: center;
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: var(--color-grey-25);
    color: var(--color-font-secondary);
  }
  .health-link:hover {
    color: var(--color-font-primary);
    background: var(--color-grey-30);
  }
  .health-link:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 3px;
  }
</style>
