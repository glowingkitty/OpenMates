<!--
  frontend/packages/ui/src/components/embeds/wiki/WikipediaEmbedPreview.svelte

  Preview card for Wikipedia article links shown as Study app embeds.
  Uses UnifiedEmbedPreview so wiki Daily Inspirations look and behave like
  other embed previews while still opening the existing Wikipedia fullscreen.
  Data is passed in directly from the inspiration payload; no client fetch.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';

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

  let proxiedThumbnail = $derived(
    thumbnailUrl ? proxyImage(thumbnailUrl, MAX_WIDTH_PREVIEW_THUMBNAIL) : '',
  );
  let displayTitle = $derived(title || wikiTitle.replaceAll('_', ' '));
  let displayDescription = $derived(description || $text('embeds.wiki.source_label'));
</script>

<UnifiedEmbedPreview
  {id}
  appId="study"
  skillId="study"
  skillIconName="study"
  {status}
  skillName={$text('embeds.wiki.wikipedia')}
  {isMobile}
  {onFullscreen}
  showStatus={!!displayDescription}
  customStatusText={displayDescription}
  showSkillIcon={true}
  hasFullWidthImage={!!proxiedThumbnail}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="wiki-preview-details" class:mobile={isMobileLayout} class:has-image={!!proxiedThumbnail}>
      {#if proxiedThumbnail}
        <img
          class="wiki-preview-image"
          src={proxiedThumbnail}
          alt={displayTitle}
          loading="lazy"
          onerror={(e) => handleImageError(e.currentTarget)}
        />
      {:else}
        <div class="wiki-preview-fallback" aria-hidden="true">
          <span class="icon_rounded study"></span>
        </div>
        <div class="wiki-preview-title">{displayTitle}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .wiki-preview-details {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-3);
    height: 100%;
    min-height: 0;
  }

  .wiki-preview-details.has-image {
    gap: 0;
  }

  .wiki-preview-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .wiki-preview-fallback {
    width: 68px;
    height: 68px;
    display: flex;
    align-items: center;
    justify-content: center;
    filter: drop-shadow(0 8px 18px rgba(0, 0, 0, 0.18));
  }

  .wiki-preview-fallback :global(.icon_rounded) {
    width: 60px;
    height: 60px;
  }

  .wiki-preview-title {
    max-width: 100%;
    font-size: var(--font-size-sm);
    font-weight: 700;
    line-height: 1.25;
    color: var(--color-grey-100);
    text-align: center;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .wiki-preview-details.mobile .wiki-preview-title {
    font-size: var(--font-size-xs);
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }

  :global(.unified-embed-preview .skill-icon[data-skill-icon="study"]),
  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="study"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/study.svg');
    mask-image: url('@openmates/ui/static/icons/study.svg');
  }
</style>
