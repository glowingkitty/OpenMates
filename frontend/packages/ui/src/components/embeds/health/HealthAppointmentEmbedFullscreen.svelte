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
  import { getProviderIconUrl } from '../../../data/providerIcons';

  interface SlotData {
    datetime: string;
    booking_url?: string;
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
    price?: number;
    service_name?: string;
    // Legacy backward-compat (old per-doctor cached embeds)
    slots_count?: number;
    next_slot?: string;
    slots?: SlotData[];
  }

  interface Props {
    appointment?: AppointmentData;
    slot_datetime?: string;
    name?: string;
    speciality?: string;
    address?: string;
    gps_coordinates?: { latitude: number; longitude: number };
    insurance?: string;
    telehealth?: boolean;
    practice_url?: string;
    provider?: string;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    // Legacy backward-compat
    slots_count?: number;
    next_slot?: string;
    slots?: SlotData[];
  }

  let {
    appointment,
    slot_datetime,
    name,
    speciality,
    address,
    gps_coordinates,
    insurance,
    telehealth,
    practice_url,
    provider,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    slots_count,
    next_slot,
    slots: slotsProp,
  }: Props = $props();

  function isNonEmptyString(value: unknown): value is string {
    return typeof value === 'string' && value.trim().length > 0;
  }

  function getAddressLines(value: unknown): string[] {
    if (!isNonEmptyString(value)) return [];
    return value
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }

  let activeAppointment = $derived.by(() => {
    if (appointment) return appointment;

    const hasFlatData =
      isNonEmptyString(name) ||
      isNonEmptyString(speciality) ||
      isNonEmptyString(address) ||
      isNonEmptyString(slot_datetime) ||
      isNonEmptyString(next_slot) ||
      isNonEmptyString(practice_url);

    if (!hasFlatData) return undefined;

    return {
      embed_id: embedId || 'health-appointment-preview',
      slot_datetime,
      name,
      speciality,
      address,
      gps_coordinates,
      insurance,
      telehealth,
      practice_url,
      provider,
      // Legacy backward-compat
      slots_count,
      next_slot,
      slots: slotsProp,
    } as AppointmentData;
  });

  function formatSlot(iso: string): string {
    try {
      const dt = new Date(iso);
      return dt.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })
        + ' \u00b7 '
        + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch { return iso; }
  }

  // Effective slot datetime: new per-slot format, or legacy per-doctor format
  let effectiveSlotDatetime = $derived(
    activeAppointment?.slot_datetime || activeAppointment?.next_slot || null
  );

  // Legacy support: old per-doctor embeds may have multiple slots
  function getLegacySlots(appt: AppointmentData | undefined): SlotData[] {
    if (!appt) return [];
    if (appt.slots && Array.isArray(appt.slots) && appt.slots.length > 0) return appt.slots;
    return [];
  }

  let legacySlots = $derived(getLegacySlots(activeAppointment));
  let isLegacyMultiSlot = $derived(!activeAppointment?.slot_datetime && legacySlots.length > 1);

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
</script>

{#if activeAppointment}
<EntryWithMapTemplate
  appId="health"
  skillId="appointment"
  {onClose}
  skillIconName="health"
  embedHeaderTitle={activeAppointment.name || activeAppointment.speciality || 'Doctor'}
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

    <!-- Legacy: old per-doctor embeds with multiple slots -->
    {#if isLegacyMultiSlot}
      <div class="slots-section">
        <div class="slots-grid">
          {#each legacySlots as slot}
            <div class="slot-card">
              <span class="slot-datetime">{formatSlot(slot.datetime)}</span>
            </div>
          {/each}
        </div>
        <p class="slots-disclaimer">{$text('embeds.health.slots_may_be_outdated')}</p>
      </div>
    {:else if effectiveSlotDatetime}
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
    padding: 12px 16px;
    border-radius: 12px;
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.08);
    border: 1px solid rgba(var(--color-primary-rgb, 74, 144, 226), 0.2);
  }
  .slot-highlight-datetime {
    font-size: 18px;
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
    margin-top: 4px;
  }
  .doctor-address {
    font-size: 13px;
    color: var(--color-font-secondary);
    line-height: 1.5;
    margin-top: 6px;
  }

  .badges-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: center;
  }
  .badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 12px;
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

  .slots-section { display: flex; flex-direction: column; gap: 8px; }
  .slots-grid {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .slot-card {
    display: flex;
    align-items: center;
    padding: 10px 14px;
    border-radius: 10px;
    background-color: var(--color-grey-5, #f9f9f9);
    border: 1px solid var(--color-grey-20);
  }
  .slot-datetime {
    font-size: 13px;
    font-weight: 500;
    color: var(--color-font-primary);
  }
  .slots-disclaimer {
    font-size: 11px;
    color: var(--color-font-secondary);
    text-align: center;
    margin: 0;
  }
  /* Rating row */
  .rating-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
  }
  .rating-stars {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-warning, #f5a623);
  }
  .rating-count {
    font-size: 13px;
    color: var(--color-font-secondary);
  }

  /* Service + Price row */
  .service-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .service-name {
    font-size: 14px;
    font-weight: 500;
    color: var(--color-font-primary);
  }
  .service-price {
    font-size: 14px;
    font-weight: 700;
    color: var(--color-font-primary);
  }


</style>
