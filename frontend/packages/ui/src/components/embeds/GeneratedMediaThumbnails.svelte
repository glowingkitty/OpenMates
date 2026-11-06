<!--
  Thumbnails of the generated children owned by one generation invocation.

  Shown inside the app-skill parent card (GeneratedMediaGroupEmbedPreview) so the
  card displays the actual output instead of only a result count. Every image is
  shown complete (`contain`) on a theme surface: black in dark mode, white in
  light mode. The first child's prompt is reported to the parent card, because
  the parent manifest itself stores only child IDs.
-->
<script lang="ts">
  import { getContext, onDestroy } from 'svelte';
  import { proxyImage } from '../../utils/imageProxy';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../types/embedFullscreen';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import { chatSyncService } from '../../services/chatSyncService';
  import { fetchAndDecryptImage, getCachedImageUrl, createImageUrlOwner } from './images/imageEmbedCrypto';
  import { hasMediaEncryptionMetadata } from '../../services/encryption/mediaEncryption';

  /** Tiles shown in the card; the rest is summarized as "+N". */
  const MAX_TILES = 4;

  interface Props {
    childEmbedIds: string[];
    /** Called with the first available child prompt (undefined while unknown). */
    onPrompt?: (prompt: string | undefined) => void;
  }

  let { childEmbedIds, onPrompt }: Props = $props();
  const chatId = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT)?.chatId ?? null;
  let owner = createImageUrlOwner();
  let urls = $state(new Map<string, string>());
  let generation = 0;
  let disposed = false;
  let retry = $state(0);

  const visibleIds = $derived(childEmbedIds.slice(0, MAX_TILES));
  const hiddenCount = $derived(Math.max(0, childEmbedIds.length - MAX_TILES));

  const refresh = (event: Event) => {
    const id = (event as CustomEvent<{ embed_id?: string }>).detail?.embed_id;
    if (id && childEmbedIds.includes(id)) retry += 1;
  };
  chatSyncService.addEventListener('embedUpdated', refresh);
  onDestroy(() => {
    disposed = true;
    generation += 1;
    owner.destroy();
    chatSyncService.removeEventListener('embedUpdated', refresh);
  });

  $effect(() => {
    const ids = [...new Set(childEmbedIds)];
    void retry;
    const current = ++generation;
    owner.destroy();
    owner = createImageUrlOwner();
    void load(ids, current);
  });

  function publicUrl(content: Record<string, unknown>): string | undefined {
    for (const key of ['previewImageUrl', 'preview_image_url', 'posterUrl', 'poster_url']) {
      const value = content[key];
      if (typeof value === 'string' && value) return proxyImage(value, 400);
    }
    return undefined;
  }

  async function load(ids: string[], current: number) {
    const next = new Map<string, string>();
    let promptReported = false;
    for (const id of ids) {
      try {
        const embed = await resolveEmbed(id, { chatId });
        const content = embed?.content ? await decodeToonContent(embed.content) : null;
        if (!content || disposed || current !== generation) continue;
        if (!promptReported && typeof content.prompt === 'string' && content.prompt.trim()) {
          promptReported = true;
          onPrompt?.(content.prompt.trim());
        }
        let url = publicUrl(content);
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
        if (url) {
          next.set(id, url);
          urls = new Map(next);
        }
      } catch (error) {
        // A child that is still processing or not yet synced is retried on its
        // next `embedUpdated` event; the tile stays a placeholder meanwhile.
        console.debug('[GeneratedMediaThumbnails] Child thumbnail unavailable:', id, error);
      }
    }
  }
</script>

<div class="thumbnails" class:single={visibleIds.length === 1} data-testid="generated-media-thumbnails">
  {#each visibleIds as id (id)}
    {@const url = urls.get(id)}
    <div class="tile" data-testid="generated-media-thumbnail" data-embed-id={id}>
      {#if url}<img src={url} alt="" />{:else}<span class="placeholder"></span>{/if}
    </div>
  {/each}
  {#if hiddenCount > 0}<span class="more" data-testid="generated-media-thumbnails-more">+{hiddenCount}</span>{/if}
</div>

<style>
  .thumbnails { display: flex; align-items: stretch; gap: var(--spacing-3); flex: 1 1 0; min-height: 0; min-width: 0; }
  .tile { position: relative; flex: 1 1 0; min-width: 0; overflow: hidden; border-radius: var(--radius-3); background: var(--color-media-letterbox); border: 1px solid var(--color-grey-20); }
  /* Complete image on a theme surface: white in light mode, black in dark mode. */
  .tile img { position: absolute; inset: 0; display: block; width: 100%; height: 100%; object-fit: contain; }
  .placeholder { display: block; width: 100%; height: 100%; background: var(--color-grey-20); animation: pulse 1.5s ease-in-out infinite; }
  .more { align-self: center; flex: 0 0 auto; font-size: var(--font-size-sm); color: var(--color-font-secondary); }
  @keyframes pulse { 0%, 100% { opacity: 0.6; } 50% { opacity: 1; } }
</style>
