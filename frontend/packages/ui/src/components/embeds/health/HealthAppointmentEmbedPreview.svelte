<!--
  frontend/packages/ui/src/components/embeds/health/HealthAppointmentEmbedPreview.svelte

  Preview card for a single doctor appointment result.
  Rendered inside the HealthSearchEmbedFullscreen grid — analogous to
  TravelConnectionEmbedPreview rendered inside TravelSearchEmbedFullscreen.

  Shows:
  - Doctor name (prominent)
  - Speciality + address
  - Next available slot date + "Book" deep link
  - Telehealth badge if applicable
  - "No slots available" if slots_count === 0
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  /**
   * Props for a single doctor appointment card.
   * Data comes from the parent fullscreen component which transforms
   * raw embed content into this structured format.
   */
  interface Props {
    /** Unique embed ID for this appointment result */
    id: string;
    /** Doctor's full name */
    name?: string;
    /** Medical speciality (e.g., "Ophthalmologist") */
    speciality?: string;
    /** Practice address */
    address?: string;
    /** Number of available slots */
    slotsCount?: number;
    /** ISO datetime of the next available slot */
    nextSlot?: string;
    /** Deep booking URL for the next slot */
    nextSlotUrl?: string;
    /** Insurance sector (e.g., "public", "private") */
    insurance?: string;
    /** Whether the doctor offers telehealth consultations */
    telehealth?: boolean;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler to open fullscreen detail view */
    onFullscreen?: () => void;
  }

  let {
    id,
    name,
    speciality,
    address,
    slotsCount = 0,
    nextSlot,
    nextSlotUrl,
    insurance,
    telehealth = false,
    status = 'finished',
    isMobile = false,
    onFullscreen
  }: Props = $props();

  /** Format ISO slot datetime as human-readable short date + time */
  function formatSlot(iso?: string): string {
    if (!iso) return '';
    try {
      const dt = new Date(iso);
      return dt.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
        + ' · '
        + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return iso;
    }
  }

  let nextSlotDisplay = $derived(formatSlot(nextSlot));
  let hasSlots = $derived(slotsCount > 0);

  // Short display name used in the BasicInfosBar title area
  let displayTitle = $derived(name || speciality || 'Doctor');

  // No-op stop (individual doctor cards are not cancellable tasks)
  async function handleStop() {
    // Not applicable
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="health"
  skillId="appointment"
  skillIconName="health"
  {status}
  skillName={displayTitle}
  {isMobile}
  onFullscreen={onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="appointment-details" class:mobile={isMobileLayout}>

      <!-- Doctor name -->
      {#if name}
        <div class="doctor-name">{name}</div>
      {/if}

      <!-- Speciality -->
      {#if speciality}
        <div class="doctor-speciality">{speciality}</div>
      {/if}

      <!-- Address (first line only) -->
      {#if address}
        <div class="doctor-address">{address.split('\n')[0]}</div>
      {/if}

      <!-- Badges row: telehealth, insurance -->
      {#if telehealth || insurance}
        <div class="badges-row">
          {#if telehealth}
            <span class="badge telehealth-badge">{$text('embeds.health.telehealth')}</span>
          {/if}
          {#if insurance}
            <span class="badge insurance-badge">{insurance}</span>
          {/if}
        </div>
      {/if}

      <!-- Slot info -->
      {#if hasSlots && nextSlotDisplay}
        <div class="slot-row">
          <span class="next-slot-label">{$text('embeds.health.next_slot')}:</span>
          <span class="next-slot-date">{nextSlotDisplay}</span>
        </div>

        <!-- Book button -->
        {#if nextSlotUrl}
          <a
            class="book-button"
            href={nextSlotUrl}
            target="_blank"
            rel="noopener noreferrer"
            onclick={(e) => e.stopPropagation()}
          >
            {$text('embeds.health.book_slot')}
          </a>
        {/if}
      {:else}
        <div class="no-slots">{$text('embeds.health.no_slots_available')}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* =============================================
     Appointment Card Content
     ============================================= */

  .appointment-details {
    display: flex;
    flex-direction: column;
    gap: 3px;
    height: 100%;
    justify-content: center;
    padding: 2px 0;
  }

  .appointment-details.mobile {
    justify-content: flex-start;
  }

  /* Doctor name — prominent */
  .doctor-name {
    font-size: 15px;
    font-weight: 700;
    color: var(--color-grey-100);
    line-height: 1.25;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .appointment-details.mobile .doctor-name {
    font-size: 14px;
  }

  /* Speciality */
  .doctor-speciality {
    font-size: 13px;
    color: var(--color-grey-70);
    line-height: 1.3;
    font-weight: 500;
  }

  .appointment-details.mobile .doctor-speciality {
    font-size: 12px;
  }

  /* Address */
  .doctor-address {
    font-size: 12px;
    color: var(--color-grey-60);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Badges row */
  .badges-row {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 2px;
  }

  .badge {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    line-height: 1.4;
  }

  .telehealth-badge {
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.1);
    color: var(--color-primary);
  }

  .insurance-badge {
    background-color: var(--color-grey-10);
    color: var(--color-grey-70);
    border: 1px solid var(--color-grey-30);
    text-transform: capitalize;
  }

  /* Slot info */
  .slot-row {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: 3px;
    flex-wrap: wrap;
    font-size: 12px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }

  .next-slot-label {
    font-weight: 500;
  }

  .next-slot-date {
    color: var(--color-primary);
    font-weight: 600;
  }

  /* Book button */
  .book-button {
    display: inline-block;
    margin-top: 6px;
    padding: 5px 14px;
    border-radius: 20px;
    background-color: var(--color-primary);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    text-decoration: none;
    line-height: 1.4;
    transition: opacity 0.15s;
    cursor: pointer;
    align-self: flex-start;
  }

  .book-button:hover {
    opacity: 0.85;
  }

  /* No slots state */
  .no-slots {
    font-size: 12px;
    color: var(--color-grey-50);
    margin-top: 3px;
    font-style: italic;
  }
</style>
