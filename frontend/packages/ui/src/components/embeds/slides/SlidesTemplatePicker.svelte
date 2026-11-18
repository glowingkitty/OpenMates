<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesTemplatePicker.svelte

  Template picker of a slide deck fullscreen: the built-in designs and the saved
  library of the deck chat's account (personal or team), each with a preview of its
  title slide. A library template the deck follows whose saved theme changed since is
  badged "Updated". Apply hands the chosen option to `onApply`, which writes the next
  deck version; the apply button is disabled while the deck streams or is edited.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import SlideCanvas from './SlideCanvas.svelte';
  import { parseSlidesMarkup, type DeckTheme } from './slidesMarkup';
  import { buildTemplateOptions, isTemplateUpdated, type TemplateOption } from './slidesTemplatePicker';
  import { listSavedTemplates } from '../../../services/savedEmbedService';
  import { chatTeamOf } from '../../../services/rustCore/embeds/embedContentEdit';
  import { notificationStore } from '../../../stores/notificationStore';
  import { text } from '@repo/ui';

  interface Props {
    /** Template id the deck carries (`builtin:…` / `library:…`). */
    deckTemplate: string;
    deckTheme: DeckTheme | undefined;
    chatId?: string;
    teamId?: string | null;
    /** Streaming or being edited: applying is disabled. */
    disabled?: boolean;
    onApply: (option: TemplateOption) => Promise<void>;
    onClose: () => void;
  }

  let { deckTemplate, deckTheme, chatId, teamId, disabled = false, onApply, onClose }: Props = $props();

  let options = $state<TemplateOption[]>(buildTemplateOptions([]));
  let accountTeamId = $state<string | null>(null);
  let selectedId = $state<string | null>(null);
  let applying = $state(false);

  onMount(() => {
    void (async () => {
      try {
        accountTeamId = teamId ?? (await chatTeamOf(chatId));
        options = buildTemplateOptions(await listSavedTemplates(accountTeamId));
      } catch (error) {
        console.error('[SlidesTemplatePicker] Could not load the template library:', error);
        notificationStore.error($text('embeds.slides_template_apply_failed'));
      }
    })();
  });

  let builtin = $derived(options.filter((o) => o.source === 'builtin'));
  let library = $derived(options.filter((o) => o.source === 'library'));
  let selected = $derived(options.find((o) => o.id === selectedId) ?? null);

  function preview(option: TemplateOption) {
    const parsed = parseSlidesMarkup(option.markup);
    return parsed.ok && parsed.deck.slides[0] ? { deck: parsed.deck, slide: parsed.deck.slides[0] } : null;
  }

  async function apply() {
    if (!selected || disabled || applying) return;
    applying = true;
    try {
      await onApply(selected);
      onClose();
    } catch (error) {
      console.error('[SlidesTemplatePicker] Applying the template failed:', error);
      notificationStore.error($text('embeds.slides_template_apply_failed'));
    } finally {
      applying = false;
    }
  }
</script>

{#snippet group(heading: string, items: TemplateOption[])}
  <section class="group">
    <h3>{heading}</h3>
    <div class="options">
      {#each items as option (option.id)}
        {@const view = preview(option)}
        <button
          type="button"
          class="option"
          class:selected={option.id === selectedId}
          data-testid="slides-template-option"
          data-template-id={option.id}
          aria-pressed={option.id === selectedId}
          onclick={() => (selectedId = option.id)}
        >
          {#if view}
            <span class="thumb" style:aspect-ratio="{view.deck.width} / {view.deck.height}">
              <SlideCanvas motion={false} slide={view.slide} width={view.deck.width} height={view.deck.height} template={view.deck.template} theme={view.deck.theme} />
            </span>
          {/if}
          <span class="name">{option.name}</span>
          {#if isTemplateUpdated(deckTemplate, deckTheme, option)}
            <span class="badge" data-testid="slides-template-updated">{$text('embeds.slides_template_updated')}</span>
          {/if}
        </button>
      {/each}
    </div>
  </section>
{/snippet}

<div class="picker" role="dialog" aria-label={$text('embeds.slides_template_picker_title')} data-testid="slides-template-picker">
  <h2>{$text('embeds.slides_template_picker_title')}</h2>
  {@render group($text('embeds.slides_template_builtin'), builtin)}
  {#if library.length > 0}
    {@render group(accountTeamId ? $text('embeds.slides_template_library_team') : $text('embeds.slides_template_library_personal'), library)}
  {:else}
    <p class="empty">{$text('embeds.slides_template_library_empty')}</p>
  {/if}
  <div class="actions">
    <button
      type="button"
      class="apply"
      data-testid="slides-template-apply"
      disabled={!selected || disabled || applying}
      onclick={apply}
    >{$text('embeds.slides_template_apply')}</button>
  </div>
</div>

<style>
  .picker {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    width: 100%;
    box-sizing: border-box;
    padding: var(--spacing-8);
    border-radius: var(--radius-3);
    background: var(--color-grey-0);
    box-shadow: 0 0 0 1px var(--color-grey-30);
  }

  h2, h3 {
    margin: 0;
    color: var(--color-font-primary);
  }

  h3 {
    font-size: var(--font-size-small);
    color: var(--color-font-secondary);
  }

  .options {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: var(--spacing-4);
  }

  .option {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    /* Undo the global button box (fixed 41px height, 112px min width, shadow). */
    width: auto;
    height: auto;
    min-width: 0;
    min-height: 0;
    margin: 0;
    filter: none;
    padding: var(--spacing-2);
    border: 2px solid transparent;
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    text-align: left;
    cursor: pointer;
  }

  .option:hover {
    background: var(--color-grey-20);
  }

  .option.selected {
    border-color: var(--color-primary-start);
  }

  .thumb {
    display: block;
    width: 100%;
    overflow: hidden;
    border-radius: var(--radius-2);
    pointer-events: none;
  }

  .name {
    font-size: var(--font-size-small);
  }

  .badge {
    position: absolute;
    top: var(--spacing-3);
    right: var(--spacing-3);
    padding: 0 var(--spacing-3);
    border-radius: var(--radius-5);
    background: var(--color-button-primary);
    color: var(--color-grey-0);
    font-size: var(--font-size-xs);
  }

  .empty {
    margin: 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  .actions {
    display: flex;
    justify-content: flex-end;
  }

  .apply {
    height: auto;
    min-width: 0;
    min-height: 0;
    margin: 0;
    padding: var(--spacing-3) var(--spacing-8);
    border: 0;
    border-radius: var(--radius-5);
    background: var(--color-button-primary);
    color: var(--color-grey-0);
    font-size: var(--font-size-small);
    cursor: pointer;
  }

  .apply:disabled {
    opacity: 0.4;
    cursor: default;
  }
</style>
