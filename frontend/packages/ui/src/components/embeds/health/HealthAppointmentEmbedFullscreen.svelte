<!--
  frontend/packages/ui/src/components/embeds/health/HealthAppointmentEmbedFullscreen.svelte

  Fullscreen detail view for a single doctor appointment result.
  Analogous to TravelConnectionEmbedFullscreen — rendered inside a ChildEmbedOverlay
  when the user clicks on a doctor card in HealthSearchEmbedFullscreen.

  Uses UnifiedEmbedFullscreen as base.

  Shows:
  - Doctor name, speciality, address
  - Telehealth badge if applicable
  - Grid of available appointment slots, each with a direct Doctolib booking link
  - "View practice" link (opens the doctor's Doctolib practice page)
  - Insurance info
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /** A single bookable appointment slot */
  interface SlotData {
    /** ISO datetime string */
    datetime: string;
    /** Deep Doctolib booking URL for this specific slot */
    booking_url: string;
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
    /** Deep Doctolib booking URL for the next slot */
    next_slot_url?: string;
    /** Available slot list (next few slots) */
    slots?: SlotData[];
    /** Insurance sector */
    insurance?: string;
    /** Offers telehealth consultations */
    telehealth?: boolean;
    /** Practice page URL on Doctolib */
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
  }

  let {
    appointment,
    onClose,
    embedId
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
    // Build from next_slot / next_slot_url as fallback (at least one slot)
    if (appt.next_slot && appt.next_slot_url) {
      return [{ datetime: appt.next_slot, booking_url: appt.next_slot_url }];
    }
    return [];
  }

  let slots = $derived(getSlotsFromAppointment(appointment));
</script>

<UnifiedEmbedFullscreen
  appId="health"
  skillId="appointment"
  title=""
  {onClose}
  skillIconName="health"
  status="finished"
  skillName={appointment.name || appointment.speciality || 'Doctor'}
  showStatus={false}
  currentEmbedId={embedId}
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

      <!-- Slots section -->
      {#if hasSlots && slots.length > 0}
        <div class="slots-section">
          <div class="slots-grid">
            {#each slots as slot}
              <a
                class="slot-card"
                href={slot.booking_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <span class="slot-datetime">{formatSlot(slot.datetime)}</span>
                <span class="slot-book-label">{$text('embeds.health.book_slot')}</span>
              </a>
            {/each}
          </div>
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
            class="practice-link"
            href={appointment.practice_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {$text('embeds.health.view_practice')}
          </a>
        {/if}

        {#if appointment.next_slot_url}
          <a
            class="doctolib-link"
            href={appointment.next_slot_url}
            target="_blank"
            rel="noopener noreferrer"
          >
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

  .slot-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-radius: 12px;
    background-color: var(--color-grey-5, #f9f9f9);
    border: 1px solid var(--color-grey-20);
    text-decoration: none;
    gap: 12px;
    transition: background-color 0.15s, border-color 0.15s;
    cursor: pointer;
  }

  .slot-card:hover {
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.06);
    border-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.3);
  }

  .slot-datetime {
    font-size: 14px;
    font-weight: 500;
    color: var(--color-font-primary);
    line-height: 1.3;
    flex: 1;
  }

  .slot-book-label {
    flex-shrink: 0;
    padding: 4px 12px;
    border-radius: 20px;
    background-color: var(--color-primary);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
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

  .practice-link,
  .doctolib-link {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-primary);
    text-decoration: none;
    padding: 8px 20px;
    border-radius: 20px;
    border: 1.5px solid var(--color-primary);
    transition: background-color 0.15s;
  }

  .practice-link:hover,
  .doctolib-link:hover {
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.08);
  }

  .doctolib-link {
    background-color: var(--color-primary);
    color: #fff;
  }

  .doctolib-link:hover {
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.85);
  }
</style>
