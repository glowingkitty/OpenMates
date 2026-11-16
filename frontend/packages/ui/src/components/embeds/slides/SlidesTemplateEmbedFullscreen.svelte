<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesTemplateEmbedFullscreen.svelte

  Fullscreen of a slide template embed: every sample slide in a responsive grid with
  its layout name. Header actions: Save / Saved (encrypted saved flag, the template
  library) and "Use this design", which sends `Use the design "<title>"` into the
  current chat so the assistant applies it.
-->
<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import SlideCanvas from './SlideCanvas.svelte';
  import { parseSlidesMarkup } from './slidesMarkup';
  import { layoutLabelKey, layoutTestName } from './slidesTemplateLayouts';
  import { sendChatMessage } from './slidesTemplateUse';
  import { savedEmbedIds, loadEmbedSaved, toggleEmbedSaved } from '../../../services/savedEmbedService';
  import { text } from '@repo/ui';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
    chatId?: string;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
    chatId
  }: Props = $props();

  let dc = $derived(data.decodedContent);
  let parsed = $derived(parseSlidesMarkup(typeof dc.slides_markup === 'string' ? dc.slides_markup : ''));
  let deck = $derived(parsed.ok ? parsed.deck : null);
  let slides = $derived(deck?.slides ?? []);
  let title = $derived(
    (typeof dc.title === 'string' && dc.title) || deck?.title || $text('embeds.slides_template_default_title')
  );
  let subtitle = $derived(
    `${$text('embeds.slides_template_label')} · ${$text('embeds.slides_template_layouts_count').replace('{count}', String(slides.length))}`
  );
  let saveTarget = $derived(embedId ?? '');
  let isSaved = $derived($savedEmbedIds.has(saveTarget));
  $effect(() => {
    if (saveTarget) void loadEmbedSaved(saveTarget);
  });

  function layoutName(layout: string | undefined): string {
    const key = layoutLabelKey(layout);
    return key ? $text(key) : (layout ?? '');
  }

  function useDesign() {
    sendChatMessage($text('embeds.slides_template_use_message').replace('{title}', title));
    onClose();
  }

  function toggleSaved() {
    if (saveTarget) void toggleEmbedSaved(saveTarget);
  }
</script>

<UnifiedEmbedFullscreen
  appId="slides"
  skillId="template"
  {onClose}
  currentEmbedId={embedId}
  owningChatId={chatId}
  skillIconName="slides"
  embedHeaderTitle={title}
  embedHeaderSubtitle={subtitle}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet embedHeaderCta()}
    <div class="header-actions">
      {#if saveTarget}
        <EmbedHeaderCtaButton
          label={$text(isSaved ? 'embeds.saved_item' : 'embeds.save_item')}
          variant="secondary"
          iconName="heart"
          pressed={isSaved}
          onclick={toggleSaved}
          testId="slides-template-save"
        />
      {/if}
      <EmbedHeaderCtaButton label={$text('embeds.slides_template_use')} onclick={useDesign} testId="slides-template-use" />
    </div>
  {/snippet}

  {#snippet content()}
    <div class="template-grid" data-testid="slides-template-fullscreen">
      {#if deck}
        {#each slides as slide (slide.id)}
          <figure class="sample" data-testid="slides-template-layout-{layoutTestName(slide.layout)}">
            <div class="sample-slide">
              <SlideCanvas motion={true} {slide} width={deck.width} height={deck.height} template={deck.template} theme={deck.theme} />
            </div>
            <figcaption>{layoutName(slide.layout)}</figcaption>
          </figure>
        {/each}
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .header-actions {
    display: flex;
    gap: var(--spacing-3);
    align-items: center;
  }

  .template-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr));
    gap: var(--spacing-8);
    padding: var(--spacing-8);
    box-sizing: border-box;
  }

  .sample {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
  }

  .sample-slide {
    border-radius: var(--radius-3);
    overflow: hidden;
    box-shadow: 0 1px 6px rgba(0, 0, 0, 0.18);
  }

  figcaption {
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
    text-align: center;
  }
</style>
