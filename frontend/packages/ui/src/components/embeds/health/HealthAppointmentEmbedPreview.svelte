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
  import ResultEmbedCard from "../ResultEmbedCard.svelte";
  import EmbedCalendarDate from "../EmbedCalendarDate.svelte";
  import ResultEmbedMapPreview from "../ResultEmbedMapPreview.svelte";

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
    /** Combined the stored provider + Google Places rating (weighted average) */
    rating?: number;
    /** Combined review count across rating sources */
    ratingCount?: number;
    /** Service price in EUR (from the stored provider) */
    price?: number;
    /** Provider platform: "the stored provider" | "the stored provider" */
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
    resultContext = "auto",
  }: Props = $props();

  let effectiveSlotDatetime = $derived(slotDatetime);

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

  {#snippet details()}
    <ResultEmbedCard title={displayTitle} titleTestId="health-appointment-title" sourceLabel={speciality}>
      {#snippet media()}{#if mapCenter}<ResultEmbedMapPreview center={mapCenter} markers={[{ ...mapCenter, label: displayTitle }]} />{/if}{/snippet}
      {#snippet badge()}{#if validDate}<div class="appointment-calendar" data-testid="health-appointment-calendar"><EmbedCalendarDate date={validDate} timeLabel={validDate.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} /></div>{/if}{/snippet}
      {#snippet facts()}
        <div class="appointment-meta">
          {#if rating != null}<span
              title={`${ratingCount ?? 0} ${$text("embeds.health.reviews")}`}
              ><Star size={12} style="color: var(--color-highlight-yellow-solid)" fill="currentColor" aria-hidden="true" />{rating.toFixed(1)}</span
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
      {/snippet}
    </ResultEmbedCard>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .appointment-calendar { --embed-calendar-time-font-size: var(--font-size-small); }
  .appointment-meta { display: flex; flex-wrap: wrap; gap: var(--spacing-2); font-size: var(--font-size-xs); line-height: 1.3; color: var(--color-font-secondary); min-width: 0; }
  .appointment-meta > span { display: inline-flex; align-items: center; gap: var(--spacing-1); }
  .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
</style>
