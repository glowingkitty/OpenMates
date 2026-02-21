<!--
  frontend/packages/ui/src/components/embeds/health/HealthSearchEmbedFullscreen.svelte

  Fullscreen view for the Health Search Appointments skill embed.
  Follows the exact same pattern as TravelSearchEmbedFullscreen.svelte.

  Shows:
  - Header with search summary and "via Doctolib"
  - Grid of doctor cards (HealthAppointmentEmbedPreview), sorted by next slot
  - Per-doctor detail overlay (HealthAppointmentEmbedFullscreen) when a card is clicked
  - Loading / empty / error states

  Child embed loading:
  - Uses UnifiedEmbedFullscreen's built-in child embed loading via embedIds prop
  - Each child embed is an individual appointment result decoded via childEmbedTransformer
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import HealthAppointmentEmbedPreview from './HealthAppointmentEmbedPreview.svelte';
  import HealthAppointmentEmbedFullscreen from './HealthAppointmentEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /** A single bookable appointment slot */
  interface SlotData {
    datetime: string;
    booking_url: string;
  }

  /**
   * Appointment result interface — one doctor with their available slots.
   * Used for both the grid cards and the detail overlay.
   */
  interface AppointmentResult {
    /** Unique embed ID (used as React-like key and for overlay navigation) */
    embed_id: string;
    type?: string;
    name?: string;
    speciality?: string;
    address?: string;
    slots_count?: number;
    next_slot?: string;
    next_slot_url?: string;
    /** Available slots (next few) */
    slots?: SlotData[];
    insurance?: string;
    telehealth?: boolean;
    practice_url?: string;
    provider?: string;
  }

  interface Props {
    /** Search query display string (e.g., "Augenarzt in Berlin") */
    query?: string;
    /** Provider platform name (e.g., "Doctolib") */
    provider?: string;
    /** Pipe-separated or array of child embed IDs (one per doctor result) */
    embedIds?: string | string[];
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Optional error message */
    errorMessage?: string;
    /** Legacy: inline results array (used if embedIds not provided) */
    results?: unknown[];
    /** Close handler */
    onClose: () => void;
    /** Optional embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Whether to show the "chat" button */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
  }

  let {
    query: queryProp,
    provider: providerProp,
    embedIds,
    status: statusProp,
    errorMessage: errorMessageProp,
    results: resultsProp,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  // Currently selected appointment for fullscreen detail overlay
  let selectedAppointment = $state<AppointmentResult | null>(null);

  // Local reactive state — initialized with defaults, synced from props via $effect below
  let localQuery = $state<string>('');
  let localProvider = $state<string>('Doctolib');
  let localEmbedIds = $state<string | string[] | undefined>(undefined);
  let localResults = $state<unknown[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let localErrorMessage = $state<string>('');

  // Keep local state in sync with prop changes
  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'Doctolib';
    localEmbedIds = embedIds;
    localResults = resultsProp || [];
    localStatus = statusProp || 'finished';
    localErrorMessage = errorMessageProp || '';
  });

  // Derived state
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let embedIdsValue = $derived(localEmbedIds);
  let legacyResults = $derived(localResults);
  let status = $derived(localStatus);
  let fullscreenStatus = $derived(status === 'cancelled' ? 'error' : status);
  let errorMessage = $derived(localErrorMessage || $text('chat.an_error_occured'));

  // Skill name from translations
  let skillName = $derived($text('app_skills.health.search_appointments'));

  // "via {provider}" text
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  /**
   * Transform raw embed content (TOON-decoded) into AppointmentResult format.
   * Used as childEmbedTransformer by UnifiedEmbedFullscreen.
   *
   * TOON encoding flattens nested objects, so slots[0].datetime → slots_0_datetime.
   * We reconstruct the slots array from these flattened keys when needed.
   */
  function transformToAppointmentResult(embedId: string, content: Record<string, unknown>): AppointmentResult {
    // Reconstruct slots array from TOON-flattened or native format
    let slots: SlotData[] = [];

    if (Array.isArray(content.slots)) {
      // Native (non-TOON-flattened) slots array
      slots = (content.slots as Record<string, unknown>[]).map(s => ({
        datetime: (s.datetime as string) || '',
        booking_url: (s.booking_url as string) || '',
      }));
    } else {
      // Reconstruct from TOON-flattened: slots_0_datetime, slots_0_booking_url, etc.
      for (let i = 0; i < 20; i++) {
        const dt = content[`slots_${i}_datetime`];
        if (typeof dt !== 'string') break;
        slots.push({
          datetime: dt,
          booking_url: (content[`slots_${i}_booking_url`] as string) || '',
        });
      }
    }

    return {
      embed_id: embedId,
      type: (content.type as string) || 'appointment',
      name: content.name as string | undefined,
      speciality: content.speciality as string | undefined,
      address: content.address as string | undefined,
      slots_count: (content.slots_count as number) || 0,
      next_slot: content.next_slot as string | undefined,
      next_slot_url: content.next_slot_url as string | undefined,
      slots,
      insurance: content.insurance as string | undefined,
      telehealth: (content.telehealth as boolean) || false,
      practice_url: content.practice_url as string | undefined,
      provider: content.provider as string | undefined,
    };
  }

  /**
   * Transform legacy inline results (non-embed-child path) into AppointmentResult format.
   */
  function transformLegacyResults(results: unknown[]): AppointmentResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) =>
      transformToAppointmentResult(`legacy-${i}`, r)
    );
  }

  /**
   * Get appointment results from context (child embeds or legacy inline results).
   */
  function getAppointmentResults(ctx: ChildEmbedContext): AppointmentResult[] {
    if (ctx.children && ctx.children.length > 0) {
      return ctx.children as AppointmentResult[];
    }
    if (ctx.legacyResults && ctx.legacyResults.length > 0) {
      return transformLegacyResults(ctx.legacyResults);
    }
    return [];
  }

  /**
   * Open the per-doctor detail overlay.
   */
  function handleAppointmentFullscreen(appointment: AppointmentResult) {
    console.debug('[HealthSearchEmbedFullscreen] Opening appointment fullscreen:', {
      embedId: appointment.embed_id,
      name: appointment.name,
      slotsCount: appointment.slots_count,
    });
    selectedAppointment = appointment;
  }

  /**
   * Close the per-doctor detail overlay, returning to the grid.
   */
  function handleAppointmentFullscreenClose() {
    selectedAppointment = null;
  }

  /**
   * Handle embed data updates during streaming.
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;

    if (
      data.status === 'processing' ||
      data.status === 'finished' ||
      data.status === 'error' ||
      data.status === 'cancelled'
    ) {
      localStatus = data.status;
    }

    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (content.embed_ids) localEmbedIds = content.embed_ids as string | string[];
    if (Array.isArray(content.results)) localResults = content.results as unknown[];
    if (typeof content.error === 'string') localErrorMessage = content.error;
  }

  /**
   * Handle main close — if a detail overlay is open, close it first.
   */
  function handleMainClose() {
    if (selectedAppointment) {
      selectedAppointment = null;
    } else {
      onClose();
    }
  }
</script>

<!-- Doctor results grid — ALWAYS rendered (base layer) -->
<UnifiedEmbedFullscreen
  appId="health"
  skillId="search_appointments"
  title=""
  onClose={handleMainClose}
  skillIconName="health"
  status={fullscreenStatus}
  {skillName}
  showStatus={true}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToAppointmentResult}
  legacyResults={legacyResults}
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content(ctx)}
    {@const appointmentResults = getAppointmentResults(ctx)}

    <!-- Header: search summary + provider -->
    <div class="fullscreen-header">
      <div class="search-query">{query}</div>
      <div class="search-provider">{viaProvider}</div>
    </div>

    <!-- Error state -->
    {#if status === 'error'}
      <div class="error-state">
        <div class="error-title">{$text('embeds.search_failed')}</div>
        <div class="error-message">{errorMessage}</div>
      </div>
    {:else if appointmentResults.length === 0}
      {#if ctx.isLoadingChildren}
        <div class="loading-state">
          <p>{$text('embeds.loading')}</p>
        </div>
      {:else}
        <div class="no-results">
          <p>{$text('embeds.health.no_appointments_found')}</p>
        </div>
      {/if}
    {:else}
      <!-- Doctor cards grid -->
      <div class="appointment-embeds-grid">
        {#each appointmentResults as result}
          <HealthAppointmentEmbedPreview
            id={result.embed_id}
            name={result.name}
            speciality={result.speciality}
            address={result.address}
            slotsCount={result.slots_count}
            nextSlot={result.next_slot}
            nextSlotUrl={result.next_slot_url}
            insurance={result.insurance}
            telehealth={result.telehealth}
            status="finished"
            isMobile={false}
            onFullscreen={() => handleAppointmentFullscreen(result)}
          />
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<!-- Per-doctor detail fullscreen overlay -->
{#if selectedAppointment}
  <ChildEmbedOverlay>
    <HealthAppointmentEmbedFullscreen
      appointment={selectedAppointment}
      onClose={handleAppointmentFullscreenClose}
      embedId={selectedAppointment.embed_id}
    />
  </ChildEmbedOverlay>
{/if}

<style>
  /* ===========================================
     Fullscreen Header
     =========================================== */

  .fullscreen-header {
    margin-top: 60px;
    margin-bottom: 40px;
    padding: 0 16px;
    text-align: center;
  }

  .search-query {
    font-size: 24px;
    font-weight: 600;
    color: var(--color-font-primary);
    line-height: 1.3;
    word-break: break-word;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .search-provider {
    font-size: 16px;
    color: var(--color-font-secondary);
    margin-top: 8px;
  }

  @container fullscreen (max-width: 500px) {
    .fullscreen-header {
      margin-top: 70px;
      margin-bottom: 24px;
    }

    .search-query {
      font-size: 20px;
    }

    .search-provider {
      font-size: 14px;
    }
  }

  /* ===========================================
     Loading and Empty States
     =========================================== */

  .loading-state,
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
    font-size: 16px;
  }

  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 24px 16px;
    color: var(--color-font-secondary);
    text-align: center;
  }

  .error-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-error);
  }

  .error-message {
    font-size: 14px;
    line-height: 1.4;
    max-width: 520px;
    word-break: break-word;
  }

  /* ===========================================
     Doctor Cards Grid
     =========================================== */

  .appointment-embeds-grid {
    display: grid;
    gap: 16px;
    width: calc(100% - 20px);
    max-width: 1000px;
    margin: 0 auto;
    padding: 0 10px;
    padding-bottom: 120px;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  }

  @container fullscreen (max-width: 500px) {
    .appointment-embeds-grid {
      grid-template-columns: 1fr;
    }
  }

  .appointment-embeds-grid :global(.unified-embed-preview) {
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
  }
</style>
