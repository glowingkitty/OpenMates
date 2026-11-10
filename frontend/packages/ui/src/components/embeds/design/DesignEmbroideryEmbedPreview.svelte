<!--
  frontend/packages/ui/src/components/embeds/design/DesignEmbroideryEmbedPreview.svelte

  Card for one embroidery result: the stitch preview (decrypted client-side),
  the sewn size, the stitch count and a row of thread colours. While converting
  it uses the shared processing state; a failed conversion shows the reason in
  plain words and nothing else.
-->
<script lang="ts">
  import { onDestroy } from 'svelte';
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import EmbroideryThreadSwatches from './EmbroideryThreadSwatches.svelte';
  import { fetchAndDecryptImage, getCachedImageUrl, createImageUrlOwner } from '../images/imageEmbedCrypto';
  import { hasMediaEncryptionMetadata } from '../../../services/encryption/mediaEncryption';
  import {
    errorTranslationKey, formatCount, formatSize, readEmbroideryDesign,
  } from './embroideryDesign';

  interface Props {
    id: string;
    /** Decoded embed content (see embroideryDesign.ts for the fields). */
    content: Record<string, unknown>;
    status: 'processing' | 'finished' | 'error';
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }
  let { id, content, status: statusProp, taskId, isMobile = false, onFullscreen }: Props = $props();

  const imageOwner = createImageUrlOwner();
  let liveContent = $state<Record<string, unknown>>();
  let liveStatus = $state<'processing' | 'finished' | 'error'>();
  let decryptedUrl = $state<string>();
  let imageError = $state(false);
  const design = $derived(readEmbroideryDesign(liveContent ?? content, liveStatus ?? statusProp));
  const status = $derived(design.status);
  const skillName = $derived($text('app_skills.design.embroidery'));
  const title = $derived(design.title || skillName);
  const reason = $derived(status === 'error' ? $text(errorTranslationKey(design.errorCode)) : '');
  const imageUrl = $derived(design.previewImageUrl || decryptedUrl);
  const stitchesLabel = $derived(`${formatCount(design.stitchCount)} ${$text('embeds.design.embroidery.stitches_unit')}`);
  const numbersText = $derived([formatSize(design), design.stitchCount === null ? '' : stitchesLabel].filter(Boolean).join(' · '));

  $effect(() => {
    const file = design.files.preview;
    if (status !== 'finished' || design.previewImageUrl || decryptedUrl || !file || !design.aesKey) return;
    if (!hasMediaEncryptionMetadata(file, file.aes_nonce ?? design.aesNonce)) return;
    void loadPreview(file.s3_key, file);
  });

  onDestroy(imageOwner.destroy);

  async function loadPreview(s3Key: string, file: unknown) {
    try {
      const nonce = (file as { aes_nonce?: string }).aes_nonce ?? design.aesNonce;
      await fetchAndDecryptImage(design.s3BaseUrl, s3Key, design.aesKey, nonce, file);
      decryptedUrl = getCachedImageUrl(s3Key);
      imageOwner.retain(s3Key);
    } catch (caught) {
      console.warn('[DesignEmbroideryEmbedPreview] preview decrypt failed:', caught);
      imageError = true;
    }
  }

  function handleUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') liveStatus = data.status;
    if (data.decodedContent) liveContent = data.decodedContent;
  }
</script>

<UnifiedEmbedPreview
  resultPreview={true}
  {id}
  appId="design"
  skillId="embroidery"
  skillIconName="embroidery"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  showSkillIcon={true}
  hasFullWidthImage={status === 'finished' && !!imageUrl}
  customStatusText={status === 'processing' ? $text('embeds.design.embroidery.converting') : status === 'error' ? reason : undefined}
  onEmbedDataUpdated={handleUpdated}
>
  {#snippet details()}
    <div class="embroidery-preview" data-testid="design-embroidery-preview" data-status={status}>
      {#if status === 'finished'}
        <ResultEmbedCard {title} mediaFit="contain">
          {#snippet media()}
            {#if imageUrl}
              <img src={imageUrl} alt={title} class="stitch-preview" data-testid="design-embroidery-preview-image" />
            {:else if imageError}
              <p class="placeholder" role="status">{$text('embeds.design.embroidery.preview_unavailable')}</p>
            {:else}
              <div class="placeholder" aria-hidden="true"></div>
            {/if}
          {/snippet}
          {#snippet facts()}
            <span class="numbers" data-testid="design-embroidery-numbers">{numbersText}</span>
            <EmbroideryThreadSwatches threads={design.threads} />
          {/snippet}
        </ResultEmbedCard>
      {:else if status === 'processing'}
        <ResultEmbedCard {title} description={$text('embeds.design.embroidery.converting')} />
      {:else}
        <ResultEmbedCard {title} description={reason} />
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .embroidery-preview { width: 100%; height: 100%; box-sizing: border-box; }
  /* Pinned to the box (Safari cannot resolve height: 100% in a flex item) and never cropped. */
  .stitch-preview {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: var(--color-media-letterbox);
  }
  .placeholder { margin: 0; position: absolute; inset: 0; display: grid; place-items: center; text-align: center; font-size: var(--font-size-xxs); color: var(--color-font-secondary); background: var(--color-media-letterbox); }
  .numbers { font-size: var(--font-size-xxs); color: var(--color-font-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
