<!--
  frontend/packages/ui/src/components/embeds/news/NewsSearchEmbedPreview.svelte
  
  Preview component for News Search skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.
  
  Details content structure:
  - Processing: query text + "via {provider}"
  - Finished: query text + "via {provider}" + favicons (first 3) + "+ N more"
  
  NOTE: Real-time updates are handled by UnifiedEmbedPreview via embedUpdated events.
  This component implements onEmbedDataUpdated to update its specific data.
  
  Favicon handling matches WebSearchEmbedPreview:
  - Supports multiple favicon field formats (favicon, favicon_url, meta_url.favicon, meta_url_favicon)
  - Loads child embeds asynchronously when parent has embed_ids but no results
  - Flattens nested results structure from backend
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  
  /**
   * News search result interface for favicon display
   * Supports multiple favicon field formats depending on data source:
   * - favicon: Direct field from backend (most common)
   * - favicon_url: Alternative flat format
   * - meta_url.favicon: Nested structure from raw Brave Search API
   */
  interface NewsSearchResult {
    title?: string;
    url: string;
    /** Direct favicon URL from backend (primary format) */
    favicon?: string;
    /** Alternative direct favicon URL */
    favicon_url?: string;
    /** Nested meta_url structure from Brave Search (raw API format) */
    meta_url?: {
      favicon?: string;
    };
    thumbnail?: {
      original?: string;
    };
    description?: string;
  }
  
  /**
   * Extract favicon URL from result (handles all possible formats)
   * Priority: favicon > favicon_url > meta_url.favicon
   * @param result - Search result object
   * @returns Favicon URL or undefined
   */
  function getFaviconUrl(result: NewsSearchResult): string | undefined {
    // Check direct favicon field first (backend format)
    if (result.favicon) return result.favicon;
    // Check alternative flat format
    if (result.favicon_url) return result.favicon_url;
    // Check nested format (raw Brave Search API)
    if (result.meta_url?.favicon) return result.meta_url.favicon;
    return undefined;
  }
  
  /**
   * Props for news search embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Search query */
    query: string;
    /** Search provider (e.g., 'Brave Search') */
    provider: string;
    /** Processing status - must match SkillExecutionStatus */
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Search results (for finished state) */
    results?: NewsSearchResult[];
    /** Task ID for cancellation of entire AI response */
    taskId?: string;
    /** Skill task ID for cancellation of just this skill (allows AI to continue) */
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
    results: resultsProp = [],
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Local reactive state for embed data - these can be updated when embed data changes
  // CRITICAL: Using $state allows us to update these values when we receive embed updates
  // via the onEmbedDataUpdated callback from UnifiedEmbedPreview
  let localQuery = $state<string>('');
  let localProvider = $state<string>('Brave Search');
  // NOTE: Must include 'cancelled' to match SkillExecutionStatus type
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localResults = $state<NewsSearchResult[]>([]);
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);
  
  // Initialize local state from props
  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'Brave Search';
    localStatus = statusProp || 'processing';
    localResults = resultsProp || [];
    localTaskId = taskIdProp;
    localSkillTaskId = skillTaskIdProp;
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);
  
  /**
   * Handle embed data updates from UnifiedEmbedPreview
   * Called when the parent component receives and decodes updated embed data
   * 
   * NOTE: When parent embed becomes "finished", it may have `embed_ids` but no `results`.
   * In this case, we need to load child embeds asynchronously to get favicon data.
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[NewsSearchEmbedPreview] 🔄 Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    // Update status - handle all SkillExecutionStatus values
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    
    // Update news-search-specific fields from decoded content
    const content = data.decodedContent;
    if (content) {
      if (typeof content.query === 'string') localQuery = content.query;
      if (typeof content.provider === 'string') localProvider = content.provider;
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results as NewsSearchResult[];
        console.debug(`[NewsSearchEmbedPreview] Updated results from callback:`, localResults.length);
      }
      // Extract skill_task_id for individual skill cancellation
      if (typeof content.skill_task_id === 'string') {
        localSkillTaskId = content.skill_task_id;
      }
      
      // CRITICAL FIX: When status is "finished" and we have embed_ids but no results,
      // load child embeds asynchronously to get favicon data for preview display.
      // This handles the architecture where parent embed only stores references.
      if (data.status === 'finished' && (!content.results || !Array.isArray(content.results) || content.results.length === 0)) {
        const embedIds = content.embed_ids;
        if (embedIds) {
          // Parse embed_ids (can be pipe-separated string or array)
          const childEmbedIds: string[] = typeof embedIds === 'string'
            ? (embedIds as string).split('|').filter((id: string) => id.length > 0)
            : Array.isArray(embedIds) ? (embedIds as string[]) : [];
          
          if (childEmbedIds.length > 0) {
            console.debug(`[NewsSearchEmbedPreview] Loading child embeds for preview (${childEmbedIds.length} embed_ids)`);
            loadChildEmbedsForPreview(childEmbedIds);
          }
        }
      }
    }
  }
  
  /**
   * Load child embeds to extract favicon data for preview display
   * Uses retry logic because child embeds might not be persisted yet
   * (they arrive via websocket after the parent embed)
   */
  async function loadChildEmbedsForPreview(childEmbedIds: string[]) {
    try {
      const { loadEmbedsWithRetry, decodeToonContent } = await import('../../../services/embedResolver');
      
      // Use retry logic with shorter timeout for preview (we just need a few favicons)
      const childEmbeds = await loadEmbedsWithRetry(childEmbedIds, 5, 300);
      
      if (childEmbeds.length > 0) {
        // Transform child embeds to NewsSearchResult format (just need basic data for favicons)
        const results = await Promise.all(childEmbeds.map(async (embed) => {
          const content = embed.content ? await decodeToonContent(embed.content) : null;
          if (!content) return null;
          
          // Extract favicon URL from multiple possible field formats:
          // 1. meta_url_favicon: TOON-flattened format (meta_url.favicon becomes meta_url_favicon)
          // 2. meta_url.favicon: Nested format (raw API or non-TOON encoded)
          // 3. favicon: Direct field (processed backend format)
          // 4. favicon_url: Alternative flat format
          const faviconUrl = 
            content.meta_url_favicon ||  // TOON flattened format (most common for stored embeds)
            (content.meta_url as { favicon?: string } | undefined)?.favicon ||  // Nested format
            content.favicon || 
            content.favicon_url ||
            '';
          
          // DEBUG: Log what we extracted to help diagnose issues
          if (childEmbeds.indexOf(embed) < 3) {
            console.debug(`[NewsSearchEmbedPreview] Child embed favicon extraction:`, {
              embedId: embed.embed_id,
              title: content.title?.substring(0, 30),
              meta_url_favicon: content.meta_url_favicon,
              meta_url: content.meta_url,
              favicon: content.favicon,
              favicon_url: content.favicon_url,
              extracted: faviconUrl
            });
          }
          
          return {
            title: content.title || '',
            url: content.url || '',
            favicon: faviconUrl,
            favicon_url: faviconUrl
          } as NewsSearchResult;
        }));
        
        const validResults = results.filter(r => r !== null) as NewsSearchResult[];
        if (validResults.length > 0) {
          localResults = validResults;
          console.debug(`[NewsSearchEmbedPreview] Loaded ${validResults.length} results from child embeds, favicons found: ${validResults.filter(r => r.favicon).length}`);
        }
      }
    } catch (error) {
      console.warn('[NewsSearchEmbedPreview] Error loading child embeds for preview:', error);
      // Continue without results - preview will just show query/provider
    }
  }
  
  // Get skill name from translations
  let skillName = $derived($text('embeds.search.text') || 'Search');
  
  // Map skillId to icon name - this is skill-specific logic
  const skillIconName = 'search';
  
  // Preview server base URL for image proxying
  // ALL external images must be proxied for user privacy (hides user IP from external servers)
  const PREVIEW_SERVER = 'https://preview.openmates.org';
  
  /**
   * Proxy a favicon URL through the preview server for privacy.
   * This prevents direct requests to external CDNs (like Brave Search) which would expose user IPs.
   * Uses the /api/v1/image endpoint which handles caching and image optimization.
   * @param faviconUrl - Direct favicon URL to proxy
   * @returns Proxied URL through preview server, or empty string if no URL
   */
  function getProxiedFaviconUrl(faviconUrl: string | undefined): string {
    if (!faviconUrl) return '';
    return `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(faviconUrl)}&max_width=38`;
  }
  
  // Get "via {provider}" text from translations
  let viaProvider = $derived(
    `${$text('embeds.via.text') || 'via'} ${provider}`
  );
  
  /**
   * Extract favicon URL from a raw result object
   * Handles multiple possible field formats from different data sources:
   * - meta_url_favicon: TOON-flattened format (most common for stored embeds)
   * - favicon: Direct field (processed backend format)
   * - favicon_url: Alternative flat format
   * - meta_url.favicon: Nested format from raw Brave Search API
   * 
   * @param rawResult - Raw result object from backend
   * @returns Favicon URL or undefined
   */
  function extractFaviconFromRaw(rawResult: Record<string, unknown>): string | undefined {
    // TOON-flattened format (meta_url.favicon becomes meta_url_favicon)
    if (rawResult.meta_url_favicon && typeof rawResult.meta_url_favicon === 'string') {
      return rawResult.meta_url_favicon;
    }
    // Direct favicon field (processed backend format)
    if (rawResult.favicon && typeof rawResult.favicon === 'string') {
      return rawResult.favicon;
    }
    // Alternative flat format
    if (rawResult.favicon_url && typeof rawResult.favicon_url === 'string') {
      return rawResult.favicon_url;
    }
    // Nested meta_url structure (raw Brave Search API format)
    if (rawResult.meta_url && typeof rawResult.meta_url === 'object') {
      const metaUrl = rawResult.meta_url as Record<string, unknown>;
      if (metaUrl.favicon && typeof metaUrl.favicon === 'string') {
        return metaUrl.favicon;
      }
    }
    return undefined;
  }
  
  /**
   * Flatten nested results structure from backend if needed
   * Backend returns results as [{ id: X, results: [...] }] for multi-query searches
   * This flattens it to a simple array of search results
   * 
   * CRITICAL: Also normalizes favicon fields during flattening to ensure
   * getFaviconUrl() can find them regardless of source format.
   */
  function flattenResults(rawResults: unknown[]): NewsSearchResult[] {
    if (!rawResults || rawResults.length === 0) return [];
    
    // Check if first item is nested structure (has 'results' array)
    const firstItem = rawResults[0] as Record<string, unknown>;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      // Nested structure - flatten all results from all entries
      const flattened: NewsSearchResult[] = [];
      for (const entry of rawResults as Array<{ id?: string; results?: unknown[] }>) {
        if (entry.results && Array.isArray(entry.results)) {
          // Normalize each result to ensure favicon is in standard format
          for (const rawResult of entry.results as Array<Record<string, unknown>>) {
            const normalizedResult: NewsSearchResult = {
              ...(rawResult as unknown as NewsSearchResult),
              // Ensure favicon is set from any available source
              favicon: extractFaviconFromRaw(rawResult) || (rawResult as unknown as NewsSearchResult).favicon
            };
            flattened.push(normalizedResult);
          }
        }
      }
      console.debug(`[NewsSearchEmbedPreview] Flattened nested results: ${rawResults.length} entries -> ${flattened.length} results`);
      return flattened;
    }
    
    // Already flat structure - but still normalize favicons
    return (rawResults as Array<Record<string, unknown>>).map(rawResult => ({
      ...(rawResult as unknown as NewsSearchResult),
      // Ensure favicon is set from any available source
      favicon: extractFaviconFromRaw(rawResult) || (rawResult as unknown as NewsSearchResult).favicon
    }));
  }
  
  // Get flattened results (handles both nested and flat backend formats)
  let flatResults = $derived(flattenResults(results));
  
  // Get first 3 results with favicons for display (uses flattened results)
  // Checks favicon, favicon_url, and meta_url.favicon formats
  let faviconResults = $derived(
    flatResults?.filter(r => getFaviconUrl(r)).slice(0, 3) || []
  );
  
  // Get remaining results count (total flat results minus displayed favicons)
  let remainingCount = $derived(
    Math.max(0, (flatResults?.length || 0) - faviconResults.length)
  );
  
  // DEBUG: Log results data to understand what we're receiving
  $effect(() => {
    if (results?.length) {
      console.debug(`[NewsSearchEmbedPreview] DEBUG id=${id} status=${status}:`, {
        rawResultsLength: results.length,
        flatResultsLength: flatResults.length,
        faviconResultsLength: faviconResults.length,
        remainingCount,
        // Show raw structure to detect nested vs flat
        firstRawResult: results[0],
        // Show all favicon-related fields in first flat result
        firstFlatResultFaviconFields: flatResults[0] ? {
          favicon: flatResults[0]?.favicon,
          favicon_url: flatResults[0]?.favicon_url,
          meta_url_favicon: flatResults[0]?.meta_url?.favicon
        } : null,
        extractedFaviconUrl: flatResults[0] ? getFaviconUrl(flatResults[0]) : undefined
      });
    } else {
      console.debug(`[NewsSearchEmbedPreview] DEBUG id=${id} status=${status}: No results available`);
    }
  });
  
  // Handle stop button click - cancels this specific skill, not the entire AI response
  // Uses skill_task_id for individual skill cancellation (AI processing continues)
  // Falls back to task_id (full task cancellation) if skill_task_id is not available
  async function handleStop() {
    if (status !== 'processing') return;
    
    // Prefer skill_task_id for individual skill cancellation
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
        console.debug(`[NewsSearchEmbedPreview] Sent cancel_skill request for skill_task_id ${skillTaskId} (embed: ${id})`);
      } catch (error) {
        console.error(`[NewsSearchEmbedPreview] Failed to cancel skill ${skillTaskId}:`, error);
      }
    } else if (taskId) {
      // Fallback: cancel entire AI task if no skill_task_id available (legacy embeds)
      console.warn(`[NewsSearchEmbedPreview] No skill_task_id available, falling back to task cancellation for task ${taskId}`);
      try {
        await chatSyncService.sendCancelAiTask(taskId);
        console.debug(`[NewsSearchEmbedPreview] Sent cancel request for task ${taskId}`);
      } catch (error) {
        console.error(`[NewsSearchEmbedPreview] Failed to cancel task ${taskId}:`, error);
      }
    } else {
      console.warn(`[NewsSearchEmbedPreview] Cannot cancel: no skill_task_id or task_id available`);
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="news"
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
    <div class="news-search-details" class:mobile={isMobileLayout}>
      <!-- Query text -->
      <div class="search-query">{query}</div>
      
      <!-- Provider subtitle -->
      <div class="search-provider">{viaProvider}</div>
      
      <!-- Finished state: show favicons and remaining count -->
      {#if status === 'finished'}
        <div class="search-results-info">
          <!-- Favicons row -->
          {#if faviconResults.length > 0}
            <div class="favicon-row">
              {#each faviconResults as result, index}
                {@const rawFaviconUrl = getFaviconUrl(result)}
                {@const proxiedFaviconUrl = getProxiedFaviconUrl(rawFaviconUrl)}
                {#if proxiedFaviconUrl}
                  <img 
                    src={proxiedFaviconUrl}
                    alt=""
                    class="favicon"
                    style="z-index: {faviconResults.length - index};"
                    loading="lazy"
                    onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                  />
                {/if}
              {/each}
            </div>
          {/if}
          
          <!-- Remaining count - uses embeds.more_results translation with {count} placeholder -->
          {#if remainingCount > 0}
            <span class="remaining-count">
              {$text('embeds.more_results.text').replace('{count}', String(remainingCount))}
            </span>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     News Search Details Content
     =========================================== */
  
  .news-search-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .news-search-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .news-search-details.mobile {
    justify-content: flex-start;
  }
  
  /* Query text */
  .search-query {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    /* Limit to 3 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  .news-search-details.mobile .search-query {
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
  
  .news-search-details.mobile .search-provider {
    font-size: 12px;
  }
  
  /* Search results info (favicons + remaining count) */
  .search-results-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
  }
  
  .news-search-details.mobile .search-results-info {
    margin-top: 2px;
  }
  
  /* Favicon row: overlapping circles */
  .favicon-row {
    display: flex;
    align-items: center;
    position: relative;
    height: 19px;
    min-width: 42px; /* 3 favicons with overlap */
  }
  
  .favicon {
    width: 19px;
    height: 19px;
    border-radius: 50%;
    border: 1px solid white;
    background-color: white;
    object-fit: cover;
    /* Overlapping effect */
    margin-left: -6px;
    position: relative;
  }
  
  .favicon:first-child {
    margin-left: 0;
  }
  
  /* Remaining count */
  .remaining-count {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
  }
  
  .news-search-details.mobile .remaining-count {
    font-size: 12px;
  }
  
  /* ===========================================
     Skill Icon Styling (skill-specific)
     =========================================== */
  
  /* News Search skill icon - this is skill-specific and belongs here, not in UnifiedEmbedPreview */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
  
  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>

