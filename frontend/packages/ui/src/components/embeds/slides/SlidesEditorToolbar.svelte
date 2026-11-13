<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesEditorToolbar.svelte

  The one slim bar above the editable slide, in the embed fullscreen's round
  icon-button language (EmbedIconButton: tooltip names each action).
  - Always: undo, redo, add (a text box), speaker notes, and at the end the
    caller's primary action (Done) with its saving state.
  - Only while an element is selected: a contextual group with delete and paint
    order; for a text element also font size, bold, alignment (one button that
    cycles left / centre / right) and colour (one swatch button that opens a
    small popover with the template swatches and a custom colour).
  Wide: one row. Narrow (phone): the always-on row, and the contextual group on
  a second row that scrolls sideways instead of wrapping.
  It only reports intents; SlidesEditor turns them into typed core operations.
  View state here: whether the colour popover is open.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { tick } from 'svelte';
  import { text } from '@repo/ui';
  import EmbedIconButton from '../shared/EmbedIconButton.svelte';
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
    notesOpen: boolean;
    /** The open slide has speaker notes (badge on the notes button). */
    hasNotes: boolean;
    notesPanelId: string;
    onUndo: () => void;
    onRedo: () => void;
    onAddText: () => void;
    onDelete: () => void;
    onForward: () => void;
    onBackward: () => void;
    onStyle: (style: DeckTextStyle) => void;
    onToggleNotes: () => void;
    /** Primary action at the end of the bar (Done, plus its saving state). */
    end: Snippet;
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
    notesOpen,
    hasNotes,
    notesPanelId,
    onUndo,
    onRedo,
    onAddText,
    onDelete,
    onForward,
    onBackward,
    onStyle,
    onToggleNotes,
    end
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
  /** The alignment button cycles through these; a stored `justify` continues with left. */
  const ALIGN_CYCLE = ['left', 'center', 'right'] as const;
  const ALIGN_LABEL_KEYS: Record<string, string> = {
    left: 'embeds.slides_editor_align_left',
    center: 'embeds.slides_editor_align_center',
    right: 'embeds.slides_editor_align_right',
    justify: 'embeds.slides_editor_align_justify'
  };
  /** Closest icons of the icon set: lines with a short last line; equal lines for centre/justify. */
  const ALIGN_ICONS: Record<string, { icon: string; flip: boolean }> = {
    left: { icon: 'text', flip: false },
    center: { icon: 'menu', flip: false },
    right: { icon: 'text', flip: true },
    justify: { icon: 'menu', flip: false }
  };
  const MIN_SIZE = 8;
  const MAX_SIZE = 400;
  const SIZE_STEP = 4;
  /** Gap between the colour button and its popover (px). */
  const POPOVER_GAP = 12;

  const colorPopoverId = $props.id();
  let root = $state<HTMLElement | null>(null);
  let colorButton = $state<HTMLButtonElement | null>(null);
  let colorPopover = $state<HTMLElement | null>(null);
  let colorOpen = $state(false);
  let popoverLeft = $state(0);
  let popoverTop = $state(0);

  let sizeDraft = $state('');
  $effect(() => {
    sizeDraft = textStyle ? String(textStyle.size) : '';
  });
  // The popover belongs to the selected text element.
  $effect(() => {
    if (!textStyle) colorOpen = false;
  });

  let bold = $derived(textStyle ? textStyle.weight === 'bold' || Number(textStyle.weight) >= 600 : false);
  let customColor = $derived(colorValue && colorValue.startsWith('#') && colorValue.length === 7 ? colorValue : '#000000');
  let currentColor = $derived(textStyle?.color ?? template.colors.foreground);
  let align = $derived(textStyle?.align ?? 'left');
  let alignIcon = $derived(ALIGN_ICONS[align] ?? ALIGN_ICONS.left);
  let alignLabel = $derived(`${$text('embeds.slides_editor_align')}: ${$text(ALIGN_LABEL_KEYS[align] ?? ALIGN_LABEL_KEYS.left)}`);

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

  function cycleAlign() {
    const position = ALIGN_CYCLE.indexOf(align as (typeof ALIGN_CYCLE)[number]);
    onStyle({ align: ALIGN_CYCLE[(position + 1) % ALIGN_CYCLE.length] });
  }

  /** The popover is placed in the bar's box, so the sideways-scrolling group cannot clip it. */
  function placePopover() {
    if (!root || !colorButton || !colorPopover) return;
    const bar = root.getBoundingClientRect();
    const trigger = colorButton.getBoundingClientRect();
    const width = colorPopover.offsetWidth;
    const centred = trigger.left - bar.left + trigger.width / 2 - width / 2;
    popoverLeft = Math.max(0, Math.min(centred, bar.width - width));
    popoverTop = trigger.bottom - bar.top + POPOVER_GAP;
  }

  async function toggleColor() {
    colorOpen = !colorOpen;
    if (!colorOpen) return;
    await tick();
    placePopover();
    colorPopover?.querySelector<HTMLElement>('[aria-pressed="true"], button')?.focus();
  }

  function closeColor(refocus: boolean) {
    colorOpen = false;
    if (refocus) colorButton?.focus();
  }

  function onRootKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && colorOpen) {
      event.preventDefault();
      event.stopPropagation();
      closeColor(true);
    }
  }

  function onWindowPointerDown(event: PointerEvent) {
    if (!colorOpen || !(event.target instanceof Node)) return;
    if (colorPopover?.contains(event.target) || colorButton?.contains(event.target)) return;
    colorOpen = false;
  }
</script>

<svelte:window onpointerdown={onWindowPointerDown} onresize={placePopover} />

<!-- svelte-ignore a11y_interactive_supports_focus -->
<div
  class="slides-editor-toolbar"
  class:has-context={hasSelection}
  role="toolbar"
  aria-label={$text('embeds.slides_editor_toolbar')}
  data-testid="slides-editor-toolbar"
  bind:this={root}
  onkeydown={onRootKeydown}
>
  <div class="slides-editor-main">
    <EmbedIconButton icon="reload" flip label={$text('embeds.slides_editor_undo')} testId="slides-editor-undo" disabled={!canUndo} onclick={onUndo} />
    <EmbedIconButton icon="reload" label={$text('embeds.slides_editor_redo')} testId="slides-editor-redo" disabled={!canRedo} onclick={onRedo} />
    <EmbedIconButton icon="plus" label={$text('embeds.slides_editor_add_text')} testId="slides-editor-add-text" onclick={onAddText} />
    <EmbedIconButton
      icon="notes"
      label={$text('embeds.slides_speaker_notes')}
      testId="slides-editor-notes-toggle"
      expanded={notesOpen}
      controls={notesPanelId}
      badge={hasNotes}
      badgeTestId="slides-editor-notes-badge"
      onclick={onToggleNotes}
    />
  </div>

  {#if hasSelection}
    <div class="slides-editor-context-scroll">
      <div class="slides-editor-context" role="group" aria-label={$text('embeds.slides_editor_selection_tools')} data-testid="slides-editor-context-bar">
        <EmbedIconButton icon="delete" label={$text('common.delete')} testId="slides-editor-delete-element" onclick={onDelete} />
        <EmbedIconButton icon="up" label={$text('embeds.slides_editor_bring_forward')} testId="slides-editor-bring-forward" disabled={!canForward} onclick={onForward} />
        <EmbedIconButton icon="down" label={$text('embeds.slides_editor_send_backward')} testId="slides-editor-send-backward" disabled={!canBackward} onclick={onBackward} />

        {#if textStyle}
          <span class="slides-editor-divider" aria-hidden="true"></span>
          <div class="slides-editor-text-tools" data-testid="slides-editor-text-tools">
            <EmbedIconButton icon="minus" label={$text('embeds.slides_editor_smaller')} testId="slides-editor-size-down" onclick={() => commitSize(textStyle.size - SIZE_STEP)} />
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
            <EmbedIconButton icon="plus" label={$text('embeds.slides_editor_larger')} testId="slides-editor-size-up" onclick={() => commitSize(textStyle.size + SIZE_STEP)} />
            <EmbedIconButton
              label={$text('embeds.slides_editor_bold')}
              testId="slides-editor-bold"
              pressed={bold}
              onclick={() => onStyle({ weight: bold ? 'normal' : 'bold' })}
            >
              {#snippet content()}<span class="slides-editor-bold-glyph" aria-hidden="true">B</span>{/snippet}
            </EmbedIconButton>
            <span class="slides-editor-align" data-align={align}>
              <EmbedIconButton icon={alignIcon.icon} flip={alignIcon.flip} label={alignLabel} testId="slides-editor-align" onclick={cycleAlign} />
            </span>
            <EmbedIconButton
              label={$text('embeds.slides_editor_color')}
              testId="slides-editor-color"
              expanded={colorOpen}
              controls={colorPopoverId}
              bind:element={colorButton}
              onclick={toggleColor}
            >
              {#snippet content()}<span class="slides-editor-color-dot" style:--swatch={currentColor} aria-hidden="true"></span>{/snippet}
            </EmbedIconButton>
          </div>
        {/if}
      </div>
    </div>
  {/if}

  <div class="slides-editor-end">{@render end()}</div>

  {#if colorOpen && textStyle}
    <div
      id={colorPopoverId}
      class="slides-editor-popover"
      role="group"
      aria-label={$text('embeds.slides_editor_color')}
      data-testid="slides-editor-color-popover"
      bind:this={colorPopover}
      style:left="{popoverLeft}px"
      style:top="{popoverTop}px"
    >
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
    position: relative;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    grid-template-areas: 'main context end';
    align-items: center;
    column-gap: var(--spacing-6);
    row-gap: var(--spacing-4);
    width: 100%;
    box-sizing: border-box;
  }

  .slides-editor-main,
  .slides-editor-context,
  .slides-editor-text-tools,
  .slides-editor-end {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
  }

  .slides-editor-main { grid-area: main; }
  .slides-editor-end { grid-area: end; justify-content: flex-end; }

  /* Sideways scroll, never wrapping; the padding keeps hover scale and shadows unclipped. */
  .slides-editor-context-scroll {
    grid-area: context;
    display: flex;
    justify-content: center;
    min-width: 0;
    overflow-x: auto;
    padding: var(--spacing-4);
    margin: calc(-1 * var(--spacing-4));
    scrollbar-width: none;
  }

  .slides-editor-context-scroll::-webkit-scrollbar {
    display: none;
  }

  .slides-editor-context {
    flex: 0 0 auto;
  }

  .slides-editor-divider {
    flex: 0 0 auto;
    width: 1px;
    height: 24px;
    background: var(--color-grey-30);
  }

  .slides-editor-bold-glyph {
    font-size: var(--font-size-h3);
    font-weight: 800;
    line-height: 25px;
    width: 25px;
    text-align: center;
  }

  .slides-editor-align {
    display: contents;
  }

  .slides-editor-color-dot {
    display: block;
    box-sizing: border-box;
    width: 25px;
    height: 25px;
    border-radius: var(--radius-full);
    background: var(--swatch);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-grey-100) 25%, transparent);
  }

  .slides-editor-size-input {
    flex: 0 0 auto;
    width: 56px;
    height: calc(25px + 2 * var(--spacing-4));
    box-sizing: border-box;
    margin: 0;
    padding: 0 var(--spacing-2);
    border: 0;
    border-radius: 40px;
    background: var(--color-grey-10);
    box-shadow: var(--shadow-md);
    color: var(--color-font-primary);
    font: inherit;
    font-size: var(--font-size-small);
    font-weight: 600;
    text-align: center;
    -moz-appearance: textfield;
    appearance: textfield;
  }

  .slides-editor-size-input::-webkit-inner-spin-button,
  .slides-editor-size-input::-webkit-outer-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }

  .slides-editor-size-input:focus-visible,
  .slides-editor-swatch:focus-visible,
  .slides-editor-custom-color:focus-within {
    outline: 2px solid var(--color-primary-start);
    outline-offset: 3px;
  }

  .slides-editor-popover {
    position: absolute;
    z-index: var(--z-index-dropdown);
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    padding: var(--spacing-4);
    border-radius: 40px;
    background: var(--color-grey-10);
    box-shadow: var(--shadow-lg);
  }

  .slides-editor-swatch {
    all: unset;
    display: block;
    box-sizing: border-box;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-full);
    background: var(--swatch);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-grey-100) 25%, transparent);
    cursor: pointer;
    transition: transform var(--duration-normal);
  }

  .slides-editor-swatch:hover {
    transform: scale(1.08);
  }

  .slides-editor-swatch[aria-pressed='true'] {
    box-shadow: 0 0 0 2px var(--color-grey-10), 0 0 0 4px var(--color-primary-start);
  }

  .slides-editor-custom-color {
    position: relative;
    display: inline-flex;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-full);
    overflow: hidden;
    background: var(--color-grey-20);
    box-shadow: inset 0 0 0 1px var(--color-grey-30);
    cursor: pointer;
  }

  /* "Custom colour" mark: the icon set's plus, like the add buttons. */
  .slides-editor-custom-color::before {
    content: '';
    position: absolute;
    inset: 8px;
    background: var(--color-font-secondary);
    -webkit-mask: var(--icon-url-plus) center / contain no-repeat;
    mask: var(--icon-url-plus) center / contain no-repeat;
    pointer-events: none;
  }

  .slides-editor-custom-color input {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0;
    border: 0;
    opacity: 0;
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

  /* Phone: the always-on row, then the contextual group on its own scrolling row. */
  @container slides-editor (max-width: 640px) {
    .slides-editor-toolbar {
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas:
        'main end'
        'context context';
    }

    .slides-editor-context-scroll {
      justify-content: flex-start;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .slides-editor-swatch {
      transition: none;
    }
  }
</style>
