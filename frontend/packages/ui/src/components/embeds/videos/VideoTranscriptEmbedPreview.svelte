<!--
  frontend/packages/ui/src/components/embeds/videos/VideoTranscriptEmbedPreview.svelte
  
  Preview component for Video Transcript app skill embeds.
  Uses UnifiedEmbedPreview as base and provides video transcript-specific details content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives results, status, taskId directly
  
  Details content structure:
  - Processing: "Processing transcript..."
  - Finished: video title + word count + video count (if multiple)
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
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
    previewData,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Extract values from either previewData (skill preview context) or direct props (embed context)
  let results = $derived(previewData?.results || resultsProp || []);
  let status = $derived(previewData?.status || statusProp || 'processing');
  let taskId = $derived(previewData?.task_id || taskIdProp);
  
  // Get skill name from translations
  let skillName = $derived($text('embeds.video_transcript.text') || 'Video Transcript');
  
  // Map skillId to icon name
  const skillIconName = 'transcript';
  
  // Extract video information from results
  let firstResult = $derived(results[0] || {});
  let videoTitle = $derived(
    firstResult.metadata?.title || 
    firstResult.url || 
    ($text('embeds.video_transcript.text') || 'Video Transcript')
  );
  let wordCount = $derived(firstResult.word_count || 0);
  let videoCount = $derived(previewData?.video_count || previewData?.success_count || results.length || 0);
  
  // Extract YouTube video ID and thumbnail URL from the first result's URL
  let videoId = $derived.by(() => {
    const url = firstResult.url;
    if (url) {
      try {
        // YouTube URL patterns
        const youtubeMatch = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)/);
        if (youtubeMatch) {
          return youtubeMatch[1];
        }
      } catch (e) {
        console.debug('[VideoTranscriptEmbedPreview] Error parsing URL:', e);
      }
    }
    return '';
  });
  
  let thumbnailUrl = $derived(
    videoId ? `https://img.youtube.com/vi/${videoId}/maxresdefault.jpg` : ''
  );
  
  // For processing state, show a generic message if no video info is available
  let processingTitle = $derived(
    videoTitle !== ($text('embeds.video_transcript.text') || 'Video Transcript')
      ? videoTitle
      : ($text('embeds.processing_transcript.text') || 'Processing transcript...')
  );
  
  // Get "via YouTube Transcript API" text
  let viaText = $derived($text('embeds.via_youtube_transcript.text') || 'via YouTube Transcript API');
  
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
  hasFullWidthImage={true}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="video-transcript-details" class:mobile={isMobileLayout}>
      {#if status === 'processing'}
        <!-- Processing state: show thumbnail if available, otherwise show hostname -->
        {#if videoId && thumbnailUrl}
          <div class="video-thumbnail-container">
            <img 
              src={thumbnailUrl} 
              alt={videoTitle}
              class="video-thumbnail"
              loading="lazy"
              onerror={(e) => {
                (e.target as HTMLImageElement).style.display = 'none';
              }}
            />
          </div>
        {:else}
          <div class="video-hostname">
            {#if firstResult.url}
              {@const urlObj = new URL(firstResult.url)}
              {urlObj.hostname}
            {:else}
              {processingTitle}
            {/if}
          </div>
        {/if}
      {:else if status === 'finished'}
        <!-- Finished state: show thumbnail if available -->
        {#if videoId && thumbnailUrl}
          <div class="video-thumbnail-container">
            <img 
              src={thumbnailUrl} 
              alt={videoTitle}
              class="video-thumbnail"
              loading="lazy"
              onerror={(e) => {
                (e.target as HTMLImageElement).style.display = 'none';
              }}
            />
          </div>
        {:else}
          <!-- Fallback: show URL hostname -->
          <div class="video-hostname">
            {#if firstResult.url}
              {@const urlObj = new URL(firstResult.url)}
              {urlObj.hostname}
            {:else}
              {videoTitle}
            {/if}
          </div>
        {/if}
      {:else}
        <!-- Error state: show thumbnail if available, otherwise show error -->
        {#if videoId && thumbnailUrl}
          <div class="video-thumbnail-container">
            <img 
              src={thumbnailUrl} 
              alt={videoTitle}
              class="video-thumbnail"
              loading="lazy"
              onerror={(e) => {
                (e.target as HTMLImageElement).style.display = 'none';
              }}
            />
          </div>
        {:else}
          <div class="video-error">
            {#if firstResult.url}
              {@const urlObj = new URL(firstResult.url)}
              {urlObj.hostname}
            {:else}
              {videoTitle}
            {/if}
          </div>
        {/if}
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Video Transcript Details Content
     =========================================== */
  
  .video-transcript-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content (only for text, not images) */
  .video-transcript-details:not(.mobile):not(:has(.video-thumbnail-container)) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .video-transcript-details.mobile {
    justify-content: flex-start;
  }
  
  /* When thumbnail is present, fill the full height */
  .video-transcript-details:has(.video-thumbnail-container) {
    gap: 0;
  }
  
  /* Video thumbnail container - full width and height */
  .video-thumbnail-container {
    position: relative;
    width: 100%;
    height: 100%;
    border-radius: 8px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    flex: 1;
    min-height: 0;
  }
  
  .video-thumbnail {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  
  /* Video hostname (for fallback states) */
  .video-hostname {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .video-transcript-details.mobile .video-hostname {
    font-size: 12px;
  }
  
  /* Error state */
  .video-error {
    font-size: 14px;
    color: var(--color-error);
    line-height: 1.3;
  }
  
  .video-transcript-details.mobile .video-error {
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

