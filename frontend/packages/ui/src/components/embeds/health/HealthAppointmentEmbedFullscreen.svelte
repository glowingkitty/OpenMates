<!--
  frontend/packages/ui/src/components/embeds/health/HealthAppointmentEmbedFullscreen.svelte

  Fullscreen detail view for a single doctor appointment result.
  Uses EntryWithMapTemplate for responsive map + detail card layout.

  Shows map when gps_coordinates are available (Doctolib provides gpsPoint).
  Falls back to details-only layout when no coordinates.

  Shows:
  - Doctor name, speciality, address
  - Telehealth/insurance badges
  - Available appointment slots (informational, not clickable -- they expire)
  - "Book on Doctolib" CTA linking to the practice_url

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import EntryWithMapTemplate from '../EntryWithMapTemplate.svelte';
  import { text } from '@repo/ui';
  import { getProviderIconUrl } from '../../../data/providerIcons';

  interface SlotData {
    datetime: string;
    booking_url?: string;
  }

  interface AppointmentData {
    embed_id: string;
    name?: string;
    speciality?: string;
    address?: string;
    gps_coordinates?: { latitude: number; longitude: number };
    slots_count?: number;
    next_slot?: string;
    next_slot_url?: string;
    slots?: SlotData[];
    insurance?: string;
    telehealth?: boolean;
    practice_url?: string;
    provider?: string;
  }

  interface Props {
    appointment: AppointmentData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    appointment,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  function formatSlot(iso: string): string {
    try {
      const dt = new Date(iso);
      return dt.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })
        + ' \u00b7 '
        + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch { return iso; }
  }

  // Defensive: appointment may be undefined during async component loading in dev preview
  let hasSlots = $derived(((appointment as AppointmentData | undefined)?.slots_count ?? 0) > 0);

  function getSlotsFromAppointment(appt: AppointmentData | undefined): SlotData[] {
    if (!appt) return [];
    if (appt.slots && Array.isArray(appt.slots) && appt.slots.length > 0) return appt.slots;
    if (appt.next_slot) return [{ datetime: appt.next_slot }];
    return [];
  }

  let slots = $derived(getSlotsFromAppointment(appointment as AppointmentData | undefined));

  // Map data from gps_coordinates
  let mapCenter = $derived(
    (appointment as AppointmentData | undefined)?.gps_coordinates?.latitude != null &&
    (appointment as AppointmentData | undefined)?.gps_coordinates?.longitude != null
      ? { lat: appointment.gps_coordinates!.latitude, lon: appointment.gps_coordinates!.longitude }
      : undefined
  );

  let mapMarkers = $derived(
    mapCenter
      ? [{ lat: mapCenter.lat, lon: mapCenter.lon, label: appointment?.name || appointment?.speciality }]
      : []
  );
</script>

<EntryWithMapTemplate
  appId="health"
  skillId="appointment"
  {onClose}
  skillIconName="health"
  embedHeaderTitle={appointment.name || appointment.speciality || 'Doctor'}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {mapCenter}
  mapZoom={16}
  {mapMarkers}
>
  {#snippet detailContent()}
    <!-- Doctor info -->
    <div class="doctor-header">
      {#if appointment.name}
        <div class="doctor-name">{appointment.name}</div>
      {/if}
      {#if appointment.speciality}
        <div class="doctor-speciality">{appointment.speciality}</div>
      {/if}
      {#if appointment.address}
        <div class="doctor-address">
          {#each appointment.address.split('\n') as line}
            <span>{line}</span><br />
          {/each}
        </div>
      {/if}
    </div>

    <!-- Badges -->
    <div class="badges-row">
      {#if appointment.telehealth}
        <span class="badge telehealth-badge">{$text('embeds.health.telehealth')}</span>
      {/if}
      {#if appointment.insurance}
        <span class="badge insurance-badge">{appointment.insurance}</span>
      {/if}
    </div>

    <!-- Slots -->
    {#if hasSlots && slots.length > 0}
      <div class="slots-section">
        <div class="slots-grid">
          {#each slots as slot}
            <div class="slot-card">
              <span class="slot-datetime">{formatSlot(slot.datetime)}</span>
            </div>
          {/each}
        </div>
        <p class="slots-disclaimer">{$text('embeds.health.slots_may_be_outdated')}</p>
      </div>
    {:else}
      <div class="no-slots">{$text('embeds.health.no_slots_available')}</div>
    {/if}
  {/snippet}

  {#snippet ctaContent()}
    {#if appointment.practice_url}
      <a
        class="doctolib-link"
        href={appointment.practice_url}
        target="_blank"
        rel="noopener noreferrer"
      >
        <img src={getProviderIconUrl('icons/doctolib.svg')} alt="" class="doctolib-btn-icon" />
        {$text('embeds.health.book_on_doctolib')}
      </a>
    {/if}
  {/snippet}
</EntryWithMapTemplate>

<style>
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
  .no-slots {
    text-align: center;
    padding: 20px 0;
    color: var(--color-font-secondary);
    font-size: 14px;
  }

  .doctolib-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    font-size: 14px;
    font-weight: 600;
    background-color: var(--color-primary);
    color: #fff;
    text-decoration: none;
    padding: 10px 20px;
    border-radius: 20px;
    border: 1.5px solid var(--color-primary);
    transition: background-color 0.15s;
    width: 100%;
    box-sizing: border-box;
  }
  .doctolib-link:hover {
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.85);
  }
  .doctolib-btn-icon {
    height: 14px;
    width: auto;
    flex-shrink: 0;
    filter: brightness(0) invert(1);
  }
</style>
