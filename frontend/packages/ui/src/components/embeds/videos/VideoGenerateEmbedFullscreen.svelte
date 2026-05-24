<!--
  frontend/packages/ui/src/components/embeds/videos/VideoGenerateEmbedFullscreen.svelte

  Fullscreen player for generated video embeds. Uses the same encrypted S3
  client-side decryption path as generated media previews.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { fetchAndDecryptAudio, releaseCachedAudio } from '../audio/audioEmbedCrypto';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface VideoFileVariant { s3_key: string; mime_type?: string; duration_seconds?: number; }
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
    data, embedId, onClose, hasPreviousEmbed = false,
    hasNextEmbed = false, onNavigatePrevious, onNavigateNext, navigateDirection = null,
    showChatButton = false, onShowChat,
  }: Props = $props();
  let dc = $derived(data.decodedContent);
  let prompt = $derived(typeof dc.prompt === 'string' ? dc.prompt : '');
  let model = $derived(typeof dc.model === 'string' ? dc.model : '');
  let resolution = $derived(typeof dc.resolution === 'string' ? dc.resolution : '');
  let s3BaseUrl = $derived(typeof dc.s3_base_url === 'string' ? dc.s3_base_url : '');
  let files = $derived((typeof dc.files === 'object' && dc.files !== null) ? dc.files as { original?: VideoFileVariant } : undefined);
  let aesKey = $derived(typeof dc.aes_key === 'string' ? dc.aes_key : '');
  let aesNonce = $derived(typeof dc.aes_nonce === 'string' ? dc.aes_nonce : '');
  let previewVideoUrl = $derived(typeof dc.previewVideoUrl === 'string' ? dc.previewVideoUrl : '');
  let videoUrl = $state<string | undefined>();
  let error = $state<string | undefined>();
  let retainedS3Key: string | undefined;

  $effect(() => {
    if (previewVideoUrl && videoUrl !== previewVideoUrl) {
      videoUrl = previewVideoUrl;
      return;
    }
    if (!videoUrl && files?.original?.s3_key && s3BaseUrl && aesKey && aesNonce) loadVideo();
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
</script>

<UnifiedEmbedFullscreen
  appId="videos"
  skillId="generate"
  skillIconName="videos"
  embedHeaderTitle={prompt || 'Generated video'}
  embedHeaderSubtitle={[model, resolution].filter(Boolean).join(' · ')}
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
    <div class="video-fullscreen" data-testid="video-generate-fullscreen">
    {#if videoUrl}
      <video src={videoUrl} controls playsinline autoplay data-testid="video-generate-fullscreen-video">
        <track kind="captions" src="data:text/vtt,WEBVTT" />
      </video>
    {:else if error}
      <p>{error}</p>
    {:else}
      <p>Loading video...</p>
    {/if}
    <dl>
      {#if prompt}<dt>Prompt</dt><dd>{prompt}</dd>{/if}
      {#if model}<dt>Model</dt><dd>{model}</dd>{/if}
      {#if resolution}<dt>Resolution</dt><dd>{resolution}</dd>{/if}
    </dl>
  </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .video-fullscreen { display: grid; gap: 16px; padding: 24px; }
  video { width: 100%; max-height: 70vh; border-radius: 16px; background: var(--color-grey-100); }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 8px 12px; color: var(--color-font-primary); }
  dt { font-weight: 700; }
  dd { margin: 0; }
</style>
