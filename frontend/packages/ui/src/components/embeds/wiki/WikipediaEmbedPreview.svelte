<!--
  frontend/packages/ui/src/components/embeds/wiki/WikipediaEmbedPreview.svelte

  Preview card for Wikipedia article links shown as Study app embeds.
  Uses UnifiedEmbedPreview so wiki Daily Inspirations look and behave like
  other embed previews while still opening the existing Wikipedia fullscreen.
  Data is passed in directly from the inspiration payload; no client fetch.
  The article title lives in BasicInfosBar; the details area shows the longer
  description/excerpt plus the article image so the card does not duplicate the
  Study skill icon/title.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import { MAX_WIDTH_PREVIEW_THUMBNAIL, proxyImage } from '../../../utils/imageProxy';

  interface Props {
    id: string;
    title: string;
    wikiTitle: string;
    description?: string | null;
    thumbnailUrl?: string | null;
    wikidataId?: string | null;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    title,
    wikiTitle,
    description = null,
    thumbnailUrl = null,
    status = 'finished',
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let displayTitle = $derived(title || wikiTitle.replaceAll('_', ' '));
  let displayDescription = $derived(description || $text('embeds.wiki.source_label'));
  let imageLoadError = $state(false);
  let imageUrl = $derived(
    thumbnailUrl && !imageLoadError ? proxyImage(thumbnailUrl, MAX_WIDTH_PREVIEW_THUMBNAIL) : null
  );
  let hasImage = $derived(!!imageUrl && status === 'finished');
</script>

<UnifiedEmbedPreview
  {id}
  appId="study"
  skillId="study"
  skillIconName="study"
  {status}
  skillName={displayTitle}
  {isMobile}
  {onFullscreen}
  showStatus={true}
  customStatusText={$text('embeds.wiki.wikipedia')}
  showSkillIcon={false}
  hasFullWidthImage={hasImage && !displayDescription && !isMobile}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="wiki-preview-details" class:mobile={isMobileLayout}>
      <div class="wiki-preview-content-row" class:no-description={!displayDescription}>
        {#if displayDescription}
          <p class="wiki-preview-description">{displayDescription}</p>
        {/if}

        {#if imageUrl && status === 'finished' && !isMobileLayout}
          <div class="wiki-preview-image" class:full-width={!displayDescription}>
            <img
              src={imageUrl}
              alt={displayTitle}
              loading="lazy"
              crossorigin="anonymous"
              onerror={(event) => {
                imageLoadError = true;
                handleImageError(event.currentTarget as HTMLImageElement);
              }}
            />
          </div>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .wiki-preview-details {
    display: flex;
    flex-direction: column;
    justify-content: center;
    height: 100%;
    width: 100%;
    min-height: 0;
  }

  .wiki-preview-content-row {
    display: flex;
    align-items: center;
    flex: 1;
    height: 100%;
    min-height: 0;
    width: 100%;
  }

  .wiki-preview-description {
    margin: 0;
    font-size: var(--font-size-sm);
    font-weight: 600;
    line-height: 1.35;
    color: var(--color-grey-80);
    text-align: left;
    flex: 0 1 42%;
    max-width: 42%;
    min-width: 0;
    display: -webkit-box;
    -webkit-line-clamp: 5;
    line-clamp: 5;
    -webkit-box-orient: vertical;
    overflow: hidden;
    overflow-wrap: break-word;
    text-overflow: ellipsis;
    align-self: center;
  }

  .wiki-preview-details.mobile .wiki-preview-description {
    font-size: var(--font-size-xs);
    flex: 1;
    max-width: 100%;
    -webkit-line-clamp: 6;
    line-clamp: 6;
  }

  .wiki-preview-image {
    flex: 1;
    min-width: 0;
    height: 171px;
    transform: translateX(20px);
  }

  .wiki-preview-image img {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .wiki-preview-content-row.no-description {
    width: 100%;
  }

  .wiki-preview-image.full-width {
    width: 100%;
    min-width: 100%;
    height: 100%;
    transform: none;
  }

  .wiki-preview-image.full-width img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
  }

  .wiki-preview-content-row:not(:has(.wiki-preview-image)) .wiki-preview-description {
    flex: 1;
    max-width: 100%;
  }
</style>
