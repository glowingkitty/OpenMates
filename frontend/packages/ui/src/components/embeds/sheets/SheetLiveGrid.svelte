<!--
  Live sheet grid (flag live_collaboration). Renders the view model the Rust core pushes
  (`liveView`) and sends one typed op per change (`liveApplyOp`): set_cell, set_header,
  insert_row, delete_row, insert_col, delete_col, dismiss_suggestion. It holds no sheet
  model, formula engine or merge logic: the core evaluates, merges, seals and saves.
  Selection is shared as presence ({cursor:{row_id,col_id}}); peers' selected cells are
  outlined in their colour with their name. A cell the view marks with a suggestion shows
  the assistant's value with accept (set_cell) and dismiss (dismiss_suggestion). No Save
  step. Architecture: docs/plans/live-collaboration-crdt/build-contract.md section 5.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  import { liveItemClient } from '../../../services/live/liveItemClient';
  import type { LiveItemClient, LivePeer, LiveStatus } from '../../../services/live/liveItemTypes';
  import { columnLabel, peerMate, sheetCursor } from '../../../services/live/liveSurface';
  import { asSheetView, cellKey, type LiveSheetAddress, type LiveSheetView } from './sheetLiveTypes';
  import { displaySheetValue, sheetCellCss, sheetPixels, visibleSheetMerges, watchSheetRows } from './sheetFormattingPresentation';
  import type { SheetFormatting } from './sheetFormattingTypes';

  interface Props {
    itemId: string;
    client?: LiveItemClient;
    projectId?: string;
    teamId?: string;
    status?: LiveStatus;
    peers?: LivePeer[];
    onFormatSelect?: (cell: LiveSheetAddress) => boolean;
  }
  let { itemId, projectId, teamId, client = liveItemClient(), status = $bindable('saving'), peers = $bindable([]), onFormatSelect }: Props = $props();

  let view = $state<LiveSheetView | null>(null);
  let active = $state<{ row: string; col: string } | null>(null);
  let draft = $state('');
  let headerEdit = $state<string | null>(null);
  let readOnly = $derived(status === 'read_only' || status === 'access_revoked');
  let formatting = $derived(view?.formatting as SheetFormatting | undefined);
  let formatted = $derived(!!formatting && Object.keys(formatting).length > 0);
  let merges = $derived(visibleSheetMerges(formatting, (view?.rows.length ?? 0) + 1, view?.cols.length ?? 0));
  let columnWidths = $derived(view?.cols.map((_, column) => (
    sheetPixels(formatting?.columnWidths?.[columnLabel(column)], 24, 1200) ?? 120
  )) ?? []);
  let rowOffsets = $state<number[]>([]);
  let leftOffsets = $derived(columnWidths.map((_, column) => columnWidths.slice(0, column).reduce((sum, width) => sum + width, 56)));
  let frozenRows = $derived(sheetPixels(formatting?.frozenRows, 0, (view?.rows.length ?? 0) + 1) ?? 0);
  let frozenColumns = $derived(sheetPixels(formatting?.frozenColumns, 0, columnWidths.length) ?? 0);

  function measureRows(table: HTMLTableElement, _formatting?: SheetFormatting) {
    return watchSheetRows(table, (offsets) => { rowOffsets = offsets; });
  }

  function rowHeight(index: number): string | undefined {
    const size = sheetPixels(formatting?.rowHeights?.[String(index + 1)], 16, 600);
    return size ? `${size}px` : undefined;
  }

  function rowTop(index: number): string | undefined {
    return index < frozenRows ? `${rowOffsets[index] ?? 0}px` : undefined;
  }

  function columnLeft(index: number): string | undefined {
    return index < frozenColumns ? `${leftOffsets[index]}px` : undefined;
  }

  onMount(() => {
    const stops = [
      client.on('liveView', (e) => { if (e.itemId === itemId) view = asSheetView(e.view); }),
      client.on('livePresence', (e) => { if (e.itemId === itemId) peers = e.peers; }),
      client.on('liveStatus', (e) => { if (e.itemId === itemId) status = e.status; }),
    ];
    client.liveOpen(itemId, 'sheet', projectId, teamId).catch((error: unknown) => {
      console.warn('[live] open failed', itemId, error);
      status = 'offline';
    });
    return () => {
      for (const stop of stops) stop();
      void client.liveClose(itemId);
    };
  });

  const send = (op: Record<string, unknown>) => { void client.liveApplyOp(itemId, op); };

  function select(rowId: string, colId: string) {
    void client.liveSetPresence(itemId, { cursor: { row_id: rowId, col_id: colId } });
  }

  function startEdit(rowId: string, colId: string) {
    if (readOnly) return;
    if (onFormatSelect?.({ rowId, colId })) return;
    active = { row: rowId, col: colId };
    const cell = view?.cells[cellKey(rowId, colId)];
    draft = cell?.formula ?? cell?.display ?? '';
    select(rowId, colId);
  }

  function startHeaderEdit(colId: string) {
    if (!readOnly && !onFormatSelect?.({ rowId: null, colId })) headerEdit = colId;
  }

  function commit() {
    const at = active;
    active = null;
    if (!at) return;
    const cell = view?.cells[cellKey(at.row, at.col)];
    if (draft === (cell?.formula ?? cell?.display ?? '')) return;
    send({ op: 'set_cell', row_id: at.row, col_id: at.col, value: draft });
  }

  function onCellKey(event: KeyboardEvent) {
    if (event.key === 'Enter') { event.preventDefault(); commit(); }
    else if (event.key === 'Escape') { event.preventDefault(); active = null; }
  }

  function commitHeader(colId: string, value: string) {
    headerEdit = null;
    if (value !== (view?.headers[colId] ?? '')) send({ op: 'set_header', col_id: colId, value });
  }

  function focusInput(node: HTMLInputElement) { node.focus(); node.select(); }

  /** Peers whose selection is this cell (the viewer's own selection is not in `peers`). */
  function peersAt(rowId: string, colId: string): LivePeer[] {
    return peers.filter((p) => { const c = sheetCursor(p); return c?.row_id === rowId && c.col_id === colId; });
  }
</script>

<div class="live-sheet" data-testid="sheet-live-grid" data-live="true" data-status={status}>
  {#if view}
    {@const headingTop = rowTop(0)}
    <div class="live-sheet-scroll">
      <table class="live-sheet-table" class:formatted aria-label={$text('embed_user_edits.live_sheet_label')}
        use:measureRows={formatting} style:width={formatted ? `${columnWidths.reduce((sum, width) => sum + width, 56)}px` : undefined}>
        {#if formatted}
          <colgroup><col style:width="56px" />
            {#each columnWidths as width}<col style:width={`${width}px`} />{/each}
          </colgroup>
        {/if}
        <tbody>
          <tr style:height={rowHeight(0)}>
            <th class="gutter" class:pinned-row={headingTop !== undefined} style:top={headingTop}></th>
            {#each view.cols as colId, colIndex (colId)}
              {@const merge = merges.get(`0:${colIndex}`)}
              {@const format = formatting?.cells?.[`${columnLabel(colIndex)}1`]}
              {@const left = columnLeft(colIndex)}
              {#if merge !== null}
              <th class="head" data-testid="sheet-live-header" data-col-id={colId}
                class:pinned-row={headingTop !== undefined} class:pinned-column={left !== undefined}
                colspan={merge?.colSpan} rowspan={merge?.rowSpan}
                style={sheetCellCss(format)} style:top={headingTop} style:left style:text-align={format?.horizontalAlign ?? view.aligns?.[colId]}>
                <span class="col-letter">{columnLabel(colIndex)}</span>
                {#if headerEdit === colId}
                  <input class="head-input" type="text" value={view.headers[colId] ?? ''} use:focusInput
                    data-testid="sheet-live-header-input"
                    onblur={(e) => commitHeader(colId, e.currentTarget.value)}
                    onkeydown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); else if (e.key === 'Escape') headerEdit = null; }} />
                {:else}
                  <button type="button" class="head-text" disabled={readOnly} onclick={() => startHeaderEdit(colId)}
                    data-testid="sheet-live-header-edit">{displaySheetValue(view.headers[colId] ?? '', format)}</button>
                {/if}
                {#if !readOnly}
                  <span class="line-actions">
                    <button type="button" class="mini" data-testid="sheet-live-insert-col" title={$text('embed_user_edits.live_sheet_insert_col')} aria-label={$text('embed_user_edits.live_sheet_insert_col')} onclick={() => send({ op: 'insert_col', after_col_id: colId })}>+</button>
                    <button type="button" class="mini" data-testid="sheet-live-delete-col" title={$text('embed_user_edits.live_sheet_delete_col')} aria-label={$text('embed_user_edits.live_sheet_delete_col')} onclick={() => send({ op: 'delete_col', col_id: colId })}>−</button>
                  </span>
                {/if}
              </th>
              {/if}
            {/each}
          </tr>
          {#each view.rows as rowId, rowIndex (rowId)}
            {@const top = rowTop(rowIndex + 1)}
            <tr data-row-id={rowId} style:height={rowHeight(rowIndex + 1)}>
              <td class="gutter" class:pinned-row={top !== undefined} style:top>
                <span>{rowIndex + 1}</span>
                {#if !readOnly}
                  <span class="line-actions">
                    <button type="button" class="mini" data-testid="sheet-live-insert-row" title={$text('embed_user_edits.live_sheet_insert_row')} aria-label={$text('embed_user_edits.live_sheet_insert_row')} onclick={() => send({ op: 'insert_row', after_row_id: rowId })}>+</button>
                    <button type="button" class="mini" data-testid="sheet-live-delete-row" title={$text('embed_user_edits.live_sheet_delete_row')} aria-label={$text('embed_user_edits.live_sheet_delete_row')} onclick={() => send({ op: 'delete_row', row_id: rowId })}>−</button>
                  </span>
                {/if}
              </td>
              {#each view.cols as colId, colIndex (colId)}
                {@const cell = view.cells[cellKey(rowId, colId)]}
                {@const merge = merges.get(`${rowIndex + 1}:${colIndex}`)}
                {@const format = formatting?.cells?.[`${columnLabel(colIndex)}${rowIndex + 2}`]}
                {@const left = columnLeft(colIndex)}
                {@const here = peersAt(rowId, colId)}
                {@const lead = here[0]}
                {#if merge !== null}
                <td
                  class="cell"
                  class:pinned-row={top !== undefined}
                  class:pinned-column={left !== undefined}
                  class:suggested={!!cell?.suggestion}
                  class:peer-here={!!lead}
                  data-testid="sheet-live-cell"
                  data-cell-id={cellKey(rowId, colId)}
                  data-formula={cell?.formula ?? undefined}
                  colspan={merge?.colSpan} rowspan={merge?.rowSpan}
                  style={sheetCellCss(format)} style:top style:left
                  style:outline-color={lead?.color}
                  style:text-align={format?.horizontalAlign ?? view.aligns?.[colId]}
                >
                  {#if active && active.row === rowId && active.col === colId}
                    <input class="cell-input" data-testid="sheet-live-cell-input" type="text" bind:value={draft} onkeydown={onCellKey} onblur={commit} use:focusInput />
                  {:else}
                    <button type="button" class="cell-text" disabled={readOnly} onclick={() => startEdit(rowId, colId)} onfocus={() => select(rowId, colId)}>{displaySheetValue(cell?.display ?? '', format)}</button>
                  {/if}
                  {#if cell?.suggestion}
                    <span class="suggestion" data-testid="sheet-live-suggestion">
                      <span class="suggestion-value">{cell.suggestion.assistant_value}</span>
                      {#if !readOnly}
                        <button type="button" class="mini" data-testid="sheet-live-suggestion-accept" title={$text('embed_user_edits.live_suggestion_accept')} aria-label={$text('embed_user_edits.live_suggestion_accept')}
                          onclick={() => send({ op: 'set_cell', row_id: rowId, col_id: colId, value: cell.suggestion?.assistant_value ?? '' })}>✓</button>
                        <button type="button" class="mini" data-testid="sheet-live-suggestion-dismiss" title={$text('embed_user_edits.live_suggestion_dismiss')} aria-label={$text('embed_user_edits.live_suggestion_dismiss')}
                          onclick={() => send({ op: 'dismiss_suggestion', row_id: rowId, col_id: colId })}>✕</button>
                      {/if}
                    </span>
                  {/if}
                  {#if lead}
                    <span class="peer-label" data-testid="sheet-live-peer" style:background={lead.color}>
                      {peerMate(lead) ? $text('embed_user_edits.live_editing_here', { values: { name: peerMate(lead) } }) : lead.display_name}
                    </span>
                  {/if}
                </td>
                {/if}
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .live-sheet { width: 100%; }
  .live-sheet-scroll { overflow: auto; }
  .live-sheet:has(.formatted) .live-sheet-scroll { max-block-size: 65dvh; }
  .live-sheet-table { border-collapse: collapse; width: 100%; font-size: var(--font-size-small); color: var(--color-font-primary); }
  .live-sheet-table.formatted { table-layout: fixed; border-collapse: separate; border-spacing: 0; }
  th, td { border: 1px solid var(--color-grey-30); padding: 0; min-width: 96px; height: 34px; position: relative; text-align: left; vertical-align: middle; }
  .gutter { min-width: 56px; width: 56px; background: var(--color-grey-10); color: var(--color-font-secondary); text-align: center; }
  .head { background: var(--color-grey-10); font-weight: 600; }
  .col-letter { display: block; font-size: 11px; font-weight: 400; color: var(--color-font-tertiary); padding: 0 var(--spacing-3); }
  .head-text, .cell-text, .head-input, .cell-input { width: 100%; min-width: 0; min-height: 0; margin: 0; border: 0; background: transparent; color: inherit; font: inherit; text-align: inherit; padding: var(--spacing-2) var(--spacing-3); box-sizing: border-box; cursor: pointer; }
  .cell-text { height: 100%; min-height: 32px; }
  .formatted :is(th, td) { min-width: 0; overflow-wrap: anywhere; }
  .formatted .cell-text { white-space: inherit; }
  .pinned-row, .pinned-column { position: sticky; z-index: var(--z-index-raised); }
  .pinned-row.pinned-column, .pinned-row.gutter { z-index: var(--z-index-raised-2); }
  .cell.pinned-row, .cell.pinned-column { background-color: var(--color-grey-0); }
  .formatted .gutter { position: sticky; left: 0; z-index: var(--z-index-raised); }
  .cell-input, .head-input { cursor: text; outline: 2px solid var(--color-primary-start); outline-offset: -2px; background: var(--color-grey-0); }
  .cell-text:focus-visible, .head-text:focus-visible { outline: 2px solid var(--color-primary-start); outline-offset: -2px; }
  .cell.peer-here { outline: 2px solid; outline-offset: -2px; }
  .cell.suggested { background: color-mix(in srgb, var(--color-primary-start) 12%, transparent); outline: 1px dashed var(--color-primary-start); outline-offset: -2px; }
  .peer-label { position: absolute; top: -1.3em; left: -1px; z-index: 2; padding: 0 var(--spacing-2); border-radius: 3px 3px 3px 0; color: #fff; font-size: 11px; font-weight: 600; white-space: nowrap; pointer-events: none; }
  .suggestion { display: flex; align-items: center; gap: var(--spacing-2); padding: 0 var(--spacing-3) var(--spacing-2); font-style: italic; color: var(--color-font-secondary); }
  .line-actions { display: inline-flex; gap: 2px; }
  .head .line-actions { position: absolute; top: 2px; right: 2px; }
  .gutter .line-actions { display: flex; justify-content: center; }
  .mini { min-width: 0; min-height: 0; width: 20px; height: 20px; margin: 0; padding: 0; border: 0; border-radius: 50%; background: var(--color-grey-20); color: var(--color-font-primary); font-size: 12px; line-height: 1; cursor: pointer; }
  .mini:hover { background: var(--color-grey-30); }
</style>
