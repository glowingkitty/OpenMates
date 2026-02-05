<!--
  frontend/packages/ui/src/components/embeds/videos/VideoTranscriptEmbedPreview.svelte
  
  Preview component for Video Transcript app skill embeds.
  Uses UnifiedEmbedPreview as base and provides video transcript-specific details content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives results, status, taskId directly
  
  Layout (per Figma design, matching VideoEmbedPreview):
  - Details section:
    - Channel thumbnail (circular, 29x29px) - YouTube channel profile picture
    - Title: video title
    - Subtitle: "via YouTube:\n{wordCount} words"
  - Basic infos bar:
    - Videos app icon (gradient circle)
    - Transcript skill icon
    - "Transcript" / "Completed" (or "Processing")
  
  Data Flow:
  - Fetches YouTube metadata from preview server (channel thumbnail, title)
  - Falls back to results metadata if preview server fetch fails
  - Channel thumbnail is proxied through preview server for privacy
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  import type { VideoTranscriptSkillPreviewData, SkillExecutionStatus } from '../../../types/appSkills';
  
  // ===========================================
  // Types
  // ===========================================
  
  /**
   * Video transcript result interface
   */
  interface VideoTranscriptResult {
    url?: string;
    metadata?: {
      title?: string;
      channel_name?: string;
      channel_thumbnail?: string;
    };
    word_count?: number;
  }
  
  /**
   * Metadata response from preview server /api/v1/youtube endpoint
   * Includes video metadata and channel thumbnail (profile picture)
   */
  interface YouTubeMetadataResponse {
    video_id: string;
    url: string;
    title?: string;
    description?: string;
    channel_name?: string;
    channel_id?: string;
    channel_thumbnail?: string;  // Channel profile picture URL
    thumbnails: {
      default?: string;
      medium?: string;
      high?: string;
      standard?: string;
      maxres?: string;
    };
    duration: {
      total_seconds: number;
      formatted: string;
    };
    view_count?: number;
    like_count?: number;
    published_at?: string;
  }
  
  /**
   * Props for video transcript embed preview
   * Supports both skill preview data format and direct embed format
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Video transcript results (direct format) */
    results?: VideoTranscriptResult[];
    /** Processing status (direct format) */
    status?: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation (direct format) */
    taskId?: string;
    /** Skill task ID for cancellation of just this skill (allows AI to continue) */
    skillTaskId?: string;
    /** Direct URL from embed content (from processing placeholder) */
    url?: string;
    /** Skill preview data (skill preview context) */
    previewData?: VideoTranscriptSkillPreviewData;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }
  
  let {
    id,
    results: resultsProp,
    status: statusProp,
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    url: urlProp,
    previewData,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // ===========================================
  // Local state for embed data (updated via onEmbedDataUpdated callback)
  // CRITICAL: Using $state allows us to update these values when we receive embed updates
  // via the onEmbedDataUpdated callback from UnifiedEmbedPreview
  // ===========================================
  let localResults = $state<VideoTranscriptResult[]>([]);
  let localUrl = $state<string>('');
  // Status type matches UnifiedEmbedPreview expectations (excludes 'cancelled')
  // We map 'cancelled' to 'error' for display purposes
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localSkillTaskId = $state<string | undefined>(undefined);
  
  // ===========================================
  // YouTube Metadata Fetching State
  // Fetches channel thumbnail and title from preview server (like VideoEmbedPreview)
  // ===========================================
  let fetchedTitle = $state<string | undefined>(undefined);
  let fetchedChannelName = $state<string | undefined>(undefined);
  let fetchedChannelThumbnail = $state<string | undefined>(undefined);
  let isLoadingMetadata = $state(false);
  let fetchedForUrl = $state<string | null>(null);
  
  // Preview server base URL for image proxying
  const PREVIEW_SERVER = 'https://preview.openmates.org';
  // Channel thumbnail size: 29x29px display, 2x for retina = 58px
  const CHANNEL_THUMBNAIL_MAX_WIDTH = 58;
  
  /**
   * Map SkillExecutionStatus to UnifiedEmbedPreview status
   * 'cancelled' is mapped to 'error' since UnifiedEmbedPreview doesn't support it
   */
  function mapStatusToEmbedStatus(status: SkillExecutionStatus): 'processing' | 'finished' | 'error' {
    if (status === 'cancelled') {
      return 'error';
    }
    return status;
  }
  
  // Initialize local state from props
  $effect(() => {
    // Initialize from previewData or direct props
    if (previewData) {
      localResults = previewData.results || [];
      // URL comes from the first result, not directly from previewData
      // The effectiveUrl derived value will handle extracting it from results
      localUrl = '';
      localStatus = mapStatusToEmbedStatus(previewData.status);
      // skill_task_id might be in previewData for skill-level cancellation
      // Check if it exists as a property (it's not in the type but may be present at runtime)
      localSkillTaskId = 'skill_task_id' in previewData ? (previewData as Record<string, unknown>).skill_task_id as string | undefined : undefined;
    } else {
      localResults = resultsProp || [];
      localUrl = urlProp || '';
      localStatus = statusProp || 'processing';
      localSkillTaskId = skillTaskIdProp;
    }
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let results = $derived(localResults);
  let status = $derived(localStatus);
  let taskId = $derived(previewData?.task_id || taskIdProp);
  let skillTaskId = $derived(localSkillTaskId);
  
  // Get first result for main display (may be undefined if results are empty)
  let firstResult = $derived(results[0]);
  
  // Get URL from multiple sources (priority: results > localUrl > direct prop)
  // CRITICAL: Even if results are empty, we may have URL from the processing placeholder
  // Note: previewData doesn't have a direct url property - URLs come from results[].url
  let effectiveUrl = $derived(
    firstResult?.url || 
    localUrl ||
    urlProp || 
    ''
  );
  
  // ===========================================
  // YouTube Metadata Fetching
  // ===========================================
  
  /**
   * Determine if we need to fetch metadata from the preview server.
   * We fetch when:
   * - We have a URL but no channel info from results
   * - The URL hasn't been fetched yet
   * - Not currently loading
   */
  let needsMetadataFetch = $derived.by(() => {
    // Need a URL to fetch
    if (!effectiveUrl) return false;
    // If we already have channel info from results, no need to fetch
    if (firstResult?.metadata?.channel_name && firstResult?.metadata?.channel_thumbnail) {
      return false;
    }
    // If we already fetched for this URL, no need to re-fetch
    if (fetchedForUrl === effectiveUrl) return false;
    // If currently loading, don't trigger another fetch
    if (isLoadingMetadata) return false;
    return true;
  });
  
  /**
   * Fetch metadata from the preview server when needed.
   * Uses the /api/v1/youtube endpoint which calls YouTube Data API v3.
   * This gets channel thumbnail and video title.
   */
  async function fetchYouTubeMetadata() {
    if (!effectiveUrl) return;
    
    isLoadingMetadata = true;
    
    // CRITICAL: Mark this URL as fetched BEFORE the request to prevent infinite loops
    const urlToFetch = effectiveUrl;
    fetchedForUrl = urlToFetch;
    
    console.debug('[VideoTranscriptEmbedPreview] Fetching YouTube metadata for URL:', urlToFetch);
    
    try {
      const response = await fetch(
        `${PREVIEW_SERVER}/api/v1/youtube?url=${encodeURIComponent(urlToFetch)}`
      );
      
      if (!response.ok) {
        console.warn('[VideoTranscriptEmbedPreview] Metadata fetch failed:', response.status, response.statusText);
        return;
      }
      
      const data: YouTubeMetadataResponse = await response.json();
      
      // Store fetched values
      fetchedTitle = data.title;
      fetchedChannelName = data.channel_name;
      fetchedChannelThumbnail = data.channel_thumbnail;
      
      console.info('[VideoTranscriptEmbedPreview] Successfully fetched YouTube metadata:', {
        title: data.title?.substring(0, 50) || 'No title',
        channelName: data.channel_name || 'Unknown',
        hasChannelThumbnail: !!data.channel_thumbnail
      });
      
    } catch (error) {
      console.error('[VideoTranscriptEmbedPreview] Error fetching YouTube metadata:', error);
    } finally {
      isLoadingMetadata = false;
    }
  }
  
  // Trigger metadata fetch when needed
  $effect(() => {
    if (needsMetadataFetch) {
      fetchYouTubeMetadata();
    }
  });
  
  /**
   * Handle embed data updates from UnifiedEmbedPreview
   * Called when the parent component receives and decodes updated embed data
   * This is the CENTRALIZED way to receive updates - no need for custom subscription
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[VideoTranscriptEmbedPreview] 🔄 Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    // Update status - map SkillExecutionStatus to embed status
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = mapStatusToEmbedStatus(data.status as SkillExecutionStatus);
    }
    
    // Update video-transcript-specific fields from decoded content
    const content = data.decodedContent;
    if (content) {
      // Update results if available
      if (content.results && Array.isArray(content.results) && content.results.length > 0) {
        console.debug(`[VideoTranscriptEmbedPreview] ✅ Updated results from callback:`, content.results.length);
        localResults = content.results as VideoTranscriptResult[];
      }
      
      // Update URL if available
      if (content.url && typeof content.url === 'string') {
        localUrl = content.url;
      }
      
      // Extract skill_task_id for individual skill cancellation
      if (content.skill_task_id && typeof content.skill_task_id === 'string') {
        localSkillTaskId = content.skill_task_id;
      }
    }
  }
  
  // Get skill name from translations
  let skillName = $derived($text('embeds.video_transcript.text') || 'Transcript');
  
  // Map skillId to icon name
  const skillIconName = 'transcript';
  
  // ===========================================
  // Effective Display Values
  // Priority: results metadata > fetched from preview server > fallbacks
  // ===========================================
  
  // Effective video title: results > fetched > fallback
  let effectiveTitle = $derived(
    firstResult?.metadata?.title || 
    fetchedTitle || 
    'YouTube Video'
  );
  
  // Effective channel name: results > fetched > fallback
  let effectiveChannelName = $derived(
    firstResult?.metadata?.channel_name || 
    fetchedChannelName || 
    ''
  );
  
  // Raw channel thumbnail URL: results > fetched
  let rawChannelThumbnailUrl = $derived(
    firstResult?.metadata?.channel_thumbnail || 
    fetchedChannelThumbnail || 
    ''
  );
  
  // Proxied channel thumbnail URL through preview server for privacy
  // Channel thumbnails are small circular profile pictures (29x29px display)
  let channelThumbnailUrl = $derived.by(() => {
    if (!rawChannelThumbnailUrl) return '';
    return `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(rawChannelThumbnailUrl)}&max_width=${CHANNEL_THUMBNAIL_MAX_WIDTH}`;
  });
  
  // Calculate total word count across all results
  let totalWordCount = $derived.by(() => {
    let count = 0;
    for (const result of results) {
      if (result.word_count) {
        count += result.word_count;
      }
    }
    return count;
  });
  
  // Subtitle text: "via YouTube:\nX words" (user-friendly, not "YouTube Transcript API")
  let subtitleText = $derived.by(() => {
    const wordCount = totalWordCount;
    if (wordCount > 0) {
      return `via YouTube:\n${wordCount.toLocaleString()} words`;
    }
    return 'via YouTube';
  });
  
  // Debug logging to help trace data flow issues
  $effect(() => {
    console.debug('[VideoTranscriptEmbedPreview] Rendering with:', {
      id,
      status,
      resultsCount: results.length,
      effectiveUrl,
      effectiveTitle,
      effectiveChannelName,
      hasChannelThumbnail: !!channelThumbnailUrl,
      wordCount: totalWordCount,
      hasPreviewData: !!previewData,
      hasUrlProp: !!urlProp,
      isLoadingMetadata
    });
  });
  
  // Handle stop button click - cancels this specific skill, not the entire AI response
  async function handleStop() {
    if (status !== 'processing') return;
    
    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
        console.debug(`[VideoTranscriptEmbedPreview] Sent cancel_skill request for skill_task_id ${skillTaskId}`);
      } catch (error) {
        console.error(`[VideoTranscriptEmbedPreview] Failed to cancel skill ${skillTaskId}:`, error);
      }
    } else if (taskId) {
      console.warn(`[VideoTranscriptEmbedPreview] No skill_task_id, falling back to task cancellation`);
      try {
        await chatSyncService.sendCancelAiTask(taskId);
        console.debug(`[VideoTranscriptEmbedPreview] Sent cancel request for task ${taskId}`);
      } catch (error) {
        console.error(`[VideoTranscriptEmbedPreview] Failed to cancel task ${taskId}:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="videos"
  skillId="get_transcript"
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="video-transcript-details" class:mobile={isMobileLayout}>
      <!-- Title row with channel thumbnail (circular, like VideoEmbedPreview) -->
      <div class="title-row">
        {#if channelThumbnailUrl}
          <img 
            src={channelThumbnailUrl} 
            alt={effectiveChannelName || ''} 
            class="channel-thumbnail"
            crossorigin="anonymous"
            onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
          />
        {:else if isLoadingMetadata}
          <!-- Placeholder while loading -->
          <div class="channel-thumbnail-placeholder"></div>
        {/if}
        <div class="transcript-title">{effectiveTitle}</div>
      </div>
      
      <!-- Subtitle: "via YouTube:\nX words" -->
      <div class="transcript-subtitle">{subtitleText}</div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Video Transcript Details Content
     Matches WebReadEmbedPreview layout
     =========================================== */
  
  .video-transcript-details {
    display: flex;
    flex-direction: column;
    gap: 6px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .video-transcript-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .video-transcript-details.mobile {
    justify-content: flex-start;
  }
  
  /* Title row with channel thumbnail and title text */
  .title-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }
  
  /* Circular channel thumbnail (profile picture) - matches VideoEmbedPreview style */
  .channel-thumbnail {
    width: 29px;
    height: 29px;
    min-width: 29px;
    border-radius: 50%;
    background-color: var(--color-grey-30);
    object-fit: cover;
    flex-shrink: 0;
    margin-top: 2px; /* Align with first line of title */
  }
  
  /* Placeholder while loading channel thumbnail */
  .channel-thumbnail-placeholder {
    width: 29px;
    height: 29px;
    min-width: 29px;
    border-radius: 50%;
    background-color: var(--color-grey-30);
    flex-shrink: 0;
    margin-top: 2px;
    animation: pulse 1.5s ease-in-out infinite;
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }
  
  /* Video title */
  .transcript-title {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-grey-100);
    line-height: 1.3;
    /* Limit to 2 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  .video-transcript-details.mobile .transcript-title {
    font-size: 14px;
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }
  
  /* Subtitle: "via YouTube Transcript API:\nX words" */
  .transcript-subtitle {
    font-size: 14px;
    font-weight: 700;
    color: var(--color-grey-70);
    line-height: 1.4;
    white-space: pre-line; /* Preserve line breaks */
  }
  
  .video-transcript-details.mobile .transcript-subtitle {
    font-size: 12px;
  }
  
  /* ===========================================
     Skill Icon Styling (skill-specific)
     =========================================== */
  
  /* Video Transcript skill icon - this is skill-specific and belongs here, not in UnifiedEmbedPreview */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="transcript"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/transcript.svg');
    mask-image: url('@openmates/ui/static/icons/transcript.svg');
  }
  
  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="transcript"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/transcript.svg');
    mask-image: url('@openmates/ui/static/icons/transcript.svg');
  }
</style>

