<!--
  frontend/packages/ui/src/components/embeds/travel/TravelSearchEmbedPreview.svelte
  
  Preview component for Travel Search Connections skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives query, provider, results directly
  
  Details content structure:
  - Processing: route summary (origin → destination) + "via {provider}"
  - Finished: route summary + "via {provider}" + connection count + price range
  
  NOTE: Real-time updates when embed status changes from 'processing' to 'finished'
  are handled by UnifiedEmbedPreview, which subscribes to embedUpdated events.
  This component implements the onEmbedDataUpdated callback to update its
  specific data (query, provider, results) when notified by the parent.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  
  /**
   * Connection result interface for preview display
   * Contains summary fields needed for the preview card
   */
  interface ConnectionResult {
    type?: string;
    transport_method?: string;
    trip_type?: string;
    total_price?: string;
    currency?: string;
    origin?: string;
    destination?: string;
    departure?: string;
    arrival?: string;
    duration?: string;
    stops?: number;
    carriers?: string[];
  }
  
  /**
   * Props for travel search embed preview
   * Supports both skill preview data format and direct embed format
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Search query summary (e.g., "Munich → London, 2025-03-15") */
    query?: string;
    /** Search provider (e.g., 'Google') */
    provider?: string;
    /** Processing status - must match SkillExecutionStatus */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Connection results (for finished state) */
    results?: ConnectionResult[];
    /** Task ID for cancellation of entire AI response */
    taskId?: string;
    /** Skill task ID for cancellation of just this skill */
    skillTaskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
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
  
  // Local reactive state for embed data - these can be updated when embed data changes
  let localQuery = $state<string>('');
  let localProvider = $state<string>('Google');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localResults = $state<ConnectionResult[]>([]);
  let localErrorMessage = $state<string>('');
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);
  
  // Initialize local state from props
  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'Google';
    localStatus = statusProp || 'processing';
    localResults = resultsProp || [];
    localTaskId = taskIdProp;
    localSkillTaskId = skillTaskIdProp;
    localErrorMessage = '';
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);
  let errorMessage = $derived(localErrorMessage || $text('chat.an_error_occured'));
  
  /**
   * Handle embed data updates from UnifiedEmbedPreview
   * Called when the parent component receives and decodes updated embed data
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[TravelSearchEmbedPreview] Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    
    const content = data.decodedContent;
    if (content) {
      if (typeof content.query === 'string') localQuery = content.query;
      if (typeof content.provider === 'string') localProvider = content.provider;
      if (typeof content.error === 'string') localErrorMessage = content.error;
      if (typeof content.skill_task_id === 'string') localSkillTaskId = content.skill_task_id;
      
      // Load child embeds if parent has embed_ids but no results
      if (data.status === 'finished' && (!content.results || !Array.isArray(content.results) || content.results.length === 0)) {
        const embedIds = content.embed_ids;
        if (embedIds) {
          const childEmbedIds: string[] = typeof embedIds === 'string'
            ? (embedIds as string).split('|').filter((cid: string) => cid.length > 0)
            : Array.isArray(embedIds) ? (embedIds as string[]) : [];
          
          if (childEmbedIds.length > 0) {
            console.debug(`[TravelSearchEmbedPreview] Loading child embeds for preview (${childEmbedIds.length} embed_ids)`);
            loadChildEmbedsForPreview(childEmbedIds);
          }
        }
      }
      
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results as ConnectionResult[];
      }
    }
  }
  
  /**
   * Load child embeds to extract connection data for preview display
   * Uses retry logic because child embeds might not be persisted yet
   */
  async function loadChildEmbedsForPreview(childEmbedIds: string[]) {
    try {
      const { loadEmbedsWithRetry, decodeToonContent } = await import('../../../services/embedResolver');
      const childEmbeds = await loadEmbedsWithRetry(childEmbedIds, 5, 300);
      
      if (childEmbeds.length > 0) {
        const connectionResults = await Promise.all(childEmbeds.map(async (embed) => {
          const content = embed.content ? await decodeToonContent(embed.content) : null;
          if (!content) return null;
          
          return {
            type: content.type as string || 'connection',
            transport_method: content.transport_method as string || 'airplane',
            trip_type: content.trip_type as string || 'one_way',
            total_price: content.total_price as string || undefined,
            currency: content.currency as string || undefined,
            origin: content.origin as string || undefined,
            destination: content.destination as string || undefined,
            departure: content.departure as string || undefined,
            arrival: content.arrival as string || undefined,
            duration: content.duration as string || undefined,
            stops: content.stops as number || 0,
            carriers: content.carriers as string[] || [],
          } as ConnectionResult;
        }));
        
        const valid = connectionResults.filter(r => r !== null) as ConnectionResult[];
        if (valid.length > 0) {
          localResults = valid;
          console.debug(`[TravelSearchEmbedPreview] Loaded ${valid.length} connection results from child embeds`);
        }
      }
    } catch (error) {
      console.warn('[TravelSearchEmbedPreview] Error loading child embeds for preview:', error);
    }
  }
  
  // Skill display name from translations
  let skillName = $derived($text('app_skills.travel.search_connections'));
  
  // Skill icon
  const skillIconName = 'search';
  
  // Get "via {provider}" text
  let viaProvider = $derived(
    `${$text('embeds.via')} ${provider}`
  );
  
  /**
   * Flatten nested results if needed (backend returns [{id, results: [...]}] for multi-request)
   */
  function flattenResults(rawResults: ConnectionResult[]): ConnectionResult[] {
    if (!rawResults || rawResults.length === 0) return [];
    
    const firstItem = rawResults[0] as Record<string, unknown>;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      const flattened: ConnectionResult[] = [];
      for (const entry of rawResults as unknown as Array<{ id?: string; results?: ConnectionResult[] }>) {
        if (entry.results && Array.isArray(entry.results)) {
          flattened.push(...entry.results);
        }
      }
      return flattened;
    }
    
    return rawResults;
  }
  
  let flatResults = $derived(flattenResults(results));
  
  // Route summary: origin → destination from first result
  let routeSummary = $derived.by(() => {
    if (flatResults.length > 0) {
      const first = flatResults[0];
      if (first.origin && first.destination) {
        return `${first.origin} → ${first.destination}`;
      }
    }
    return query || '';
  });
  
  // Date display: extract departure date from first result
  let dateDisplay = $derived.by(() => {
    if (flatResults.length === 0) return '';
    const first = flatResults[0];
    if (!first.departure) return '';
    try {
      const date = new Date(first.departure);
      return date.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  });
  
  // Price range display
  let priceInfo = $derived.by(() => {
    if (flatResults.length === 0) return '';
    
    const prices = flatResults
      .filter(r => r.total_price)
      .map(r => parseFloat(r.total_price!));
    
    if (prices.length === 0) return '';
    
    const currency = flatResults[0]?.currency || 'EUR';
    const minPrice = Math.min(...prices);
    
    if (prices.length === 1) {
      return `${currency} ${Math.round(minPrice)}`;
    }
    
    return `${$text('embeds.from')} ${currency} ${Math.round(minPrice)}`;
  });
  
  // Connection count display
  let connectionCount = $derived(flatResults.length);
  
  // Handle stop button click
  async function handleStop() {
    if (status !== 'processing') return;
    
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
      } catch (error) {
        console.error(`[TravelSearchEmbedPreview] Failed to cancel skill:`, error);
      }
    } else if (taskId) {
      try {
        await chatSyncService.sendCancelAiTask(taskId);
      } catch (error) {
        console.error(`[TravelSearchEmbedPreview] Failed to cancel task:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="travel"
  skillId="search_connections"
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
    <div class="travel-search-details" class:mobile={isMobileLayout}>
      <!-- Route summary (e.g., "Munich (MUC) → London Heathrow (LHR)") -->
      <div class="search-query">{routeSummary || query}</div>
      
      <!-- Trip date (e.g., "Fri, Mar 7") -->
      {#if dateDisplay}
        <div class="search-date">{dateDisplay}</div>
      {/if}
      
      <!-- Provider subtitle -->
      <div class="search-provider">{viaProvider}</div>
      
      <!-- Error state -->
      {#if status === 'error'}
        <div class="search-error">
          <div class="search-error-title">{$text('embeds.search_failed')}</div>
          <div class="search-error-message">{errorMessage}</div>
        </div>
      {:else if status === 'finished'}
        <!-- Finished state: show connection count and price -->
        <div class="search-results-info">
          {#if connectionCount > 0}
            <span class="connection-count">
              {connectionCount} {connectionCount === 1 ? $text('embeds.connection') : $text('embeds.connections')}
            </span>
          {/if}
          
          {#if priceInfo}
            <span class="price-info">{priceInfo}</span>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Travel Search Details Content
     =========================================== */
  
  .travel-search-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .travel-search-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .travel-search-details.mobile {
    justify-content: flex-start;
  }
  
  /* Query/route text */
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
  
  .travel-search-details.mobile .search-query {
    font-size: 14px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }
  
  /* Trip date */
  .search-date {
    font-size: 14px;
    color: var(--color-grey-80);
    font-weight: 500;
    line-height: 1.3;
  }
  
  .travel-search-details.mobile .search-date {
    font-size: 12px;
  }
  
  /* Provider subtitle */
  .search-provider {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .travel-search-details.mobile .search-provider {
    font-size: 12px;
  }
  
  /* Search results info (count + price) */
  .search-results-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
    flex-wrap: wrap;
  }
  
  .travel-search-details.mobile .search-results-info {
    margin-top: 2px;
  }
  
  /* Connection count */
  .connection-count {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
  }
  
  .travel-search-details.mobile .connection-count {
    font-size: 12px;
  }
  
  /* Price info */
  .price-info {
    font-size: 14px;
    color: var(--color-primary);
    font-weight: 600;
  }
  
  .travel-search-details.mobile .price-info {
    font-size: 12px;
  }
  
  /* Error styling */
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
  
  /* Skill icon uses the existing 'search' icon mapping from BasicInfosBar */
</style>
