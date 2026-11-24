/** Props for the standalone sheet formatting toolbar preview. */
const action = (name: string) => (value?: unknown) => console.info('Sheet format preview', name, JSON.stringify(value));

export default {
  selection: 'B2',
  cellStyle: { bold: true, numberFormat: { kind: 'currency' as const, currency: 'USD', decimals: 2 } },
  columnWidth: 140,
  rowHeight: 32,
  frozenRows: 1,
  columnCount: 5,
  rowCount: 20,
  canMerge: true,
  canUndoFormatting: true,
  onStyle: action('style'),
  onColumnWidth: action('column width'),
  onRowHeight: action('row height'),
  onFrozenRows: action('frozen rows'),
  onFrozenColumns: action('frozen columns'),
  onMerge: action('merge'),
  onUnmerge: action('unmerge'),
  onUndoFormatting: action('undo formatting'),
};
