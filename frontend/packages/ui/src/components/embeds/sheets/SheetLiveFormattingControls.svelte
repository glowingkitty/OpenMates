<script lang="ts">
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import type { LiveStatus } from '../../../services/live/liveItemTypes';
  import SheetFormattingToolbar from './SheetFormattingToolbar.svelte';
  import { colIndexToLetter } from './sheetEmbedContent';
  import type { SheetFormatting } from './sheetFormattingTypes';
  import type { LiveSheetAddress, LiveSheetFormatChange } from './sheetLiveTypes';
  import type { createSheetFormattingBridge } from './sheetFormattingBridge';

  interface Props {
    bridge: ReturnType<typeof createSheetFormattingBridge>;
    status: LiveStatus;
    mergeStart?: LiveSheetAddress | null;
  }
  let { bridge, status, mergeStart = $bindable(null) }: Props = $props();
  let view = $derived(bridge.view);
  let selection = $derived(bridge.selection);
  let format = $derived($view?.formatting as SheetFormatting | undefined);
  let row = $derived($selection?.rowId ? ($view?.rows.indexOf($selection.rowId) ?? -1) + 2 : 1);
  let column = $derived($selection ? ($view?.cols.indexOf($selection.colId) ?? -1) : -1);
  let letter = $derived(column >= 0 ? colIndexToLetter(column) : '');
  let address = $derived(letter && (!$selection?.rowId || row > 1) ? `${letter}${row}` : undefined);
  let merge = $derived(format?.merges?.find((range) => range.start === address));
  let disabled = $derived(!$view || status === 'read_only' || status === 'access_revoked');

  async function apply(changes: LiveSheetFormatChange[]) {
    try { await bridge.applyFormatting(changes); }
    catch { notificationStore.error($text('embeds.sheets.sheet.formatting_failed')); }
  }

  async function undo() {
    try { await bridge.undoFormatting(); }
    catch { notificationStore.error($text('embeds.sheets.sheet.formatting_failed')); }
  }
</script>

{#if $view}
  <SheetFormattingToolbar
    selection={address}
    cellStyle={address ? format?.cells?.[address] : undefined}
    columnWidth={format?.columnWidths?.[letter]}
    rowHeight={format?.rowHeights?.[String(row)]}
    frozenRows={format?.frozenRows}
    frozenColumns={format?.frozenColumns}
    rowCount={$view.rows.length + 1}
    columnCount={$view.cols.length}
    canMerge={!!address && !merge}
    canUnmerge={!!merge}
    choosingMergeEnd={!!mergeStart}
    canUndoFormatting={$view.canUndoFormatting}
    {disabled}
    onStyle={(patch) => { if ($selection) void apply([{ kind: 'cellStyle', cell: $selection, patch }]); }}
    onColumnWidth={(value) => { if ($selection) void apply([{ kind: 'columnWidth', colId: $selection.colId, value }]); }}
    onRowHeight={(value) => { if ($selection) void apply([{ kind: 'rowHeight', rowId: $selection.rowId, value }]); }}
    onFrozenRows={(value) => void apply([{ kind: 'frozenRows', value }])}
    onFrozenColumns={(value) => void apply([{ kind: 'frozenColumns', value }])}
    onMerge={() => { mergeStart = $selection; }}
    onUnmerge={() => { if ($selection) void apply([{ kind: 'merge', start: $selection, end: null }]); }}
    onCancelMerge={() => { mergeStart = null; }}
    onUndoFormatting={() => void undo()}
  />
{/if}
