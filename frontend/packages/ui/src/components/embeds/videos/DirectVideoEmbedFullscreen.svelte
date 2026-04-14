<!--
  frontend/packages/ui/src/components/embeds/videos/DirectVideoEmbedFullscreen.svelte

  Fullscreen player for a direct MP4/HLS video URL (e.g. api.video product demos).
  Uses UnifiedEmbedFullscreen as the visual shell — same chrome as all other embed
  fullscreens (top bar, gradient header, close/share buttons, slide-in animation).

  Unlike VideoEmbedFullscreen (which is YouTube-specific and uses videoIframeStore),
  this component renders a native <video> element with the direct URL.

  Use cases:
  - Product demo videos hosted on api.video
  - Any direct MP4/HLS URL that should open in the embed fullscreen shell

  Props:
    mp4Url        — direct MP4 URL (required)
    title         — optional title shown in the embed header banner
    startTime     — seek to this timestamp (seconds) on load (default: 0)
    onClose       — close handler (required)
-->
<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';

  interface Props {
    /** Direct MP4 URL to play. */
    mp4Url: string;
    /** Title shown in the embed header banner. */
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

<UnifiedEmbedFullscreen
  appId="videos"
  embedHeaderTitle={title}
  showSkillIcon={false}
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

<style>
  .direct-video-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    padding: var(--spacing-6) var(--spacing-4);
    box-sizing: border-box;
  }

  .direct-video-player {
    display: block;
    width: 100%;
    max-width: 960px;
    height: auto;
    border-radius: var(--radius-4);
    background: #000;
  }
</style>
