<!--
  frontend/packages/ui/src/components/embeds/models3d/Model3DGenerateEmbedFullscreen.svelte

  Fullscreen metadata and poster view for a generated 3D model. The model GLB
  remains encrypted and is only fetched by the dedicated interactive renderer.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { fetchAndDecryptImage } from '../images/imageEmbedCrypto';
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
  const prompt = $derived(typeof content.prompt === 'string' ? content.prompt : 'Generated 3D model');
  const providerModel = $derived(typeof content.provider_model === 'string' ? content.provider_model : '');
  const s3BaseUrl = $derived(typeof content.s3_base_url === 'string' ? content.s3_base_url : '');
  const aesKey = $derived(typeof content.aes_key === 'string' ? content.aes_key : '');
  const poster = $derived(
    typeof content.files === 'object' && content.files !== null
      ? (content.files as { poster?: PosterFile }).poster
      : undefined,
  );
  let posterUrl = $state<string>();
  let posterError = $state<string>();

  $effect(() => {
    if (posterUrl || !poster?.s3_key || !poster.aes_nonce || !aesKey) return;
    void loadPoster(poster);
  });

  onDestroy(() => posterUrl && URL.revokeObjectURL(posterUrl));

  async function loadPoster(file: PosterFile) {
    try {
      const image = await fetchAndDecryptImage(s3BaseUrl, file.s3_key, aesKey, file.aes_nonce ?? '');
      posterUrl = URL.createObjectURL(image);
    } catch (caught) {
      posterError = caught instanceof Error ? caught.message : 'Failed to load model preview';
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
  {#snippet content()}
    <div class="model-fullscreen" data-testid="models3d-generate-fullscreen">
      {#if posterUrl}
        <img src={posterUrl} alt={prompt} />
      {:else if posterError}
        <p>{posterError}</p>
      {:else}
        <p>Loading model preview...</p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .model-fullscreen { display: grid; place-items: center; min-height: 320px; padding: 24px; }
  img { max-width: 100%; max-height: 70vh; border-radius: 16px; object-fit: contain; }
  p { color: var(--color-font-primary); }
</style>
