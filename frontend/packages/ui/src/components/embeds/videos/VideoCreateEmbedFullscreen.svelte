<!--
  frontend/packages/ui/src/components/embeds/videos/VideoCreateEmbedFullscreen.svelte

  Fullscreen view for videos.create Remotion embeds. The component reads the
  decoded embed payload directly, supports playback/timeline/source inspection,
  and exposes render lifecycle actions without executing Remotion code locally.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Embeds/Renderers/RemotionVideoCreateRenderer.swift
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedVersionTimeline from '../shared/EmbedVersionTimeline.svelte';
  import VideoTimeline from './VideoTimeline.svelte';
  import { parseRemotionTimeline } from '../../../utils/remotionTimelineParser';
  import { fetchAndDecryptAudio, releaseCachedAudio } from '../audio/audioEmbedCrypto';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface VideoFileVariant { s3_key: string; mime_type?: string; duration_seconds?: number; }
  type ViewMode = 'video' | 'timeline' | 'code';

  interface Props {
    data: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next' | null;
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data, embedId, onClose, hasPreviousEmbed = false, hasNextEmbed = false,
    onNavigatePrevious, onNavigateNext, navigateDirection = null, showChatButton = false, onShowChat,
  }: Props = $props();

  let dc = $derived(data.decodedContent || {});
  let selectedSource = $state<string | null>(null);
  let source = $derived(typeof dc.remotion_source === 'string' ? dc.remotion_source : '');
  let renderSource = $derived(selectedSource ?? source);
  let filename = $derived(typeof dc.filename === 'string' ? dc.filename : 'Composition.tsx');
  let status = $derived(typeof dc.status === 'string' ? dc.status : 'processing');
  let s3BaseUrl = $derived(typeof dc.s3_base_url === 'string' ? dc.s3_base_url : '');
  let files = $derived((typeof dc.files === 'object' && dc.files !== null) ? dc.files as { original?: VideoFileVariant; thumbnail?: VideoFileVariant } : undefined);
  let aesKey = $derived(typeof dc.aes_key === 'string' ? dc.aes_key : '');
  let aesNonce = $derived(typeof dc.aes_nonce === 'string' ? dc.aes_nonce : '');
  let publicVideoUrl = $derived(
    typeof dc.video_url === 'string'
      ? dc.video_url
      : typeof dc.public_video_url === 'string'
        ? dc.public_video_url
        : '',
  );
  let currentSourceVersion = $derived(typeof dc.current_source_version === 'number' ? dc.current_source_version : data.embedData?.version_number ?? 1);
  let manifest = $derived(parseRemotionTimeline(renderSource));
  let videoUrl = $state<string | undefined>();
  let error = $state<string | undefined>();
  let currentTime = $state(0);
  let isPlaying = $state(false);
  let viewMode = $state<ViewMode>('video');
  let videoEl: HTMLVideoElement | undefined = $state();
  let retainedS3Key: string | undefined;

  $effect(() => {
    if (!videoUrl && publicVideoUrl) {
      videoUrl = publicVideoUrl;
    } else if (!videoUrl && files?.original?.s3_key && s3BaseUrl && aesKey && aesNonce) {
      void loadVideo();
    }
  });

  onDestroy(() => { if (retainedS3Key) releaseCachedAudio(retainedS3Key); });

  async function loadVideo() {
    const file = files?.original;
    if (!file?.s3_key) return;
    try {
      videoUrl = await fetchAndDecryptAudio(s3BaseUrl, file.s3_key, aesKey, aesNonce, file.mime_type || 'video/mp4');
      retainedS3Key = file.s3_key;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load video';
    }
  }

  function handleTimeUpdate() {
    if (videoEl) currentTime = videoEl.currentTime;
  }

  function handleSeek(timeSeconds: number) {
    if (videoEl) videoEl.currentTime = timeSeconds;
    currentTime = timeSeconds;
  }

  function togglePlayback() {
    if (!videoEl) return;
    if (videoEl.paused) void videoEl.play(); else videoEl.pause();
  }

  async function postAction(path: string, sourceVersion?: number) {
    if (!embedId) return;
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ chat_id: String(data.attrs?.chat_id || data.embedData?.chat_id || ''), source_version: sourceVersion }),
    });
    if (!response.ok) throw new Error(await response.text());
  }

  async function rerender(sourceVersion?: number) {
    await postAction(`/v1/videos/remotion/${embedId}/render`, sourceVersion);
  }

  async function stopRender() {
    await postAction(`/v1/videos/remotion/${embedId}/render/current/stop`);
  }

  function formatTimestamp(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }
</script>

<UnifiedEmbedFullscreen
  appId="videos"
  skillId="create"
  skillIconName="videos"
  embedHeaderTitle={filename}
  embedHeaderSubtitle={`Remotion · v${currentSourceVersion} · ${status}`}
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="video-create-fullscreen" data-testid="video-create-fullscreen">
      <div class="toolbar">
        <button class:active={viewMode === 'video'} onclick={() => viewMode = 'video'}>Video</button>
        <button class:active={viewMode === 'timeline'} onclick={() => viewMode = 'timeline'}>Timeline</button>
        <button class:active={viewMode === 'code'} onclick={() => viewMode = 'code'}>Code</button>
        <span class="spacer"></span>
        {#if status === 'rendering'}<button onclick={stopRender}>Stop render</button>{/if}
        <button onclick={() => rerender()}>Rerender</button>
        <button onclick={() => rerender(currentSourceVersion)}>Render this version</button>
      </div>

      {#if viewMode === 'code'}
        <pre class="source-code"><code>{renderSource}</code></pre>
      {:else}
        {#if viewMode === 'video'}
          <div class="video-wrapper">
            {#if videoUrl}
              <video bind:this={videoEl} src={videoUrl} ontimeupdate={handleTimeUpdate} onplay={() => isPlaying = true} onpause={() => isPlaying = false} controls playsinline preload="metadata">
                <track kind="captions" src="data:text/vtt,WEBVTT" />
              </video>
            {:else if error}
              <p>{error}</p>
            {:else}
              <p>{status === 'rendering' ? 'Rendering video...' : 'Video is not available yet.'}</p>
            {/if}
          </div>
          <div class="controls-bar">
            <button class="play-btn" onclick={togglePlayback} disabled={!videoUrl}>{isPlaying ? 'Pause' : 'Play'}</button>
            <span>{formatTimestamp(currentTime)} / {formatTimestamp(manifest.meta.durationSeconds)}</span>
          </div>
        {/if}
        <VideoTimeline {manifest} {currentTime} onSeek={handleSeek} />
      {/if}
      {#if embedId && currentSourceVersion > 1}
        <EmbedVersionTimeline
          {embedId}
          currentVersion={currentSourceVersion}
          currentContent={source}
          buildRestoredContent={(content, newVersion) => ({ ...dc, remotion_source: content, current_source_version: newVersion, version_number: newVersion })}
          onVersionSelect={(version, content) => {
            selectedSource = content;
            console.log('[VideoCreateEmbedFullscreen] Version selected:', version);
          }}
        />
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .video-create-fullscreen { display: grid; gap: 16px; padding: 20px; color: var(--color-font-primary); }
  .toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .toolbar button, .play-btn { border: 1px solid var(--color-grey-25, #ddd); border-radius: 10px; background: var(--color-grey-10, #f4f4f4); color: var(--color-font-primary); padding: 8px 12px; cursor: pointer; }
  .toolbar button.active { background: var(--color-button-primary); color: var(--color-font-button, #fff); }
  .spacer { flex: 1; }
  .video-wrapper { display: grid; place-items: center; min-height: 240px; border-radius: 16px; background: var(--color-grey-100, #111); overflow: hidden; }
  video { width: 100%; max-height: 62vh; object-fit: contain; }
  .controls-bar { display: flex; gap: 12px; align-items: center; }
  .source-code { max-height: 62vh; overflow: auto; padding: 16px; border-radius: 14px; background: var(--color-grey-10, #f4f4f4); color: var(--color-font-primary); }
</style>
