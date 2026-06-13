<!--
  frontend/packages/ui/src/components/embeds/events/EventsSearchEmbedPreview.svelte

  Preview component for Events Search skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.

  Details content structure:
  - Processing: query text + selected provider label when available
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
    providers?: string[] | string;
    /** Processing status - must match SkillExecutionStatus */
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Event results (for finished state) */
    results?: EventResult[];
    /** Parent-embed result count used without hydrating child embeds */
    result_count?: number;
    /** Searched start date/time, echoed from the skill request */
    start_date?: string;
    /** Searched end date/time, echoed from the skill request */
    end_date?: string;
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
      case 'eventbrite':          return 'Eventbrite';
      case 'google_events':       return 'Google';
      case 'resident_advisor':    return 'Resident Advisor';
      case 'siegessaeule':        return 'Siegessäule';
      case 'classictic':          return 'Classictic';
      case 'berlin_philharmonic': return 'Berlin Philharmonic';
      case 'bachtrack':           return 'Bachtrack';
      default:                    return slug || '';
    }
  }

  function normalizeProviderSlug(slug: string): string {
    return slug.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  }

  function parseProviders(value: unknown): string[] {
    if (Array.isArray(value)) {
      return value.filter((provider): provider is string => typeof provider === 'string' && provider.trim().length > 0);
    }
    if (typeof value === 'string') {
      return value.split('|').map((provider) => provider.trim()).filter((provider) => provider.length > 0);
    }
    return [];
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    providers: providersProp,
    status: statusProp,
    results: resultsProp = [],
    result_count: resultCountProp = 0,
    start_date: startDateProp,
    end_date: endDateProp,
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
  let localResultCount = $state(0);
  let localStartDate = $state<string>('');
  let localEndDate = $state<string>('');
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);

  // Initialize local state from props
  $effect(() => {
    if (!storeResolved) {
      localQuery = queryProp || '';
      localProvider = providerProp || '';
      localProviders = parseProviders(providersProp);
      localStatus = statusProp || 'processing';
      localResults = resultsProp || [];
      localResultCount = resultCountProp || resultsProp?.length || 0;
      localStartDate = startDateProp || '';
      localEndDate = endDateProp || '';
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
  let startDate = $derived(localStartDate);
  let endDate = $derived(localEndDate);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);

  /**
   * Handle embed data updates from UnifiedEmbedPreview.
   * Called when the parent component receives and decodes updated embed data.
   *
   * Preview cards must remain metadata-only. Full child event rows are loaded by
   * fullscreen views on explicit user action, not by the chat transcript preview.
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
      if (typeof content.start_date === 'string') localStartDate = content.start_date;
      if (typeof content.end_date === 'string') localEndDate = content.end_date;
      const decodedProviders = parseProviders(content.providers);
      if (decodedProviders.length > 0) localProviders = decodedProviders;
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results as EventResult[];
        localResultCount = localResults.length;
        console.debug(`[EventsSearchEmbedPreview] Updated results (inline):`, localResults.length);
      }
      if (typeof content.result_count === 'number') {
        localResultCount = content.result_count;
      } else if (data.status === 'finished' && localResultCount === 0) {
        const embedIds = content.embed_ids;
        const childEmbedIds: string[] = typeof embedIds === 'string'
          ? embedIds.split('|').filter((eid: string) => eid.length > 0)
          : Array.isArray(embedIds) ? (embedIds as string[]) : [];
        localResultCount = childEmbedIds.length;
      }
      if (typeof content.skill_task_id === 'string') {
        localSkillTaskId = content.skill_task_id;
      }
    }
  }

  // Get skill name from translations (reuse embeds.search key — "Search")
  let skillName = $derived($text('common.search'));

  // Use "search" icon (magnifying glass) matching WebSearch and TravelSearch conventions.
  // The app-level icon is "event" (calendar), but the search *skill* uses "search".
  const skillIconName = 'search';

  let viaProvider = $derived($text('embeds.via'));

  function formatSearchDate(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    }).format(date);
  }

  let searchRange = $derived.by(() => {
    if (startDate && endDate) return `${formatSearchDate(startDate)} - ${formatSearchDate(endDate)}`;
    if (startDate) return formatSearchDate(startDate);
    if (endDate) return formatSearchDate(endDate);
    return '';
  });

  // Event count for finished state: the total number of results
  let eventCount = $derived(localResultCount || results?.length || 0);

  let providerBadges = $derived.by(() => {
    const providerSources = providers.length > 0 ? providers : [provider];
    const seen = new Set<string>();
    return providerSources
      .map((providerSlug) => ({
        slug: normalizeProviderSlug(providerSlug),
        label: getProviderLabel(providerSlug)
      }))
      .filter((provider) => {
        if (!provider.slug || provider.slug === 'none' || provider.slug === 'auto' || seen.has(provider.slug)) {
          return false;
        }
        seen.add(provider.slug);
        return provider.label.length > 0;
      });
  });

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

      {#if searchRange}
        <div class="events-search-range" data-testid="events-search-range">{searchRange}</div>
      {/if}

      <!-- Provider attribution: text "via" plus icon chips, matching web search previews. -->
      <div class="provider-attribution" aria-label={providerBadges.map((provider) => provider.label).join(', ')}>
        <span class="ds-search-provider">{viaProvider}</span>
        {#if providerBadges.length > 0}
          <span class="provider-badges">
          {#each providerBadges as provider}
            <span class={`provider-badge provider-badge-${provider.slug}`} title={provider.label}>
              <span class="provider-badge-icon" aria-hidden="true"></span>
            </span>
          {/each}
          </span>
        {/if}
      </div>

      <!-- Finished state: show event count or loading -->
      {#if status === 'finished'}
        <div class="ds-search-results-info">
          {#if eventCount > 0}
            <span class="event-count">
              {$text('embeds.more_results').replace('{count}', String(eventCount))}
            </span>
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

  .provider-attribution {
    display: flex;
    align-items: center;
    gap: var(--spacing-2);
    min-width: 0;
  }

  .events-search-range {
    color: var(--color-grey-70);
    font-size: var(--font-size-xs);
    font-weight: 500;
    line-height: 1.3;
  }

  .events-search-details.mobile .events-search-range {
    font-size: var(--font-size-xxs);
  }

  .provider-badges {
    display: flex;
    flex-wrap: nowrap;
    align-items: center;
  }

  .provider-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 19px;
    height: 19px;
    margin-left: -6px;
    border: 1px solid var(--color-grey-0);
    border-radius: 50%;
    background: var(--color-grey-0);
    color: var(--color-grey-70);
    box-sizing: border-box;
  }

  .provider-badge:first-child {
    margin-left: 0;
  }

  .provider-badge-icon {
    width: 13px;
    height: 13px;
    flex: 0 0 auto;
    background-color: currentColor;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
  }

  .provider-badge-meetup .provider-badge-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/meetup.svg');
    mask-image: url('@openmates/ui/static/icons/meetup.svg');
  }

  .provider-badge-luma .provider-badge-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/luma.svg');
    mask-image: url('@openmates/ui/static/icons/luma.svg');
  }

  .provider-badge-resident_advisor .provider-badge-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/resident_advisor.svg');
    mask-image: url('@openmates/ui/static/icons/resident_advisor.svg');
  }

  .events-search-details.mobile .ds-search-results-info {
    margin-top: var(--spacing-1);
  }

  /* .ds-loading-text base styles are generated from
     frontend/packages/ui/src/tokens/sources/components/loading.yml */

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
