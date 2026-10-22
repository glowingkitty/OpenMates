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
  import UnifiedEmbedPreview from "../UnifiedEmbedPreview.svelte";
  import ResultEmbedMapPreview from "../ResultEmbedMapPreview.svelte";
  import ExternalLink from '@lucide/svelte/icons/external-link';
  import Star from '@lucide/svelte/icons/star';
  import Shield from '@lucide/svelte/icons/shield-question';
  import Video from '@lucide/svelte/icons/video';
  import { text } from "@repo/ui";

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
    status?: "processing" | "finished" | "error";
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler to open fullscreen detail view */
    onFullscreen: () => void;
    gpsCoordinates?: { latitude?: number; longitude?: number };
    bookingUrl?: string;
    resultContext?: "auto" | "chat" | "results";
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
    status = "finished",
    isMobile = false,
    onFullscreen,
    gpsCoordinates,
    bookingUrl,
    resultContext = "auto",
  }: Props = $props();

  /** Format ISO slot datetime as human-readable short date + time */
  function formatSlot(iso?: string): string {
    if (!iso) return "";
    try {
      const dt = new Date(iso);
      return (
        dt.toLocaleDateString([], {
          weekday: "short",
          month: "short",
          day: "numeric",
        }) +
        " · " +
        dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      );
    } catch {
      return iso;
    }
  }

  let effectiveSlotDatetime = $derived(slotDatetime);
  let slotDisplay = $derived(formatSlot(effectiveSlotDatetime));

  let mapCenter = $derived(
    gpsCoordinates?.latitude != null &&
      gpsCoordinates.longitude != null &&
      Number.isFinite(gpsCoordinates.latitude) &&
      Number.isFinite(gpsCoordinates.longitude) &&
      Math.abs(gpsCoordinates.latitude) <= 90 &&
      Math.abs(gpsCoordinates.longitude) <= 180
      ? { lat: gpsCoordinates.latitude, lon: gpsCoordinates.longitude }
      : undefined,
  );
  let slotDate = $derived(
    effectiveSlotDatetime ? new Date(effectiveSlotDatetime) : undefined,
  );
  let validDate = $derived(
    slotDate && !Number.isNaN(slotDate.getTime()) ? slotDate : undefined,
  );
  // Short display name used in the BasicInfosBar title area
  let displayTitle = $derived(name || speciality || "Doctor");
  let providerName = $derived(providerPlatform?.trim() || "the provider");

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
  {onFullscreen}
  onStop={handleStop}
  resultPreview={true}
  {resultContext}
>
  {#snippet resultPrimaryAction()}
    {#if bookingUrl}<a
        href={bookingUrl}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={$text("embeds.open_on_provider").replace(
          "{provider}",
          providerName,
        )}
        onclick={(event) => event.stopPropagation()}
        ><ExternalLink size={18} aria-hidden="true" /></a
      >{/if}
  {/snippet}
  {#snippet details()}
    <div class="appointment-card" data-testid="health-appointment-result-card">
      <div class="appointment-map">
        {#if mapCenter}<ResultEmbedMapPreview
            center={mapCenter}
            markers={[{ ...mapCenter, label: displayTitle }]}
          />{/if}
      </div>
      {#if validDate}
        <div class="appointment-date" title={slotDisplay}>
          <span>{validDate.toLocaleDateString([], { weekday: "short" })}</span
          ><strong>{validDate.getDate()}</strong>
        </div>
        <span class="appointment-time"
          >{validDate.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}</span
        >
      {/if}
      <div class="appointment-copy">
        {#if speciality}<span class="speciality">{speciality}</span>{/if}
        <strong class="doctor-name">{displayTitle}</strong>
        <div class="appointment-meta">
          {#if rating != null}<span
              title={`${ratingCount ?? 0} ${$text("embeds.health.reviews")}`}
              ><Star size={12} aria-hidden="true" />{rating.toFixed(1)}</span
            >{/if}
          {#if price != null}<span>{price} EUR</span>{/if}
          {#if insurance === "unknown"}<span
              class="insurance-unknown-badge"
              title={$text("embeds.health.insurance_verify_tooltip").replace(
                "{provider}",
                providerName,
              )}
              ><Shield size={14} aria-hidden="true" /><span class="sr-only"
                >{$text("embeds.health.insurance_verify_on_provider").replace(
                  "{provider}",
                  providerName,
                )}</span
              ></span
            >
          {:else if insurance}<span
              >{insurance === "public"
                ? $text("embeds.search_domain.insurance_public")
                : insurance === "private"
                  ? $text("embeds.search_domain.insurance_private")
                  : insurance}</span
            >{/if}
          {#if telehealth}<span title={$text("embeds.health.telehealth")}
              ><Video size={14} aria-hidden="true" /></span
            >{/if}
          {#if additionalSlotCount > 0}<span
              title={$text("embeds.health.also_available")}
              >+{additionalSlotCount}</span
            >{/if}
        </div>
        {#if address}<span class="sr-only">{address}</span>{/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .appointment-card {
    height: 100%;
    position: relative;
    display: flex;
    flex-direction: column;
  }
  .appointment-map {
    z-index: 0;
    position: absolute;
    inset: 0 0 2rem;
    background: var(--color-grey-20);
    overflow: hidden;
  }
  .appointment-map::after {
    position: absolute;
    content: "";
    inset: 45% 0 0;
    background: linear-gradient(transparent, var(--color-grey-0));
    pointer-events: none;
    z-index: 401;
  }
  .appointment-date {
    position: absolute;
    z-index: 402;
    top: var(--spacing-4);
    left: 48px;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: var(--spacing-1) var(--spacing-3);
    border-radius: var(--radius-3);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-sm);
    line-height: 1.1;
  }
  .appointment-date span {
    font-size: 0.625rem;
    color: var(--color-semantic-error);
  }
  .appointment-date strong {
    font-size: 1.4rem;
    font-weight: 400;
  }
  .appointment-time {
    position: absolute;
    z-index: 402;
    top: var(--spacing-6);
    left: 95px;
    background: var(--color-grey-0);
    padding: var(--spacing-1) var(--spacing-2);
    border-radius: var(--radius-2);
    font-size: 0.75rem;
    font-weight: 600;
  }
  .appointment-copy {
    z-index: 402;
    position: relative;
    margin-top: auto;
    padding: var(--spacing-5) var(--spacing-8);
    display: flex;
    flex-direction: column;
    gap: var(--spacing-1);
  }
  .speciality,
  .appointment-meta {
    font-size: 0.75rem;
    color: var(--color-font-secondary);
  }
  .doctor-name {
    font-size: 0.875rem;
    font-weight: 650;
    line-height: 1.3;
  }
  .appointment-meta {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-3);
  }
  .appointment-meta > span {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-1);
  }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  @container result-card (min-width: 400px) {
    .appointment-map {
      inset: 0 0 0 34%;
    }
    .appointment-map::after {
      display: none;
    }
    .appointment-copy {
      width: 34%;
      box-sizing: border-box;
      margin-block: auto;
      padding-inline: var(--spacing-6);
    }
    .appointment-date {
      top: 3.5rem;
      left: var(--spacing-6);
    }
    .appointment-time {
      top: 4rem;
      left: 4rem;
    }
  }
</style>
