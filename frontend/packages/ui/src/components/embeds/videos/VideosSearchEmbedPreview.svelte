<!--
  frontend/packages/ui/src/components/embeds/VideosSearchEmbedPreview.svelte
  
  Preview component for Videos Search skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.
  
  Details content structure:
  - Processing: query text + "via {provider}"
  - Finished: query text + "via {provider}" + thumbnails (first 3) + "+ N more"
  
  NOTE: Real-time updates are handled by UnifiedEmbedPreview via embedUpdated events.
  This component implements onEmbedDataUpdated to update its specific data.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  
  /**
   * Video search result interface for thumbnail display
   */
  interface VideoSearchResult {
    title?: string;
    url: string;
    thumbnail?: {
      src?: string;
      original?: string;
    };
    meta_url?: {
      favicon?: string;
    };
    description?: string;
  }
  
  /**
   * Props for videos search embed preview
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
    results?: VideoSearchResult[];
    /** Task ID for cancellation */
    taskId?: string;
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
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Local reactive state for embed data
  let localQuery = $state<string>('');
  let localProvider = $state<string>('Brave Search');
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localResults = $state<VideoSearchResult[]>([]);
  let localTaskId = $state<string | undefined>(undefined);
  
  // Initialize local state from props
  $effect(() => {
    localQuery = queryProp || '';
    localProvider = providerProp || 'Brave Search';
    localStatus = statusProp || 'processing';
    localResults = resultsProp || [];
    localTaskId = taskIdProp;
  });
  
  // Use local state as the source of truth
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  
  /**
   * Handle embed data updates from UnifiedEmbedPreview
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: any }) {
    console.debug(`[VideosSearchEmbedPreview] 🔄 Received embed data update for ${id}`);
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
    }
    
    const content = data.decodedContent;
    if (content) {
      if (content.query) localQuery = content.query;
      if (content.provider) localProvider = content.provider;
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results;
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
  
  // Get first 3 results with thumbnails for display
  let thumbnailResults = $derived(
    results?.filter(r => r.thumbnail?.src || r.thumbnail?.original).slice(0, 3) || []
  );
  
  // Get remaining results count
  let remainingCount = $derived(
    Math.max(0, (results?.length || 0) - 1)
  );
  
  // Handle stop button click
  async function handleStop() {
    if (status === 'processing' && taskId) {
      try {
        await chatSyncService.sendCancelAiTask(taskId);
        console.debug(`[VideosSearchEmbedPreview] Sent cancel request for task ${taskId}`);
      } catch (error) {
        console.error(`[VideosSearchEmbedPreview] Failed to cancel task ${taskId}:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="videos"
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
    <div class="videos-search-details" class:mobile={isMobileLayout}>
      <!-- Query text -->
      <div class="search-query">{query}</div>
      
      <!-- Provider subtitle -->
      <div class="search-provider">{viaProvider}</div>
      
      <!-- Finished state: show thumbnails and remaining count -->
      {#if status === 'finished'}
        <div class="search-results-info">
          <!-- Thumbnail row -->
          {#if thumbnailResults.length > 0}
            <div class="thumbnail-row">
              {#each thumbnailResults as result, index}
                {@const thumbnailUrl = result.thumbnail?.original || result.thumbnail?.src}
                <img 
                  src={thumbnailUrl}
                  alt={result.title || ''}
                  class="thumbnail"
                  style="z-index: {thumbnailResults.length - index};"
                  loading="lazy"
                />
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
     Videos Search Details Content
     =========================================== */
  
  .videos-search-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .videos-search-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .videos-search-details.mobile {
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
  
  .videos-search-details.mobile .search-query {
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
  
  .videos-search-details.mobile .search-provider {
    font-size: 12px;
  }
  
  /* Search results info (thumbnails + remaining count) */
  .search-results-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
  }
  
  .videos-search-details.mobile .search-results-info {
    margin-top: 2px;
  }
  
  /* Thumbnail row: overlapping rectangles */
  .thumbnail-row {
    display: flex;
    align-items: center;
    position: relative;
    height: 19px;
    min-width: 42px; /* 3 thumbnails with overlap */
  }
  
  .thumbnail {
    width: 19px;
    height: 19px;
    border-radius: 4px;
    border: 1px solid white;
    background-color: white;
    object-fit: cover;
    /* Overlapping effect */
    margin-left: -6px;
    position: relative;
  }
  
  .thumbnail:first-child {
    margin-left: 0;
  }
  
  /* Remaining count */
  .remaining-count {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
  }
  
  .videos-search-details.mobile .remaining-count {
    font-size: 12px;
  }
  
  /* ===========================================
     Skill Icon Styling (skill-specific)
     =========================================== */
  
  /* Videos Search skill icon - this is skill-specific and belongs here, not in UnifiedEmbedPreview */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
  
  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>

