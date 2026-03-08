<!--
  frontend/packages/ui/src/components/embeds/images/ImageResultEmbedPreviewLarge.svelte

  Large preview variant for Image Result embeds ([!](embed:ref) syntax).
  Shows the image covering the full card width with a gradient overlay at bottom
  displaying the source favicon, domain, and title.

  BasicInfosBar shows the source domain with favicon (no skill icon),
  matching the pattern from WebsiteEmbedPreview.

  Click dispatches embedfullscreen event to deep-link into fullscreen view.

  Uses UnifiedEmbedPreview directly (not EmbedReferencePreview) to have full control
  over the image display layout in the details snippet.

  Architecture: See docs/architecture/embeds.md for the large-preview pipeline.
-->

<script lang="ts">
  import UnifiedEmbedPreviewLarge from '../UnifiedEmbedPreviewLarge.svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { embedStore, embedRefIndexVersion } from '../../../services/embedStore';
  import { resolveEmbed, decodeToonContent } from '../../../services/embedResolver';
  import { proxyImage } from '../../../utils/imageProxy';
  import { handleImageError } from '../../../utils/offlineImageHandler';

  interface Props {
    /** Short embed reference slug (e.g. "macbook-air-k8D") */
    embedRef: string;
    /** Pre-resolved UUID embed ID — may be null when first created */
    embedId?: string | null;
  }

  let { embedRef, embedId = null }: Props = $props();

  // Resolved content fields
  let title = $state('');
  let sourceDomain = $state('');
  let imageUrl = $state<string | undefined>(undefined);
  let thumbnailUrl = $state<string | undefined>(undefined);
  let faviconUrl = $state<string | undefined>(undefined);
  let status = $state<'processing' | 'finished' | 'error'>('processing');
  let resolvedEmbedId = $state('');

  // Track ref index version changes to re-resolve
  let refVersion = $derived($embedRefIndexVersion);

  // Resolve embed data
  $effect(() => {
    void refVersion;
    const eid = embedId || embedStore.resolveByRef(embedRef) || null;
    if (eid) {
      resolvedEmbedId = eid;
      loadEmbedData(eid);
    }
  });

  async function loadEmbedData(eid: string) {
    try {
      const embedData = await resolveEmbed(eid);
      if (!embedData) return;

      status = (embedData.status as typeof status) || 'processing';

      if (embedData.content) {
        const decoded = await decodeToonContent(embedData.content);
        if (decoded) {
          title = (decoded.title as string) || '';
          sourceDomain = (decoded.source as string) || '';
          const rawImageUrl = (decoded.image_url as string) || '';
          const rawThumbnailUrl = (decoded.thumbnail_url as string) || '';
          const rawFaviconUrl = (decoded.favicon_url as string) || '';

          imageUrl = rawImageUrl ? proxyImage(rawImageUrl) : undefined;
          thumbnailUrl = rawThumbnailUrl ? proxyImage(rawThumbnailUrl) : undefined;
          faviconUrl = rawFaviconUrl ? proxyImage(rawFaviconUrl) : undefined;
        }
      }
    } catch (error) {
      console.error('[ImageResultEmbedPreviewLarge] Failed to load embed data:', error);
      status = 'error';
    }
  }

  let _skillName = $derived(sourceDomain || $text('embeds.image_search') || 'Image');

  /** Handle updates from UnifiedEmbedPreview (processing -> finished transitions) */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      status = data.status;
    }
    if (data.decodedContent) {
      const c = data.decodedContent;
      if (c.title) title = c.title as string;
      if (c.source) sourceDomain = c.source as string;
      if (c.image_url) imageUrl = proxyImage(c.image_url as string);
      if (c.thumbnail_url) thumbnailUrl = proxyImage(c.thumbnail_url as string);
      if (c.favicon_url) faviconUrl = proxyImage(c.favicon_url as string);
    }
  }

  /**
   * Dispatch embedfullscreen event to deep-link into fullscreen view.
   * This matches the pattern used by renderers and ChatMessage.svelte.
   * ActiveChat listens for this event and opens the corresponding fullscreen component.
   */
  function handleFullscreen() {
    const eid = resolvedEmbedId || embedRef;
    if (!eid) return;

    const event = new CustomEvent('embedfullscreen', {
      bubbles: true,
      cancelable: true,
      detail: {
        embedId: eid,
        embedType: 'app-skill-use',
        attrs: {
          embedRef,
          app_id: 'images',
          skill_id: 'image_result',
        },
        embedData: null,
        decodedContent: null,
      },
    });
    document.dispatchEvent(event);
  }

  let imageLoaded = $state(false);
</script>

<div class="image-result-large">
  <UnifiedEmbedPreviewLarge>
    <UnifiedEmbedPreview
      id={resolvedEmbedId || embedRef}
      appId="images"
      skillId="image_result"
      skillIconName="image"
      {status}
      skillName={sourceDomain || 'Image'}
      isMobile={false}
      showSkillIcon={false}
      faviconUrl={faviconUrl}
      showStatus={false}
      hasFullWidthImage={true}
      customHeight={350}
      onEmbedDataUpdated={handleEmbedDataUpdated}
      onFullscreen={handleFullscreen}
    >
      {#snippet details()}
        <div class="image-result-details">
          {#if (imageUrl || thumbnailUrl) && status === 'finished'}
            <img
              src={imageUrl || thumbnailUrl}
              alt={title || ''}
              class="result-image"
              class:loaded={imageLoaded}
              onload={() => { imageLoaded = true; }}
              use:handleImageError
            />
            <!-- Gradient overlay with source info -->
            {#if imageLoaded && (title || sourceDomain)}
              <div class="image-overlay">
                {#if sourceDomain || faviconUrl}
                  <div class="source-line">
                    {#if faviconUrl}
                      <img src={faviconUrl} alt="" class="favicon" use:handleImageError />
                    {/if}
                    {#if sourceDomain}
                      <span class="source-domain">{sourceDomain}</span>
                    {/if}
                  </div>
                {/if}
                {#if title}
                  <span class="result-title">{title}</span>
                {/if}
              </div>
            {/if}
          {:else if status === 'processing'}
            <div class="skeleton-image"></div>
          {:else}
            <div class="image-placeholder">
              <span class="placeholder-icon clickable-icon icon_image"></span>
            </div>
          {/if}
        </div>
      {/snippet}
    </UnifiedEmbedPreview>
  </UnifiedEmbedPreviewLarge>
</div>

<style>
  .image-result-large {
    width: 100%;
  }

  .image-result-details {
    width: 100%;
    height: 100%;
    position: relative;
    overflow: hidden;
    border-radius: 30px 30px 0 0;
  }

  .result-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    opacity: 0;
    transition: opacity 0.25s ease;
  }

  .result-image.loaded {
    opacity: 1;
  }

  /* Gradient overlay at the bottom for readability */
  .image-overlay {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 32px 20px 16px;
    background: linear-gradient(transparent, rgba(0, 0, 0, 0.6));
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .source-line {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .favicon {
    width: 14px;
    height: 14px;
    flex-shrink: 0;
    object-fit: contain;
    border-radius: 2px;
  }

  .source-domain {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.75);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .result-title {
    font-size: 14px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.95);
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
  }

  /* Skeleton loading state */
  .skeleton-image {
    width: 100%;
    height: 100%;
    background: var(--color-grey-15, #ebebeb);
    animation: pulse 1.5s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50%       { opacity: 1; }
  }

  /* Placeholder when no image */
  .image-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-grey-15, #ebebeb);
  }

  .placeholder-icon {
    width: 40px;
    height: 40px;
    background: var(--color-grey-40, #bbb) !important;
  }

  /* Dark mode */
  :global(.dark) .skeleton-image {
    background: var(--color-grey-85, #222);
  }

  :global(.dark) .image-placeholder {
    background: var(--color-grey-85, #222);
  }

  :global(.dark) .placeholder-icon {
    background: var(--color-grey-70, #555) !important;
  }
</style>
