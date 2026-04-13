<!--
  frontend/packages/ui/src/components/embeds/health/HealthAppointmentEmbedPreview.svelte

  Preview card for a single appointment slot.
  Rendered inside the HealthSearchEmbedFullscreen grid — analogous to
  TravelConnectionEmbedPreview rendered inside TravelSearchEmbedFullscreen.

  Shows:
  - Slot datetime (prominent)
  - Doctor name + speciality
  - Address
  - Telehealth badge if applicable
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  /**
   * Props for a single appointment slot card.
   * Data comes from the parent fullscreen component which transforms
   * raw embed content into this structured format.
   */
  interface Props {
    /** Unique embed ID for this appointment result */
    id: string;
    /** ISO datetime of this specific appointment slot */
    slotDatetime?: string;
    /** Doctor's full name */
    name?: string;
    /** Medical speciality (e.g., "Ophthalmologist") */
    speciality?: string;
    /** Practice address */
    address?: string;
    /** Insurance sector (e.g., "public", "private") */
    insurance?: string;
    /** Whether the doctor offers telehealth consultations */
    telehealth?: boolean;
    /** Combined Jameda + Google Places rating (weighted average) */
    rating?: number;
    /** Combined review count across rating sources */
    ratingCount?: number;
    /** Service price in EUR (from Jameda) */
    price?: number;
    /** Provider platform: "Doctolib" | "Jameda" */
    providerPlatform?: string;
    /** Number of additional alternate slots available for this doctor */
    additionalSlotCount?: number;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error';
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler to open fullscreen detail view */
    onFullscreen: () => void;
  }

  let {
    id,
    slotDatetime,
    name,
    speciality,
    address,
    insurance,
    telehealth = false,
    rating,
    ratingCount,
    price,
    providerPlatform,
    additionalSlotCount = 0,
    status = 'finished',
    isMobile = false,
    onFullscreen,
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

  let effectiveSlotDatetime = $derived(slotDatetime);
  let slotDisplay = $derived(formatSlot(effectiveSlotDatetime));

  // Short display name used in the BasicInfosBar title area
  let displayTitle = $derived(name || speciality || 'Doctor');

  // No-op stop (individual slot cards are not cancellable tasks)
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

      <!-- Slot datetime — prominent — with "+N more" badge when alternates exist -->
      {#if slotDisplay}
        <div class="slot-datetime-row">
          <span class="slot-datetime">{slotDisplay}</span>
          {#if additionalSlotCount > 0}
            <span class="more-slots-badge">+{additionalSlotCount} more</span>
          {/if}
        </div>
      {/if}

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

      <!-- Rating + Price row (combined Jameda + Google Places) -->
      {#if rating != null || price != null}
        <div class="extras-row">
          {#if rating != null}
            <span class="rating-compact">
              {rating.toFixed(1)} ★
              {#if ratingCount != null && ratingCount > 0}
                <span class="rating-count">({ratingCount})</span>
              {/if}
            </span>
          {/if}
          {#if price != null}
            <span class="price-compact">{price} €</span>
          {/if}
          {#if providerPlatform}
            <span class="provider-compact">{providerPlatform}</span>
          {/if}
        </div>
      {/if}

      <!-- Badges row: telehealth, insurance -->
      {#if telehealth || insurance}
        <div class="badges-row">
          {#if telehealth}
            <span class="badge telehealth-badge">{$text('embeds.health.telehealth')}</span>
          {/if}
          {#if insurance === 'unknown'}
            <!-- Jameda doesn't expose per-doctor insurance sector info — warn
                 the user that they need to verify it on Jameda before booking -->
            <span class="badge insurance-unknown-badge" title="Insurance requirement not available — verify on Jameda before booking">
              Insurance: verify on Jameda
            </span>
          {:else if insurance}
            <span class="badge insurance-badge">{insurance}</span>
          {/if}
        </div>
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

  /* Slot datetime row — holds the primary time + optional "+N more" badge */
  .slot-datetime-row {
    display: flex;
    align-items: center;
    gap: var(--spacing-2);
    flex-wrap: wrap;
  }

  /* Slot datetime — most prominent element */
  .slot-datetime {
    font-weight: 700;
    color: var(--color-primary);
    line-height: 1.25;
  }

  .appointment-details.mobile .slot-datetime {
    font-size: var(--font-size-small);
  }

  /* "+N more" badge showing alternate slots for the same doctor */
  .more-slots-badge {
    font-size: var(--font-size-tiny);
    font-weight: 600;
    padding: 1px 6px;
    border-radius: var(--radius-8);
    background-color: rgba(var(--color-primary-rgb, 74, 144, 226), 0.1);
    color: var(--color-primary);
    line-height: 1.4;
  }

  /* Doctor name */
  .doctor-name {
    font-size: var(--font-size-small);
    font-weight: 600;
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
    font-size: var(--font-size-xs);
  }

  /* Speciality */
  .doctor-speciality {
    font-size: var(--font-size-xs);
    color: var(--color-grey-70);
    line-height: 1.3;
    font-weight: 500;
  }

  .appointment-details.mobile .doctor-speciality {
    font-size: var(--font-size-xxs);
  }

  /* Address */
  .doctor-address {
    font-size: var(--font-size-xxs);
    color: var(--color-grey-60);
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Rating + Price extras row */
  .extras-row {
    display: flex;
    align-items: center;
    gap: var(--spacing-3);
    margin-top: 1px;
  }

  .rating-compact {
    font-size: var(--font-size-xxs);
    font-weight: 600;
    color: var(--color-warning, #f5a623);
  }

  .rating-compact .rating-count {
    color: var(--color-grey-60);
    font-weight: 500;
    margin-left: 2px;
  }

  .price-compact {
    font-size: var(--font-size-xxs);
    font-weight: 600;
    color: var(--color-font-secondary);
  }

  .provider-compact {
    font-size: var(--font-size-tiny);
    font-weight: 500;
    color: var(--color-grey-50);
  }

  /* Badges row */
  .badges-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-2);
    margin-top: var(--spacing-1);
  }

  .badge {
    display: inline-block;
    padding: 2px 7px;
    border-radius: var(--radius-8);
    font-size: var(--font-size-tiny);
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

  .insurance-unknown-badge {
    background-color: rgba(var(--color-warning-rgb, 245, 166, 35), 0.12);
    color: var(--color-warning, #f5a623);
    border: 1px solid rgba(var(--color-warning-rgb, 245, 166, 35), 0.3);
  }

</style>
