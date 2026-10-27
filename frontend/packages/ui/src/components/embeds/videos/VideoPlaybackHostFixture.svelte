<!-- Bare host for the production fullscreen/store/iframe PiP lifecycle.
     The player remains mounted as a sibling while the fullscreen closes/remounts,
     matching ActiveChat's ownership boundary without loading an account or chat. -->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import VideoEmbedFullscreen from './VideoEmbedFullscreen.svelte';
  import VideoIframe from './VideoIframe.svelte';
  import { videoIframeStore } from '../../../stores/videoIframeStore';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  let fullscreenOpen = $state(true);
  let restoreFromPip = $state(false);
  const video = {
    url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    video_id: 'dQw4w9WgXcQ',
    title: 'Persistent video player',
    channel_name: 'Video lifecycle fixture',
    thumbnail: '/images/examples/group1.jpg',
  };
  const data = $derived({ decodedContent: video, restoreFromPip } as EmbedFullscreenRawData);
  const playerStyle = $derived.by(() => {
    if ($videoIframeStore.isPipMode) return undefined;
    const anchor = $videoIframeStore.fullscreenAnchor;
    return anchor ? `top:${anchor.top}px;left:${anchor.left}px;width:${anchor.width}px;` : undefined;
  });
  function restoreFullscreen() {
    if (!$videoIframeStore.isActive || !$videoIframeStore.isPipMode) return;
    // ActiveChat exits PiP and remounts the actual result view with this flag.
    videoIframeStore.exitPipMode();
    restoreFromPip = true;
    fullscreenOpen = true;
  }
  onMount(() => videoIframeStore.clear());
  onDestroy(() => videoIframeStore.clear());
</script>

<div class="active-chat-container playback-host" data-testid="video-playback-host">
  {#if fullscreenOpen}
    <VideoEmbedFullscreen {data} onClose={() => { fullscreenOpen = false; }} />
  {/if}
  {#if ($videoIframeStore.isActive || $videoIframeStore.isClosing) && $videoIframeStore.videoId && $videoIframeStore.embedUrl}
    <div class="player-host" class:pip={$videoIframeStore.isPipMode} style={playerStyle} data-testid="video-playback-player-host">
      <VideoIframe
        videoId={$videoIframeStore.videoId}
        title={$videoIframeStore.title || 'Video'}
        embedUrl={$videoIframeStore.embedUrl}
        isPipMode={$videoIframeStore.isPipMode}
        onPipOverlayClick={restoreFullscreen}
      />
    </div>
  {/if}
</div>

<style>
  .playback-host { position: relative; width: 100%; height: 100dvh; min-height: 36rem; }
  .player-host { position: absolute; z-index: var(--z-index-dropdown); aspect-ratio: 16 / 9; }
  .player-host.pip { top: var(--spacing-8); right: var(--spacing-8); left: auto; width: min(20rem, calc(100% - 2rem)); z-index: var(--z-index-modal); }
</style>
