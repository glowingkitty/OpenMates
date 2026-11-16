<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesTemplateEmbedPreview.svelte

  Preview card of a slide template embed: the title sample slide rendered with the
  template's own theme, the template name, "Template · N layouts" and a Save / Saved
  action that sets the encrypted saved flag (the template library). Built on
  UnifiedEmbedPreview like the deck card.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import SlideCanvas from './SlideCanvas.svelte';
  import { parseSlidesMarkup } from './slidesMarkup';
  import { savedEmbedIds, loadEmbedSaved, toggleEmbedSaved } from '../../../services/savedEmbedService';

  interface Props {
    id: string;
    title?: string;
    slideCount?: number;
    aspect?: string;
    slidesMarkup?: string;
    status: 'processing' | 'finished' | 'error';
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    title: titleProp,
    slideCount: slideCountProp = 0,
    slidesMarkup: markupProp = '',
    status: statusProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  let localMarkup = $state('');
  let localTitle = $state<string | undefined>(undefined);
  let localCount = $state(0);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localTaskId = $state<string | undefined>(undefined);
  let storeResolved = $state(false);

  $effect(() => {
    void id;
    storeResolved = false;
  });

  $effect(() => {
    if (storeResolved) return;
    localMarkup = markupProp || '';
    localTitle = titleProp;
    localCount = slideCountProp || 0;
    localStatus = statusProp || 'processing';
    localTaskId = taskIdProp;
  });

  $effect(() => {
    if (id) void loadEmbedSaved(id);
  });

  let parsed = $derived(parseSlidesMarkup(localMarkup, { partial: localStatus === 'processing' }));
  let deck = $derived(parsed.ok ? parsed.deck : null);
  let firstSlide = $derived(deck?.slides[0]);
  let displayTitle = $derived(localTitle || deck?.title || $text('embeds.slides_template_default_title'));
  let count = $derived(localCount || deck?.slides.length || 0);
  let statusText = $derived(
    count > 0
      ? `${$text('embeds.slides_template_label')} · ${$text('embeds.slides_template_layouts_count').replace('{count}', String(count))}`
      : $text('embeds.slides_template_label')
  );
  let isSaved = $derived($savedEmbedIds.has(id));

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    const content = data.decodedContent;
    if (content) {
      if (typeof content.slides_markup === 'string') localMarkup = content.slides_markup;
      if (typeof content.title === 'string') localTitle = content.title;
      if (typeof content.slide_count === 'number') localCount = content.slide_count;
      if (typeof content.task_id === 'string') localTaskId = content.task_id;
    }
    if (data.status) localStatus = data.status as 'processing' | 'finished' | 'error';
    if (data.status !== 'processing') storeResolved = true;
  }

  async function handleStop() {
  }

  function handleToggleSaved(event: MouseEvent) {
    event.stopPropagation();
    void toggleEmbedSaved(id);
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="slides"
  skillId="template"
  skillIconName="slides"
  status={localStatus}
  skillName={displayTitle}
  taskId={localTaskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="template-details" data-testid="slides-template-card">
      {#if deck && firstSlide}
        <div class="first-slide" style:aspect-ratio="{deck.width} / {deck.height}" style:--deck-ratio={deck.width / deck.height}>
          <SlideCanvas motion={false} slide={firstSlide} width={deck.width} height={deck.height} template={deck.template} theme={deck.theme} />
        </div>
      {:else}
        <div class="template-empty" data-skill-icon="slides"></div>
      {/if}
      {#if localStatus === 'finished'}
        <button
          type="button"
          class="save-button"
          class:saved={isSaved}
          aria-pressed={isSaved}
          data-testid="slides-template-save"
          onclick={handleToggleSaved}
        >{$text(isSaved ? 'embeds.saved_item' : 'embeds.save_item')}</button>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .template-details {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    box-sizing: border-box;
    padding: var(--spacing-4);
    container-type: size;
    background: var(--color-grey-20);
    overflow: hidden;
  }

  /* Size containers have no height of their own: an intrinsic-height card (assistant
     results, e.g. the large carousel of EmbedPreviewLarge) would collapse to its header. */
  :global(.intrinsic-preview) .template-details {
    height: 280px;
  }

  .first-slide {
    width: min(100cqw, calc(100cqh * var(--deck-ratio)));
    border-radius: var(--radius-2);
    overflow: hidden;
  }

  .save-button {
    position: absolute;
    right: var(--spacing-3);
    bottom: var(--spacing-3);
    /* Undo the global button box (fixed 41px height, 112px min width, shadow). */
    width: auto;
    height: auto;
    min-width: 0;
    margin: 0;
    filter: none;
    padding: var(--spacing-1) var(--spacing-4);
    border: none;
    border-radius: var(--radius-8);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font-size: var(--font-size-xs);
    cursor: pointer;
  }

  .save-button.saved {
    background: var(--color-primary-start);
    color: var(--color-grey-0);
  }

  .template-empty {
    width: 48px;
    height: 48px;
    background: var(--color-grey-50);
    -webkit-mask-image: url('@openmates/ui/static/icons/slides.svg');
    mask-image: url('@openmates/ui/static/icons/slides.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
  }
</style>
