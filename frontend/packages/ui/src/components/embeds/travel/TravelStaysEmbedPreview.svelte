<!--
  frontend/packages/ui/src/components/embeds/travel/TravelStaysEmbedPreview.svelte
  
  Preview component for Travel Search Stays skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.
  
  This is a composite skill: each stay result is a separate child embed.
  The parent embed contains metadata (query, provider, result_count, embed_ids).
  
  Shows:
  - Search query / destination
  - Check-in → check-out dates
  - Provider ("via Google")
  - Property count and cheapest nightly rate (when finished)
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  
  /**
   * Stay result interface for preview display.
   * Contains summary fields needed for the preview card.
   */
  interface StayResult {
    type?: string;
    name?: string;
    property_type?: string;
    rate_per_night?: string;
    extracted_rate_per_night?: number;
    total_rate?: string;
    extracted_total_rate?: number;
    currency?: string;
    overall_rating?: number;
    reviews?: number;
    hotel_class?: number;
    thumbnail?: string;
    amenities?: string[];
    eco_certified?: boolean;
    free_cancellation?: boolean;
  }
  
  /**
   * Props for travel stays embed preview.
   * Supports both skill preview data format and direct embed format.
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Search query summary (e.g., "Hotels in Barcelona") */
    query?: string;
    /** Search provider (e.g., 'Google') */
    provider?: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Stay results (for finished state) */
    results?: StayResult[];
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
  
  // Local reactive state for embed data - updated when embed data changes
  let localQuery = $state<string>('');
  let localProvider = $state<string>('Google');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localResults = $state<StayResult[]>([]);
  let localResultCount = $state<number | undefined>(undefined);
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
   * Handle embed data updates from UnifiedEmbedPreview.
   * Called when the parent component receives and decodes updated embed data.
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[TravelStaysEmbedPreview] Received embed data update for ${id}:`, {
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
      
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results as StayResult[];
      }
      // Composite pattern: parent embed has result_count instead of individual results
      if (typeof content.result_count === 'number') {
        localResultCount = content.result_count;
      }
    }
  }
  
  // Skill display name from translations
  let skillName = $derived($text('app_skills.travel.search_stays'));
  
  // Skill icon
  const skillIconName = 'search';
  
  // Get "via {provider}" text
  let viaProvider = $derived(
    `${$text('embeds.via')} ${provider}`
  );
  
  /**
   * Flatten nested results if needed (backend returns [{id, results: [...]}] for multi-request)
   */
  function flattenResults(rawResults: StayResult[]): StayResult[] {
    if (!rawResults || rawResults.length === 0) return [];
    
    const firstItem = rawResults[0] as Record<string, unknown>;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      const flattened: StayResult[] = [];
      for (const entry of rawResults as unknown as Array<{ id?: string; results?: StayResult[] }>) {
        if (entry.results && Array.isArray(entry.results)) {
          flattened.push(...entry.results);
        }
      }
      return flattened;
    }
    
    return rawResults;
  }
  
  let flatResults = $derived(flattenResults(results));
  
  // Property count display
  // Prefer inline results length (legacy), fall back to result_count from composite parent metadata
  let propertyCount = $derived(flatResults.length > 0 ? flatResults.length : (localResultCount ?? 0));
  
  // Price range display: cheapest nightly rate
  let priceInfo = $derived.by(() => {
    if (flatResults.length === 0) return '';
    
    const prices = flatResults
      .filter(r => r.extracted_rate_per_night != null && r.extracted_rate_per_night > 0)
      .map(r => r.extracted_rate_per_night!);
    
    if (prices.length === 0) return '';
    
    const currency = flatResults[0]?.currency || 'EUR';
    const minPrice = Math.min(...prices);
    
    const perNightText = $text('embeds.per_night');
    
    if (prices.length === 1) {
      return `${currency} ${Math.round(minPrice)} ${perNightText}`;
    }
    
    return `${$text('embeds.from')} ${currency} ${Math.round(minPrice)} ${perNightText}`;
  });
  
  // Handle stop button click
  async function handleStop() {
    if (status !== 'processing') return;
    
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
      } catch (error) {
        console.error(`[TravelStaysEmbedPreview] Failed to cancel skill:`, error);
      }
    } else if (taskId) {
      try {
        await chatSyncService.sendCancelAiTask(taskId);
      } catch (error) {
        console.error(`[TravelStaysEmbedPreview] Failed to cancel task:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="travel"
  skillId="search_stays"
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
    <div class="travel-stays-details" class:mobile={isMobileLayout}>
      <!-- Search query (e.g., "Hotels in Barcelona") -->
      <div class="search-query">{query}</div>
      
      <!-- Provider subtitle -->
      <div class="search-provider">{viaProvider}</div>
      
      <!-- Error state -->
      {#if status === 'error'}
        <div class="search-error">
          <div class="search-error-title">{$text('embeds.search_failed')}</div>
          <div class="search-error-message">{errorMessage}</div>
        </div>
      {:else if status === 'finished'}
        <!-- Finished state: show property count and price -->
        <div class="search-results-info">
          {#if propertyCount > 0}
            <span class="property-count">
              {propertyCount} {propertyCount === 1 ? $text('embeds.stay') : $text('embeds.stays')}
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
     Travel Stays Details Content
     =========================================== */
  
  .travel-stays-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .travel-stays-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .travel-stays-details.mobile {
    justify-content: flex-start;
  }
  
  /* Query text */
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
  
  .travel-stays-details.mobile .search-query {
    font-size: 14px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }
  
  /* Provider subtitle */
  .search-provider {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .travel-stays-details.mobile .search-provider {
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
  
  .travel-stays-details.mobile .search-results-info {
    margin-top: 2px;
  }
  
  /* Property count */
  .property-count {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
  }
  
  .travel-stays-details.mobile .property-count {
    font-size: 12px;
  }
  
  /* Price info */
  .price-info {
    font-size: 14px;
    color: var(--color-primary);
    font-weight: 600;
  }
  
  .travel-stays-details.mobile .price-info {
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
</style>
