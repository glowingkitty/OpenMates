<!-- frontend/packages/ui/src/components/RecommendationsCard.svelte
     Recommendations container between the chat history and the follow-up suggestion
     chips. Keeps the colored chat-category gradient of the former quick tips card and
     shows one recommendation at a time: a heading naming the kind (memory/workflow)
     and whether it is new or an update, then the entry as an embed preview card (a
     click opens the same draft as the button), with the Create/Update button below it and previous/next buttons plus one dot per
     recommendation underneath. There is no dismiss control: the next completed turn
     replaces the set, and saving an entry removes it. Presentational only; the
     ChatRecommendations container owns persistence and drafts.
     Spec: app-memories.suggestions.post-processor
-->
<script lang="ts">
  import { text } from '../i18n/translations';
  import { getCategoryGradientColors } from '../utils/categoryUtils';
  import RecommendationEmbedPreview from './RecommendationEmbedPreview.svelte';
  import type { ChatRecommendation } from '../types/recommendations';

  interface Props {
    items: ChatRecommendation[];
    /** Chat category; selects the same gradient the quick tips card used. */
    category: string | null;
    /** Recommendation whose draft is being prepared (action disabled meanwhile). */
    busyId: string | null;
    /** Optional status line for the visible recommendation (e.g. "already up to date"). */
    statusText: string | null;
    onAction: (item: ChatRecommendation) => void;
  }
  let { items, category, busyId, statusText, onAction }: Props = $props();

  const HEADING_KEYS = {
    memory: { create: 'recommendations.heading_memory_create', update: 'recommendations.heading_memory_update' },
    workflow: { create: 'recommendations.heading_workflow_create', update: 'recommendations.heading_workflow_update' },
  } as const;

  let index = $state(0);
  // Keep the position valid when items are saved or replaced by a newer turn.
  let current = $derived(items.length > 0 ? Math.min(index, items.length - 1) : 0);
  let item = $derived(items[current] ?? null);
  let multiple = $derived(items.length > 1);
  let gradientStyle = $derived.by(() => {
    const colors = category ? getCategoryGradientColors(category) : null;
    return colors
      ? `background: linear-gradient(135deg, ${colors.start}, ${colors.end});`
      : 'background: var(--color-primary);';
  });

  function show(next: number): void {
    if (items.length === 0) return;
    index = (next + items.length) % items.length;
  }

  function open(target: ChatRecommendation): void {
    if (busyId !== null) return;
    onAction(target);
  }
</script>

{#if item}
  <section class="recommendations-card" data-testid="recommendations-card" data-count={items.length}
    data-index={current} aria-label={$text('recommendations.card_title')} style={gradientStyle}>
    <h3 class="heading" data-testid="recommendation-heading">{$text(HEADING_KEYS[item.kind][item.action])}</h3>

    <div class="recommendation" data-testid="recommendation-item" data-recommendation-id={item.id}
      data-kind={item.kind} data-action={item.action}>
      {#key item.id}
        <RecommendationEmbedPreview {item} onOpen={() => open(item)} />
      {/key}
      <button type="button" class="action" data-testid="recommendation-action" disabled={busyId !== null}
        onclick={() => open(item)}>
        {item.action === 'update' ? $text('recommendations.update') : $text('recommendations.create')}
      </button>
      {#if busyId === item.id}
        <p class="status" role="status" data-testid="recommendation-status">{$text('recommendations.preparing')}</p>
      {:else if statusText}
        <p class="status" role="status" data-testid="recommendation-status">{statusText}</p>
      {/if}
    </div>

    <div class="pager">
      {#if multiple}
        <button type="button" class="icon-button" data-testid="recommendation-previous"
          aria-label={$text('recommendations.previous')} onclick={() => show(current - 1)}>
          <span class="clickable-icon icon_back" aria-hidden="true"></span>
        </button>
      {/if}
      <div class="dots">
        {#each items as entry, position (entry.id)}
          <button type="button" class="dot" class:active={position === current} data-testid="recommendation-dot"
            aria-current={position === current ? 'true' : undefined}
            aria-label={$text('recommendations.position', { values: { current: position + 1, total: items.length } })}
            onclick={() => show(position)}></button>
        {/each}
      </div>
      {#if multiple}
        <button type="button" class="icon-button" data-testid="recommendation-next"
          aria-label={$text('recommendations.next')} onclick={() => show(current + 1)}>
          <span class="clickable-icon icon_back mirrored" aria-hidden="true"></span>
        </button>
      {/if}
    </div>
  </section>
{/if}

<style>
  /* Global button styles (buttons.css) add min-width, fixed height, drop shadow and
     margins; every button here resets them explicitly. */
  .recommendations-card {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-4);
    width: 100%;
    box-sizing: border-box;
    overflow: hidden;
    padding: var(--spacing-5) var(--spacing-4);
    border-radius: var(--radius-6);
    box-shadow: var(--shadow-lg);
    color: var(--color-font-button);
  }
  /* Same soft highlights as the former quick tips card. */
  .recommendations-card::before {
    content: '';
    position: absolute;
    inset: 0;
    background:
      radial-gradient(circle at 15% 20%, color-mix(in srgb, var(--color-font-button) 45%, transparent), transparent 24%),
      radial-gradient(circle at 86% 82%, color-mix(in srgb, var(--color-font-button) 22%, transparent), transparent 32%);
    pointer-events: none;
  }
  .recommendations-card > * { position: relative; }
  .heading {
    margin: 0;
    color: var(--color-font-button);
    font-size: var(--font-size-p);
    font-weight: 800;
    line-height: 1.2;
    text-align: center;
  }
  .recommendation { display: flex; flex-direction: column; align-items: center; gap: var(--spacing-4); max-width: 100%; }
  .action {
    min-width: 0;
    height: auto;
    min-height: 2.25rem;
    margin: 0;
    padding: var(--spacing-2) var(--spacing-6);
    border-radius: var(--radius-full);
    background-color: color-mix(in srgb, var(--color-font-button) 24%, transparent);
    color: var(--color-font-button);
    filter: none;
    font: inherit;
    font-size: var(--font-size-small);
    font-weight: 700;
  }
  .action:hover:not(:disabled) { background-color: color-mix(in srgb, var(--color-font-button) 45%, transparent); }
  .action:active:not(:disabled) { background-color: color-mix(in srgb, var(--color-font-button) 50%, transparent); filter: none; }
  .status { margin: 0; color: var(--color-font-button); font-size: var(--font-size-small); text-align: center; opacity: 0.9; }
  .pager { display: flex; align-items: center; gap: var(--spacing-3); }
  .icon-button {
    display: inline-grid;
    place-items: center;
    flex: none;
    width: 2.25rem;
    min-width: 2.25rem;
    height: 2.25rem;
    margin: 0;
    padding: 0;
    border-radius: var(--radius-full);
    background-color: color-mix(in srgb, var(--color-font-button) 24%, transparent);
    filter: none;
  }
  .icon-button:hover { background-color: color-mix(in srgb, var(--color-font-button) 45%, transparent); }
  .icon-button .clickable-icon { width: 1.1rem; height: 1.1rem; background: var(--color-font-button); }
  .mirrored { transform: scaleX(-1); }
  .dots { display: flex; align-items: center; gap: var(--spacing-2); }
  .dot {
    width: 0.5rem;
    min-width: 0.5rem;
    height: 0.5rem;
    margin: 0;
    padding: 0;
    border-radius: var(--radius-full);
    background-color: color-mix(in srgb, var(--color-font-button) 45%, transparent);
    filter: none;
  }
  .dot.active { background-color: var(--color-font-button); }
  .recommendations-card button:focus-visible { outline: 2px solid color-mix(in srgb, var(--color-font-button) 90%, transparent); outline-offset: 2px; }
</style>
