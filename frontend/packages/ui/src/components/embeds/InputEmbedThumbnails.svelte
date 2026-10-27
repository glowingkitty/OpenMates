<!-- Source images shared by skill cards; originals open through the normal image viewer. -->
<script lang="ts">
  import { getContext, onDestroy } from 'svelte';
  import { text } from '../../i18n/translations';
  import { proxyImage } from '../../utils/imageProxy';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../types/embedFullscreen';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import { chatSyncService } from '../../services/chatSyncService';
  import { fetchAndDecryptImage, getCachedImageUrl, createImageUrlOwner } from './images/imageEmbedCrypto';
  import { hasMediaEncryptionMetadata } from '../../services/encryption/mediaEncryption';

  let { inputEmbedIds }: { inputEmbedIds: string[] } = $props();
  const chatId = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT)?.chatId ?? null;
  let owner = createImageUrlOwner();
  let images = $state(new Map<string, { url: string; content: Record<string, unknown> }>());
  let generation = 0;
  let disposed = false;
  let retry = $state(0);
  const update = (event: Event) => {
    const id = (event as CustomEvent<{ embed_id?: string }>).detail?.embed_id;
    if (id && inputEmbedIds.includes(id)) retry += 1;
  };
  chatSyncService.addEventListener('embedUpdated', update);
  onDestroy(() => {
    disposed = true;
    generation += 1;
    owner.destroy();
    chatSyncService.removeEventListener('embedUpdated', update);
  });
  $effect(() => {
    const ids = [...new Set(inputEmbedIds)];
    void retry;
    const current = ++generation;
    images = new Map();
    owner.destroy();
    owner = createImageUrlOwner();
    void load(ids, current);
  });

  async function load(ids: string[], current: number) {
    for (const id of ids) {
      try {
        const embed = await resolveEmbed(id, { chatId });
        const content = embed?.content ? await decodeToonContent(embed.content) : null;
        if (!content || disposed || current !== generation) continue;
        let url = typeof content.previewImageUrl === 'string' ? proxyImage(content.previewImageUrl, 120) : undefined;
        const files = content.files as Record<string, { s3_key: string; aes_nonce?: string; encryption?: string }> | undefined;
        const preview = files?.preview ?? files?.original;
        if (!url && preview && typeof content.s3_base_url === 'string' && typeof content.aes_key === 'string'
            && hasMediaEncryptionMetadata(preview, content.aes_nonce as string | undefined)) {
          url = getCachedImageUrl(preview.s3_key);
          if (!url) {
            await fetchAndDecryptImage(content.s3_base_url, preview.s3_key, content.aes_key,
              (content.aes_nonce as string) ?? '', preview);
            url = getCachedImageUrl(preview.s3_key);
          }
          if (disposed || current !== generation) continue;
          owner.retain(preview.s3_key);
        }
        if (url) images = new Map(images).set(id, { url, content });
      } catch { /* A later encrypted embed update retries missing source images. */ }
    }
  }

  function open(event: MouseEvent, id: string) {
    event.preventDefault();
    event.stopPropagation();
    const image = images.get(id);
    if (!image) return;
    const content = image.content;
    document.dispatchEvent(new CustomEvent('imagefullscreen', { detail: {
      src: content.files ? undefined : image.url, embedId: id,
      filename: content.filename ?? '', s3Files: content.files, s3BaseUrl: content.s3_base_url ?? '',
      aesKey: content.aes_key ?? '', aesNonce: content.aes_nonce ?? '', isAuthenticated: true,
      fileSize: content.file_size, fileType: content.file_type, aiDetection: content.ai_detection ?? null,
    }, bubbles: true }));
  }
</script>

{#if inputEmbedIds.length}
  <div class="input-images" data-testid="skill-input-images">
    <span class="source-label">{$text('embeds_input.image_used')}</span>
    <div class="thumbnails">
      {#each [...new Set(inputEmbedIds)] as id (id)}
        {@const image = images.get(id)}
        <button type="button" class="thumbnail" disabled={!image}
          aria-label={$text('embeds_input.open_image')} data-embed-id={id}
          onclick={(event) => open(event, id)} onkeydown={(event) => event.stopPropagation()}
          onpointerdown={(event) => event.stopPropagation()}>
          {#if image}<img src={image.url} alt="" />{:else}<span class="placeholder"></span>{/if}
        </button>
      {/each}
    </div>
  </div>
{/if}

<style>
  .input-images { display: flex; align-items: center; gap: 8px; min-width: 0; flex-shrink: 0; padding: 4px 8px; box-sizing: border-box; }
  .source-label { font-size: 11px; color: var(--color-font-secondary); flex-shrink: 0; }
  .thumbnails { display: flex; gap: 5px; min-width: 0; overflow-x: auto; }
  /* Finished preview layouts disable descendant hit testing by default. Source
     buttons are independent actions and must opt back in, including on hover. */
  .thumbnail { pointer-events: auto; width: 34px; height: 30px; flex: 0 0 34px; padding: 0; border: 1px solid var(--color-grey-30); border-radius: 6px; overflow: hidden; background: var(--color-grey-20); cursor: pointer; }
  .thumbnail:disabled { cursor: default; }
  .thumbnail:focus-visible { outline: 2px solid var(--color-font-primary); outline-offset: 1px; }
  img, .placeholder { display: block; width: 100%; height: 100%; object-fit: cover; }
</style>
