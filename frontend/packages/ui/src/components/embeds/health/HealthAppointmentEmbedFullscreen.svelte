<!--
  frontend/packages/ui/src/components/embeds/health/HealthAppointmentEmbedFullscreen.svelte

  Fullscreen detail view for a single doctor appointment result.
  Analogous to TravelConnectionEmbedFullscreen — rendered inside a ChildEmbedOverlay
  when the user clicks on a doctor card in HealthSearchEmbedFullscreen.

  Uses UnifiedEmbedFullscreen as base.

  Shows:
  - Doctor name, speciality, address
  - Telehealth badge if applicable
  - Grid of available appointment slots as informational chips (no deep links —
    slot URLs expire as slots get booked; users are directed to the practice page instead)
  - Staleness disclaimer below slots
  - "Book on Doctolib" button linking to the practice_url (live availability page)
  - "View practice" link (same target)
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { getProviderIconUrl } from '../../../data/providerIcons';

  /**
   * A single appointment slot — datetime only.
   * Slot deep-links are intentionally absent: they encode a specific ISO timestamp
   * that expires as soon as the slot is taken or ages past its window.
   */
  interface SlotData {
    /** ISO datetime string */
    datetime: string;
    /** Legacy field — may be present in cached embeds but is ignored in the UI */
    booking_url?: string;
  }

  /** Full appointment data for a single doctor */
  interface AppointmentData {
    /** Unique embed ID */
    embed_id: string;
    /** Doctor's full name */
    name?: string;
    /** Medical speciality */
    speciality?: string;
    /** Practice address (may be multiline) */
    address?: string;
    /** Number of available slots */
    slots_count?: number;
    /** ISO datetime of the next available slot */
    next_slot?: string;
    /**
     * Legacy field — kept for backward-compat with old cached embeds.
     * No longer used in the UI; the practice_url is used instead.
     */
    next_slot_url?: string;
    /** Available slot list (next few slots, datetimes only) */
    slots?: SlotData[];
    /** Insurance sector */
    insurance?: string;
    /** Offers telehealth consultations */
    telehealth?: boolean;
    /** Live availability page on Doctolib — always valid */
    practice_url?: string;
    /** Doctolib provider label */
    provider?: string;
  }

  interface Props {
    /** Full appointment data for this doctor */
    appointment: AppointmentData;
    /** Close handler to dismiss the overlay */
    onClose: () => void;
    /** Optional embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous sibling appointment to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next sibling appointment to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous appointment */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next appointment */
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

  /** Format ISO datetime as readable slot label */
  function formatSlot(iso: string): string {
    try {
      const dt = new Date(iso);
      return dt.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })
        + ' · '
        + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return iso;
    }
  }

  let hasSlots = $derived((appointment.slots_count ?? 0) > 0);

  /**
   * Reconstruct slots array from TOON-flattened content.
   * TOON flattening turns slots[0].datetime → slots_0_datetime.
   * This handles the case where slots come from raw embed content.
   */
  function getSlotsFromAppointment(appt: AppointmentData): SlotData[] {
    if (appt.slots && Array.isArray(appt.slots) && appt.slots.length > 0) {
      return appt.slots;
    }
    // Fallback: synthesise a single slot entry from next_slot if slots array is absent
    if (appt.next_slot) {
      return [{ datetime: appt.next_slot }];
    }
    return [];
  }

  let slots = $derived(getSlotsFromAppointment(appointment));
</script>

<UnifiedEmbedFullscreen
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
>
  {#snippet content()}
    <div class="appointment-fullscreen">

      <!-- Header: doctor name, speciality, address -->
      <div class="fullscreen-header">
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

        <!-- Badges -->
        <div class="badges-row">
          {#if appointment.telehealth}
            <span class="badge telehealth-badge">{$text('embeds.health.telehealth')}</span>
          {/if}
          {#if appointment.insurance}
            <span class="badge insurance-badge">{appointment.insurance}</span>
          {/if}
        </div>
      </div>

      <!-- Slots section — datetimes are informational only.
           Slot deep-links are not available because they encode a specific time
           that expires once the slot is taken. Users book via the practice page. -->
      {#if hasSlots && slots.length > 0}
        <div class="slots-section">
          <div class="slots-grid">
            {#each slots as slot}
              <div class="slot-card">
                <span class="slot-datetime">{formatSlot(slot.datetime)}</span>
              </div>
            {/each}
          </div>
          <!-- Staleness disclaimer -->
          <p class="slots-disclaimer">{$text('embeds.health.slots_may_be_outdated')}</p>
        </div>
      {:else}
        <div class="no-slots-message">
          {$text('embeds.health.no_slots_available')}
        </div>
      {/if}

      <!-- Practice / provider links -->
      <div class="footer-links">
        {#if appointment.practice_url}
          <a
            class="doctolib-link"
            href={appointment.practice_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            <img
              src={getProviderIconUrl('icons/doctolib.svg')}
              alt=""
              class="doctolib-btn-icon"
            />
            {$text('embeds.health.book_on_doctolib')}
          </a>
        {/if}
      </div>

    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Appointment Fullscreen Layout
     =========================================== */

  .appointment-fullscreen {
    display: flex;
    flex-direction: column;
    gap: 0;
    width: 100%;
    max-width: 700px;
    margin: 0 auto;
    padding: 0 16px 120px;
  }

  /* ===========================================
     Header
     =========================================== */

  .fullscreen-header {
    margin-top: 60px;
    margin-bottom: 32px;
    text-align: center;
    padding: 0 8px;
  }

  .doctor-name {
    font-size: 26px;
    font-weight: 700;
    color: var(--color-font-primary);
    line-height: 1.25;
    word-break: break-word;
  }

  .doctor-speciality {
    font-size: 16px;
    font-weight: 500;
    color: var(--color-font-secondary);
    margin-top: 6px;
  }

  .doctor-address {
    font-size: 14px;
    color: var(--color-font-secondary);
    line-height: 1.5;
    margin-top: 8px;
  }

  .doctor-address br {
    display: block;
    content: '';
    margin-top: 0;
  }

  /* Badges */
  .badges-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: center;
    margin-top: 12px;
  }

  .badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.4;
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

  @container fullscreen (max-width: 500px) {
    .fullscreen-header {
      margin-top: 70px;
      margin-bottom: 20px;
    }

    .doctor-name {
      font-size: 20px;
    }

    .doctor-speciality {
      font-size: 14px;
    }
  }

  /* ===========================================
     Slots Grid
     =========================================== */

  .slots-section {
    margin-bottom: 32px;
  }

  .slots-grid {
    display: grid;
    gap: 10px;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  }

  @container fullscreen (max-width: 500px) {
    .slots-grid {
      grid-template-columns: 1fr;
    }
  }

  /* Slot chips are informational only — not clickable */
  .slot-card {
    display: flex;
    align-items: center;
    padding: 12px 16px;
    border-radius: 12px;
    background-color: var(--color-grey-5, #f9f9f9);
    border: 1px solid var(--color-grey-20);
    gap: 12px;
  }

  .slot-datetime {
    font-size: 14px;
    font-weight: 500;
    color: var(--color-font-primary);
    line-height: 1.3;
    flex: 1;
  }

  /* Disclaimer shown below the slot grid */
  .slots-disclaimer {
    margin-top: 10px;
    font-size: 12px;
    color: var(--color-font-secondary);
    text-align: center;
    line-height: 1.4;
  }

  /* ===========================================
     No Slots State
     =========================================== */

  .no-slots-message {
    text-align: center;
    padding: 40px 16px;
    color: var(--color-font-secondary);
    font-size: 16px;
  }

  /* ===========================================
     Footer Links
     =========================================== */

  .footer-links {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    margin-top: 16px;
  }

  .doctolib-link {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-size: 14px;
    font-weight: 600;
    background-color: var(--color-primary);
    color: #fff;
    text-decoration: none;
    padding: 8px 20px;
    border-radius: 20px;
    border: 1.5px solid var(--color-primary);
    transition: background-color 0.15s;
  }

  .doctolib-link:hover {
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.85);
  }

  /* White Doctolib logo inside the filled blue button */
  .doctolib-btn-icon {
    height: 14px;
    width: auto;
    flex-shrink: 0;
    filter: brightness(0) invert(1);
  }
</style>
