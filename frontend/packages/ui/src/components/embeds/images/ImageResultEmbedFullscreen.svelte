<!--
  frontend/packages/ui/src/components/embeds/images/ImageResultEmbedFullscreen.svelte

  Fullscreen view for a single image_result child embed.
  Shows the full-size proxied image, title, source domain, and a link to the source page.

  Used as a drill-down overlay from ImagesSearchEmbedFullscreen.
  External images are proxied here so standalone and gallery entry points use
  the same privacy-preserving transport.

  Architecture: See docs/architecture/embeds.md
-->

<script lang="ts">
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { text } from '@repo/ui';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import { resolveImageSourceDomain } from '../../../utils/embedSourceDomain';
  import { proxyImage, MAX_WIDTH_HEADER_IMAGE, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    /** Raw embed data containing decodedContent */
    data: EmbedFullscreenRawData;
    /** Child embed ID */
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    onClose: () => void;
  }

  let {
    data,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    onClose
  }: Props = $props();

  // Extract fields from data.decodedContent
  let dc = $derived(data.decodedContent);
  let title = $derived(typeof dc.title === 'string' ? dc.title : undefined);
  let sourceDomain = $derived(resolveImageSourceDomain(dc) || undefined);
  let sourcePageUrl = $derived(typeof dc.source_page_url === 'string' ? dc.source_page_url : undefined);
  let imageUrl = $derived(typeof dc.image_url === 'string' ? dc.image_url : undefined);
  let thumbnailUrl = $derived(typeof dc.thumbnail_url === 'string' ? dc.thumbnail_url : undefined);
  let displayImageUrl = $derived(proxyImage(imageUrl, MAX_WIDTH_HEADER_IMAGE));
  let displayThumbnailUrl = $derived(proxyImage(thumbnailUrl, MAX_WIDTH_PREVIEW_THUMBNAIL));
  let _faviconUrl = $derived(typeof dc.favicon_url === 'string' ? dc.favicon_url : undefined);

  let imageLoaded = $state(false);
  let imageFailed = $state(false);
  let thumbnailFailed = $state(false);
  let showThumbnail = $state(true); // show thumbnail as placeholder until full image loads


  function handleImageLoad() {
    imageLoaded = true;
    showThumbnail = false;
  }

  function handleImageFail() {
    imageFailed = true;
    showThumbnail = false;
  }

  let embedHeaderTitle    = $derived(title || $text('embeds.image_search'));
  let embedHeaderSubtitle = $derived(sourceDomain || '');
</script>

<ResultEmbedFullscreen
  result={{ title, source_domain: sourceDomain, source_page_url: sourcePageUrl, image_url: imageUrl }}
  mediaLayout="immersive"
  appId="images"
  skillId="image_result"
  {embedHeaderTitle}
  {embedHeaderSubtitle}
  skillIconName="image"
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet embedHeaderCta()}
    {#if sourcePageUrl}
      <EmbedHeaderCtaButton href={sourcePageUrl} label={$text('embeds.image_search.view_source')} testId="image-result-source" />
    {/if}
  {/snippet}
  {#snippet media()}
    <div class="result-fullscreen" >
      <!-- Image display section -->
      <div class="image-section">
        {#if displayImageUrl && !imageFailed}
          <!-- Progressive: thumbnail first, then full-size -->
          {#if showThumbnail && displayThumbnailUrl && !thumbnailFailed}
            <img
              src={displayThumbnailUrl}
              alt={title || ''}
              class="result-primary-media display-image blurred"
                onerror={() => { thumbnailFailed = true; }}
              use:handleImageError
            />
          {/if}
          <img
            src={displayImageUrl}
            alt={title || ''}
            class="result-primary-media display-image"
            data-testid="image-result-fullscreen-image"
            class:hidden={!imageLoaded}
            onload={handleImageLoad}
            onerror={handleImageFail}
            use:handleImageError
          />
        {:else if displayThumbnailUrl && !thumbnailFailed}
          <img
            src={displayThumbnailUrl}
            alt={title || ''}
            class="result-primary-media display-image"
            onerror={() => { thumbnailFailed = true; }}
            use:handleImageError
          />
        {:else}
          <div class="image-placeholder" data-testid="image-result-fullscreen-placeholder">
            <span class="placeholder-icon clickable-icon icon_image"></span>
          </div>
        {/if}
      </div>

    </div>
  {/snippet}
  {#snippet detailContent()}
      <!-- Metadata section -->
      <div class="meta-section">
        <!-- Title -->
        {#if title}
          <h2 class="result-title">{title}</h2>
        {/if}

        <!-- Open full image link -->
        {#if imageUrl}
          <a
            href={imageUrl}
            target="_blank"
            rel="noopener noreferrer"
            class="open-image-link"
          >
            <span class="clickable-icon icon_image open-icon"></span>
            <span>{$text('embeds.image_search.open_image')}</span>
          </a>
        {/if}
      </div>
  {/snippet}
</ResultEmbedFullscreen>

<style>
  .result-fullscreen {
    display: flex;
    flex-direction: column;
    width: 100%;
    min-height: 0;
    overflow-y: auto;
  }


  /* Image section — top by default; left column only for portrait images. */
  .image-section {
    flex: none;
    display: flex;
    box-sizing: border-box;
    align-items: center;
    justify-content: center;
    position: relative;
    padding: 0;
    width: 100%;
    max-height: none;
    min-width: 0;
    overflow: hidden;
    background: var(--color-grey-5, #fafafa);
  }


  .display-image {
    width: 100%;
    height: auto;
    max-width: 100%;
    max-height: none;
    object-fit: contain;
    border-radius: var(--radius-4);
    box-shadow: 0px 4px 16px rgba(0, 0, 0, 0.15);
    display: block;
  }


  .display-image.blurred {
    filter: blur(4px);
    position: absolute;
    inset: 24px;
  }

  .display-image.hidden {
    opacity: 0;
  }

  /* Image fallback placeholder */
  .image-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 200px;
    height: 200px;
    background: color-mix(in srgb, var(--color-grey-20) 27.272727%, var(--color-grey-25));
    border-radius: var(--radius-7);
  }

  .placeholder-icon {
    width: 48px;
    height: 48px;
    background: var(--color-grey-40, #bbb) !important;
  }

  /* Metadata section — below image by default; right column only for portrait images. */
  .meta-section {
    width: 100%;
    max-width: 760px;
    flex: none;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    padding: 0;
    overflow-y: auto;
    align-self: flex-start;
  }


  .result-title {
    font-family: 'Lexend Deca', sans-serif;
    font-size: var(--font-size-p);
    font-weight: 500;
    color: var(--color-grey-90, #1a1a1a);
    line-height: 1.4;
    margin: 0;
    word-break: break-word;
  }

  .open-image-link {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-3);
    font-size: var(--font-size-xs);
    font-weight: 500;
    color: var(--color-primary-50, #5b8dd9);
    text-decoration: none;
    padding: 6px 0;
  }

  .open-image-link:hover {
    text-decoration: underline;
  }

  .open-icon {
    width: 16px;
    height: 16px;
    background: var(--color-primary-50, #5b8dd9) !important;
    flex-shrink: 0;
  }

  /* Dark mode */
  :global([data-theme="dark"]) .image-section {
    background: var(--color-grey-0);
  }

  :global([data-theme="dark"]) .display-image {
    box-shadow: 0px 4px 16px rgba(0, 0, 0, 0.4);
  }

  :global([data-theme="dark"]) .image-placeholder {
    background: var(--color-grey-20);
  }

  :global([data-theme="dark"]) .placeholder-icon {
    background: var(--color-grey-70, #555) !important;
  }

  :global([data-theme="dark"]) .open-image-link {
    color: var(--color-primary-40, #7a9ed0);
  }

  :global([data-theme="dark"]) .open-icon {
    background: var(--color-primary-40, #7a9ed0) !important;
  }

  /* Responsive: narrow containers — stack vertically */
  @container fullscreen (max-width: 560px) {
    .result-fullscreen {
      flex-direction: column;
      height: auto;
      min-height: 0;
      overflow-y: auto;
    }

    .image-section {
      flex: none;
      width: 100%;
      max-height: none;
      padding: 0;
    }

    .display-image {
      max-height: none;
    }

    .meta-section {
      width: 100%;
      max-width: none;
      padding: 0 16px 16px 16px;
      align-self: stretch;
    }
  }
</style>
