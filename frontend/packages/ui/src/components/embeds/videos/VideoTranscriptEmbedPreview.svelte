<!--
  frontend/packages/ui/src/components/embeds/videos/VideoTranscriptEmbedPreview.svelte
  
  Preview component for Video Transcript app skill embeds.
  Uses UnifiedEmbedPreview as base and provides video transcript-specific details content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives results, status, taskId directly
  
  Layout (per Figma design, matching WebReadEmbedPreview):
  - Details section:
    - Thumbnail (rounded, top-left of title) - YouTube video thumbnail
    - Title: video title or hostname
    - Subtitle: "via YouTube Transcript API:\n{wordCount} words"
  - Basic infos bar:
    - Videos app icon (gradient circle)
    - Transcript skill icon
    - "Transcript" / "Completed" (or "Processing")
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  // @ts-expect-error - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';
  import type { VideoTranscriptSkillPreviewData } from '../../../types/appSkills';
  
  /**
   * Video transcript result interface
   */
  interface VideoTranscriptResult {
    url?: string;
    metadata?: {
      title?: string;
    };
    word_count?: number;
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
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  
  // Initialize local state from props
  $effect(() => {
    // Initialize from previewData or direct props
    if (previewData) {
      localResults = previewData.results || [];
      localUrl = previewData.url || '';
      localStatus = previewData.status || 'processing';
    } else {
      localResults = resultsProp || [];
      localUrl = urlProp || '';
      localStatus = statusProp || 'processing';
    }
  });
  
  // Use local state as the source of truth (allows updates from embed events)
  let results = $derived(localResults);
  let status = $derived(localStatus);
  let taskId = $derived(previewData?.task_id || taskIdProp);
  
  // Get first result for main display (may be undefined if results are empty)
  let firstResult = $derived(results[0]);
  
  // Get URL from multiple sources (priority: results > localUrl > previewData > direct prop)
  // CRITICAL: Even if results are empty, we may have URL from the processing placeholder
  let effectiveUrl = $derived(
    firstResult?.url || 
    localUrl ||
    previewData?.url || 
    urlProp || 
    ''
  );
  
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
    
    // Update status
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
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
    }
  }
  
  /**
   * Safely extract hostname from URL
   * Falls back to stripping the scheme if URL parsing fails
   */
  function safeHostname(url?: string): string {
    if (!url) return '';
    try {
      return new URL(url).hostname;
    } catch {
      // Fallback: try to strip scheme if present, then take host part.
      const withoutScheme = url.replace(/^[a-zA-Z]+:\/\//, '');
      return withoutScheme.split('/')[0] || '';
    }
  }
  
  // Extract hostname from effective URL
  let hostname = $derived(safeHostname(effectiveUrl));
  
  // Get skill name from translations
  let skillName = $derived($text('embeds.video_transcript.text') || 'Transcript');
  
  // Map skillId to icon name
  const skillIconName = 'transcript';
  
  // Display title: video title from results, or fallback to hostname
  // CRITICAL: Use effectiveUrl-derived hostname if results are empty
  let displayTitle = $derived(
    firstResult?.metadata?.title || 
    hostname || 
    ($text('embeds.video_transcript.text') || 'Video Transcript')
  );
  
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
  
  // Extract YouTube video ID from the effective URL for thumbnail
  let videoId = $derived.by(() => {
    if (effectiveUrl) {
      try {
        // YouTube URL patterns
        const youtubeMatch = effectiveUrl.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)/);
        if (youtubeMatch) {
          return youtubeMatch[1];
        }
      } catch (e) {
        console.debug('[VideoTranscriptEmbedPreview] Error parsing URL:', e);
      }
    }
    return '';
  });
  
  // Thumbnail URL - use YouTube video thumbnail (medium quality for small display)
  let thumbnailUrl = $derived(() => {
    if (videoId) {
      // Use mqdefault (320x180) for small thumbnail display - loads faster than maxresdefault
      return `https://img.youtube.com/vi/${videoId}/mqdefault.jpg`;
    }
    return undefined;
  });
  
  // Subtitle text: "via YouTube Transcript API:\nX words" (matches WebReadEmbedPreview pattern)
  let subtitleText = $derived(() => {
    const wordCount = totalWordCount;
    if (wordCount > 0) {
      return `via YouTube Transcript API:\n${wordCount.toLocaleString()} words`;
    }
    return 'via YouTube Transcript API';
  });
  
  // Debug logging to help trace data flow issues
  $effect(() => {
    console.debug('[VideoTranscriptEmbedPreview] Rendering with:', {
      id,
      status,
      resultsCount: results.length,
      effectiveUrl,
      hostname,
      displayTitle,
      wordCount: totalWordCount,
      hasPreviewData: !!previewData,
      hasUrlProp: !!urlProp
    });
  });
  
  // Handle stop button click
  async function handleStop() {
    if (status === 'processing' && taskId) {
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
      <!-- Title row with thumbnail -->
      <div class="title-row">
        {#if thumbnailUrl()}
          <img 
            src={thumbnailUrl()} 
            alt="" 
            class="title-thumbnail"
            onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
          />
        {/if}
        <div class="transcript-title">{displayTitle}</div>
      </div>
      
      <!-- Subtitle: "via YouTube Transcript API:\nX words" -->
      <div class="transcript-subtitle">{subtitleText()}</div>
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
  
  /* Title row with thumbnail and title text */
  .title-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }
  
  /* Thumbnail next to title - rounded rectangle (video aspect ratio hint) */
  .title-thumbnail {
    width: 32px;
    height: 18px;
    min-width: 32px;
    border-radius: 4px;
    background-color: var(--color-grey-30);
    object-fit: cover;
    flex-shrink: 0;
    margin-top: 2px; /* Align with first line of title */
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

