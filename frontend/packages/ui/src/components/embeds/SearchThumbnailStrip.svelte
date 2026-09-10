<!--
  Shared bounded thumbnail strip for web, news, and image search previews.
  Prefers parent metadata; visible legacy parents resolve at most ten cached children.
  URLs are deduplicated by the caller and proxied at thumbnail resolution.
  Native lazy loading avoids fetching offscreen search result thumbnails.
  Architecture: docs/architecture/embeds.md
-->
<script lang="ts">
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../utils/imageProxy';
  import { handleImageError } from '../../utils/offlineImageHandler';
  import { resolveSearchPreviewImages } from '../../utils/searchPreviewImages';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  let { images, appId, childEmbedIds = [] }: {
    images: Array<{ url: string; title: string }>;
    appId: string;
    childEmbedIds?: string[];
  } = $props();
  let isVisible = $state(false);
  let fallbackImages = $state<Array<{ url: string; title: string }>>([]);
  let displayedImages = $derived(images.length > 0 ? images : fallbackImages);

  function observeVisibility(node: HTMLElement) {
    // Observe the details container: an empty strip must not reserve layout space.
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        isVisible = true;
        observer.disconnect();
      }
    });
    observer.observe(node.parentElement ?? node);
    return { destroy: () => observer.disconnect() };
  }

  $effect(() => {
    const controller = new AbortController();
    const ids = childEmbedIds;
    fallbackImages = [];
    if (isVisible && images.length === 0 && ids.length > 0) {
      void resolveSearchPreviewImages([], ids, async childId => {
        const child = await resolveEmbed(childId);
        return child?.content ? decodeToonContent(child.content) : null;
      }, controller.signal).then(resolved => {
        if (!controller.signal.aborted) fallbackImages = resolved;
      }).catch(error => {
        if (!controller.signal.aborted) console.warn('[SearchThumbnailStrip] Could not load legacy preview images:', error);
      });
    }
    return () => controller.abort();
  });
</script>

<div use:observeVisibility class="thumbnail-strip" class:empty={displayedImages.length === 0} data-testid={`${appId}-search-thumbnail-strip`}>
  {#each displayedImages as image (image.url)}
    <img src={proxyImage(image.url, MAX_WIDTH_PREVIEW_THUMBNAIL)} alt={image.title}
      data-testid={`${appId}-search-thumbnail`} loading="lazy" decoding="async"
      use:handleImageError />
  {/each}
</div>

<style>
  .thumbnail-strip {
    display: flex;
    gap: var(--spacing-1);
    width: 100%;
    height: 30px;
    flex-shrink: 0;
    overflow: hidden;
  }
  .thumbnail-strip.empty { display: none; }
  img {
    height: 30px;
    width: 40px;
    flex-shrink: 0;
    object-fit: cover;
    display: block;
  }
</style>
