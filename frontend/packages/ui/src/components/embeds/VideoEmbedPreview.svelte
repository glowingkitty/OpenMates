<!--
  frontend/packages/ui/src/components/embeds/VideoEmbedPreview.svelte
  
  Preview component for Video URL embeds (YouTube, etc.).
  Uses UnifiedEmbedPreview as base and provides video-specific details content.
  
  Details content structure:
  - Processing: URL hostname
  - Finished: video title + thumbnail (if available)
-->

<script lang="ts">
  import UnifiedEmbedPreview from './UnifiedEmbedPreview.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  
  /**
   * Props for video embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Video URL */
    url: string;
    /** Video title */
    title?: string;
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
    url,
    title,
    status,
    taskId,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Map skillId to icon name
  const skillIconName = 'video';
  
  // Extract video ID and thumbnail for YouTube URLs
  let videoId = $derived('');
  let thumbnailUrl = $derived('');
  let displayTitle = $derived(title || 'YouTube Video');
  let hostname = $derived('');
  
  // Process URL to extract video information
  $effect(() => {
    if (url) {
      try {
        const urlObj = new URL(url);
        hostname = urlObj.hostname;
        
        // YouTube URL patterns
        const youtubeMatch = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)/);
        if (youtubeMatch) {
          videoId = youtubeMatch[1];
          thumbnailUrl = `https://img.youtube.com/vi/${videoId}/maxresdefault.jpg`;
          if (!title) {
            displayTitle = 'YouTube Video';
          }
        }
      } catch (e) {
        console.debug('[VideoEmbedPreview] Error parsing URL:', e);
        hostname = url;
      }
    }
  });
  
  // Handle stop button click (not applicable for videos, but included for consistency)
  async function handleStop() {
    // Videos don't have cancellable tasks, but we include this for API consistency
    console.debug('[VideoEmbedPreview] Stop requested (not applicable for videos)');
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="videos"
  skillId="video"
  {skillIconName}
  {status}
  skillName={displayTitle}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="video-details" class:mobile={isMobileLayout}>
      {#if status === 'processing'}
        <!-- Processing state: show hostname only -->
        <div class="video-hostname">{hostname}</div>
      {:else if status === 'finished'}
        <!-- Finished state: show thumbnail if available -->
        {#if videoId && thumbnailUrl}
          <div class="video-thumbnail-container">
            <img 
              src={thumbnailUrl} 
              alt={displayTitle}
              class="video-thumbnail"
              loading="lazy"
              onerror={(e) => {
                (e.target as HTMLImageElement).style.display = 'none';
              }}
            />
          </div>
        {:else}
          <!-- Fallback: show URL path -->
          <div class="video-url-fallback">
            {#if hostname}
              <div class="video-hostname">{hostname}</div>
            {/if}
            {#if url}
              {@const urlObj = new URL(url)}
              {@const path = urlObj.pathname + urlObj.search + urlObj.hash}
              {#if path !== '/'}
                <div class="video-path">{path}</div>
              {/if}
            {/if}
          </div>
        {/if}
      {:else}
        <!-- Error state -->
        <div class="video-error">{hostname || url}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Video Details Content
     =========================================== */
  
  .video-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content */
  .video-details:not(.mobile) {
    justify-content: center;
  }
  
  /* Mobile layout: top-aligned content */
  .video-details.mobile {
    justify-content: flex-start;
  }
  
  /* Video thumbnail container */
  .video-thumbnail-container {
    position: relative;
    width: 100%;
    max-width: 260px;
    aspect-ratio: 16 / 9;
    border-radius: 8px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    margin-top: 8px;
  }
  
  .video-thumbnail {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  
  /* Video hostname (for processing state) */
  .video-hostname {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .video-details.mobile .video-hostname {
    font-size: 12px;
  }
  
  /* Video URL fallback (when no thumbnail) */
  .video-url-fallback {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  
  .video-path {
    font-size: 12px;
    color: var(--color-grey-60);
    line-height: 1.3;
    word-break: break-all;
  }
  
  /* Error state */
  .video-error {
    font-size: 14px;
    color: var(--color-error);
    line-height: 1.3;
  }
</style>

