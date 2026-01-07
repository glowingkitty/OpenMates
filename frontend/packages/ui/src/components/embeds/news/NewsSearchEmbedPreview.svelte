<!--
  frontend/packages/ui/src/components/embeds/NewsSearchEmbedPreview.svelte
  
  Preview component for News Search skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.
  
  Details content structure:
  - Processing: query text + "via {provider}"
  - Finished: query text + "via {provider}" + favicons (first 3) + "+ N more"
  
  NOTE: Real-time updates are handled by UnifiedEmbedPreview via embedUpdated events.
  This component implements onEmbedDataUpdated to update its specific data.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  // @ts-expect-error - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  
  /**
   * News search result interface for favicon display
   */
  interface NewsSearchResult {
    title?: string;
    url: string;
    favicon_url?: string;
    meta_url?: {
      favicon?: string;
    };
    thumbnail?: {
      original?: string;
    };
    description?: string;
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
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
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
  
  // Local reactive state for embed data
  let localQuery = $state<string>('');
  let localProvider = $state<string>('Brave Search');
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
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
  
  // Use local state as the source of truth
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);
  
  /**
   * Handle embed data updates from UnifiedEmbedPreview
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[NewsSearchEmbedPreview] 🔄 Received embed data update for ${id}`);
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
    }
    
    const content = data.decodedContent;
    if (content) {
      if (typeof content.query === 'string') localQuery = content.query;
      if (typeof content.provider === 'string') localProvider = content.provider;
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results as NewsSearchResult[];
      }
      // Extract skill_task_id for individual skill cancellation
      if (typeof content.skill_task_id === 'string') {
        localSkillTaskId = content.skill_task_id;
      }
    }
  }
  
  // Get skill name from translations
  let skillName = $derived($text('embeds.search.text') || 'Search');
  
  // Map skillId to icon name - this is skill-specific logic
  const skillIconName = 'search';
  
  // Get "via {provider}" text from translations
  let viaProvider = $derived(
    `${$text('embeds.via.text') || 'via'} ${provider}`
  );
  
  // Get first 3 results with favicons for display
  // Extract favicon from meta_url.favicon or favicon_url
  let faviconResults = $derived(
    results?.filter(r => r.favicon_url || r.meta_url?.favicon).slice(0, 3) || []
  );
  
  // Get remaining results count
  let remainingCount = $derived(
    Math.max(0, (results?.length || 0) - 1)
  );
  
  // Handle stop button click - cancels this specific skill, not the entire AI response
  async function handleStop() {
    if (status !== 'processing') return;
    
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
        console.debug(`[NewsSearchEmbedPreview] Sent cancel_skill request for skill_task_id ${skillTaskId}`);
      } catch (error) {
        console.error(`[NewsSearchEmbedPreview] Failed to cancel skill ${skillTaskId}:`, error);
      }
    } else if (taskId) {
      console.warn(`[NewsSearchEmbedPreview] No skill_task_id, falling back to task cancellation`);
      try {
        await chatSyncService.sendCancelAiTask(taskId);
        console.debug(`[NewsSearchEmbedPreview] Sent cancel request for task ${taskId}`);
      } catch (error) {
        console.error(`[NewsSearchEmbedPreview] Failed to cancel task ${taskId}:`, error);
      }
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
                {@const faviconSrc = result.meta_url?.favicon || result.favicon_url}
                {#if faviconSrc}
                  <img 
                    src={faviconSrc}
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
          
          <!-- Remaining count -->
          {#if remainingCount > 0}
            <span class="remaining-count">
              + {remainingCount} {$text('embeds.more.text') || 'more'}
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

