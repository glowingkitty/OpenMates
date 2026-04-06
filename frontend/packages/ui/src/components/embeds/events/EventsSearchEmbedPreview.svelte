<!--
  frontend/packages/ui/src/components/embeds/events/EventsSearchEmbedPreview.svelte

  Preview component for Events Search skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.

  Details content structure:
  - Processing: query text + "via Meetup"
  - Finished: query text + "via {provider}" + event count ("+ N events")

  NOTE: Real-time updates are handled by UnifiedEmbedPreview via embedUpdated events.
  This component implements onEmbedDataUpdated to update its specific data.

  Events data is stored inline in the parent embed TOON (not as separate child embeds).
  image_url is always None from backend — no image/favicon display, just event count.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';

  /**
   * Single event result from the events/search skill backend.
   * See backend/apps/events/skills/search_skill.py for the full schema.
   */
  interface EventResult {
    id?: string;
    provider?: string;
    title?: string;
    description?: string;
    url?: string;
    date_start?: string;
    date_end?: string;
    timezone?: string;
    /** "PHYSICAL" or "ONLINE" */
    event_type?: string;
    venue?: {
      name?: string;
      address?: string;
      city?: string;
      state?: string;
      country?: string;
      lat?: number;
      lon?: number;
    };
    organizer?: {
      id?: string;
      name?: string;
      slug?: string;
    };
    rsvp_count?: number;
    is_paid?: boolean;
    fee?: {
      amount?: number;
      currency?: string;
    };
    /** Always None from backend */
    image_url?: string | null;
  }

  /**
   * Props for events search embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Search query */
    query: string;
    /** Events provider (e.g., 'Meetup') — legacy single-provider field */
    provider: string;
    /** List of provider slugs that contributed results (e.g. ['meetup', 'luma']) */
    providers?: string[];
    /** Processing status - must match SkillExecutionStatus */
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Event results (for finished state) */
    results?: EventResult[];
    /** Task ID for cancellation of entire AI response */
    taskId?: string;
    /** Skill task ID for cancellation of just this skill (allows AI to continue) */
    skillTaskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
  }

  /** Map backend provider slugs to human-readable display names. */
  function getProviderLabel(slug: string): string {
    switch (slug?.toLowerCase()) {
      case 'meetup':              return 'Meetup';
      case 'luma':                return 'Luma';
      case 'google_events':       return 'Google';
      case 'resident_advisor':    return 'Resident Advisor';
      case 'siegessaeule':        return 'Siegessäule';
      case 'classictic':          return 'Classictic';
      case 'berlin_philharmonic': return 'Berlin Philharmonic';
      case 'bachtrack':           return 'Bachtrack';
      default:                    return slug || '';
    }
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    providers: providersProp,
    status: statusProp,
    results: resultsProp = [],
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  // Local reactive state — updated when embed data changes via onEmbedDataUpdated
  let localQuery = $state<string>('');
  let localProvider = $state<string>('');
  let localProviders = $state<string[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let storeResolved = $state(false);
  let localResults = $state<EventResult[]>([]);
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);
  let isLoadingChildren = $state(false);

  // Initialize local state from props
  $effect(() => {
    if (!storeResolved) {
      localQuery = queryProp || '';
      localProvider = providerProp || '';
      localProviders = providersProp || [];
      localStatus = statusProp || 'processing';
      localResults = resultsProp || [];
      localTaskId = taskIdProp;
      localSkillTaskId = skillTaskIdProp;
    }
  });

  // Use local state as source of truth
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let providers = $derived(localProviders);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);

  /**
   * Handle embed data updates from UnifiedEmbedPreview.
   * Called when the parent component receives and decodes updated embed data.
   *
   * Events results are stored as child embeds (like news/web search). When status becomes
   * "finished" and embed_ids are present but no inline results, we load child embeds
   * asynchronously to get the total event count for the preview card.
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[EventsSearchEmbedPreview] 🔄 Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent
    });

    // Update status
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
      if (data.status !== 'processing') { storeResolved = true; }
    }

    const content = data.decodedContent;
    if (content) {
      if (typeof content.query === 'string') localQuery = content.query;
      if (typeof content.provider === 'string') localProvider = content.provider;
      if (Array.isArray(content.providers)) localProviders = content.providers as string[];
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results as EventResult[];
        console.debug(`[EventsSearchEmbedPreview] Updated results (inline):`, localResults.length);
      }
      if (typeof content.skill_task_id === 'string') {
        localSkillTaskId = content.skill_task_id;
      }

      // When finished and embed_ids are present but no inline results, load child embeds
      // to get the count for display. Events don't have favicons so we just need the count.
      if (data.status === 'finished' && (!content.results || !Array.isArray(content.results) || (content.results as unknown[]).length === 0)) {
        const embedIds = content.embed_ids;
        if (embedIds) {
          const childEmbedIds: string[] = typeof embedIds === 'string'
            ? (embedIds as string).split('|').filter((eid: string) => eid.length > 0)
            : Array.isArray(embedIds) ? (embedIds as string[]) : [];
          if (childEmbedIds.length > 0 && !isLoadingChildren) {
            console.debug(`[EventsSearchEmbedPreview] Loading child embeds for count (${childEmbedIds.length} embed_ids)`);
            isLoadingChildren = true;
            loadChildEmbedCount(childEmbedIds);
          }
        }
      }
    }
  }

  /**
   * Load child embeds to get total event count for preview display.
   * We only need the count — no content decoding required.
   * Uses retry logic because child embeds might not be persisted yet.
   */
  async function loadChildEmbedCount(childEmbedIds: string[]) {
    try {
      const { loadEmbedsWithRetry } = await import('../../../services/embedResolver');
      const childEmbeds = await loadEmbedsWithRetry(childEmbedIds, 5, 300);
      if (childEmbeds.length > 0) {
        // Create minimal placeholder results (just need the count — no content needed)
        localResults = childEmbeds.map(() => ({} as EventResult));
        console.debug(`[EventsSearchEmbedPreview] Loaded ${childEmbeds.length} child embeds for count display`);
      }
    } catch (error) {
      console.warn('[EventsSearchEmbedPreview] Error loading child embeds for count:', error);
      // Continue without results — preview will just show query/provider without count
    } finally {
      isLoadingChildren = false;
    }
  }

  // Get skill name from translations (reuse embeds.search key — "Search")
  let skillName = $derived($text('common.search'));

  // Use "search" icon (magnifying glass) matching WebSearch and TravelSearch conventions.
  // The app-level icon is "event" (calendar), but the search *skill* uses "search".
  const skillIconName = 'search';

  // "via {provider}" subtitle — use providers list when available for multi-source display
  let viaProvider = $derived.by(() => {
    const via = $text('embeds.via');
    // Prefer the providers list (actual contributing providers) over the single provider field
    if (providers.length > 0) {
      const labels = providers.map(getProviderLabel);
      if (labels.length <= 2) {
        return `${via} ${labels.join(', ')}`;
      }
      return `${via} ${labels[0]}, ${labels[1]} +${labels.length - 2}`;
    }
    // Fallback to legacy single provider (backwards compatibility with existing embeds)
    if (provider && provider !== 'auto' && provider !== 'none') {
      return `${via} ${getProviderLabel(provider)}`;
    }
    return '';
  });

  // Event count for finished state: the total number of results
  let eventCount = $derived(results?.length || 0);

  /**
   * Handle stop button — cancels this specific skill or the entire AI task as fallback.
   */
  async function handleStop() {
    if (status !== 'processing') return;

    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
        console.debug(`[EventsSearchEmbedPreview] Sent cancel_skill for skill_task_id ${skillTaskId}`);
      } catch (error) {
        console.error(`[EventsSearchEmbedPreview] Failed to cancel skill ${skillTaskId}:`, error);
      }
    } else if (taskId) {
      console.warn(`[EventsSearchEmbedPreview] No skill_task_id, falling back to task cancellation for task ${taskId}`);
      try {
        await chatSyncService.sendCancelAiTask(taskId);
        console.debug(`[EventsSearchEmbedPreview] Sent cancel for task ${taskId}`);
      } catch (error) {
        console.error(`[EventsSearchEmbedPreview] Failed to cancel task ${taskId}:`, error);
      }
    } else {
      console.warn(`[EventsSearchEmbedPreview] Cannot cancel: no skill_task_id or task_id available`);
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="events"
  skillId="search"
  skillIconName={skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="events-search-details" class:mobile={isMobileLayout}>
      <!-- Query text -->
      <div class="ds-search-query">{query}</div>

      <!-- Provider subtitle -->
      <div class="ds-search-provider">{viaProvider}</div>

      <!-- Finished state: show event count or loading -->
      {#if status === 'finished'}
        <div class="ds-search-results-info">
          {#if eventCount > 0}
            <span class="event-count">
              {$text('embeds.more_results').replace('{count}', String(eventCount))}
            </span>
          {:else if isLoadingChildren}
            <span class="loading-text">{$text('common.loading')}</span>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Events Search Details Content
     =========================================== */

  .events-search-details {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    height: 100%;
  }

  /* Desktop layout: vertically centered content */
  .events-search-details:not(.mobile) {
    justify-content: center;
  }

  /* Mobile layout: top-aligned content */
  .events-search-details.mobile {
    justify-content: flex-start;
  }

  /* Base styles for .ds-search-query / .ds-search-provider / .ds-search-results-info
     are generated from frontend/packages/ui/src/tokens/sources/components/search-results.yml
     See docs/architecture/frontend/design-tokens.md (Phase E). */

  .events-search-details.mobile .ds-search-query {
    font-size: var(--font-size-small);
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }

  .events-search-details.mobile .ds-search-provider {
    font-size: var(--font-size-xxs);
  }

  .events-search-details.mobile .ds-search-results-info {
    margin-top: var(--spacing-1);
  }

  /* Loading text (shown while child embeds are being fetched) */
  .loading-text {
    font-size: var(--font-size-small);
    color: var(--color-grey-70);
    font-weight: 500;
  }

  /* Event count badge */
  .event-count {
    font-size: var(--font-size-small);
    color: var(--color-grey-70);
    font-weight: 500;
  }

  .events-search-details.mobile .event-count {
    font-size: var(--font-size-xxs);
  }

  /* ===========================================
     Skill Icon Styling (skill-specific)
     =========================================== */

  /* Events search skill icon — maps to search.svg (magnifying glass).
     The "search" icon is already registered in BasicInfosBar.svelte and
     used by WebSearch and TravelSearch. This rule ensures it also works
     within the unified-embed-preview context for the events app. */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }

  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>
