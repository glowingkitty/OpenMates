<!--
  frontend/packages/ui/src/components/embeds/travel/TravelPriceCalendarEmbedPreview.svelte
  
  Preview component for Travel Price Calendar skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.
  
  Shows:
  - Route summary (origin -> destination)
  - Month display (e.g., "March 2026")
  - Price range (e.g., "EUR 43 - 93")
  - Days with data count (e.g., "22 of 31 days")
  
  This is a non-composite skill: the embed contains the full calendar data
  directly (no child embeds to load).
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  
  /**
   * Price calendar entry for a single day
   */
  interface PriceCalendarEntry {
    date: string;
    price: number;
    transfers?: number;
    duration_minutes?: number;
    distance_km?: number;
    actual?: boolean;
  }
  
  /**
   * Price calendar result from the backend
   */
  interface PriceCalendarResult {
    type?: string;
    origin?: string;
    origin_name?: string;
    destination?: string;
    destination_name?: string;
    month?: string;
    currency?: string;
    cheapest_price?: number;
    most_expensive_price?: number;
    days_with_data?: number;
    total_days_in_month?: number;
    entries?: PriceCalendarEntry[];
  }
  
  /**
   * Props for travel price calendar embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Search query summary */
    query?: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Price calendar results */
    results?: PriceCalendarResult[];
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
    status: statusProp,
    results: resultsProp,
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Local reactive state for embed data
  let localQuery = $state<string>('');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localResults = $state<PriceCalendarResult[]>([]);
  let localErrorMessage = $state<string>('');
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);
  
  // Initialize local state from props
  $effect(() => {
    localQuery = queryProp || '';
    localStatus = statusProp || 'processing';
    localResults = resultsProp || [];
    localTaskId = taskIdProp;
    localSkillTaskId = skillTaskIdProp;
    localErrorMessage = '';
  });
  
  // Use local state as the source of truth
  let query = $derived(localQuery);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);
  let errorMessage = $derived(localErrorMessage || ($text('chat.an_error_occured') || 'Processing failed.'));
  
  /**
   * Handle embed data updates from UnifiedEmbedPreview
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[TravelPriceCalendarEmbedPreview] Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    
    const content = data.decodedContent;
    if (content) {
      if (typeof content.query === 'string') localQuery = content.query;
      if (typeof content.error === 'string') localErrorMessage = content.error;
      if (typeof content.skill_task_id === 'string') localSkillTaskId = content.skill_task_id;
      
      if (content.results && Array.isArray(content.results)) {
        localResults = flattenResults(content.results as PriceCalendarResult[]);
      }
    }
  }
  
  // Skill display name from translations
  let skillName = $derived($text('app_skills.travel.price_calendar') || 'Price Calendar');
  
  // Skill icon
  const skillIconName = 'calendar';
  
  /**
   * Flatten nested results if needed (backend returns [{id, results: [...]}])
   */
  function flattenResults(rawResults: PriceCalendarResult[]): PriceCalendarResult[] {
    if (!rawResults || rawResults.length === 0) return [];
    
    const firstItem = rawResults[0] as Record<string, unknown>;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      const flattened: PriceCalendarResult[] = [];
      for (const entry of rawResults as unknown as Array<{ id?: string; results?: PriceCalendarResult[] }>) {
        if (entry.results && Array.isArray(entry.results)) {
          flattened.push(...entry.results);
        }
      }
      return flattened;
    }
    
    return rawResults;
  }
  
  let flatResults = $derived(flattenResults(results));
  
  // First result (price calendar returns one result per request)
  let firstResult = $derived(flatResults.length > 0 ? flatResults[0] : null);
  
  // Route summary: origin -> destination
  let routeSummary = $derived.by(() => {
    if (!firstResult) return query || '';
    const origin = firstResult.origin_name || firstResult.origin || '';
    const dest = firstResult.destination_name || firstResult.destination || '';
    if (origin && dest) return `${origin} \u2192 ${dest}`;
    return query || '';
  });
  
  // Month display (e.g., "March 2026")
  let monthDisplay = $derived.by(() => {
    if (!firstResult?.month) return '';
    try {
      const [year, month] = firstResult.month.split('-');
      const date = new Date(parseInt(year), parseInt(month) - 1, 1);
      return date.toLocaleDateString([], { month: 'long', year: 'numeric' });
    } catch {
      return firstResult.month;
    }
  });
  
  // Price range display (e.g., "EUR 43 - 93")
  let priceRange = $derived.by(() => {
    if (!firstResult?.cheapest_price) return '';
    const currency = firstResult.currency || 'EUR';
    const min = Math.round(firstResult.cheapest_price);
    const max = firstResult.most_expensive_price ? Math.round(firstResult.most_expensive_price) : null;
    if (max && max !== min) {
      return `${currency} ${min} \u2013 ${max}`;
    }
    return `${currency} ${min}`;
  });
  
  // Days with data display (e.g., "22 of 31 days")
  let daysInfo = $derived.by(() => {
    if (!firstResult) return '';
    const days = firstResult.days_with_data || 0;
    const total = firstResult.total_days_in_month || 31;
    if (days === 0) return '';
    return `${days} / ${total} ${$text('embeds.days') || 'days'}`;
  });
  
  // Handle stop button click
  async function handleStop() {
    if (status !== 'processing') return;
    
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
      } catch (error) {
        console.error(`[TravelPriceCalendarEmbedPreview] Failed to cancel skill:`, error);
      }
    } else if (taskId) {
      try {
        await chatSyncService.sendCancelAiTask(taskId);
      } catch (error) {
        console.error(`[TravelPriceCalendarEmbedPreview] Failed to cancel task:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="travel"
  skillId="price_calendar"
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
    <div class="price-calendar-details" class:mobile={isMobileLayout}>
      <!-- Route summary (e.g., "Munich -> London") -->
      <div class="route-summary">{routeSummary}</div>
      
      <!-- Month (e.g., "March 2026") -->
      {#if monthDisplay}
        <div class="month-display">{monthDisplay}</div>
      {/if}
      
      <!-- Provider -->
      <div class="provider-text">{$text('embeds.via') || 'via'} Travelpayouts</div>
      
      <!-- Error state -->
      {#if status === 'error'}
        <div class="calendar-error">
          <div class="calendar-error-title">{$text('embeds.search_failed') || 'Search failed'}</div>
          <div class="calendar-error-message">{errorMessage}</div>
        </div>
      {:else if status === 'finished'}
        <!-- Finished state: price range and days info -->
        <div class="calendar-results-info">
          {#if priceRange}
            <span class="price-range">{priceRange}</span>
          {/if}
          
          {#if daysInfo}
            <span class="days-info">{daysInfo}</span>
          {/if}
          
          {#if !priceRange && !daysInfo && firstResult}
            <span class="no-data-text">{$text('embeds.no_price_data') || 'No price data available'}</span>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Price Calendar Details Content
     =========================================== */
  
  .price-calendar-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .price-calendar-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .price-calendar-details.mobile {
    justify-content: flex-start;
  }
  
  /* Route summary text */
  .route-summary {
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
  
  .price-calendar-details.mobile .route-summary {
    font-size: 14px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }
  
  /* Month display */
  .month-display {
    font-size: 14px;
    color: var(--color-grey-80);
    font-weight: 500;
    line-height: 1.3;
  }
  
  .price-calendar-details.mobile .month-display {
    font-size: 12px;
  }
  
  /* Provider subtitle */
  .provider-text {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .price-calendar-details.mobile .provider-text {
    font-size: 12px;
  }
  
  /* Calendar results info (price range + days) */
  .calendar-results-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
    flex-wrap: wrap;
  }
  
  .price-calendar-details.mobile .calendar-results-info {
    margin-top: 2px;
  }
  
  /* Price range */
  .price-range {
    font-size: 14px;
    color: var(--color-primary);
    font-weight: 600;
  }
  
  .price-calendar-details.mobile .price-range {
    font-size: 12px;
  }
  
  /* Days info */
  .days-info {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
  }
  
  .price-calendar-details.mobile .days-info {
    font-size: 12px;
  }
  
  /* No data text */
  .no-data-text {
    font-size: 14px;
    color: var(--color-grey-60);
    font-style: italic;
  }
  
  .price-calendar-details.mobile .no-data-text {
    font-size: 12px;
  }
  
  /* Error styling */
  .calendar-error {
    margin-top: 6px;
    padding: 8px 10px;
    border-radius: 12px;
    background-color: rgba(var(--color-error-rgb), 0.08);
    border: 1px solid rgba(var(--color-error-rgb), 0.3);
  }
  
  .calendar-error-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-error);
  }
  
  .calendar-error-message {
    margin-top: 2px;
    font-size: 12px;
    color: var(--color-grey-70);
    line-height: 1.4;
    word-break: break-word;
  }
</style>
