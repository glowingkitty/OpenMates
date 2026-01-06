<!--
  frontend/packages/ui/src/components/embeds/web/WebSearchEmbedPreview.svelte
  
  Preview component for Web Search skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives query, provider, results directly
  
  Details content structure:
  - Processing: query text + "via {provider}"
  - Finished: query text + "via {provider}" + favicons (first 3) + "+ N more"
  
  NOTE: Real-time updates when embed status changes from 'processing' to 'finished'
  are handled by UnifiedEmbedPreview, which subscribes to embedUpdated events.
  This component implements the onEmbedDataUpdated callback to update its
  specific data (query, provider, results) when notified by the parent.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  import type { WebSearchSkillPreviewData } from '../../../types/appSkills';
  
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
   * Supports both skill preview data format and direct embed format
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Search query (direct format) */
    query?: string;
    /** Search provider (e.g., 'Brave Search') (direct format) */
    provider?: string;
    /** Processing status (direct format) */
    status?: 'processing' | 'finished' | 'error';
    /** Search results (for finished state) (direct format) */
    results?: WebSearchResult[];
    /** Task ID for cancellation of entire AI response (direct format) */
    taskId?: string;
    /** Skill task ID for cancellation of just this skill (allows AI to continue) */
    skillTaskId?: string;
    /** Skill preview data (skill preview context) */
    previewData?: WebSearchSkillPreviewData;
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
    previewData,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Local reactive state for embed data - these can be updated when embed data changes
  // CRITICAL: Using $state allows us to update these values when we receive embed updates
  // via the onEmbedDataUpdated callback from UnifiedEmbedPreview
  let localQuery = $state<string>('');
  let localProvider = $state<string>('Brave Search');
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localResults = $state<WebSearchResult[]>([]);
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);
  
  // Initialize local state from props
  $effect(() => {
    // Initialize from previewData or direct props
    if (previewData) {
      localQuery = previewData.query || '';
      localProvider = previewData.provider || 'Brave Search';
      localStatus = previewData.status || 'processing';
      localResults = previewData.results || [];
      localTaskId = previewData.task_id;
      // skill_task_id might be in previewData for skill-level cancellation
      localSkillTaskId = (previewData as any).skill_task_id;
    } else {
      localQuery = queryProp || '';
      localProvider = providerProp || 'Brave Search';
      localStatus = statusProp || 'processing';
      localResults = resultsProp || [];
      localTaskId = taskIdProp;
      localSkillTaskId = skillTaskIdProp;
    }
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
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: any }) {
    console.debug(`[WebSearchEmbedPreview] 🔄 Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    // Update status
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
    }
    
    // Update web-search-specific fields from decoded content
    const content = data.decodedContent;
    if (content) {
      if (content.query) localQuery = content.query;
      if (content.provider) localProvider = content.provider;
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results;
        console.debug(`[WebSearchEmbedPreview] Updated results from callback:`, localResults.length);
      }
      // Extract skill_task_id for individual skill cancellation
      if (content.skill_task_id) {
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
  let faviconResults = $derived(
    results?.filter(r => r.favicon_url).slice(0, 3) || []
  );
  
  // Get remaining results count
  let remainingCount = $derived(
    Math.max(0, (results?.length || 0) - 1)
  );
  
  // Handle stop button click - cancels this specific skill, not the entire AI response
  // Uses skill_task_id for individual skill cancellation (AI processing continues)
  // Falls back to task_id (full task cancellation) if skill_task_id is not available
  async function handleStop() {
    if (status !== 'processing') return;
    
    // Prefer skill_task_id for individual skill cancellation
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
        console.debug(`[WebSearchEmbedPreview] Sent cancel_skill request for skill_task_id ${skillTaskId} (embed: ${id})`);
      } catch (error) {
        console.error(`[WebSearchEmbedPreview] Failed to cancel skill ${skillTaskId}:`, error);
      }
    } else if (taskId) {
      // Fallback: cancel entire AI task if no skill_task_id available (legacy embeds)
      console.warn(`[WebSearchEmbedPreview] No skill_task_id available, falling back to task cancellation for task ${taskId}`);
      try {
        await chatSyncService.sendCancelAiTask(taskId);
        console.debug(`[WebSearchEmbedPreview] Sent cancel request for task ${taskId}`);
      } catch (error) {
        console.error(`[WebSearchEmbedPreview] Failed to cancel task ${taskId}:`, error);
      }
    } else {
      console.warn(`[WebSearchEmbedPreview] Cannot cancel: no skill_task_id or task_id available`);
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
  onEmbedDataUpdated={handleEmbedDataUpdated}
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

