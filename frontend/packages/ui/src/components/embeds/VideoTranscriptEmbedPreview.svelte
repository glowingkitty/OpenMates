<!--
  frontend/packages/ui/src/components/embeds/VideoTranscriptEmbedPreview.svelte
  
  Preview component for Video Transcript app skill embeds.
  Uses UnifiedEmbedPreview as base and provides video transcript-specific details content.
  
  Details content structure:
  - Processing: "Processing transcript..."
  - Finished: video title + word count + video count (if multiple)
-->

<script lang="ts">
  import UnifiedEmbedPreview from './UnifiedEmbedPreview.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../services/chatSyncService';
  
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
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Video transcript results */
    results?: VideoTranscriptResult[];
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }
  
  let {
    id,
    results = [],
    status,
    taskId,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
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
  let videoCount = $derived(results.length || 0);
  
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
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="video-transcript-details" class:mobile={isMobileLayout}>
      {#if status === 'processing'}
        <!-- Processing state -->
        <div class="transcript-processing">
          <div class="transcript-title">{processingTitle}</div>
          <div class="transcript-subtitle">{viaText}</div>
        </div>
      {:else if status === 'finished'}
        <!-- Finished state -->
        <div class="transcript-content">
          <div class="transcript-title">{videoTitle}</div>
          <div class="transcript-subtitle">{viaText}</div>
          
          {#if wordCount > 0}
            <div class="transcript-word-count">
              {wordCount.toLocaleString()} {$text('embeds.words.text') || 'words'}
            </div>
          {/if}
          
          {#if videoCount > 1}
            <div class="transcript-video-count">
              {videoCount} {$text('embeds.videos.text') || 'videos'}
            </div>
          {/if}
        </div>
      {:else}
        <!-- Error state -->
        <div class="transcript-error">
          <div class="transcript-title">{videoTitle}</div>
          <div class="transcript-error-message">
            {$text('embeds.error.text') || 'Error loading transcript'}
          </div>
        </div>
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
  
  /* Desktop layout: vertically centered content */
  .video-transcript-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .video-transcript-details.mobile {
    justify-content: flex-start;
  }
  
  /* Transcript content container */
  .transcript-content,
  .transcript-processing {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  
  /* Transcript title */
  .transcript-title {
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
  
  .video-transcript-details.mobile .transcript-title {
    font-size: 14px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }
  
  /* Transcript subtitle */
  .transcript-subtitle {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .video-transcript-details.mobile .transcript-subtitle {
    font-size: 12px;
  }
  
  /* Word count */
  .transcript-word-count {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
    margin-top: 4px;
  }
  
  .video-transcript-details.mobile .transcript-word-count {
    font-size: 12px;
    margin-top: 2px;
  }
  
  /* Video count */
  .transcript-video-count {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
    margin-top: 2px;
  }
  
  .video-transcript-details.mobile .transcript-video-count {
    font-size: 12px;
  }
  
  /* Error state */
  .transcript-error {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  
  .transcript-error-message {
    font-size: 14px;
    color: var(--color-error);
    line-height: 1.3;
  }
  
  .video-transcript-details.mobile .transcript-error-message {
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

