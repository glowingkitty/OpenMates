<!--
  frontend/packages/ui/src/components/embeds/models3d/Model3DGenerateEmbedPreview.svelte

  Lightweight preview for a generated 3D model. The encrypted provider poster
  is decrypted client-side; the heavier GLB remains a fullscreen concern.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { fetchAndDecryptImage } from '../images/imageEmbedCrypto';

  interface ModelFile { s3_key: string; aes_nonce?: string; }
  interface Props {
    id: string;
    prompt?: string;
    providerModel?: string;
    s3BaseUrl?: string;
    files?: { poster?: ModelFile };
    aesKey?: string;
    status: 'processing' | 'finished' | 'error';
    error?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id, prompt = '', providerModel = '', s3BaseUrl = '', files, aesKey = '',
    status, error = '', taskId, isMobile = false, onFullscreen,
  }: Props = $props();
  let posterUrl = $state<string>();
  let posterError = $state<string>();
  const skillName = $text('app_skills.models3d.generate');

  $effect(() => {
    const poster = files?.poster;
    if (status !== 'finished' || posterUrl || !poster?.s3_key || !poster.aes_nonce || !aesKey) return;
    void loadPoster(poster);
  });

  onDestroy(() => posterUrl && URL.revokeObjectURL(posterUrl));

  async function loadPoster(poster: ModelFile) {
    try {
      const image = await fetchAndDecryptImage(s3BaseUrl, poster.s3_key, aesKey, poster.aes_nonce ?? '');
      posterUrl = URL.createObjectURL(image);
    } catch (caught) {
      posterError = caught instanceof Error ? caught.message : 'Failed to load model preview';
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="models3d"
  skillId="generate"
  skillIconName="3dmodels"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  customStatusText={status === 'error' ? error : providerModel}
>
  {#snippet details()}
    <div class="model-preview" data-testid="models3d-generate-preview">
      {#if posterUrl}
        <img src={posterUrl} alt={prompt || skillName} />
      {:else if posterError}
        <p>{posterError}</p>
      {:else}
        <p>{prompt || skillName}</p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .model-preview { display: grid; place-items: center; height: 100%; padding: 12px; }
  img { max-width: 100%; max-height: 100%; border-radius: 12px; object-fit: contain; }
  p { margin: 0; color: var(--color-font-primary); text-align: center; }
</style>
