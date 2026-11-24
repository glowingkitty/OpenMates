<script lang="ts">
  import { text } from '@repo/ui';
  import { stripEmbedLinks, stripWikiLinks } from '../../../utils/embedLinkUtils';
  import { colIndexToLetter, type ParsedTable } from './sheetEmbedContent';
  import { displaySheetValue, sheetCellCss, sheetPixels, visibleSheetMerges } from './sheetFormattingPresentation';
  import type { SheetFormatting } from './sheetFormattingTypes';

  let { table, formatting }: { table: ParsedTable; formatting: SheetFormatting } = $props();
  let rows = $derived([table.headers, ...table.rows]);
  let merges = $derived(visibleSheetMerges(formatting, rows.length, table.colCount));
  let widths = $derived(table.headers.map((header, column) => (
    sheetPixels(formatting.columnWidths?.[colIndexToLetter(column)], 24, 1200)
      ?? Math.max(96, Math.min(320, (stripEmbedLinks(header.content).length + 3) * 8))
  )));
  let gridWidth = $derived(widths.reduce((sum, width) => sum + width, 40));
  let rowOffsets = $state<number[]>([]);
  let columnOffsets = $state<number[]>([]);
  let frozenRows = $derived(sheetPixels(formatting.frozenRows, 0, rows.length) ?? 0);
  let frozenColumns = $derived(sheetPixels(formatting.frozenColumns, 0, table.colCount) ?? 0);

  function measure(node: HTMLTableElement) {
    const update = () => {
      let vertical = 0;
      rowOffsets = Array.from(node.rows, (row) => {
        const top = vertical;
        vertical += row.getBoundingClientRect().height;
        return top;
      });
      let horizontal = 0;
      columnOffsets = Array.from(node.rows[0]?.cells ?? [], (cell) => {
        const left = horizontal;
        horizontal += cell.getBoundingClientRect().width;
        return left;
      });
    };
    const observer = new ResizeObserver(update);
    observer.observe(node);
    update();
    return { destroy: () => observer.disconnect() };
  }

  function height(row: number): string | undefined {
    const size = sheetPixels(formatting.rowHeights?.[String(row + 1)], 16, 600);
    return size ? `${size}px` : undefined;
  }

  function rowPin(row: number): string | undefined {
    return row < frozenRows ? `${rowOffsets[row + 1] ?? 0}px` : undefined;
  }

  function columnPin(column: number): string | undefined {
    return column < frozenColumns ? `${columnOffsets[column + 1] ?? 0}px` : undefined;
  }
</script>

<!-- Keyboard users focus the scroll region to navigate the grid with arrow keys. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div class="grid-scroll" role="region" aria-label={$text('embeds.table')} tabindex="0">
  <table class="grid" aria-label={$text('embeds.table')} style:width={`${gridWidth}px`} use:measure data-testid="formatted-sheet-grid">
    <colgroup>
      <col style:width="40px" />
      {#each widths as width}
        <col style:width={`${width}px`} />
      {/each}
    </colgroup>
    <thead>
      <tr class="letters">
        <td class="row-label"></td>
        {#each table.headers as _, column}
          {@const left = columnPin(column)}
          <th class:pinned-column={left !== undefined} style:left scope="col">
            {colIndexToLetter(column)}
          </th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each rows as row, index}
        {@const top = rowPin(index)}
        <tr style:height={height(index)} class:heading={index === 0}>
          <th class="row-label" class:pinned-row={top !== undefined} style:top scope="row">
            {index + 1}
          </th>
          {#each row as cell, column}
            {@const merge = merges.get(`${index}:${column}`)}
            {@const address = `${colIndexToLetter(column)}${index + 1}`}
            {@const format = formatting.cells?.[address]}
            {@const left = columnPin(column)}
            {#if merge !== null}
              <td
                class:pinned-column={left !== undefined} class:pinned-row={top !== undefined}
                class:formula={!!cell.formula} colspan={merge?.colSpan} rowspan={merge?.rowSpan}
                style={sheetCellCss(format)} style:left style:top
                data-testid="formatted-sheet-cell" data-cell={address}
                title={cell.formula ?? undefined}
              >{displaySheetValue(stripWikiLinks(stripEmbedLinks(cell.content)), format)}</td>
            {/if}
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .grid-scroll {
    overflow: auto;
    max-block-size: 65vh;
    max-block-size: 65dvh;
  }

  .grid {
    border-spacing: 0;
    table-layout: fixed;
    font-size: var(--font-size-xs);
    line-height: 1.4;
    color: var(--color-font-primary);
  }

  th, td {
    box-sizing: border-box;
    border-right: 1px solid var(--color-grey-25);
    border-bottom: 1px solid var(--color-grey-25);
    padding: var(--spacing-3) var(--spacing-5);
    white-space: nowrap;
    text-overflow: ellipsis;
    overflow: hidden;
    background-color: var(--color-grey-0);
  }

  .heading td, .letters th, .row-label {
    background-color: var(--color-grey-10);
    font-weight: 600;
  }

  .letters th, .row-label { text-align: center; }
  .formula { color: var(--color-sheet-formula); font-style: italic; }

  .pinned-row, .pinned-column, .row-label, .letters > * {
    position: sticky;
    z-index: var(--z-index-raised);
  }

  .row-label { left: 0; }
  .letters > * { top: 0; z-index: var(--z-index-raised-3); }
  .pinned-row.pinned-column, .row-label.pinned-row {
    z-index: var(--z-index-raised-2);
  }
</style>
