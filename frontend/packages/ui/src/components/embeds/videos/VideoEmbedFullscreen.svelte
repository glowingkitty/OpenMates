<!--
  frontend/packages/ui/src/components/embeds/videos/VideoEmbedFullscreen.svelte
  
  Fullscreen view for Video URL embeds (YouTube, etc.).
  Uses UnifiedEmbedFullscreen as base and provides video-specific content.
  
  Shows:
  - Video thumbnail preview image (780px max width)
  - "Open on YouTube" button
  - Video title and metadata
  - Basic infos bar at the bottom
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  
  /**
   * Props for video embed fullscreen
   */
  interface Props {
    /** Video URL */
    url: string;
    /** Video title */
    title?: string;
    /** Close handler */
    onClose: () => void;
  }
  
  let {
    url,
    title,
    onClose
  }: Props = $props();
  
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
        console.debug('[VideoEmbedFullscreen] Error parsing URL:', e);
        hostname = url;
      }
    }
  });
  
  // Handle opening video on YouTube
  function handleOpenOnYouTube() {
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  }
  
  // Handle copy - copies video URL to clipboard
  async function handleCopy() {
    try {
      if (url) {
        await navigator.clipboard.writeText(url);
        console.debug('[VideoEmbedFullscreen] Copied video URL to clipboard');
      }
    } catch (error) {
      console.error('[VideoEmbedFullscreen] Failed to copy URL:', error);
    }
  }
  
  // Handle download - not applicable for video embeds (placeholder)
  function handleDownload() {
    console.debug('[VideoEmbedFullscreen] Download action (not applicable for video embeds)');
  }
  
  // Handle share - opens share menu (placeholder for now)
  function handleShare() {
    // TODO: Implement share functionality for video embeds
    console.debug('[VideoEmbedFullscreen] Share action (not yet implemented)');
  }
</script>

<UnifiedEmbedFullscreen
  appId="videos"
  skillId="video"
  title=""
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  onShare={handleShare}
  skillIconName="video"
  status="finished"
  skillName={displayTitle}
  showSkillIcon={false}
>
  {#snippet content()}
    <div class="video-container">
      <!-- Video thumbnail preview (780px max width) -->
      {#if videoId && thumbnailUrl}
        <div class="video-thumbnail-wrapper">
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
        <!-- Fallback: show URL hostname if no thumbnail -->
        <div class="video-fallback">
          <div class="video-hostname">{hostname || url}</div>
        </div>
      {/if}
      
      <!-- Open on YouTube button -->
      {#if url}
        <div class="button-container">
          <button 
            class="open-on-youtube-button"
            onclick={handleOpenOnYouTube}
            type="button"
          >
            {$text('embeds.open_on_youtube.text') || 'Open on YouTube'}
          </button>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Video Fullscreen - Layout
     =========================================== */
  
  .video-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 24px;
    width: 100%;
    margin-top: 80px;
  }
  
  /* Video thumbnail wrapper - 780px max width, centered */
  .video-thumbnail-wrapper {
    width: 100%;
    max-width: 780px;
    display: flex;
    justify-content: center;
    border-radius: 16px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }
  
  .video-thumbnail {
    width: 100%;
    height: auto;
    display: block;
    object-fit: contain;
  }
  
  /* Fallback container for when no thumbnail is available */
  .video-fallback {
    width: 100%;
    max-width: 780px;
    display: flex;
    justify-content: center;
    padding: 40px;
  }
  
  .video-hostname {
    font-size: 16px;
    color: var(--color-grey-70);
    text-align: center;
  }
  
  /* Button container - centered */
  .button-container {
    display: flex;
    justify-content: center;
    width: 100%;
    max-width: 780px;
  }
  
  /* Open on YouTube button - styled similar to other action buttons */
  .open-on-youtube-button {
    margin-top: -60px;
  }
</style>
