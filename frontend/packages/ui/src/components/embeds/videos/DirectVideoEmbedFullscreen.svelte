<!--
  frontend/packages/ui/src/components/embeds/videos/DirectVideoEmbedFullscreen.svelte

  Fullscreen player for a direct MP4/HLS video URL (e.g. api.video product demos).
  Uses UnifiedEmbedFullscreen as the visual shell — same slide-in animation, top bar,
  and close button as all other embed fullscreens.

  The EmbedHeader gradient banner is intentionally hidden — the video fills the full
  height so the viewer sees just the video and the EmbedTopBar controls.

  Unlike VideoEmbedFullscreen (YouTube-specific), this renders a native <video> element.
-->
<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';

  interface Props {
    /** Direct MP4 URL to play. */
    mp4Url: string;
    /** Title shown in the EmbedTopBar (not the gradient header — that is hidden). */
    title?: string;
    /** Seek to this timestamp (seconds) when the video loads. */
    startTime?: number;
    /** Close handler — called when the user closes the fullscreen. */
    onClose: () => void;
  }

  let { mp4Url, title = '', startTime = 0, onClose }: Props = $props();

  function handleVideoMetadata(e: Event) {
    if (startTime > 0) {
      (e.target as HTMLVideoElement).currentTime = startTime;
    }
  }
</script>

<!-- Wrapper class lets us scope :global CSS to this fullscreen only -->
<div class="direct-video-fullscreen">
  <UnifiedEmbedFullscreen
    appId="videos"
    embedHeaderTitle={title}
    skillIconName="video"
    showShare={false}
    {onClose}
  >
    {#snippet content()}
      <div class="direct-video-wrapper">
        <video
          class="direct-video-player"
          src={mp4Url}
          autoplay
          controls
          playsinline
          onloadedmetadata={handleVideoMetadata}
        >
          <track kind="captions" />
        </video>
      </div>
    {/snippet}
  </UnifiedEmbedFullscreen>
</div>

<style>
  /* Fill parent container so UnifiedEmbedFullscreen takes full height */
  .direct-video-fullscreen {
    position: absolute;
    inset: 0;
  }

  /* Hide the gradient header banner — video takes full height instead.
     EmbedTopBar (close button) remains visible above the content area. */
  .direct-video-fullscreen :global(.embed-header) {
    display: none;
  }

  .direct-video-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    padding: 0;
    box-sizing: border-box;
    background: #000;
  }

  .direct-video-player {
    display: block;
    width: 100%;
    height: 100%;
    max-height: 100%;
    object-fit: contain;
    border-radius: 0;
    background: #000;
  }
</style>
