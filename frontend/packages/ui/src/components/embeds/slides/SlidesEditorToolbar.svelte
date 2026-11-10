<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesEditorToolbar.svelte

  Toolbar of the slides editor: undo/redo, Add text, Delete, and for a selected
  text element its font size, colour (template swatches plus a custom colour),
  bold and alignment, and the paint order of the selected element (forward or
  backward one step). It only reports intents; SlidesEditor turns them into
  typed core operations (`set_text_style`, `add_element`, ...). Wraps on narrow
  screens so nothing leaves the viewport.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import type { DeckTextStyle } from '../../../services/rustCore/deckDocument/deckDocumentTypes';
  import type { SlideTemplate } from './slidesTemplates';
  import type { EffectiveTextStyle } from './slidesEditorView';

  interface Props {
    canUndo: boolean;
    canRedo: boolean;
    hasSelection: boolean;
    /** The selected element can move one step to the front / to the back. */
    canForward: boolean;
    canBackward: boolean;
    /** Style of the selected text element; null when no text element is selected. */
    textStyle: EffectiveTextStyle | null;
    /** Colour attribute as stored (token or #hex), for the active swatch. */
    colorValue: string | null;
    template: SlideTemplate;
    onUndo: () => void;
    onRedo: () => void;
    onAddText: () => void;
    onDelete: () => void;
    onForward: () => void;
    onBackward: () => void;
    onStyle: (style: DeckTextStyle) => void;
  }

  let {
    canUndo,
    canRedo,
    hasSelection,
    canForward,
    canBackward,
    textStyle,
    colorValue,
    template,
    onUndo,
    onRedo,
    onAddText,
    onDelete,
    onForward,
    onBackward,
    onStyle
  }: Props = $props();

  const SWATCHES = ['foreground', 'accent', 'accent-2', 'muted', 'surface', 'background'] as const;
  const SWATCH_LABEL_KEYS: Record<(typeof SWATCHES)[number], string> = {
    foreground: 'embeds.slides_editor_color_foreground',
    accent: 'embeds.slides_editor_color_accent',
    'accent-2': 'embeds.slides_editor_color_accent_2',
    muted: 'embeds.slides_editor_color_muted',
    surface: 'embeds.slides_editor_color_surface',
    background: 'embeds.slides_editor_color_background'
  };
  const ALIGNS = ['left', 'center', 'right', 'justify'] as const;
  const ALIGN_LABEL_KEYS: Record<(typeof ALIGNS)[number], string> = {
    left: 'embeds.slides_editor_align_left',
    center: 'embeds.slides_editor_align_center',
    right: 'embeds.slides_editor_align_right',
    justify: 'embeds.slides_editor_align_justify'
  };
  const MIN_SIZE = 8;
  const MAX_SIZE = 400;
  const SIZE_STEP = 4;

  let sizeDraft = $state('');
  $effect(() => {
    sizeDraft = textStyle ? String(textStyle.size) : '';
  });

  let bold = $derived(textStyle ? textStyle.weight === 'bold' || Number(textStyle.weight) >= 600 : false);
  let customColor = $derived(colorValue && colorValue.startsWith('#') && colorValue.length === 7 ? colorValue : '#000000');

  function commitSize(value: number) {
    if (!textStyle || !Number.isFinite(value)) return;
    const size = Math.round(Math.max(MIN_SIZE, Math.min(MAX_SIZE, value)));
    sizeDraft = String(size);
    if (size !== textStyle.size) onStyle({ size });
  }

  function onSizeKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      event.preventDefault();
      commitSize(Number(sizeDraft));
    }
  }
</script>

<div class="slides-editor-toolbar" role="toolbar" aria-label={$text('embeds.slides_editor_toolbar')} data-testid="slides-editor-toolbar">
  <div class="slides-editor-group">
    <button type="button" class="slides-editor-tool" data-testid="slides-editor-undo" disabled={!canUndo} onclick={onUndo}>
      {$text('embeds.slides_editor_undo')}
    </button>
    <button type="button" class="slides-editor-tool" data-testid="slides-editor-redo" disabled={!canRedo} onclick={onRedo}>
      {$text('embeds.slides_editor_redo')}
    </button>
  </div>

  <div class="slides-editor-group">
    <button type="button" class="slides-editor-tool" data-testid="slides-editor-add-text" onclick={onAddText}>
      {$text('embeds.slides_editor_add_text')}
    </button>
    <button
      type="button"
      class="slides-editor-tool"
      data-testid="slides-editor-delete-element"
      disabled={!hasSelection}
      onclick={onDelete}
    >{$text('common.delete')}</button>
    <button
      type="button"
      class="slides-editor-tool"
      data-testid="slides-editor-bring-forward"
      disabled={!canForward}
      onclick={onForward}
    >{$text('embeds.slides_editor_bring_forward')}</button>
    <button
      type="button"
      class="slides-editor-tool"
      data-testid="slides-editor-send-backward"
      disabled={!canBackward}
      onclick={onBackward}
    >{$text('embeds.slides_editor_send_backward')}</button>
  </div>

  {#if textStyle}
    <div class="slides-editor-group" data-testid="slides-editor-text-tools">
      <div class="slides-editor-size">
        <button
          type="button"
          class="slides-editor-tool slides-editor-square"
          data-testid="slides-editor-size-down"
          aria-label={$text('embeds.slides_editor_smaller')}
          onclick={() => commitSize(textStyle.size - SIZE_STEP)}
        >−</button>
        <input
          class="slides-editor-size-input"
          type="number"
          inputmode="numeric"
          min={MIN_SIZE}
          max={MAX_SIZE}
          aria-label={$text('embeds.slides_editor_font_size')}
          data-testid="slides-editor-font-size"
          bind:value={sizeDraft}
          onkeydown={onSizeKeydown}
          onchange={() => commitSize(Number(sizeDraft))}
        />
        <button
          type="button"
          class="slides-editor-tool slides-editor-square"
          data-testid="slides-editor-size-up"
          aria-label={$text('embeds.slides_editor_larger')}
          onclick={() => commitSize(textStyle.size + SIZE_STEP)}
        >+</button>
      </div>

      <button
        type="button"
        class="slides-editor-tool slides-editor-square slides-editor-bold"
        data-testid="slides-editor-bold"
        aria-label={$text('embeds.slides_editor_bold')}
        aria-pressed={bold}
        onclick={() => onStyle({ weight: bold ? 'normal' : 'bold' })}
      >B</button>

      <select
        class="slides-editor-select"
        aria-label={$text('embeds.slides_editor_align')}
        data-testid="slides-editor-align"
        value={textStyle.align}
        onchange={(event) => onStyle({ align: (event.currentTarget as HTMLSelectElement).value })}
      >
        {#each ALIGNS as align (align)}
          <option value={align}>{$text(ALIGN_LABEL_KEYS[align])}</option>
        {/each}
      </select>
    </div>

    <div class="slides-editor-group" role="group" aria-label={$text('embeds.slides_editor_color')}>
      {#each SWATCHES as token (token)}
        <button
          type="button"
          class="slides-editor-swatch"
          style:--swatch={template.colors[token]}
          aria-label={$text(SWATCH_LABEL_KEYS[token])}
          aria-pressed={colorValue === token}
          data-testid="slides-editor-swatch"
          data-color={token}
          onclick={() => onStyle({ color: token })}
        ></button>
      {/each}
      <label class="slides-editor-custom-color">
        <span class="slides-editor-visually-hidden">{$text('embeds.slides_editor_custom_color')}</span>
        <input
          type="color"
          data-testid="slides-editor-custom-color"
          value={customColor}
          onchange={(event) => onStyle({ color: (event.currentTarget as HTMLInputElement).value.toLowerCase() })}
        />
      </label>
    </div>
  {/if}
</div>

<style>
  .slides-editor-toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--spacing-4);
    width: 100%;
    box-sizing: border-box;
  }

  .slides-editor-group {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--spacing-2);
    min-width: 0;
  }

  /* Global buttons.css sizes every button (min-width 112px, height 41px, hover scale): reset it. */
  .slides-editor-tool {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 0;
    min-height: 36px;
    height: auto;
    margin: 0;
    padding: var(--spacing-2) var(--spacing-6);
    border: 0;
    border-radius: var(--radius-full);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: 0 0 0 1px var(--color-grey-30);
    font-size: var(--font-size-small);
    line-height: 1.2;
    cursor: pointer;
    transform: none;
  }

  .slides-editor-tool:hover:not(:disabled) {
    background: var(--color-grey-10);
    transform: none;
  }

  .slides-editor-tool:active:not(:disabled) {
    transform: scale(0.95);
  }

  .slides-editor-tool:disabled {
    opacity: 0.4;
    cursor: default;
  }

  .slides-editor-tool:focus-visible,
  .slides-editor-swatch:focus-visible,
  .slides-editor-select:focus-visible,
  .slides-editor-size-input:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 2px;
  }

  .slides-editor-square {
    width: 36px;
    height: 36px;
    padding: 0;
  }

  .slides-editor-bold {
    font-weight: 700;
  }

  .slides-editor-bold[aria-pressed='true'] {
    background: var(--color-button-primary);
    color: var(--color-grey-0);
    box-shadow: none;
  }

  .slides-editor-size {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-2);
  }

  .slides-editor-size-input {
    width: 4.5em;
    height: 36px;
    box-sizing: border-box;
    margin: 0;
    padding: 0 var(--spacing-2);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-3);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
    text-align: center;
  }

  .slides-editor-select {
    height: 36px;
    margin: 0;
    padding: 0 var(--spacing-4);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-3);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
  }

  .slides-editor-swatch {
    display: block;
    width: 28px;
    height: 28px;
    min-width: 0;
    min-height: 0;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: var(--radius-full);
    background: var(--swatch);
    box-shadow: 0 0 0 1px var(--color-grey-40);
    cursor: pointer;
    transform: none;
  }

  .slides-editor-swatch[aria-pressed='true'] {
    box-shadow: 0 0 0 2px var(--color-grey-0), 0 0 0 4px var(--color-primary-start);
  }

  .slides-editor-custom-color {
    position: relative;
    display: inline-flex;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-full);
    overflow: hidden;
    box-shadow: 0 0 0 1px var(--color-grey-40);
    cursor: pointer;
  }

  .slides-editor-custom-color input {
    width: 200%;
    height: 200%;
    margin: -50%;
    padding: 0;
    border: 0;
    cursor: pointer;
  }

  .slides-editor-visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
</style>
