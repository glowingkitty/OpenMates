<!--
  frontend/packages/ui/src/components/embeds/health/HealthAppointmentEmbedFullscreen.svelte

  Fullscreen detail view for a single appointment slot.
  Uses EntryWithMapTemplate for responsive map + detail card layout.

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
  import EntryWithMapTemplate from '../EntryWithMapTemplate.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { text } from '@repo/ui';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

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
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'string') { const n = Number(v); if (Number.isFinite(n)) return n; }
    return undefined;
  }

  function asString(v: unknown): string | undefined {
    return typeof v === 'string' ? v : undefined;
  }

  function asStringArray(v: unknown): string[] | undefined {
    if (!Array.isArray(v)) return undefined;
    const out: string[] = [];
    for (const s of v) if (typeof s === 'string' && s.trim().length > 0) out.push(s);
    return out.length > 0 ? out : undefined;
  }

  function parseGoogleReviews(v: unknown): GoogleReview[] | undefined {
    if (!Array.isArray(v)) return undefined;
    const out: GoogleReview[] = [];
    for (const entry of v) {
      if (entry && typeof entry === 'object') {
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

  function parseGps(content: Record<string, unknown>): AppointmentData['gps_coordinates'] {
    // Nested: gps_coordinates: { latitude, longitude }
    const gps = content.gps_coordinates;
    if (gps && typeof gps === 'object') {
      const g = gps as Record<string, unknown>;
      const lat = asNumber(g.latitude) ?? asNumber(g.lat);
      const lon = asNumber(g.longitude) ?? asNumber(g.lon);
      if (lat != null && lon != null) return { latitude: lat, longitude: lon };
    }
    // Flat TOON: gps_coordinates_latitude, gps_coordinates_longitude
    const flatLat = asNumber(content.gps_coordinates_latitude);
    const flatLon = asNumber(content.gps_coordinates_longitude);
    if (flatLat != null && flatLon != null) return { latitude: flatLat, longitude: flatLon };
    return undefined;
  }

  let appointment: AppointmentData = $derived.by(() => ({
    embed_id: asString(dc.embed_id) || (embedId || ''),
    slot_datetime: asString(dc.slot_datetime),
    name: asString(dc.name),
    speciality: asString(dc.speciality),
    address: asString(dc.address),
    gps_coordinates: parseGps(dc),
    insurance: asString(dc.insurance),
    telehealth: typeof dc.telehealth === 'boolean' ? dc.telehealth : undefined,
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
        dt.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })
        + ' · '
        + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      );
    } catch {
      return iso;
    }
  }

  /** Map accessibility flag keys to short German/English labels. */
  function accessibilityLabel(flag: string): string {
    switch (flag) {
      case 'wheelchair_entrance':
        return 'Wheelchair entrance';
      case 'wheelchair_parking':
        return 'Wheelchair parking';
      case 'wheelchair_seating':
        return 'Wheelchair seating';
      case 'wheelchair_restroom':
        return 'Wheelchair restroom';
      default:
        return flag;
    }
  }

  function getAddressLines(value: unknown): string[] {
    if (typeof value !== 'string' || !value.trim()) return [];
    return value
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }

  // appointment is always an object (from $derived.by above), so alias directly
  let activeAppointment = $derived(appointment);

  function formatSlot(iso: string): string {
    try {
      const dt = new Date(iso);
      return dt.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })
        + ' \u00b7 '
        + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch { return iso; }
  }

  let effectiveSlotDatetime = $derived(activeAppointment?.slot_datetime || null);

  // Map data from gps_coordinates
  let mapCenter = $derived(
    activeAppointment?.gps_coordinates?.latitude != null &&
    activeAppointment?.gps_coordinates?.longitude != null
      ? {
          lat: activeAppointment.gps_coordinates.latitude,
          lon: activeAppointment.gps_coordinates.longitude,
        }
      : undefined
  );

  let mapMarkers = $derived(
    mapCenter
      ? [{ lat: mapCenter.lat, lon: mapCenter.lon, label: activeAppointment?.name || activeAppointment?.speciality }]
      : []
  );

  let addressLines = $derived(getAddressLines(activeAppointment?.address));

  /** Booking platform name for labels/disclaimer — falls back to a generic word. */
  let providerName = $derived(activeAppointment?.provider_platform?.trim() || 'the provider');

  /** Header title: formatted appointment date/time (most important info at a glance) */
  let headerTitle = $derived.by(() => {
    if (effectiveSlotDatetime) return formatSlot(effectiveSlotDatetime);
    return activeAppointment?.name || activeAppointment?.speciality || 'Appointment';
  });

  /** Header subtitle: doctor name + speciality (secondary context) */
  let headerSubtitle = $derived.by(() => {
    const parts: string[] = [];
    if (effectiveSlotDatetime && activeAppointment?.name) parts.push(activeAppointment.name);
    if (activeAppointment?.speciality) parts.push(activeAppointment.speciality);
    return parts.join(' · ') || undefined;
  });
</script>

{#if activeAppointment}
<EntryWithMapTemplate
  appId="health"
  skillId="appointment"
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
>
  {#snippet detailContent(_ctx)}
    <!-- Slot datetime — prominent -->
    {#if effectiveSlotDatetime}
      <div class="slot-highlight">
        <span class="slot-highlight-datetime">{formatSlot(effectiveSlotDatetime)}</span>
      </div>
    {/if}

    <!-- Doctor info -->
    <div class="doctor-header">
      {#if activeAppointment.name}
        <div class="doctor-name">{activeAppointment.name}</div>
      {/if}
      {#if activeAppointment.speciality}
        <div class="doctor-speciality">{activeAppointment.speciality}</div>
      {/if}
      {#if addressLines.length > 0}
        <div class="doctor-address">
          {#each addressLines as line}
            <span>{line}</span><br />
          {/each}
        </div>
      {/if}
    </div>

    <!-- Rating (Jameda) -->
    {#if activeAppointment.rating != null}
      <div class="rating-row">
        <span class="rating-stars">{activeAppointment.rating.toFixed(1)} ★</span>
        {#if activeAppointment.rating_count}
          <span class="rating-count">({activeAppointment.rating_count} {$text('embeds.health.reviews')})</span>
        {/if}
      </div>
    {/if}

    <!-- Service + Price (Jameda) -->
    {#if activeAppointment.service_name || activeAppointment.price != null}
      <div class="service-row">
        {#if activeAppointment.service_name}
          <span class="service-name">{activeAppointment.service_name}</span>
        {/if}
        {#if activeAppointment.price != null}
          <span class="service-price">{activeAppointment.price} €</span>
        {/if}
      </div>
    {/if}

    <!-- Badges -->
    <div class="badges-row">
      {#if activeAppointment.telehealth}
        <span class="badge telehealth-badge">{$text('embeds.health.telehealth')}</span>
      {/if}
      {#if activeAppointment.insurance === 'unknown'}
        <!-- Jameda doesn't expose per-doctor insurance sector info — warn
             the user that they need to verify it on Jameda before booking -->
        <span class="badge insurance-unknown-badge" title="Insurance requirement not available — verify on Jameda before booking">
          Insurance: verify on Jameda
        </span>
      {:else if activeAppointment.insurance}
        <span class="badge insurance-badge">{activeAppointment.insurance}</span>
      {/if}
      {#if activeAppointment.accessibility}
        {#each activeAppointment.accessibility as flag}
          <span class="badge accessibility-badge">{accessibilityLabel(flag)}</span>
        {/each}
      {/if}
    </div>

    <!-- Alternate slot times for the same doctor (from _group_slots_by_doctor) -->
    {#if activeAppointment.additional_slot_datetimes && activeAppointment.additional_slot_datetimes.length > 0}
      <div class="alternate-slots">
        <div class="section-title">Also available</div>
        <div class="alternate-slots-list">
          {#each activeAppointment.additional_slot_datetimes as altIso}
            <span class="alternate-slot">{formatAlternateSlot(altIso)}</span>
          {/each}
        </div>
      </div>
    {/if}

    <!-- Editorial summary from Google Places (practice description) -->
    {#if activeAppointment.description}
      <div class="editorial-summary">{activeAppointment.description}</div>
    {/if}

    <!-- Opening hours from Google Places -->
    {#if activeAppointment.opening_hours && activeAppointment.opening_hours.length > 0}
      <div class="opening-hours">
        <div class="section-title">Opening hours</div>
        <ul class="opening-hours-list">
          {#each activeAppointment.opening_hours as line}
            <li>{line}</li>
          {/each}
        </ul>
      </div>
    {/if}

    <!-- Patient reviews from Google Places (up to 5) -->
    {#if activeAppointment.google_reviews && activeAppointment.google_reviews.length > 0}
      <div class="reviews">
        <div class="section-title">Patient reviews</div>
        {#each activeAppointment.google_reviews as review}
          <div class="review-card">
            <div class="review-header">
              {#if review.rating != null}
                <span class="review-rating">{review.rating.toFixed(1)} ★</span>
              {/if}
              {#if review.author}
                <span class="review-author">{review.author}</span>
              {/if}
              {#if review.relative_time}
                <span class="review-time">· {review.relative_time}</span>
              {/if}
            </div>
            {#if review.text}
              <p class="review-text">{review.text}</p>
            {/if}
          </div>
        {/each}
      </div>
    {/if}

    <!-- External links: phone, website, Google Maps (from Google Places) -->
    {#if activeAppointment.phone || activeAppointment.website || activeAppointment.google_maps_uri}
      <div class="external-links">
        {#if activeAppointment.phone}
          <a class="external-link" href={`tel:${activeAppointment.phone}`}>{activeAppointment.phone}</a>
        {/if}
        {#if activeAppointment.website}
          <a class="external-link" href={activeAppointment.website} target="_blank" rel="noopener noreferrer">Website</a>
        {/if}
        {#if activeAppointment.google_maps_uri}
          <a class="external-link" href={activeAppointment.google_maps_uri} target="_blank" rel="noopener noreferrer">View on Google Maps</a>
        {/if}
      </div>
    {/if}

    {#if effectiveSlotDatetime}
      <p class="slots-disclaimer">{$text('embeds.health.slots_may_be_outdated').replace('{provider}', providerName)}</p>
    {/if}
  {/snippet}

  {#snippet embedHeaderCta()}
    {#if activeAppointment.booking_url}
      <EmbedHeaderCtaButton label={$text('embeds.open_on_provider').replace('{provider}', providerName)} href={activeAppointment.booking_url} />
    {:else if activeAppointment.practice_url}
      <EmbedHeaderCtaButton label={$text('embeds.open_on_provider').replace('{provider}', providerName)} href={activeAppointment.practice_url} />
    {/if}
  {/snippet}
</EntryWithMapTemplate>
{/if}

<style>
  .slot-highlight {
    text-align: center;
    padding: var(--spacing-6) var(--spacing-8);
    border-radius: var(--radius-5);
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.08);
    border: 1px solid rgba(var(--color-primary-rgb, 74, 144, 226), 0.2);
  }
  .slot-highlight-datetime {
    font-size: var(--font-size-h3-mobile);
    font-weight: 700;
    color: var(--color-primary);
    line-height: 1.3;
  }

  .doctor-header { text-align: center; }
  .doctor-name {
    font-size: var(--font-size-xl);
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.25;
    word-break: break-word;
  }
  .doctor-speciality {
    font-size: null;
    font-weight: 500;
    color: var(--color-font-secondary);
    margin-top: var(--spacing-2);
  }
  .doctor-address {
    font-size: var(--font-size-xs);
    color: var(--color-font-secondary);
    line-height: 1.5;
    margin-top: var(--spacing-3);
  }

  .badges-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-3);
    justify-content: center;
  }
  .badge {
    display: inline-block;
    padding: var(--spacing-2) var(--spacing-5);
    border-radius: var(--radius-8);
    font-size: var(--font-size-xxs);
    font-weight: 600;
  }
  .telehealth-badge {
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.12);
    color: var(--color-primary);
  }
  .insurance-badge {
    background-color: var(--color-grey-10);
    color: var(--color-grey-70);
    border: 1px solid var(--color-grey-30);
    text-transform: capitalize;
  }
  .insurance-unknown-badge {
    background-color: rgba(var(--color-warning-rgb, 245, 166, 35), 0.12);
    color: var(--color-warning, #f5a623);
    border: 1px solid rgba(var(--color-warning-rgb, 245, 166, 35), 0.3);
  }
  .accessibility-badge {
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.08);
    color: var(--color-primary);
    border: 1px solid rgba(var(--color-primary-rgb, 74, 144, 226), 0.2);
  }

  /* Section titles reused across alternate slots, hours, reviews */
  .section-title {
    font-size: var(--font-size-small);
    font-weight: 700;
    color: var(--color-font-primary);
    margin-bottom: var(--spacing-3);
  }

  /* Alternate slot times list */
  .alternate-slots-list {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-2);
  }
  .alternate-slot {
    display: inline-block;
    padding: var(--spacing-2) var(--spacing-4);
    border-radius: var(--radius-8);
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.08);
    color: var(--color-primary);
    font-size: var(--font-size-xxs);
    font-weight: 600;
    border: 1px solid rgba(var(--color-primary-rgb, 74, 144, 226), 0.2);
  }

  /* Editorial summary — Google's practice description */
  .editorial-summary {
    font-size: var(--font-size-small);
    color: var(--color-font-secondary);
    line-height: 1.5;
  }

  /* Opening hours list */
  .opening-hours-list {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .opening-hours-list li {
    font-size: var(--font-size-xs);
    color: var(--color-font-secondary);
    line-height: 1.5;
  }

  /* Review cards — one per Google review */
  .review-card {
    padding: var(--spacing-4);
    border-radius: var(--radius-5);
    background-color: var(--color-grey-10);
    border: 1px solid var(--color-grey-20);
    margin-bottom: var(--spacing-3);
  }
  .review-header {
    display: flex;
    align-items: baseline;
    gap: var(--spacing-2);
    margin-bottom: var(--spacing-2);
    flex-wrap: wrap;
  }
  .review-rating {
    font-size: var(--font-size-xs);
    font-weight: 700;
    color: var(--color-warning, #f5a623);
  }
  .review-author {
    font-size: var(--font-size-xs);
    font-weight: 600;
    color: var(--color-font-primary);
  }
  .review-time {
    font-size: var(--font-size-tiny);
    color: var(--color-font-secondary);
  }
  .review-text {
    margin: 0;
    font-size: var(--font-size-xs);
    color: var(--color-font-secondary);
    line-height: 1.5;
    word-break: break-word;
  }

  /* External links row (phone / website / google maps) */
  .external-links {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-3);
    justify-content: center;
  }
  .external-link {
    display: inline-block;
    padding: var(--spacing-2) var(--spacing-4);
    border-radius: var(--radius-8);
    background-color: var(--color-grey-10);
    color: var(--color-primary);
    text-decoration: none;
    font-size: var(--font-size-xs);
    font-weight: 600;
    border: 1px solid var(--color-grey-20);
  }
  .external-link:hover {
    background-color: var(--color-grey-20);
  }

  .slots-disclaimer {
    font-size: var(--font-size-tiny);
    color: var(--color-font-secondary);
    text-align: center;
    margin: 0;
  }
  /* Rating row */
  .rating-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-3);
  }
  .rating-stars {
    font-size: var(--font-size-p);
    font-weight: 700;
    color: var(--color-warning, #f5a623);
  }
  .rating-count {
    font-size: var(--font-size-xs);
    color: var(--color-font-secondary);
  }

  /* Service + Price row */
  .service-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-4);
    flex-wrap: wrap;
  }
  .service-name {
    font-size: var(--font-size-small);
    font-weight: 500;
    color: var(--color-font-primary);
  }
  .service-price {
    font-size: var(--font-size-small);
    font-weight: 700;
    color: var(--color-font-primary);
  }


</style>
