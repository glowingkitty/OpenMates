<!--
  frontend/packages/ui/src/components/embeds/models3d/Model3DGenerateEmbedFullscreen.svelte

  Fullscreen poster and model download for a generated 3D asset.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import { text } from '@repo/ui';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { getApiEndpoint } from '../../../config/api';
  import { fetchAndDecryptImage, getCachedImageUrl, createImageUrlOwner } from '../images/imageEmbedCrypto';
  const imageOwner = createImageUrlOwner();
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface PosterFile { s3_key: string; aes_nonce?: string; }
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
    onNavigatePrevious, onNavigateNext, navigateDirection = null,
    showChatButton = false, onShowChat,
  }: Props = $props();
  const content = $derived(data.decodedContent);
  const skillName = $derived($text('app_skills.models3d.generate'));
  const prompt = $derived(typeof content.prompt === 'string' ? content.prompt : skillName);
  const providerModel = $derived(
    typeof content.provider_model === 'string' ? content.provider_model
      : typeof content.model === 'string' ? content.model : '',
  );
  const posterUrl = $derived(
    typeof content.poster_url === 'string'
      ? content.poster_url
      : typeof content.posterUrl === 'string'
        ? content.posterUrl
        : '',
  );
  const publicModelUrl = $derived(
    typeof content.modelUrl === 'string' ? content.modelUrl
      : typeof content.model_url === 'string' ? content.model_url : '',
  );
  const hasPrivateModel = $derived(
    !!embedId && typeof content.files === 'object' && content.files !== null
      && typeof (content.files as { master?: { s3_key?: string } }).master?.s3_key === 'string',
  );
  const s3BaseUrl = $derived(typeof content.s3_base_url === 'string' ? content.s3_base_url : '');
  const aesKey = $derived(typeof content.aes_key === 'string' ? content.aes_key : '');
  const poster = $derived(
    typeof content.files === 'object' && content.files !== null
      ? (content.files as { poster?: PosterFile }).poster
      : undefined,
  );
  let decryptedPosterUrl = $state<string>();
  let posterError = $state<string>();
  let downloadError = $state(false);
  let downloading = $state(false);

  $effect(() => {
    if (posterUrl || decryptedPosterUrl || !poster?.s3_key || !poster.aes_nonce || !aesKey) return;
    void loadPoster(poster);
  });

  onDestroy(imageOwner.destroy);

  async function loadPoster(file: PosterFile) {
    try {
      await fetchAndDecryptImage(s3BaseUrl, file.s3_key, aesKey, file.aes_nonce ?? '');
      decryptedPosterUrl = getCachedImageUrl(file.s3_key) ?? '';
      imageOwner.retain(file.s3_key);
    } catch (caught) {
      posterError = caught instanceof Error ? caught.message : 'Failed to load model preview';
    }
  }

  async function downloadModel() {
    if (!embedId || downloading) return;
    downloading = true;
    downloadError = false;
    try {
      const response = await fetch(
        getApiEndpoint(`/v1/generated-assets/${encodeURIComponent(embedId)}/files/master/download-url`),
        { credentials: 'include' },
      );
      if (!response.ok) throw new Error(`Model download unavailable (${response.status})`);
      const result = await response.json() as { download_url?: string };
      if (!result.download_url) throw new Error('Model download URL missing');
      const link = document.createElement('a');
      link.href = result.download_url;
      link.rel = 'noopener noreferrer';
      link.download = 'openmates-generated-model.glb';
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch {
      downloadError = true;
    } finally {
      downloading = false;
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="models3d"
  skillId="generate"
  skillIconName="3dmodels"
  embedHeaderTitle={prompt}
  embedHeaderSubtitle={providerModel}
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
  {#snippet embedHeaderCta()}
    {#if publicModelUrl}
      <EmbedHeaderCtaButton label={`${$text('common.download')} GLB`} href={publicModelUrl} testId="models3d-download-model" />
    {:else if hasPrivateModel}
      <EmbedHeaderCtaButton
        label={`${$text('common.download')} GLB`}
        onclick={downloadModel}
        variant={downloading ? 'loading' : 'primary'}
        testId="models3d-download-model"
      />
    {/if}
  {/snippet}
  {#snippet content()}
    <div class="model-fullscreen" data-testid="models3d-generate-fullscreen">
      {#if posterUrl || decryptedPosterUrl}
        <img src={posterUrl || decryptedPosterUrl} alt={prompt} />
      {:else if posterError}
        <p>{posterError}</p>
      {:else}
        <p>{skillName}</p>
      {/if}
      <div class="model-details">
        <p class="model-prompt">{prompt}</p>
        {#if providerModel}<p class="model-model">{providerModel}</p>{/if}
        {#if downloadError}<p role="alert">{$text('embeds.action_failed')}</p>{/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .model-fullscreen { display: grid; place-items: center; min-height: 320px; padding: 24px; gap: 20px; }
  img { max-width: 100%; max-height: 70vh; border-radius: 16px; object-fit: contain; }
  p { color: var(--color-font-primary); }
  .model-details { width: min(100%, 720px); }
  .model-prompt { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0 0 10px; }
  .model-model { opacity: .75; margin: 0; }
</style>
