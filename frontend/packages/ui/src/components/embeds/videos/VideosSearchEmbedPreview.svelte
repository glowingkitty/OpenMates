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
  import { chatSyncService } from '../../../services/chatSyncService';
  
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
  let localResults = $state<VideoSearchResult[]>([]);
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
   * Called when the parent component receives and decodes updated embed data
   * 
   * NOTE: When parent embed becomes "finished", it may have `embed_ids` but no direct `results`.
   * In this case, we need to load child embeds asynchronously to get channel thumbnail data.
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[VideosSearchEmbedPreview] 🔄 Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
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
      
      // CRITICAL: When status is "finished" and we have embed_ids but no results,
      // load child embeds asynchronously to get channel thumbnail data for preview display.
      if (data.status === 'finished' && (!content.results || !Array.isArray(content.results) || content.results.length === 0)) {
        const embedIds = content.embed_ids;
        if (embedIds) {
          // Parse embed_ids (can be pipe-separated string or array)
          const childEmbedIds: string[] = typeof embedIds === 'string'
            ? (embedIds as string).split('|').filter((id: string) => id.length > 0)
            : Array.isArray(embedIds) ? (embedIds as string[]) : [];
          
          if (childEmbedIds.length > 0) {
            console.debug(`[VideosSearchEmbedPreview] Loading child embeds for preview (${childEmbedIds.length} embed_ids)`);
            loadChildEmbedsForPreview(childEmbedIds);
          }
        }
      }
    }
  }
  
  /**
   * Load child embeds to extract channel thumbnail data for preview display
   * Uses retry logic because child embeds might not be persisted yet
   * (they arrive via websocket after the parent embed)
   */
  async function loadChildEmbedsForPreview(childEmbedIds: string[]) {
    try {
      const { loadEmbedsWithRetry, decodeToonContent } = await import('../../../services/embedResolver');
      
      // Use retry logic with shorter timeout for preview (we just need a few channel thumbnails)
      const childEmbeds = await loadEmbedsWithRetry(childEmbedIds, 5, 300);
      
      if (childEmbeds.length > 0) {
        // Transform child embeds to VideoSearchResult format (just need basic data for channel thumbnails)
        const results = await Promise.all(childEmbeds.map(async (embed) => {
          const content = embed.content ? await decodeToonContent(embed.content) : null;
          if (!content) return null;
          
          // Extract channel thumbnail URL from multiple possible field formats:
          // 1. meta_url_profile_image: TOON-flattened format (most common for stored embeds)
          // 2. meta_url.profile_image: Nested format (raw API)
          // 3. channelThumbnail: Alternative direct field
          const channelThumbnailUrl = 
            content.meta_url_profile_image ||
            (content.meta_url as { profile_image?: string } | undefined)?.profile_image ||
            content.channelThumbnail ||
            '';
          
          // DEBUG: Log what we extracted to help diagnose issues
          if (childEmbeds.indexOf(embed) < 3) {
            console.debug(`[VideosSearchEmbedPreview] Child embed channel thumbnail extraction:`, {
              embedId: embed.embed_id,
              title: (content.title as string)?.substring(0, 30),
              meta_url_profile_image: content.meta_url_profile_image,
              meta_url: content.meta_url,
              channelThumbnail: content.channelThumbnail,
              extracted: channelThumbnailUrl
            });
          }
          
          return {
            title: content.title || '',
            url: content.url || '',
            meta_url_profile_image: channelThumbnailUrl,
            channelThumbnail: channelThumbnailUrl
          } as VideoSearchResult;
        }));
        
        const validResults = results.filter(r => r !== null) as VideoSearchResult[];
        if (validResults.length > 0) {
          localResults = validResults;
          console.debug(`[VideosSearchEmbedPreview] Loaded ${validResults.length} results from child embeds, channel thumbnails found: ${validResults.filter(r => getChannelThumbnailUrl(r)).length}`);
        }
      }
    } catch (error) {
      console.warn('[VideosSearchEmbedPreview] Error loading child embeds for preview:', error);
      // Continue without results - preview will just show query/provider
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
  let skillName = $derived($text('embeds.search'));
  
  // Map skillId to icon name - this is skill-specific logic
  const skillIconName = 'search';
  
  // Preview server base URL for image proxying
  // ALL external images must be proxied for user privacy (hides user IP from external servers)
  const PREVIEW_SERVER = 'https://preview.openmates.org';
  // Channel thumbnails are small (19x19px display), request 2x for retina = 38px
  const CHANNEL_THUMBNAIL_MAX_WIDTH = 38;
  
  /**
   * Proxy a channel thumbnail URL through the preview server for privacy.
   * This prevents direct requests to external CDNs which would expose user IPs.
   * Uses the /api/v1/image endpoint which handles caching and image optimization.
   * @param thumbnailUrl - Direct channel thumbnail URL to proxy
   * @returns Proxied URL through preview server, or empty string if no URL
   */
  function getProxiedChannelThumbnailUrl(thumbnailUrl: string | undefined): string {
    if (!thumbnailUrl) return '';
    return `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(thumbnailUrl)}&max_width=${CHANNEL_THUMBNAIL_MAX_WIDTH}`;
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
      <div class="search-query">{query}</div>
      
      <!-- Provider subtitle -->
      <div class="search-provider">{viaProvider}</div>
      
      <!-- Finished state: show channel thumbnails (circular) and remaining count -->
      {#if status === 'finished'}
        <div class="search-results-info">
          <!-- Channel thumbnails row (circular, overlapping - like favicons in WebSearchEmbedPreview) -->
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
                    onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
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
  
  /* Search results info (channel thumbnails + remaining count) */
  .search-results-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
  }
  
  .videos-search-details.mobile .search-results-info {
    margin-top: 2px;
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

