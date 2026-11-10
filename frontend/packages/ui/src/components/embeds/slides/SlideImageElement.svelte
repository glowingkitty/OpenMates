<!--
  frontend/packages/ui/src/components/embeds/slides/SlideImageElement.svelte

  Image element of a slide. Resolves the `embed:` ref through the existing
  encrypted image pipeline (slideImage.ts); shows a neutral placeholder box
  while loading or when the embed is unavailable. Never loads other URLs.
-->
<script lang="ts">
  import { getContext, onDestroy } from 'svelte';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../../types/embedFullscreen';
  import { createImageUrlOwner } from '../images/imageEmbedCrypto';
  import { resolveSlideImage } from './slideImage';

  interface Props {
    embedRef: string;
    alt: string;
    fit: 'cover' | 'contain';
  }

  let { embedRef, alt, fit }: Props = $props();

  const chatId = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT)?.chatId ?? null;
  const owner = createImageUrlOwner();
  let url = $state<string | null>(null);

  $effect(() => {
    const ref = embedRef;
    let cancelled = false;
    url = null;
    resolveSlideImage(ref, chatId)
      .then((resolved) => {
        if (cancelled || !resolved) return;
        owner.retain(resolved.cacheKey);
        url = resolved.url;
      })
      .catch((error: unknown) => {
        console.warn('[SlideImageElement] image unavailable, showing placeholder:', ref, error);
      });
    return () => {
      cancelled = true;
    };
  });

  onDestroy(() => owner.destroy());
</script>

{#if url}
  <img class="slide-image" src={url} {alt} style:object-fit={fit} draggable="false" />
{:else}
  <div class="slide-image-placeholder" role="img" aria-label={alt}></div>
{/if}

<style>
  .slide-image,
  .slide-image-placeholder {
    display: block;
    width: 100%;
    height: 100%;
  }
  .slide-image-placeholder {
    background: var(--slide-color-surface);
    border: 2px dashed var(--slide-color-muted);
    box-sizing: border-box;
  }
</style>
