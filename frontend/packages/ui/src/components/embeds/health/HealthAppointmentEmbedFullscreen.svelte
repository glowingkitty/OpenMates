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
    price?: number;
    service_name?: string;
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
    price: asNumber(dc.price),
    service_name: asString(dc.service_name),
  }));

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
      {#if activeAppointment.insurance}
        <span class="badge insurance-badge">{activeAppointment.insurance}</span>
      {/if}
    </div>

    {#if effectiveSlotDatetime}
      <p class="slots-disclaimer">{$text('embeds.health.slots_may_be_outdated')}</p>
    {/if}
  {/snippet}

  {#snippet embedHeaderCta()}
    {#if activeAppointment.booking_url}
      <EmbedHeaderCtaButton label={$text('embeds.open_on_provider').replace('{provider}', 'Jameda')} href={activeAppointment.booking_url} />
    {:else if activeAppointment.practice_url}
      <EmbedHeaderCtaButton label={$text('embeds.open_on_provider').replace('{provider}', 'Doctolib')} href={activeAppointment.practice_url} />
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
    font-size: 22px;
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.25;
    word-break: break-word;
  }
  .doctor-speciality {
    font-size: 15px;
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
