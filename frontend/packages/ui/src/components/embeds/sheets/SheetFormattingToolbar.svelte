<script lang="ts">
  import { text } from '@repo/ui';
  import type { SheetBorder, SheetBorderSide, SheetCellStyle, SheetDatePattern, SheetNumberFormat } from './sheetFormattingTypes';

  type CellPatch = { [Key in keyof SheetCellStyle]?: SheetCellStyle[Key] | null };
  interface Props {
    selection?: string;
    cellStyle?: SheetCellStyle;
    columnWidth?: number;
    rowHeight?: number;
    frozenRows?: number;
    frozenColumns?: number;
    rowCount: number;
    columnCount: number;
    canMerge?: boolean;
    canUnmerge?: boolean;
    choosingMergeEnd?: boolean;
    canUndoFormatting?: boolean;
    disabled?: boolean;
    onStyle: (patch: CellPatch) => void;
    onColumnWidth: (pixels: number | null) => void;
    onRowHeight: (pixels: number | null) => void;
    onFrozenRows: (count: number) => void;
    onFrozenColumns: (count: number) => void;
    onMerge: () => void;
    onUnmerge: () => void;
    onCancelMerge?: () => void;
    onUndoFormatting?: () => void;
  }
  let {
    selection, cellStyle, columnWidth, rowHeight, frozenRows = 0, frozenColumns = 0,
    rowCount, columnCount, canMerge = false, canUnmerge = false, choosingMergeEnd = false,
    canUndoFormatting = false, disabled = false, onStyle, onColumnWidth, onRowHeight,
    onFrozenRows, onFrozenColumns, onMerge, onUnmerge, onCancelMerge, onUndoFormatting,
  }: Props = $props();

  const marks = [
    { key: 'bold', glyph: 'B', label: 'embed_user_edits.docs_editor_bold' },
    { key: 'italic', glyph: 'I', label: 'embed_user_edits.docs_editor_italic' },
    { key: 'underline', glyph: 'U', label: 'embed_user_edits.docs_editor_underline' },
    { key: 'strikethrough', glyph: 'S', label: 'embeds.sheets.sheet.strikethrough' },
    { key: 'wrap', glyph: '↵', label: 'embeds.sheets.sheet.wrap' },
  ] as const;
  const datePatterns: SheetDatePattern[] = ['yyyy-mm-dd', 'mm/dd/yyyy', 'dd/mm/yyyy', 'mmm d, yyyy'];
  const borderStyles: SheetBorder['style'][] = ['thin', 'medium', 'thick', 'dashed', 'dotted', 'double'];
  const borderSides: SheetBorderSide[] = ['top', 'right', 'bottom', 'left'];
  const key = (name: string) => `embeds.sheets.sheet.${name}`;
  const dark = '#000000';
  const light = '#ffffff';
  let borderSide = $state<SheetBorderSide>('bottom');
  let edge = $derived(cellStyle?.borders?.[borderSide]);
  let numberFormat = $derived(cellStyle?.numberFormat);

  function commitNumber(input: HTMLInputElement, apply: (value: number | null) => void) {
    if (!input.validity.valid) { input.reportValidity(); return; }
    apply(input.value === '' ? null : input.valueAsNumber);
  }

  function selectFormat(kind: string) {
    const formats: Record<string, SheetNumberFormat> = {
      number: { kind: 'number', decimals: 2 },
      percent: { kind: 'percent', decimals: 1 },
      currency: { kind: 'currency', currency: 'USD', decimals: 2 },
      date: { kind: 'date', pattern: 'yyyy-mm-dd' },
    };
    onStyle({ numberFormat: formats[kind] ?? null });
  }

  function changeBorder(style: SheetBorder['style'] | '') {
    const borders = { ...cellStyle?.borders };
    if (style) borders[borderSide] = { style, color: edge?.color ?? dark };
    else delete borders[borderSide];
    onStyle({ borders: Object.keys(borders).length ? borders : null });
  }
</script>

<div class="toolbar" role="toolbar" aria-label={$text(key('formatting_toolbar'))} data-testid="sheet-format-toolbar">
  <div class="marks">
    <output class="selection" aria-label={$text(key('selection'))}>{selection ?? '—'}</output>
    {#if onUndoFormatting}
      <button type="button" disabled={disabled || !canUndoFormatting} aria-label={$text(key('undo_formatting'))}
        title={$text(key('undo_formatting'))} onclick={onUndoFormatting} data-testid="sheet-format-undo">↶</button>
    {/if}
    {#each marks as mark (mark.key)}
      {@const label = $text(mark.label)}
      <button type="button" disabled={disabled || !selection} class={mark.key}
        aria-pressed={cellStyle?.[mark.key] === true} aria-label={label} title={label}
        onclick={() => onStyle({ [mark.key]: !cellStyle?.[mark.key] })}
        data-testid={`sheet-format-${mark.key}`}>{mark.glyph}</button>
    {/each}
  </div>

  <details class="options">
    <summary>{$text(key('cell_format'))}</summary>
    <fieldset disabled={disabled || !selection}>
      <label>{$text(key('font_family'))}
        <input type="text" maxlength="64" pattern="[A-Za-z0-9][A-Za-z0-9 \-]*" value={cellStyle?.fontFamily ?? ''}
          onchange={(event) => {
            const input = event.currentTarget;
            if (input.reportValidity()) onStyle({ fontFamily: input.value || null });
          }} data-testid="sheet-format-font-family" />
      </label>
      <label>{$text(key('font_size'))}
        <input type="number" min="8" max="96" value={cellStyle?.fontSize ?? ''}
          onchange={(event) => commitNumber(event.currentTarget, (fontSize) => onStyle({ fontSize }))}
          data-testid="sheet-format-font-size" />
      </label>
      <label>{$text(key('text_color'))}
        <input type="color" value={cellStyle?.textColor ?? dark}
          onchange={(event) => onStyle({ textColor: event.currentTarget.value })}
          data-testid="sheet-format-text-color" />
      </label>
      <label>{$text(key('fill_color'))}
        <input type="color" value={cellStyle?.backgroundColor ?? light}
          onchange={(event) => onStyle({ backgroundColor: event.currentTarget.value })}
          data-testid="sheet-format-fill-color" />
      </label>
      <label>{$text(key('horizontal_align'))}
        <select value={cellStyle?.horizontalAlign ?? ''}
          onchange={(event) => onStyle({ horizontalAlign: (event.currentTarget.value || null) as CellPatch['horizontalAlign'] })}
          data-testid="sheet-format-horizontal-align">
          <option value="">{$text(key('default'))}</option>
          {#each ['left', 'center', 'right'] as align}
            <option value={align}>{$text(key(align))}</option>
          {/each}
        </select>
      </label>
      <label>{$text(key('vertical_align'))}
        <select value={cellStyle?.verticalAlign ?? ''}
          onchange={(event) => onStyle({ verticalAlign: (event.currentTarget.value || null) as CellPatch['verticalAlign'] })}
          data-testid="sheet-format-vertical-align">
          <option value="">{$text(key('default'))}</option>
          {#each ['top', 'middle', 'bottom'] as align}
            <option value={align}>{$text(key(align))}</option>
          {/each}
        </select>
      </label>
      <label>{$text(key('number_format'))}
        <select value={numberFormat?.kind ?? ''} onchange={(event) => selectFormat(event.currentTarget.value)}
          data-testid="sheet-format-number">
          <option value="">{$text(key('default'))}</option>
          {#each ['number', 'percent', 'currency', 'date'] as kind}
            <option value={kind}>{$text(key(kind))}</option>
          {/each}
        </select>
      </label>
      {#if numberFormat && numberFormat.kind !== 'date'}
        <label>{$text(key('decimals'))}
          <input type="number" min="0" max="10" value={numberFormat.decimals ?? ''}
            onchange={(event) => commitNumber(event.currentTarget, (value) => onStyle({
              numberFormat: { ...numberFormat, decimals: value ?? undefined } as SheetNumberFormat,
            }))} data-testid="sheet-format-decimals" />
        </label>
      {/if}
      {#if numberFormat?.kind === 'currency'}
        <label>{$text(key('currency_code'))}
          <input type="text" maxlength="3" pattern="[A-Z]{3}" required value={numberFormat.currency}
            onchange={(event) => {
              const input = event.currentTarget;
              input.value = input.value.toUpperCase();
              if (input.reportValidity()) onStyle({ numberFormat: { ...numberFormat, kind: 'currency', currency: input.value } });
            }} data-testid="sheet-format-currency-code" />
        </label>
      {/if}
      {#if numberFormat?.kind === 'date'}
        <label>{$text(key('date_pattern'))}
          <select value={numberFormat.pattern}
            onchange={(event) => onStyle({ numberFormat: { kind: 'date', pattern: event.currentTarget.value as SheetDatePattern } })}
            data-testid="sheet-format-date-pattern">
            {#each datePatterns as pattern}
              <option value={pattern}>{pattern}</option>
            {/each}
          </select>
        </label>
      {/if}
      <label>{$text(key('border_side'))}
        <select bind:value={borderSide} data-testid="sheet-format-border-side">
          {#each borderSides as side}
            <option value={side}>{$text(key(side))}</option>
          {/each}
        </select>
      </label>
      <label>{$text(key('border_style'))}
        <select value={edge?.style ?? ''} onchange={(event) => changeBorder(event.currentTarget.value as SheetBorder['style'] | '')}
          data-testid="sheet-format-border-style">
          <option value="">{$text(key('default'))}</option>
          {#each borderStyles as style}
            <option value={style}>{$text(key(style))}</option>
          {/each}
        </select>
      </label>
      <label>{$text(key('border_color'))}
        <input type="color" value={edge?.color ?? dark}
          onchange={(event) => onStyle({ borders: {
            ...cellStyle?.borders, [borderSide]: { style: edge?.style ?? 'thin', color: event.currentTarget.value },
          } })} data-testid="sheet-format-border-color" />
      </label>
      <button type="button" onclick={() => onStyle({ textColor: null, backgroundColor: null })}
        data-testid="sheet-format-clear-colors">
        {$text(key('reset_colors'))}
      </button>
    </fieldset>
  </details>

  <details class="options">
    <summary>{$text(key('layout'))}</summary>
    <fieldset disabled={disabled}>
      <label>{$text(key('column_width'))}
        <input type="number" min="24" max="1200" disabled={!selection} value={columnWidth ?? ''}
          onchange={(event) => commitNumber(event.currentTarget, onColumnWidth)} data-testid="sheet-format-column-width" />
      </label>
      <label>{$text(key('row_height'))}
        <input type="number" min="16" max="600" disabled={!selection} value={rowHeight ?? ''}
          onchange={(event) => commitNumber(event.currentTarget, onRowHeight)} data-testid="sheet-format-row-height" />
      </label>
      <label>{$text(key('frozen_rows'))}
        <input type="number" min="0" max={Math.min(rowCount, 1000)} value={frozenRows}
          onchange={(event) => commitNumber(event.currentTarget, (value) => onFrozenRows(value ?? 0))}
          data-testid="sheet-format-frozen-rows" />
      </label>
      <label>{$text(key('frozen_columns'))}
        <input type="number" min="0" max={Math.min(columnCount, 256)} value={frozenColumns}
          onchange={(event) => commitNumber(event.currentTarget, (value) => onFrozenColumns(value ?? 0))}
          data-testid="sheet-format-frozen-columns" />
      </label>
      {#if choosingMergeEnd}
        <span role="status">{$text(key('select_merge_end'))}</span>
        <button type="button" onclick={onCancelMerge} data-testid="sheet-format-cancel-merge">{$text('common.cancel')}</button>
      {:else}
        <button type="button" disabled={!canMerge} onclick={onMerge} data-testid="sheet-format-merge">{$text(key('merge'))}</button>
      {/if}
      <button type="button" disabled={!canUnmerge} onclick={onUnmerge} data-testid="sheet-format-unmerge">{$text(key('unmerge'))}</button>
    </fieldset>
  </details>
</div>

<style>
  .toolbar,
  .marks {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-2);
    align-items: center;
  }

  .toolbar {
    padding: var(--spacing-3) var(--spacing-5);
    border-bottom: 1px solid var(--color-grey-30);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
  }

  .toolbar:has(details[open]) {
    align-items: flex-start;
  }

  .selection {
    min-width: 2.5em;
    padding-inline: var(--spacing-2);
    font-variant-numeric: tabular-nums;
  }

  button, summary, select, input {
    box-sizing: border-box;
    min-block-size: var(--spacing-12);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-5);
    background: var(--color-grey-5);
    color: inherit;
    font: inherit;
  }

  button, summary {
    padding: var(--spacing-2) var(--spacing-4);
    cursor: pointer;
  }

  button[aria-pressed='true'] {
    background: var(--color-grey-25);
    border-color: var(--color-grey-50);
  }

  .marks button {
    min-inline-size: 2.25rem;
    padding-inline: var(--spacing-2);
    margin: 0;
  }

  button:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .bold { font-weight: 700; }
  .italic { font-style: italic; }
  .underline { text-decoration: underline; }
  .strikethrough { text-decoration: line-through; }
  .options[open] { flex: 1 0 100%; }

  fieldset {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    min-inline-size: 0;
    gap: var(--spacing-3) var(--spacing-5);
    margin: 0;
    padding: var(--spacing-3) 0 0;
    border: 0;
  }

  label {
    display: grid;
    gap: var(--spacing-1);
    font-size: var(--font-size-xs);
  }

  input, select {
    inline-size: 8em;
    padding-inline: var(--spacing-3);
  }
</style>
