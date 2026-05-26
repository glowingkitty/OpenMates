<!--
  frontend/packages/ui/src/components/embeds/wiki/WikipediaEmbedPreview.svelte

  Preview card for Wikipedia article links shown as Study app embeds.
  Uses UnifiedEmbedPreview so wiki Daily Inspirations look and behave like
  other embed previews while still opening the existing Wikipedia fullscreen.
  Data is passed in directly from the inspiration payload; no client fetch.
  The article title lives in BasicInfosBar; the details area shows the longer
  description/excerpt so the card does not duplicate the Study icon/title.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';

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
    status = 'finished',
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let displayTitle = $derived(title || wikiTitle.replaceAll('_', ' '));
  let displayDescription = $derived(description || $text('embeds.wiki.source_label'));
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
  showSkillIcon={true}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="wiki-preview-details" class:mobile={isMobileLayout}>
      <p class="wiki-preview-description">{displayDescription}</p>
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

  .wiki-preview-description {
    max-width: 100%;
    margin: 0;
    font-size: var(--font-size-sm);
    font-weight: 600;
    line-height: 1.35;
    color: var(--color-grey-80);
    text-align: left;
    display: -webkit-box;
    -webkit-line-clamp: 5;
    line-clamp: 5;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .wiki-preview-details.mobile .wiki-preview-description {
    font-size: var(--font-size-xs);
    -webkit-line-clamp: 6;
    line-clamp: 6;
  }

  :global(.unified-embed-preview .skill-icon[data-skill-icon="study"]),
  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="study"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/study.svg');
    mask-image: url('@openmates/ui/static/icons/study.svg');
  }
</style>
