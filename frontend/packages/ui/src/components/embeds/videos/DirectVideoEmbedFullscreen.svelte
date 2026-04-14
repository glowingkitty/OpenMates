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
  import { proxyImage, MAX_WIDTH_VIDEO_FULLSCREEN } from '../../../utils/imageProxy';

  interface Props {
    /** Direct MP4 URL to play. */
    mp4Url: string;
    /** Thumbnail image URL shown before play. */
    thumbnailUrl?: string;
    /** Title shown in the embed header banner. */
    title?: string;
    /** Seek to this timestamp (seconds) on load (background video start point). */
    startTime?: number;
    /** Close handler. */
    onClose: () => void;
  }

  // startTime is accepted for API compatibility but fullscreen always plays from 0
  let { mp4Url, thumbnailUrl = '', title = '', startTime: _startTime = 0, onClose }: Props = $props();

  let isPlaying = $state(false);

  /** Proxy the thumbnail through our image proxy so user IP never hits api.video directly. */
  let proxiedThumbnailUrl = $derived(
    thumbnailUrl ? proxyImage(thumbnailUrl, MAX_WIDTH_VIDEO_FULLSCREEN) : ''
  );

  function handlePlay() {
    isPlaying = true;
  }


</script>

<UnifiedEmbedFullscreen
  appId="videos"
  embedHeaderTitle={title}
  skillIconName="video"
  showShare={false}
  {onClose}
>
  {#snippet content()}
    <div class="video-container">

      {#if !isPlaying}
        <!-- Thumbnail + play button overlay (same pattern as VideoEmbedFullscreen) -->
        <div class="video-thumbnail-wrapper">
          {#if proxiedThumbnailUrl}
            <img
              src={proxiedThumbnailUrl}
              alt={title}
              class="video-thumbnail"
              loading="lazy"
            />
          {:else}
            <div class="video-thumbnail-placeholder"></div>
          {/if}

          <button
            class="play-button-overlay"
            onclick={handlePlay}
            aria-label="Play video"
            type="button"
          >
            <span class="play-icon" aria-hidden="true"></span>
          </button>
        </div>

      {:else}
        <!-- Native video player — replaces thumbnail after play is clicked -->
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
      {/if}

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
    gap: var(--spacing-8);
  }

  /* ── Thumbnail (matches VideoEmbedFullscreen) ── */

  .video-thumbnail-wrapper {
    position: relative;
    width: 100%;
    max-width: 780px;
    aspect-ratio: 16 / 9;
    border-radius: var(--radius-7);
    overflow: hidden;
    background-color: var(--color-grey-15);
    box-shadow: var(--shadow-md);
    margin-top: var(--spacing-8);
  }

  .video-thumbnail {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .video-thumbnail-placeholder {
    width: 100%;
    height: 100%;
    background: var(--color-grey-15);
  }

  /* ── Play button overlay (identical to VideoEmbedFullscreen) ── */

  .play-button-overlay {
    position: absolute !important;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: rgba(0, 0, 0, 0.7) !important;
    border: none !important;
    border-radius: 50% !important;
    width: 80px !important;
    height: 80px !important;
    min-width: unset !important;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all var(--duration-normal) var(--easing-in-out);
    padding: 0 !important;
    margin: 0 !important;
    filter: none !important;
    z-index: var(--z-index-dropdown-1);
    pointer-events: auto;
  }

  .play-button-overlay:hover {
    background: rgba(0, 0, 0, 0.85) !important;
    transform: translate(-50%, -50%) scale(1.1);
    scale: none !important;
    filter: none !important;
  }

  .play-button-overlay:active {
    transform: translate(-50%, -50%) scale(0.95);
    filter: none !important;
    scale: none !important;
  }

  .play-icon {
    width: 48px;
    height: 48px;
    display: block;
    background-image: url('@openmates/ui/static/icons/play.svg');
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    filter: brightness(0) invert(1);
    pointer-events: none;
  }

  /* ── Native video player (after play clicked) ── */

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
