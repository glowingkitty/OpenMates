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
    /** Animated SVG images play; false (cards, thumbnails) always shows the still picture. */
    motion: boolean;
    /** Already resolved URLs (component previews); skips the embed pipeline. */
    resolved?: { url: string; animatedUrl?: string };
  }

  let { embedRef, alt, fit, motion, resolved }: Props = $props();

  const chatId = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT)?.chatId ?? null;
  const owner = createImageUrlOwner();
  let url = $state<string | null>(null);
  let animatedUrl = $state<string | null>(null);

  $effect(() => {
    const ref = embedRef;
    if (resolved) {
      url = resolved.url;
      animatedUrl = resolved.animatedUrl ?? null;
      return;
    }
    let cancelled = false;
    url = null;
    animatedUrl = null;
    resolveSlideImage(ref, chatId)
      .then((result) => {
        if (cancelled || !result) return;
        owner.retain(result.cacheKey);
        if (result.animatedUrl && result.animatedCacheKey) owner.retain(result.animatedCacheKey);
        url = result.url;
        animatedUrl = result.animatedUrl ?? null;
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

{#if url && animatedUrl && motion}
  <picture>
    <source srcset={url} media="(prefers-reduced-motion: reduce)" />
    <img class="slide-image" data-testid="slide-image-animated" src={animatedUrl} {alt} style:object-fit={fit} draggable="false" />
  </picture>
{:else if url}
  <img class="slide-image" src={url} {alt} style:object-fit={fit} draggable="false" />
{:else}
  <div class="slide-image-placeholder" role="img" aria-label={alt}></div>
{/if}

<style>
  picture {
    display: block;
    width: 100%;
    height: 100%;
  }
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
