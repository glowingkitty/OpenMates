<!--
  frontend/packages/ui/src/components/embeds/videos/VideoGenerateEmbedPreview.svelte

  Preview for videos.generate embeds. Generated videos are encrypted in S3 and
  decrypted client-side before playback, matching generated image/audio embeds.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { fetchAndDecryptAudio, releaseCachedAudio } from '../audio/audioEmbedCrypto';

  interface VideoFileVariant {
    s3_key: string;
    size_bytes?: number;
    format?: string;
    mime_type?: string;
    duration_seconds?: number;
  }

  interface Props {
    id: string;
    prompt?: string;
    model?: string;
    durationSeconds?: number;
    resolution?: string;
    s3BaseUrl?: string;
    files?: { original?: VideoFileVariant };
    aesKey?: string;
    aesNonce?: string;
    status: 'processing' | 'finished' | 'error';
    error?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id, prompt = '', model = '', durationSeconds, resolution = '', s3BaseUrl = '', files,
    aesKey = '', aesNonce = '', status, error = '', taskId, isMobile = false, onFullscreen,
  }: Props = $props();

  let videoUrl = $state<string | undefined>();
  let videoError = $state<string | undefined>();
  let retainedS3Key: string | undefined;
  const skillName = $text('app_skills.videos.generate');

  let updatedStatus = $state<'processing' | 'finished' | 'error' | undefined>();
  let updatedPrompt = $state<string | undefined>();
  let updatedModel = $state<string | undefined>();
  let updatedDurationSeconds = $state<number | undefined>();
  let updatedResolution = $state<string | undefined>();
  let updatedS3BaseUrl = $state<string | undefined>();
  let updatedFiles = $state<{ original?: VideoFileVariant } | undefined>();
  let updatedAesKey = $state<string | undefined>();
  let updatedAesNonce = $state<string | undefined>();
  let updatedError = $state<string | undefined>();

  const currentStatus = $derived(updatedStatus ?? status);
  const currentPrompt = $derived(updatedPrompt ?? prompt);
  const currentModel = $derived(updatedModel ?? model);
  const currentDurationSeconds = $derived(updatedDurationSeconds ?? durationSeconds);
  const currentResolution = $derived(updatedResolution ?? resolution);
  const currentS3BaseUrl = $derived(updatedS3BaseUrl ?? s3BaseUrl);
  const currentFiles = $derived(updatedFiles ?? files);
  const currentAesKey = $derived(updatedAesKey ?? aesKey);
  const currentAesNonce = $derived(updatedAesNonce ?? aesNonce);
  const currentError = $derived(updatedError ?? error);

  $effect(() => {
    if (currentStatus === 'finished' && !videoUrl && currentFiles?.original?.s3_key && currentS3BaseUrl && currentAesKey && currentAesNonce) {
      loadVideo();
    }
  });

  onDestroy(() => {
    if (retainedS3Key) releaseCachedAudio(retainedS3Key);
  });

  async function loadVideo() {
    const file = currentFiles?.original;
    if (!file?.s3_key) return;
    try {
      videoError = undefined;
      videoUrl = await fetchAndDecryptAudio(currentS3BaseUrl, file.s3_key, currentAesKey, currentAesNonce, file.mime_type || 'video/mp4');
      retainedS3Key = file.s3_key;
    } catch (err) {
      videoError = err instanceof Error ? err.message : 'Failed to load video';
    }
  }

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    const decoded = data.decodedContent;
    updatedStatus = (decoded.status as 'processing' | 'finished' | 'error') || (data.status as 'processing' | 'finished' | 'error') || currentStatus;
    updatedPrompt = typeof decoded.prompt === 'string' ? decoded.prompt : updatedPrompt;
    updatedModel = typeof decoded.model === 'string' ? decoded.model : updatedModel;
    updatedDurationSeconds = typeof decoded.duration_seconds === 'number' ? decoded.duration_seconds : updatedDurationSeconds;
    updatedResolution = typeof decoded.resolution === 'string' ? decoded.resolution : updatedResolution;
    updatedS3BaseUrl = typeof decoded.s3_base_url === 'string' ? decoded.s3_base_url : updatedS3BaseUrl;
    updatedFiles = typeof decoded.files === 'object' && decoded.files !== null ? decoded.files as { original?: VideoFileVariant } : updatedFiles;
    updatedAesKey = typeof decoded.aes_key === 'string' ? decoded.aes_key : updatedAesKey;
    updatedAesNonce = typeof decoded.aes_nonce === 'string' ? decoded.aes_nonce : updatedAesNonce;
    updatedError = typeof decoded.error === 'string' ? decoded.error : updatedError;
  }

  function statusText(): string {
    if (currentStatus === 'processing') return 'Generating video';
    if (currentStatus === 'error') return currentError || 'Video generation failed';
    return [currentModel || 'Veo', currentResolution, currentDurationSeconds ? `${currentDurationSeconds}s` : ''].filter(Boolean).join(' · ');
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="videos"
  skillId="generate"
  skillIconName="videos"
  status={currentStatus}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  customStatusText={statusText()}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="video-generate-preview" data-testid="video-generate-preview">
      {#if currentStatus === 'finished' && videoUrl}
        <video src={videoUrl} controls playsinline preload="metadata" data-testid="video-generate-video">
          <track kind="captions" src="data:text/vtt,WEBVTT" />
        </video>
      {:else if videoError}
        <div class="error">{videoError}</div>
      {:else}
        <div class="placeholder">{currentPrompt || 'Generating video...'}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .video-generate-preview { height: 100%; display: flex; align-items: center; justify-content: center; padding: 12px; }
  video { width: 100%; max-height: 100%; border-radius: 12px; background: var(--color-grey-100); }
  .placeholder, .error { color: var(--color-font-primary); font-size: 14px; text-align: center; }
  .error { color: var(--color-error, #b00020); }
</style>
