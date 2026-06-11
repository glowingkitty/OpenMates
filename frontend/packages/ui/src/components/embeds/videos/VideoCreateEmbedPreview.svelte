<!--
  frontend/packages/ui/src/components/embeds/videos/VideoCreateEmbedPreview.svelte

  Preview card for code-backed Remotion videos.create embeds. It renders source
  and render lifecycle states from decoded embed content, decrypting finished
  media through the same generated-media client path as other encrypted media.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Embeds/Renderers/RemotionVideoCreateRenderer.swift
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import VideoTimeline from './VideoTimeline.svelte';
  import { parseRemotionTimeline, type VideoManifest } from '../../../utils/remotionTimelineParser';
  import { fetchAndDecryptAudio, releaseCachedAudio } from '../audio/audioEmbedCrypto';

  interface VideoFileVariant { s3_key: string; mime_type?: string; duration_seconds?: number; }
  type RemotionStatus = 'processing' | 'rendering' | 'finished' | 'error' | 'cancelled' | 'needs_rerender';

  interface Props {
    id: string;
    remotionSource?: string;
    filename?: string;
    manifest?: VideoManifest;
    status: RemotionStatus;
    s3BaseUrl?: string;
    files?: { original?: VideoFileVariant; thumbnail?: VideoFileVariant };
    aesKey?: string;
    aesNonce?: string;
    videoUrl?: string;
    thumbnailUrl?: string;
    errorMessage?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id, remotionSource = '', filename = 'Composition.tsx', manifest, status,
    s3BaseUrl = '', files, aesKey = '', aesNonce = '', videoUrl: initialVideoUrl = '',
    thumbnailUrl: initialThumbnailUrl = '', errorMessage = '', taskId, isMobile = false, onFullscreen,
  }: Props = $props();

  let updatedStatus = $state<RemotionStatus | undefined>();
  let updatedSource = $state<string | undefined>();
  let updatedFilename = $state<string | undefined>();
  let updatedS3BaseUrl = $state<string | undefined>();
  let updatedFiles = $state<{ original?: VideoFileVariant; thumbnail?: VideoFileVariant } | undefined>();
  let updatedAesKey = $state<string | undefined>();
  let updatedAesNonce = $state<string | undefined>();
  let updatedError = $state<string | undefined>();
  let videoUrl = $state<string | undefined>();
  let thumbnailUrl = $state<string | undefined>();
  let retainedVideoKey: string | undefined;
  let retainedThumbnailKey: string | undefined;

  const currentStatus = $derived(updatedStatus ?? status);
  const currentSource = $derived(updatedSource ?? remotionSource);
  const currentFilename = $derived(updatedFilename ?? filename);
  const currentS3BaseUrl = $derived(updatedS3BaseUrl ?? s3BaseUrl);
  const currentFiles = $derived(updatedFiles ?? files);
  const currentAesKey = $derived(updatedAesKey ?? aesKey);
  const currentAesNonce = $derived(updatedAesNonce ?? aesNonce);
  const currentError = $derived(updatedError ?? errorMessage);
  const currentManifest = $derived(manifest ?? parseRemotionTimeline(currentSource || ''));
  const unifiedStatus = $derived(currentStatus === 'error' ? 'error' : currentStatus === 'finished' ? 'finished' : 'processing');
  const durationLabel = $derived(`${currentManifest.meta.durationSeconds}s`);
  const resolutionLabel = $derived(`${currentManifest.meta.width}x${currentManifest.meta.height}`);

  $effect(() => {
    if (initialVideoUrl && !videoUrl) videoUrl = initialVideoUrl;
    if (initialThumbnailUrl && !thumbnailUrl) thumbnailUrl = initialThumbnailUrl;
    if (currentStatus === 'finished' && currentFiles?.original?.s3_key && currentS3BaseUrl && currentAesKey && currentAesNonce && !videoUrl) {
      void loadVideo();
    }
    if (currentStatus === 'finished' && currentFiles?.thumbnail?.s3_key && currentS3BaseUrl && currentAesKey && currentAesNonce && !thumbnailUrl) {
      void loadThumbnail();
    }
  });

  onDestroy(() => {
    if (retainedVideoKey) releaseCachedAudio(retainedVideoKey);
    if (retainedThumbnailKey) releaseCachedAudio(retainedThumbnailKey);
  });

  async function loadVideo() {
    const file = currentFiles?.original;
    if (!file?.s3_key) return;
    videoUrl = await fetchAndDecryptAudio(currentS3BaseUrl, file.s3_key, currentAesKey, currentAesNonce, file.mime_type || 'video/mp4');
    retainedVideoKey = file.s3_key;
  }

  async function loadThumbnail() {
    const file = currentFiles?.thumbnail;
    if (!file?.s3_key) return;
    thumbnailUrl = await fetchAndDecryptAudio(currentS3BaseUrl, file.s3_key, currentAesKey, currentAesNonce, file.mime_type || 'image/png');
    retainedThumbnailKey = file.s3_key;
  }

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    const decoded = data.decodedContent;
    updatedStatus = (decoded.status as RemotionStatus) || (data.status as RemotionStatus) || currentStatus;
    updatedSource = typeof decoded.remotion_source === 'string' ? decoded.remotion_source : updatedSource;
    updatedFilename = typeof decoded.filename === 'string' ? decoded.filename : updatedFilename;
    updatedS3BaseUrl = typeof decoded.s3_base_url === 'string' ? decoded.s3_base_url : updatedS3BaseUrl;
    updatedFiles = typeof decoded.files === 'object' && decoded.files !== null ? decoded.files as { original?: VideoFileVariant; thumbnail?: VideoFileVariant } : updatedFiles;
    updatedAesKey = typeof decoded.aes_key === 'string' ? decoded.aes_key : updatedAesKey;
    updatedAesNonce = typeof decoded.aes_nonce === 'string' ? decoded.aes_nonce : updatedAesNonce;
    updatedError = typeof decoded.error === 'string' ? decoded.error : updatedError;
  }

  function statusText(): string {
    if (currentStatus === 'rendering') return 'Rendering video...';
    if (currentStatus === 'processing') return 'Preparing Remotion source...';
    if (currentStatus === 'cancelled') return 'Render stopped';
    if (currentStatus === 'needs_rerender') return 'Needs rerender';
    if (currentStatus === 'error') return currentError || 'Render failed';
    return `${durationLabel} · ${resolutionLabel}`;
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="videos"
  skillId="create"
  skillIconName="videos"
  status={unifiedStatus}
  skillName="Video Create"
  {taskId}
  {isMobile}
  {onFullscreen}
  customStatusText={statusText()}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="preview-details" data-testid="video-create-preview">
      {#if currentStatus === 'finished' && (thumbnailUrl || videoUrl)}
        <div class="thumbnail-wrapper">
          {#if thumbnailUrl}
            <img src={thumbnailUrl} alt={currentManifest.meta.title} class="thumbnail" />
          {:else if videoUrl}
            <!-- Public example chats can expose a video URL without private thumbnail storage. -->
            <video src={videoUrl} class="thumbnail" muted playsinline preload="metadata" aria-label={currentManifest.meta.title}>
              <track kind="captions" src="data:text/vtt,WEBVTT" />
            </video>
          {/if}
          <div class="play-overlay"><span class="play-icon">&#9654;</span></div>
          <span class="duration-badge">{durationLabel}</span>
        </div>
      {:else if currentStatus === 'error'}
        <div class="error-area"><span class="error-icon">&#9888;</span><span class="error-text">{currentError || 'Render failed'}</span></div>
      {:else}
        <div class="timeline-wrapper">
          <div class="title-row"><span class="video-title">{currentFilename}</span><span class="meta-badge">{statusText()}</span></div>
          <VideoTimeline manifest={currentManifest} compact />
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .preview-details { width: 100%; height: 100%; display: flex; flex-direction: column; padding: 10px 12px 4px; box-sizing: border-box; overflow: hidden; }
  .thumbnail-wrapper { position: relative; flex: 1; border-radius: 6px; overflow: hidden; background: var(--color-grey-15, #eee); }
  .thumbnail { width: 100%; height: 100%; object-fit: cover; }
  .play-overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(0, 0, 0, 0.25); opacity: 0; transition: opacity 0.15s; }
  .thumbnail-wrapper:hover .play-overlay { opacity: 1; }
  .play-icon { font-size: 32px; color: white; filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.4)); }
  .duration-badge { position: absolute; bottom: 6px; right: 6px; padding: 2px 6px; border-radius: 4px; background: rgba(0, 0, 0, 0.7); color: white; font-size: 10px; font-weight: 500; font-variant-numeric: tabular-nums; }
  .timeline-wrapper { flex: 1; display: flex; flex-direction: column; gap: 4px; }
  .title-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .video-title { font-size: 12px; font-weight: 500; color: var(--color-font-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .meta-badge { font-size: 10px; color: var(--color-font-tertiary, #888); flex-shrink: 0; font-variant-numeric: tabular-nums; }
  .error-area { flex: 1; display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--color-font-tertiary, #888); font-size: 13px; }
  .error-icon { font-size: 18px; color: var(--color-error, #e74c3c); }
  .error-text { color: var(--color-font-secondary, #555); }
</style>
