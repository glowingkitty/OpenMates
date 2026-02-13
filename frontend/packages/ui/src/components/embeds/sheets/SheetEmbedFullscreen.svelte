<!--
  frontend/packages/ui/src/components/embeds/sheets/SheetEmbedFullscreen.svelte
  
  Fullscreen view for Sheet/Table embeds.
  Uses UnifiedEmbedFullscreen as base and provides table-specific content.
  
  Shows:
  - Table title and dimensions in header
  - Full scrollable table with column sorting and per-column text filtering
  - Copy as CSV / Markdown buttons, Download CSV button
  - Basic infos bar at the bottom
  
  Sorting: Click column headers to cycle through ascending → descending → none.
  Filtering: Toggle filter row via toolbar button. Type in filter inputs to
  match rows whose cell content includes the filter text (case-insensitive).
  All operations are performed on in-memory arrays — no external dependencies.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import { 
    parseSheetEmbedContent, 
    formatTableDimensions, 
    type TableCell
  } from './sheetEmbedContent';
  
  /**
   * Props for sheet embed fullscreen
   */
  interface Props {
    /** Table title */
    title?: string;
    /** Number of rows */
    rowCount?: number;
    /** Number of columns */
    colCount?: number;
    /** Table content (markdown format) */
    tableContent: string;
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Whether to show the "chat" button */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
  }
  
  let {
    title = '',
    rowCount = 0,
    colCount = 0,
    tableContent,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat
  }: Props = $props();
  
  // Parse table content
  let parsedContent = $derived.by(() => parseSheetEmbedContent(tableContent, { title }));
  let renderTitle = $derived(parsedContent.title);
  let parsedTable = $derived(parsedContent.parsedTable);
  let renderMarkdown = $derived(parsedContent.markdown);
  
  // Get actual dimensions
  let actualRowCount = $derived(rowCount > 0 ? rowCount : parsedTable.rowCount);
  let actualColCount = $derived(colCount > 0 ? colCount : parsedTable.colCount);
  
  // ── Sorting state ──────────────────────────────────────────────────
  // sortColumnIndex: which column is sorted (-1 = none)
  // sortDirection: 'asc' | 'desc' | 'none'
  let sortColumnIndex = $state(-1);
  let sortDirection = $state<'asc' | 'desc' | 'none'>('none');
  
  /**
   * Cycle sort direction for a column header click.
   * Clicking the same column cycles: none → asc → desc → none.
   * Clicking a different column starts at asc.
   */
  function handleSortClick(colIndex: number) {
    if (sortColumnIndex !== colIndex) {
      // New column — start ascending
      sortColumnIndex = colIndex;
      sortDirection = 'asc';
    } else {
      // Same column — cycle
      if (sortDirection === 'asc') {
        sortDirection = 'desc';
      } else if (sortDirection === 'desc') {
        sortDirection = 'none';
        sortColumnIndex = -1;
      } else {
        sortDirection = 'asc';
      }
    }
  }
  
  // ── Filtering state ────────────────────────────────────────────────
  // One filter string per column. Empty string = no filter for that column.
  let showFilters = $state(false);
  let columnFilters = $state<string[]>([]);
  
  // Reset filters when the table content changes (e.g. navigating between embeds)
  $effect(() => {
    // Access parsedTable to track it as a dependency
    const colCount = parsedTable.headers.length;
    columnFilters = new Array(colCount).fill('');
    sortColumnIndex = -1;
    sortDirection = 'none';
  });
  
  /** Check whether any column filter is active */
  let hasActiveFilters = $derived(columnFilters.some(f => f.length > 0));
  
  /**
   * Clear all column filters
   */
  function clearFilters() {
    columnFilters = columnFilters.map(() => '');
  }
  
  // ── Derived: filtered + sorted rows ────────────────────────────────
  /**
   * Apply column filters and sorting to produce the visible rows.
   * All operations are pure array transforms — no mutation of parsedTable.
   */
  let displayRows = $derived.by(() => {
    let rows = parsedTable.rows;
    
    // 1. Filter: keep rows where every column with a non-empty filter matches
    if (hasActiveFilters) {
      rows = rows.filter(row => {
        return columnFilters.every((filter, colIdx) => {
          if (!filter) return true;
          const cellContent = row[colIdx]?.content ?? '';
          return cellContent.toLowerCase().includes(filter.toLowerCase());
        });
      });
    }
    
    // 2. Sort by selected column
    if (sortColumnIndex >= 0 && sortDirection !== 'none') {
      const col = sortColumnIndex;
      const dir = sortDirection === 'asc' ? 1 : -1;
      
      // Spread to avoid mutating the original array
      rows = [...rows].sort((a, b) => {
        const aVal = a[col]?.content ?? '';
        const bVal = b[col]?.content ?? '';
        
        // Try numeric comparison first
        const aNum = Number(aVal);
        const bNum = Number(bVal);
        if (!isNaN(aNum) && !isNaN(bNum) && aVal !== '' && bVal !== '') {
          return (aNum - bNum) * dir;
        }
        
        // Fall back to locale-aware string comparison
        return aVal.localeCompare(bVal) * dir;
      });
    }
    
    return rows;
  });
  
  /** How many rows are visible after filtering (used in status text) */
  let filteredRowCount = $derived(displayRows.length);
  
  // Build skill name for BasicInfosBar
  let skillName = $derived.by(() => {
    if (renderTitle) {
      return renderTitle;
    }
    return $text('embeds.table.text');
  });
  
  // Build status text — show filtered count when filters are active
  let statusText = $derived.by(() => {
    if (actualRowCount === 0 && actualColCount === 0) return '';
    const dims = formatTableDimensions(actualRowCount, actualColCount);
    if (hasActiveFilters && filteredRowCount !== actualRowCount) {
      return `${dims} (${filteredRowCount} shown)`;
    }
    return dims;
  });
  
  // No header title in fullscreen (buttons overlay the top area)
  const fullscreenTitle = '';
  
  // Icon for tables
  const skillIconName = 'table';
  
  /**
   * Copy table as CSV to clipboard
   */
  async function handleCopyCSV() {
    try {
      const csv = displayRowsToCSV(parsedTable.headers, displayRows);
      await navigator.clipboard.writeText(csv);
      console.debug('[SheetEmbedFullscreen] Copied table as CSV to clipboard');
      notificationStore.success('Table copied to clipboard as CSV');
    } catch (error) {
      console.error('[SheetEmbedFullscreen] Failed to copy table:', error);
      notificationStore.error('Failed to copy table to clipboard');
    }
  }
  
  /**
   * Copy table as markdown to clipboard
   */
  async function handleCopyMarkdown() {
    try {
      await navigator.clipboard.writeText(renderMarkdown);
      console.debug('[SheetEmbedFullscreen] Copied table as markdown to clipboard');
      notificationStore.success('Table copied to clipboard as Markdown');
    } catch (error) {
      console.error('[SheetEmbedFullscreen] Failed to copy table:', error);
      notificationStore.error('Failed to copy table to clipboard');
    }
  }
  
  /**
   * Download table as CSV file.
   * When filters/sorting are active, exports only the visible rows.
   */
  async function handleDownloadCSV() {
    try {
      const csv = displayRowsToCSV(parsedTable.headers, displayRows);
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${renderTitle || 'table'}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      console.debug('[SheetEmbedFullscreen] Downloaded table as CSV');
      notificationStore.success('Table downloaded as CSV');
    } catch (error) {
      console.error('[SheetEmbedFullscreen] Failed to download table:', error);
      notificationStore.error('Failed to download table');
    }
  }
  
  /**
   * Convert headers + display rows (possibly filtered/sorted) to CSV string.
   */
  function displayRowsToCSV(headers: TableCell[], rows: TableCell[][]): string {
    const lines: string[] = [];
    lines.push(headers.map(h => escapeCSVCell(h.content)).join(','));
    for (const row of rows) {
      lines.push(row.map(cell => escapeCSVCell(cell.content)).join(','));
    }
    return lines.join('\n');
  }
  
  /**
   * Escape a cell value for CSV output.
   */
  function escapeCSVCell(value: string): string {
    if (value.includes(',') || value.includes('"') || value.includes('\n')) {
      return `"${value.replace(/"/g, '""')}"`;
    }
    return value;
  }
</script>

<UnifiedEmbedFullscreen
  appId="sheets"
  skillId="sheet"
  {skillIconName}
  {skillName}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
  title={fullscreenTitle}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="sheet-fullscreen">
      <!-- Action buttons -->
      <div class="action-buttons">
        <button class="action-btn" onclick={handleCopyCSV} title="Copy as CSV">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          <span>Copy CSV</span>
        </button>
        <button class="action-btn" onclick={handleCopyMarkdown} title="Copy as Markdown">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          <span>Copy Markdown</span>
        </button>
        <button class="action-btn" onclick={handleDownloadCSV} title="Download CSV">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7 10 12 15 17 10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
          </svg>
          <span>Download</span>
        </button>
        
        <!-- Separator -->
        <div class="action-separator"></div>
        
        <!-- Filter toggle button -->
        <button
          class="action-btn"
          class:action-btn-active={showFilters}
          onclick={() => { showFilters = !showFilters; if (!showFilters) clearFilters(); }}
          title="Toggle column filters"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
          </svg>
          <span>Filter</span>
        </button>
        
        <!-- Clear filters (only shown when filters are active) -->
        {#if hasActiveFilters}
          <button class="action-btn action-btn-clear" onclick={clearFilters} title="Clear all filters">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
            <span>Clear</span>
          </button>
        {/if}
      </div>
      
      <!-- Table content -->
      <div class="table-wrapper">
        {#if parsedTable.headers.length > 0}
          <table class="fullscreen-table">
            <thead>
              <!-- Header row with sort controls -->
              <tr>
                {#each parsedTable.headers as header, i}
                  <th
                    style:text-align={header.align || 'left'}
                    class="sortable-header"
                    onclick={() => handleSortClick(i)}
                    title="Click to sort"
                  >
                    <span class="header-content">
                      <span class="col-index">#{i + 1}</span>
                      <span class="header-text">{header.content}</span>
                      <span class="sort-indicator" class:sort-active={sortColumnIndex === i && sortDirection !== 'none'}>
                        {#if sortColumnIndex === i && sortDirection === 'asc'}
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <polyline points="18 15 12 9 6 15"></polyline>
                          </svg>
                        {:else if sortColumnIndex === i && sortDirection === 'desc'}
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <polyline points="6 9 12 15 18 9"></polyline>
                          </svg>
                        {:else}
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3">
                            <polyline points="8 10 12 6 16 10"></polyline>
                            <polyline points="8 14 12 18 16 14"></polyline>
                          </svg>
                        {/if}
                      </span>
                    </span>
                  </th>
                {/each}
              </tr>
              
              <!-- Filter row (toggled by filter button) -->
              {#if showFilters}
                <tr class="filter-row">
                  {#each parsedTable.headers as header, i}
                    <th class="filter-cell">
                      <input
                        type="text"
                        class="filter-input"
                        placeholder="Filter {header.content}..."
                        bind:value={columnFilters[i]}
                      />
                    </th>
                  {/each}
                </tr>
              {/if}
            </thead>
            <tbody>
              {#each displayRows as row}
                <tr>
                  {#each row as cell}
                    <td style:text-align={cell.align || 'left'}>{cell.content}</td>
                  {/each}
                </tr>
              {/each}
              
              <!-- Empty filtered state -->
              {#if displayRows.length === 0 && parsedTable.rows.length > 0}
                <tr>
                  <td colspan={parsedTable.headers.length} class="no-results">
                    No rows match the current filters
                  </td>
                </tr>
              {/if}
            </tbody>
          </table>
        {:else}
          <div class="empty-state">
            <span class="empty-icon">📊</span>
            <p>No table data available</p>
          </div>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .sheet-fullscreen {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }
  
  /* Action buttons */
  .action-buttons {
    display: flex;
    gap: 8px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--color-grey-15, #f0f0f0);
    background: var(--color-grey-5, #fafafa);
    flex-shrink: 0;
  }
  
  .action-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    border: 1px solid var(--color-grey-20, #eaeaea);
    border-radius: 6px;
    background: var(--color-grey-0, #fff);
    color: var(--color-grey-70, #444);
    font-size: 13px;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  
  .action-btn:hover {
    background: var(--color-grey-10, #f5f5f5);
    border-color: var(--color-grey-30, #d0d0d0);
  }
  
  .action-btn:active {
    transform: scale(0.98);
  }
  
  .action-btn svg {
    flex-shrink: 0;
  }
  
  .action-btn-active {
    background: var(--color-primary-10, #e8f0fe);
    border-color: var(--color-primary-50, #4285f4);
    color: var(--color-primary-60, #1a73e8);
  }
  
  .action-btn-active:hover {
    background: var(--color-primary-15, #d2e3fc);
  }
  
  .action-btn-clear {
    color: var(--color-error-50, #d93025);
    border-color: var(--color-error-30, #f5c6c2);
  }
  
  .action-btn-clear:hover {
    background: var(--color-error-5, #fef0ef);
    border-color: var(--color-error-50, #d93025);
  }
  
  .action-separator {
    width: 1px;
    align-self: stretch;
    margin: 4px 4px;
    background: var(--color-grey-20, #eaeaea);
  }
  
  /* Table wrapper */
  .table-wrapper {
    flex: 1;
    overflow: auto;
    padding: 16px;
  }
  
  .fullscreen-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    line-height: 1.5;
    background: var(--color-grey-0, #fff);
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  }
  
  .fullscreen-table th,
  .fullscreen-table td {
    padding: 12px 16px;
    border-bottom: 1px solid var(--color-grey-15, #f0f0f0);
    border-right: 1px solid var(--color-grey-10, #f5f5f5);
  }
  
  .fullscreen-table th:last-child,
  .fullscreen-table td:last-child {
    border-right: none;
  }
  
  .fullscreen-table th {
    background: var(--color-grey-10, #f5f5f5);
    font-weight: 600;
    color: var(--color-grey-90, #1a1a1a);
    position: sticky;
    top: 0;
    z-index: 1;
  }
  
  .col-index {
    font-size: 10px;
    color: var(--color-grey-40, #999);
    margin-right: 6px;
    font-weight: 400;
  }
  
  /* Sortable headers */
  .sortable-header {
    cursor: pointer;
    user-select: none;
  }
  
  .sortable-header:hover {
    background: var(--color-grey-15, #f0f0f0);
  }
  
  .header-content {
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }
  
  .header-text {
    flex: 1;
  }
  
  .sort-indicator {
    display: inline-flex;
    align-items: center;
    margin-left: 4px;
    flex-shrink: 0;
  }
  
  .sort-active {
    color: var(--color-primary-60, #1a73e8);
  }
  
  /* Filter row */
  .filter-row th {
    padding: 4px 8px;
    background: var(--color-grey-5, #fafafa);
    border-bottom: 2px solid var(--color-primary-30, #a8c7fa);
  }
  
  .filter-cell {
    font-weight: 400;
  }
  
  .filter-input {
    width: 100%;
    padding: 4px 8px;
    border: 1px solid var(--color-grey-20, #eaeaea);
    border-radius: 4px;
    font-size: 12px;
    background: var(--color-grey-0, #fff);
    color: var(--color-grey-80, #333);
    outline: none;
    box-sizing: border-box;
  }
  
  .filter-input:focus {
    border-color: var(--color-primary-50, #4285f4);
    box-shadow: 0 0 0 2px var(--color-primary-10, #e8f0fe);
  }
  
  .filter-input::placeholder {
    color: var(--color-grey-40, #999);
  }
  
  /* No results row */
  .no-results {
    text-align: center;
    padding: 24px 16px;
    color: var(--color-grey-50, #888);
    font-style: italic;
  }
  
  .fullscreen-table td {
    color: var(--color-grey-80, #333);
  }
  
  .fullscreen-table tbody tr:hover {
    background: var(--color-grey-5, #fafafa);
  }
  
  .fullscreen-table tbody tr:last-child td {
    border-bottom: none;
  }
  
  /* Alternating row colors */
  .fullscreen-table tbody tr:nth-child(even) {
    background: var(--color-grey-3, #fcfcfc);
  }
  
  .fullscreen-table tbody tr:nth-child(even):hover {
    background: var(--color-grey-8, #f7f7f7);
  }
  
  /* Empty state */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 200px;
    color: var(--color-grey-50, #888);
  }
  
  .empty-icon {
    font-size: 48px;
    margin-bottom: 16px;
    opacity: 0.5;
  }
  
  .empty-state p {
    font-size: 14px;
    margin: 0;
  }
  
  /* Dark mode */
  :global(.dark) .action-buttons {
    background: var(--color-grey-90, #1a1a1a);
    border-bottom-color: var(--color-grey-80, #333);
  }
  
  :global(.dark) .action-btn {
    background: var(--color-grey-85, #252525);
    border-color: var(--color-grey-75, #404040);
    color: var(--color-grey-30, #d0d0d0);
  }
  
  :global(.dark) .action-btn:hover {
    background: var(--color-grey-80, #333);
    border-color: var(--color-grey-60, #666);
  }
  
  :global(.dark) .action-btn-active {
    background: var(--color-primary-90, #1a2744);
    border-color: var(--color-primary-50, #4285f4);
    color: var(--color-primary-30, #a8c7fa);
  }
  
  :global(.dark) .action-btn-active:hover {
    background: var(--color-primary-85, #1e3050);
  }
  
  :global(.dark) .action-btn-clear {
    color: var(--color-error-40, #f28b82);
    border-color: var(--color-error-80, #5c2624);
  }
  
  :global(.dark) .action-btn-clear:hover {
    background: var(--color-error-90, #3c1513);
    border-color: var(--color-error-40, #f28b82);
  }
  
  :global(.dark) .action-separator {
    background: var(--color-grey-75, #404040);
  }
  
  :global(.dark) .fullscreen-table {
    background: var(--color-grey-90, #1a1a1a);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  }
  
  :global(.dark) .fullscreen-table th {
    background: var(--color-grey-85, #252525);
    color: var(--color-grey-10, #f5f5f5);
    border-bottom-color: var(--color-grey-75, #404040);
  }
  
  :global(.dark) .fullscreen-table td {
    color: var(--color-grey-20, #eaeaea);
    border-bottom-color: var(--color-grey-80, #333);
    border-right-color: var(--color-grey-85, #252525);
  }
  
  :global(.dark) .fullscreen-table tbody tr:hover {
    background: var(--color-grey-85, #252525);
  }
  
  :global(.dark) .fullscreen-table tbody tr:nth-child(even) {
    background: var(--color-grey-88, #202020);
  }
  
  :global(.dark) .fullscreen-table tbody tr:nth-child(even):hover {
    background: var(--color-grey-83, #282828);
  }
  
  :global(.dark) .col-index {
    color: var(--color-grey-60, #666);
  }
  
  :global(.dark) .sortable-header:hover {
    background: var(--color-grey-80, #333);
  }
  
  :global(.dark) .sort-active {
    color: var(--color-primary-30, #a8c7fa);
  }
  
  :global(.dark) .filter-row th {
    background: var(--color-grey-88, #202020);
    border-bottom-color: var(--color-primary-70, #2b5797);
  }
  
  :global(.dark) .filter-input {
    background: var(--color-grey-85, #252525);
    border-color: var(--color-grey-70, #444);
    color: var(--color-grey-20, #eaeaea);
  }
  
  :global(.dark) .filter-input:focus {
    border-color: var(--color-primary-50, #4285f4);
    box-shadow: 0 0 0 2px var(--color-primary-90, #1a2744);
  }
  
  :global(.dark) .filter-input::placeholder {
    color: var(--color-grey-60, #666);
  }
  
  :global(.dark) .no-results {
    color: var(--color-grey-50, #888);
  }
  
  /* Responsive */
  @media (max-width: 768px) {
    .action-buttons {
      padding: 8px 12px;
      gap: 6px;
      flex-wrap: wrap;
    }
    
    .action-btn {
      padding: 6px 10px;
      font-size: 12px;
    }
    
    .action-btn span {
      display: none;
    }
    
    .table-wrapper {
      padding: 12px;
    }
    
    .fullscreen-table {
      font-size: 12px;
    }
    
    .fullscreen-table th,
    .fullscreen-table td {
      padding: 8px 12px;
    }
  }
</style>
