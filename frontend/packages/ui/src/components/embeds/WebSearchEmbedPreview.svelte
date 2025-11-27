<!--
  frontend/packages/ui/src/components/embeds/WebSearchEmbedPreview.svelte
  
  Preview component for Web Search skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.
  
  Details content structure:
  - Processing: query text + "via {provider}"
  - Finished: query text + "via {provider}" + favicons (first 3) + "+ N more"
  
  Future: Preview images placeholder (48px height) when images are available
-->

<script lang="ts">
  import UnifiedEmbedPreview from './UnifiedEmbedPreview.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../services/chatSyncService';
  
  /**
   * Web search result interface for favicon display
   */
  interface WebSearchResult {
    title?: string;
    url: string;
    favicon_url?: string;
    preview_image_url?: string;
    snippet?: string;
  }
  
  /**
   * Props for web search embed preview
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
    results?: WebSearchResult[];
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }
  
  let {
    id,
    query,
    provider,
    status,
    results = [],
    taskId,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Get skill name from translations
  let skillName = $derived($text('embeds.search.text') || 'Search');
  
  // Map skillId to icon name - this is skill-specific logic
  const skillIconName = 'search';
  
  // Get "via {provider}" text from translations
  let viaProvider = $derived(
    `${$text('embeds.via.text') || 'via'} ${provider}`
  );
  
  // Get first 3 results with favicons for display
  let faviconResults = $derived(
    results?.filter(r => r.favicon_url).slice(0, 3) || []
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
        console.debug(`[WebSearchEmbedPreview] Sent cancel request for task ${taskId}`);
      } catch (error) {
        console.error(`[WebSearchEmbedPreview] Failed to cancel task ${taskId}:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="web"
  skillId="search"
  skillIconName={skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="web-search-details" class:mobile={isMobileLayout}>
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
                <img 
                  src={result.favicon_url}
                  alt=""
                  class="favicon"
                  style="z-index: {faviconResults.length - index};"
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
        
        <!-- Future: Preview images placeholder (48px height) -->
        <!-- Uncomment when preview images are implemented:
        {#if !isMobileLayout && hasPreviewImages}
          <div class="preview-images-row">
            Images would go here
          </div>
        {/if}
        -->
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Web Search Details Content
     =========================================== */
  
  .web-search-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .web-search-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .web-search-details.mobile {
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
  
  .web-search-details.mobile .search-query {
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
  
  .web-search-details.mobile .search-provider {
    font-size: 12px;
  }
  
  /* Search results info (favicons + remaining count) */
  .search-results-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
  }
  
  .web-search-details.mobile .search-results-info {
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
  
  .web-search-details.mobile .remaining-count {
    font-size: 12px;
  }
  
  /* Future: Preview images row placeholder (48px height) */
  .preview-images-row {
    height: 48px;
    margin-top: 8px;
    display: flex;
    gap: 4px;
    overflow: hidden;
    border-radius: 8px;
  }
  
  /* ===========================================
     Skill Icon Styling (skill-specific)
     =========================================== */
  
  /* Web Search skill icon - this is skill-specific and belongs here, not in UnifiedEmbedPreview */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
  
  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>

