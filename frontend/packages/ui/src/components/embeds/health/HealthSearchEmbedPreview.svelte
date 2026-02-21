<!--
  frontend/packages/ui/src/components/embeds/health/HealthSearchEmbedPreview.svelte

  Preview card for the Health Search Appointments skill embed.
  Follows the same pattern as TravelSearchEmbedPreview.svelte.

  Shows while processing:
  - "Searching for {speciality} in {city}" summary line
  - "via Doctolib" provider label

  Shows when finished:
  - Same summary line
  - Doctor count + earliest available slot date
  - Error message if status === 'error'

  Real-time updates during streaming are handled by UnifiedEmbedPreview which
  subscribes to embedUpdated events. This component implements the
  onEmbedDataUpdated callback to update its local state when notified.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';

  /**
   * A single appointment result (doctor with slots).
   * Only the fields needed for the preview card.
   */
  interface AppointmentResult {
    type?: string;
    name?: string;
    speciality?: string;
    address?: string;
    slots_count?: number;
    next_slot?: string;
    insurance?: string;
    telehealth?: boolean;
  }

  interface Props {
    /** Unique embed ID */
    id: string;
    /** Human-readable search summary, e.g. "Augenarzt in Berlin" */
    query?: string;
    /** Provider platform name, e.g. "Doctolib" */
    provider?: string;
    /** Current processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Appointment results (for finished state) */
    results?: AppointmentResult[];
    /** Task ID for cancelling the entire AI response */
    taskId?: string;
    /** Skill task ID for cancelling just this skill */
    skillTaskId?: string;
    /** Whether to render in mobile layout */
    isMobile?: boolean;
    /** Callback when user clicks to open fullscreen */
    onFullscreen?: () => void;
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    status: statusProp,
    results: resultsProp,
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  // Local reactive state — updated by handleEmbedDataUpdated during streaming
  let localQuery = $state<string>('');
  let localProvider = $state<string>('Doctolib');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localResults = $state<AppointmentResult[]>([]);
  let localErrorMessage = $state<string>('');
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);

  // Sync local state from props on mount / prop change
  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'Doctolib';
    localStatus = statusProp || 'processing';
    localResults = resultsProp || [];
    localTaskId = taskIdProp;
    localSkillTaskId = skillTaskIdProp;
    localErrorMessage = '';
  });

  // Derived state (source of truth for template)
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);
  let errorMessage = $derived(localErrorMessage || $text('chat.an_error_occured'));

  /**
   * Called by UnifiedEmbedPreview when the embed's streamed content updates.
   * Updates local state so the card reflects the latest data without remounting.
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[HealthSearchEmbedPreview] Embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent
    });

    if (
      data.status === 'processing' ||
      data.status === 'finished' ||
      data.status === 'error' ||
      data.status === 'cancelled'
    ) {
      localStatus = data.status;
    }

    const content = data.decodedContent;
    if (content) {
      if (typeof content.query === 'string') localQuery = content.query;
      if (typeof content.provider === 'string') localProvider = content.provider;
      if (typeof content.error === 'string') localErrorMessage = content.error;
      if (typeof content.skill_task_id === 'string') localSkillTaskId = content.skill_task_id;

      // When finished, load child embeds if parent has embed_ids but no inline results
      if (
        data.status === 'finished' &&
        (!content.results || !Array.isArray(content.results) || content.results.length === 0)
      ) {
        const embedIds = content.embed_ids;
        if (embedIds) {
          const childEmbedIds: string[] =
            typeof embedIds === 'string'
              ? (embedIds as string).split('|').filter((cid: string) => cid.length > 0)
              : Array.isArray(embedIds)
              ? (embedIds as string[])
              : [];

          if (childEmbedIds.length > 0) {
            console.debug(`[HealthSearchEmbedPreview] Loading child embeds for preview (${childEmbedIds.length})`);
            loadChildEmbedsForPreview(childEmbedIds);
          }
        }
      }

      if (content.results && Array.isArray(content.results)) {
        localResults = content.results as AppointmentResult[];
      }
    }
  }

  /**
   * Load child embeds to extract appointment data for the preview card.
   * Uses retry logic because child embeds might not be persisted immediately.
   */
  async function loadChildEmbedsForPreview(childEmbedIds: string[]) {
    try {
      const { loadEmbedsWithRetry, decodeToonContent } = await import('../../../services/embedResolver');
      const childEmbeds = await loadEmbedsWithRetry(childEmbedIds, 5, 300);

      if (childEmbeds.length > 0) {
        const appointmentResults = await Promise.all(childEmbeds.map(async (embed) => {
          const c = embed.content ? await decodeToonContent(embed.content) : null;
          if (!c) return null;
          return {
            type: (c.type as string) || 'appointment',
            name: (c.name as string) || undefined,
            speciality: (c.speciality as string) || undefined,
            address: (c.address as string) || undefined,
            slots_count: (c.slots_count as number) || 0,
            next_slot: (c.next_slot as string) || undefined,
            insurance: (c.insurance as string) || undefined,
            telehealth: (c.telehealth as boolean) || false,
          } as AppointmentResult;
        }));

        const valid = appointmentResults.filter(r => r !== null) as AppointmentResult[];
        if (valid.length > 0) {
          localResults = valid;
          console.debug(`[HealthSearchEmbedPreview] Loaded ${valid.length} appointment results from child embeds`);
        }
      }
    } catch (error) {
      console.warn('[HealthSearchEmbedPreview] Error loading child embeds for preview:', error);
    }
  }

  // Flatten grouped results (backend returns [{id, results: [...]}])
  function flattenResults(rawResults: AppointmentResult[]): AppointmentResult[] {
    if (!rawResults || rawResults.length === 0) return [];
    const firstItem = rawResults[0] as Record<string, unknown>;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      const flattened: AppointmentResult[] = [];
      for (const entry of rawResults as unknown as Array<{ id?: string; results?: AppointmentResult[] }>) {
        if (entry.results && Array.isArray(entry.results)) {
          flattened.push(...entry.results);
        }
      }
      return flattened;
    }
    return rawResults;
  }

  let flatResults = $derived(flattenResults(results));

  // Summary line: "Augenarzt in Berlin" or raw query
  let searchSummary = $derived(query || '');

  // Count doctors with at least one slot
  let doctorsWithSlots = $derived(flatResults.filter(r => (r.slots_count ?? 0) > 0).length);

  // Total doctors found
  let totalDoctors = $derived(flatResults.length);

  // Earliest available slot across all results
  let earliestSlot = $derived.by(() => {
    const slots = flatResults
      .map(r => r.next_slot)
      .filter((s): s is string => !!s)
      .sort();
    return slots[0] || null;
  });

  // Format earliest slot as human-readable date
  let earliestSlotDisplay = $derived.by(() => {
    if (!earliestSlot) return '';
    try {
      const dt = new Date(earliestSlot);
      return dt.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  });

  // "via {provider}" label
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  // Skill display name from translations
  let skillName = $derived($text('app_skills.health.search_appointments'));

  // Handle cancel button
  async function handleStop() {
    if (status !== 'processing') return;
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
      } catch (error) {
        console.error(`[HealthSearchEmbedPreview] Failed to cancel skill:`, error);
      }
    } else if (taskId) {
      try {
        await chatSyncService.sendCancelAiTask(taskId);
      } catch (error) {
        console.error(`[HealthSearchEmbedPreview] Failed to cancel task:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="health"
  skillId="search_appointments"
  skillIconName="search"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="health-search-details" class:mobile={isMobileLayout}>
      <!-- Search summary: "Augenarzt in Berlin" -->
      <div class="search-query">{searchSummary}</div>

      <!-- Provider label: "via Doctolib" -->
      <div class="search-provider">{viaProvider}</div>

      <!-- Error state -->
      {#if status === 'error'}
        <div class="search-error">
          <div class="search-error-title">{$text('embeds.search_failed')}</div>
          <div class="search-error-message">{errorMessage}</div>
        </div>

      {:else if status === 'finished'}
        <!-- Finished state: doctor count + earliest slot -->
        <div class="search-results-info">
          {#if totalDoctors > 0}
            <span class="doctor-count">
              {doctorsWithSlots}
              {doctorsWithSlots === 1
                ? $text('embeds.health.doctor_with_slots')
                : $text('embeds.health.doctors_with_slots')}
            </span>
          {/if}

          {#if earliestSlotDisplay}
            <span class="earliest-slot">
              {$text('embeds.from')} {earliestSlotDisplay}
            </span>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* =============================================
     Health Search Details — Preview Card Content
     ============================================= */

  .health-search-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }

  .health-search-details:not(.mobile) {
    justify-content: center;
  }

  .health-search-details.mobile {
    justify-content: flex-start;
  }

  /* Main search summary text */
  .search-query {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }

  .health-search-details.mobile .search-query {
    font-size: 14px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }

  /* "via Doctolib" label */
  .search-provider {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }

  .health-search-details.mobile .search-provider {
    font-size: 12px;
  }

  /* Results summary row */
  .search-results-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
    flex-wrap: wrap;
  }

  .health-search-details.mobile .search-results-info {
    margin-top: 2px;
  }

  /* Doctor count */
  .doctor-count {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
  }

  .health-search-details.mobile .doctor-count {
    font-size: 12px;
  }

  /* Earliest slot date — accent colour to draw attention */
  .earliest-slot {
    font-size: 14px;
    color: var(--color-primary);
    font-weight: 600;
  }

  .health-search-details.mobile .earliest-slot {
    font-size: 12px;
  }

  /* Error state */
  .search-error {
    margin-top: 6px;
    padding: 8px 10px;
    border-radius: 12px;
    background-color: rgba(var(--color-error-rgb), 0.08);
    border: 1px solid rgba(var(--color-error-rgb), 0.3);
  }

  .search-error-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-error);
  }

  .search-error-message {
    margin-top: 2px;
    font-size: 12px;
    color: var(--color-grey-70);
    line-height: 1.4;
    word-break: break-word;
  }
</style>
