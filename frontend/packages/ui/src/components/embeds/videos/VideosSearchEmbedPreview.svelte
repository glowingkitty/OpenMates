<!--
  frontend/packages/ui/src/components/embeds/VideosSearchEmbedPreview.svelte
  
  Preview component for Videos Search skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.
  
  Details content structure:
  - Processing: query text + "via {provider}"
  - Finished: query text + "via {provider}" + channel thumbnails (first 3, circular) + "+ N more"
  
  NOTE: Real-time updates are handled by UnifiedEmbedPreview via embedUpdated events.
  This component implements onEmbedDataUpdated to update its specific data.
  
  Channel thumbnails are displayed as circular profile images (similar to favicons in WebSearchEmbedPreview)
  using the meta_url_profile_image field from video search results.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  // @ts-expect-error - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import { proxyImage, MAX_WIDTH_FAVICON } from '../../../utils/imageProxy';
  import { chatSyncService } from '../../../services/chatSyncService';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  
  /**
   * Video search result interface for channel thumbnail display
   * Supports multiple field formats depending on data source:
   * - meta_url_profile_image: TOON-flattened format (most common for stored embeds)
   * - meta_url.profile_image: Nested structure (raw API format)
   * - channelThumbnail: Alternative direct field
   */
  interface VideoSearchResult {
    title?: string;
    url: string;
    /** TOON-flattened channel profile image URL */
    meta_url_profile_image?: string;
    /** Alternative direct channel thumbnail field */
    channelThumbnail?: string;
    /** Nested meta_url structure (raw API format) */
    meta_url?: {
      profile_image?: string;
      favicon?: string;
    };
    /** Video thumbnail (used for fullscreen, not preview) */
    thumbnail?: {
      src?: string;
      original?: string;
    };
    /** Alternative flattened thumbnail field */
    thumbnail_original?: string;
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
    /** Task ID for cancellation of entire AI response */
    taskId?: string;
    /** Skill task ID for cancellation of just this skill (allows AI to continue) */
    skillTaskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
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
  let storeResolved = $state(false);
  let localResults = $state<VideoSearchResult[]>([]);
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);

  // Initialize local state from props
  $effect(() => {
    if (!storeResolved) {
      localQuery = queryProp || '';
      localProvider = providerProp || 'Brave Search';
      localStatus = statusProp || 'processing';
      localResults = resultsProp || [];
      localTaskId = taskIdProp;
      localSkillTaskId = skillTaskIdProp;
    }
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
   * Called when the parent component receives and decodes updated embed data
   * 
    * Parent previews are intentionally self-contained: child video embeds are
    * hydrated only after an explicit fullscreen/open action.
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[VideosSearchEmbedPreview] 🔄 Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
      if (data.status !== 'processing') { storeResolved = true; }
    }

    const content = data.decodedContent;
    if (content) {
      if (typeof content.query === 'string') localQuery = content.query;
      if (typeof content.provider === 'string') localProvider = content.provider;
      if (content.results && Array.isArray(content.results)) {
        localResults = content.results as VideoSearchResult[];
        console.debug(`[VideosSearchEmbedPreview] Updated results from callback:`, localResults.length);
      }
      // Extract skill_task_id for individual skill cancellation
      if (typeof content.skill_task_id === 'string') {
        localSkillTaskId = content.skill_task_id;
      }
      
    }
  }
  
  /**
   * Extract channel thumbnail URL from a video search result
   * Handles multiple possible field formats from different data sources:
   * - meta_url_profile_image: TOON-flattened format (most common for stored embeds)
   * - channelThumbnail: Alternative direct field
   * - meta_url.profile_image: Nested format from raw API
   * 
   * @param result - Video search result object
   * @returns Channel thumbnail URL or undefined
   */
  function getChannelThumbnailUrl(result: VideoSearchResult): string | undefined {
    // TOON-flattened format (meta_url.profile_image becomes meta_url_profile_image)
    if (result.meta_url_profile_image && typeof result.meta_url_profile_image === 'string') {
      return result.meta_url_profile_image;
    }
    // Alternative direct channel thumbnail field
    if (result.channelThumbnail && typeof result.channelThumbnail === 'string') {
      return result.channelThumbnail;
    }
    // Nested meta_url structure (raw API format)
    if (result.meta_url && typeof result.meta_url === 'object' && result.meta_url.profile_image) {
      return result.meta_url.profile_image;
    }
    return undefined;
  }
  
  // Get skill name from translations
  let skillName = $derived($text('common.search'));
  
  // Map skillId to icon name - this is skill-specific logic
  const skillIconName = 'search';
  
  
  /**
   * Proxy a channel thumbnail URL through the preview server for privacy.
   * This prevents direct requests to external CDNs which would expose user IPs.
   * Uses the /api/v1/image endpoint which handles caching and image optimization.
   * @param thumbnailUrl - Direct channel thumbnail URL to proxy
   * @returns Proxied URL through preview server, or empty string if no URL
   */
  function getProxiedChannelThumbnailUrl(thumbnailUrl: string | undefined): string {
    if (!thumbnailUrl) return '';
    return proxyImage(thumbnailUrl, MAX_WIDTH_FAVICON);
  }
  
  // Get "via {provider}" text from translations
  let viaProvider = $derived(
    `${$text('embeds.via')} ${provider}`
  );
  
  // Get first 3 results with channel thumbnails for display (circular profile images)
  // Similar to how WebSearchEmbedPreview shows favicons
  let channelThumbnailResults = $derived(
    results?.filter(r => getChannelThumbnailUrl(r)).slice(0, 3) || []
  );
  
  // Get remaining results count (total results minus displayed channel thumbnails)
  let remainingCount = $derived(
    Math.max(0, (results?.length || 0) - channelThumbnailResults.length)
  );
  
  // Handle stop button click - cancels this specific skill, not the entire AI response
  async function handleStop() {
    if (status !== 'processing') return;
    
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
        console.debug(`[VideosSearchEmbedPreview] Sent cancel_skill request for skill_task_id ${skillTaskId}`);
      } catch (error) {
        console.error(`[VideosSearchEmbedPreview] Failed to cancel skill ${skillTaskId}:`, error);
      }
    } else if (taskId) {
      console.warn(`[VideosSearchEmbedPreview] No skill_task_id, falling back to task cancellation`);
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
      <div class="ds-search-query">{query}</div>
      
      <!-- Provider subtitle -->
      <div class="ds-search-provider">{viaProvider}</div>
      
      <!-- Finished state: show channel thumbnails (circular) and remaining count -->
      {#if status === 'finished'}
        <div class="ds-search-results-info">
          {#if channelThumbnailResults.length > 0}
            <div class="channel-thumbnail-row">
              {#each channelThumbnailResults as result, index}
                {@const rawChannelThumbnailUrl = getChannelThumbnailUrl(result)}
                {@const proxiedChannelThumbnailUrl = getProxiedChannelThumbnailUrl(rawChannelThumbnailUrl)}
                {#if proxiedChannelThumbnailUrl}
                  <img 
                    src={proxiedChannelThumbnailUrl}
                    alt=""
                    class="channel-thumbnail"
                    style="z-index: {channelThumbnailResults.length - index};"
                    loading="lazy"
                    crossorigin="anonymous"
                    onerror={(e) => { handleImageError(e.currentTarget as HTMLImageElement); }}
                  />
                {/if}
              {/each}
            </div>
          {/if}
          
          <!-- Remaining count - uses embeds.more_results translation with {count} placeholder -->
          {#if remainingCount > 0}
            <span class="remaining-count">
              {$text('embeds.more_results').replace('{count}', String(remainingCount))}
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
    gap: var(--spacing-2);
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
  
  /* Base styles for .ds-search-query / .ds-search-provider / .ds-search-results-info
     are generated from frontend/packages/ui/src/tokens/sources/components/search-results.yml
     See docs/architecture/frontend/design-tokens.md (Phase E). */

  .videos-search-details.mobile .ds-search-query {
    font-size: var(--font-size-small);
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }

  .videos-search-details.mobile .ds-search-provider {
    font-size: var(--font-size-xxs);
  }

  .videos-search-details.mobile .ds-search-results-info {
    margin-top: var(--spacing-1);
  }
  
  /* Channel thumbnail row: overlapping circles (like favicons in WebSearchEmbedPreview) */
  .channel-thumbnail-row {
    display: flex;
    align-items: center;
    position: relative;
    height: 19px;
    min-width: 42px; /* 3 thumbnails with overlap */
  }
  
  /* Channel thumbnail: circular profile image (like favicon in web search) */
  .channel-thumbnail {
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
  
  .channel-thumbnail:first-child {
    margin-left: 0;
  }
  
  /* .ds-loading-text base styles are generated from
     frontend/packages/ui/src/tokens/sources/components/loading.yml */

  /* Remaining count */
  .remaining-count {
    font-size: var(--font-size-small);
    color: var(--color-grey-70);
    font-weight: 500;
  }
  
  .videos-search-details.mobile .remaining-count {
    font-size: var(--font-size-xxs);
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
