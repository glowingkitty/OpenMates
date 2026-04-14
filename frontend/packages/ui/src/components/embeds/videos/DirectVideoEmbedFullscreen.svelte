<!--
  frontend/packages/ui/src/components/embeds/videos/DirectVideoEmbedFullscreen.svelte

  Fullscreen player for a direct MP4 video URL (e.g. api.video product demos).
  Matches the visual pattern of VideoEmbedFullscreen:
    - Thumbnail image with play button overlay (initial state)
    - Click play → native <video> element plays in-place
    - Same UnifiedEmbedFullscreen shell, same layout/styling

  Unlike VideoEmbedFullscreen (YouTube-specific, uses videoIframeStore),
  this component plays a direct MP4 URL with a native video element.
-->
<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';

  interface Props {
    /** Direct MP4 URL to play. */
    mp4Url: string;
    /** Title shown in the embed header banner. */
    title?: string;
    /** Close handler. */
    onClose: () => void;
  }

  let { mp4Url, title = '', onClose }: Props = $props();


</script>

<UnifiedEmbedFullscreen
  appId="videos"
  embedHeaderTitle={title}
  skillIconName="video"
  showShare={false}
  {onClose}
>
  {#snippet content()}
    <!-- Video autoplays from the start as soon as the fullscreen opens. -->
    <div class="video-container">
      <div class="video-player-wrapper">
        <video
          class="video-player"
          src={mp4Url}
          autoplay
          controls
          playsinline
        >
          <track kind="captions" />
        </video>
      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .video-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 100%;
    margin-top: var(--spacing-10);
  }

  .video-player-wrapper {
    width: 100%;
    max-width: 780px;
    aspect-ratio: 16 / 9;
    border-radius: var(--radius-7);
    overflow: hidden;
    background: #000;
    box-shadow: var(--shadow-md);
    margin-top: var(--spacing-8);
  }

  .video-player {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: contain;
  }
</style>
