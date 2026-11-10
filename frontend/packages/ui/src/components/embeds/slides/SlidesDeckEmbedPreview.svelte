<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesDeckEmbedPreview.svelte

  Preview card of a slide deck embed: the first slide as a miniature, the deck
  title and "N slides". While the deck streams, the slides completed so far are
  shown. Built on UnifiedEmbedPreview like the document embed.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import SlideCanvas from './SlideCanvas.svelte';
  import { parseSlidesMarkup } from './slidesMarkup';

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

  let parsed = $derived(parseSlidesMarkup(localMarkup, { partial: localStatus === 'processing' }));
  let deck = $derived(parsed.ok ? parsed.deck : null);
  let firstSlide = $derived(deck?.slides[0]);
  let displayTitle = $derived(localTitle || deck?.title || $text('embeds.slides_deck_default_title'));
  let count = $derived(localCount || deck?.slides.length || 0);
  let statusText = $derived(
    count > 0 ? `${count} ${count === 1 ? $text('embeds.slides_count_singular') : $text('embeds.slides_count_plural')}` : ''
  );

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
    // A deck is produced inside the assistant message stream; there is no separate task to stop.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="slides"
  skillId="deck"
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
    <div class="deck-details" data-testid="slides-deck-preview">
      {#if deck && firstSlide}
        <div class="first-slide" style:aspect-ratio="{deck.width} / {deck.height}" style:--deck-ratio={deck.width / deck.height}>
          <SlideCanvas slide={firstSlide} width={deck.width} height={deck.height} template={deck.template} />
        </div>
      {:else}
        <div class="deck-empty" data-skill-icon="slides"></div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .deck-details {
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

  /* Largest slide that fits the card area at the deck aspect ratio. */
  .first-slide {
    width: min(100cqw, calc(100cqh * var(--deck-ratio)));
    border-radius: var(--radius-2);
    overflow: hidden;
  }

  .deck-empty {
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
