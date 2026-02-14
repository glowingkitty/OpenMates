<!--
  frontend/packages/ui/src/components/embeds/sheets/SheetEmbedFullscreen.svelte
  
  Fullscreen view for Sheet/Table embeds.
  Uses UnifiedEmbedFullscreen as base and provides table-specific content.
  
  Design: Excel/Google Sheets-like appearance
  - Always white background regardless of dark mode (like real spreadsheet software)
  - Thin grey grid lines on all cell borders
  - Light grey header row with bold text
  - Row numbers in a fixed left gutter column
  - Horizontal + vertical scrolling for wide/tall tables (no squeezing)
  - Column sorting (click headers to cycle asc → desc → none)
  - Per-column text filtering (toggle via filter button in the action bar)
  
  Copy/Download:
  - Copy button copies TSV (tab-separated) — pastes correctly into Excel/Sheets
  - Download button exports .xlsx (Office Open XML) — opens natively in Excel/Sheets
  - Both are wired through UnifiedEmbedFullscreen's onCopy/onDownload props
    (uses the standard top-bar icon buttons, no custom text toolbar)
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import { 
    parseSheetEmbedContent, 
    formatTableDimensions, 
    tableToTSV,
    tableToXlsx,
    colIndexToLetter,
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
  
  // Get actual dimensions
  let actualRowCount = $derived(rowCount > 0 ? rowCount : parsedTable.rowCount);
  let actualColCount = $derived(colCount > 0 ? colCount : parsedTable.colCount);
  
  // ── Sorting state ──────────────────────────────────────────────────
  let sortColumnIndex = $state(-1);
  let sortDirection = $state<'asc' | 'desc' | 'none'>('none');
  
  /**
   * Cycle sort direction for a column header click.
   * Same column: none → asc → desc → none. Different column: start at asc.
   */
  function handleSortClick(colIndex: number) {
    if (sortColumnIndex !== colIndex) {
      sortColumnIndex = colIndex;
      sortDirection = 'asc';
    } else {
      if (sortDirection === 'asc') sortDirection = 'desc';
      else if (sortDirection === 'desc') { sortDirection = 'none'; sortColumnIndex = -1; }
      else sortDirection = 'asc';
    }
  }
  
  // ── Filtering state ────────────────────────────────────────────────
  let showFilters = $state(false);
  let columnFilters = $state<string[]>([]);
  
  // Reset filters when table changes
  $effect(() => {
    const cols = parsedTable.headers.length;
    columnFilters = new Array(cols).fill('');
    sortColumnIndex = -1;
    sortDirection = 'none';
  });
  
  let hasActiveFilters = $derived(columnFilters.some(f => f.length > 0));
  
  function clearFilters() {
    columnFilters = columnFilters.map(() => '');
  }
  
  // ── Derived: filtered + sorted rows ────────────────────────────────
  let displayRows = $derived.by(() => {
    let rows = parsedTable.rows;
    
    // Filter
    if (hasActiveFilters) {
      rows = rows.filter(row =>
        columnFilters.every((filter, colIdx) => {
          if (!filter) return true;
          const cellContent = row[colIdx]?.content ?? '';
          return cellContent.toLowerCase().includes(filter.toLowerCase());
        })
      );
    }
    
    // Sort
    if (sortColumnIndex >= 0 && sortDirection !== 'none') {
      const col = sortColumnIndex;
      const dir = sortDirection === 'asc' ? 1 : -1;
      rows = [...rows].sort((a, b) => {
        const aVal = a[col]?.content ?? '';
        const bVal = b[col]?.content ?? '';
        const aNum = Number(aVal);
        const bNum = Number(bVal);
        if (!isNaN(aNum) && !isNaN(bNum) && aVal !== '' && bVal !== '') {
          return (aNum - bNum) * dir;
        }
        return aVal.localeCompare(bVal) * dir;
      });
    }
    
    return rows;
  });
  
  let filteredRowCount = $derived(displayRows.length);
  
  // Build skill name for BasicInfosBar
  let skillName = $derived.by(() => renderTitle || $text('embeds.table'));
  
  // Build status text
  let statusText = $derived.by(() => {
    if (actualRowCount === 0 && actualColCount === 0) return '';
    const dims = formatTableDimensions(actualRowCount, actualColCount);
    if (hasActiveFilters && filteredRowCount !== actualRowCount) {
      return `${dims} (${filteredRowCount} shown)`;
    }
    return dims;
  });
  
  // No header title in fullscreen
  const fullscreenTitle = '';
  const skillIconName = 'table';
  
  /**
   * Copy table as TSV to clipboard.
   * TSV (tab-separated values) is what Excel and Google Sheets expect on paste.
   */
  async function handleCopy() {
    try {
      const tsv = tableToTSV(parsedTable.headers, displayRows);
      await navigator.clipboard.writeText(tsv);
      console.debug('[SheetEmbedFullscreen] Copied table as TSV to clipboard');
      notificationStore.success('Table copied — paste into Excel or Google Sheets');
    } catch (error) {
      console.error('[SheetEmbedFullscreen] Failed to copy table:', error);
      notificationStore.error('Failed to copy table to clipboard');
    }
  }
  
  /**
   * Download table as .xlsx file.
   * Generates a minimal Office Open XML workbook using zero external dependencies.
   * When filters/sorting are active, exports only the visible rows.
   */
  async function handleDownload() {
    try {
      const sheetName = renderTitle || 'Table';
      const blob = await tableToXlsx(parsedTable.headers, displayRows, sheetName);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${renderTitle || 'table'}.xlsx`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      console.debug('[SheetEmbedFullscreen] Downloaded table as .xlsx');
      notificationStore.success('Table downloaded as .xlsx');
    } catch (error) {
      console.error('[SheetEmbedFullscreen] Failed to download table:', error);
      notificationStore.error('Failed to download table');
    }
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
  onCopy={handleCopy}
  onDownload={handleDownload}
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
      <!-- Filter action bar — only shown when filter is toggled on -->
      {#if showFilters}
        <div class="filter-bar">
          <div class="filter-bar-inner">
            {#each parsedTable.headers as header, i}
              <div class="filter-field">
                <input
                  type="text"
                  class="filter-input"
                  placeholder={header.content}
                  bind:value={columnFilters[i]}
                />
              </div>
            {/each}
            {#if hasActiveFilters}
              <button class="filter-clear-btn" onclick={clearFilters} title="Clear all filters" aria-label="Clear all filters">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            {/if}
          </div>
        </div>
      {/if}
      
      <!-- Spreadsheet area — scrolls both directions -->
      <div class="spreadsheet-wrapper">
        {#if parsedTable.headers.length > 0}
          <table class="spreadsheet">
            <thead>
              <!-- Column letter row (A, B, C...) — Excel-style -->
              <tr class="col-letter-row">
                <th class="row-num-header col-letter-gutter">
                  <!-- Filter toggle lives in the gutter -->
                  <button
                    class="filter-toggle"
                    class:filter-toggle-active={showFilters}
                    onclick={() => { showFilters = !showFilters; if (!showFilters) clearFilters(); }}
                    title="Toggle column filters"
                    aria-label="Toggle column filters"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
                    </svg>
                  </button>
                </th>
                {#each Array.from({ length: parsedTable.headers.length }, (__, i) => i) as colIdx}
                  <th class="col-letter">{colIndexToLetter(colIdx)}</th>
                {/each}
              </tr>
              <!-- Data header row (actual column names) -->
              <tr>
                <th class="row-num-header"></th>
                {#each parsedTable.headers as header, i}
                  <th
                    class="col-header"
                    onclick={() => handleSortClick(i)}
                    title="Click to sort"
                  >
                    <span class="col-header-content">
                      <span class="col-header-text">{header.content}</span>
                      <span class="sort-icon" class:sort-icon-active={sortColumnIndex === i && sortDirection !== 'none'}>
                        {#if sortColumnIndex === i && sortDirection === 'asc'}
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="18 15 12 9 6 15"></polyline></svg>
                        {:else if sortColumnIndex === i && sortDirection === 'desc'}
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="6 9 12 15 18 9"></polyline></svg>
                        {:else}
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.35"><polyline points="8 10 12 6 16 10"></polyline><polyline points="8 14 12 18 16 14"></polyline></svg>
                        {/if}
                      </span>
                    </span>
                  </th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each displayRows as row, rowIndex}
                <tr>
                  <td class="row-num">{rowIndex + 1}</td>
                  {#each row as cell}
                    <td>{cell.content}</td>
                  {/each}
                </tr>
              {/each}
              
              {#if displayRows.length === 0 && parsedTable.rows.length > 0}
                <tr>
                  <td colspan={parsedTable.headers.length + 1} class="no-results">
                    No rows match the current filters
                  </td>
                </tr>
              {/if}
            </tbody>
          </table>
        {:else}
          <div class="empty-state">
            <p>No table data available</p>
          </div>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ═══════════════════════════════════════════════════════════
     Sheet Fullscreen — Excel / Google Sheets inspired design
     Always white background, thin grid lines, row numbers.
     ═══════════════════════════════════════════════════════════ */
  
  /* ── Override parent UnifiedEmbedFullscreen backgrounds to white ── */
  /* The parent overlay, content-area and bottom gradient default to
     var(--color-grey-20) (dark grey). For the spreadsheet look we need
     everything white. We target the parent classes via :global() from
     within this component's scope. */
  .sheet-fullscreen {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }
  
  /* Parent overlay container → white */
  :global(.unified-embed-fullscreen-overlay:has(.sheet-fullscreen)) {
    background-color: #ffffff !important;
  }
  
  /* Bottom gradient → fade to white instead of grey */
  :global(.unified-embed-fullscreen-overlay:has(.sheet-fullscreen) .bottom-gradient) {
    background: linear-gradient(to bottom, transparent 0%, #ffffff 100%) !important;
  }
  
  /* Top-bar button wrappers → white background to match */
  :global(.unified-embed-fullscreen-overlay:has(.sheet-fullscreen) .button-wrapper) {
    background-color: #f0f0f0 !important;
  }
  
  /* ── Filter bar ────────────────────────────────────────── */
  
  .filter-bar {
    flex-shrink: 0;
    padding: 6px 12px;
    background: #f8f9fa;
    border-bottom: 1px solid #e0e0e0;
  }
  
  .filter-bar-inner {
    display: flex;
    gap: 6px;
    align-items: center;
    overflow-x: auto;
  }
  
  .filter-field {
    flex: 0 0 auto;
    min-width: 100px;
    max-width: 180px;
  }
  
  .filter-input {
    width: 100%;
    padding: 4px 8px;
    border: 1px solid #d0d0d0;
    border-radius: 3px;
    font-size: 12px;
    background: #fff;
    color: #333;
    outline: none;
    box-sizing: border-box;
  }
  
  .filter-input:focus {
    border-color: #1a73e8;
    box-shadow: 0 0 0 2px rgba(26, 115, 232, 0.15);
  }
  
  .filter-input::placeholder {
    color: #999;
  }
  
  .filter-clear-btn {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border: none;
    border-radius: 3px;
    background: transparent;
    color: #d93025;
    cursor: pointer;
  }
  
  .filter-clear-btn:hover {
    background: #fce8e6;
  }
  
  /* ── Spreadsheet wrapper — scrolls both axes ───────────── */
  
  .spreadsheet-wrapper {
    flex: 1;
    overflow: auto;
    /* Top padding to clear the floating top-bar buttons (~70px) */
    padding-top: 70px;
  }
  
  /* ── Table: always white, thin grid, no rounding ──────── */
  
  .spreadsheet {
    border-collapse: collapse;
    font-size: 13px;
    line-height: 1.4;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    /* Do NOT set width: 100% — let columns size naturally so wide tables scroll */
    white-space: nowrap;
    background: #ffffff;
  }
  
  /* All cells: thin grey border on every edge */
  .spreadsheet th,
  .spreadsheet td {
    border: 1px solid #e2e2e2;
    padding: 6px 12px;
    text-align: left;
    color: #202124;
  }
  
  /* ── Header rows ─────────────────────────────────────── */
  
  .spreadsheet thead th {
    background: #f8f9fa;
    font-weight: 600;
    color: #202124;
    position: sticky;
    z-index: 2;
  }
  
  /* Column letter row (A, B, C...) — sits at the very top */
  .col-letter-row th {
    top: 0;
    border-bottom: 1px solid #dadce0;
    font-weight: 500;
    font-size: 11px;
    color: #80868b;
    padding: 2px 12px;
    text-align: center;
  }
  
  .col-letter-gutter {
    /* Sticky in both directions (top + left) */
    z-index: 3 !important;
  }
  
  .col-letter {
    user-select: none;
  }
  
  /* Data header row — offset below the column-letter row */
  .spreadsheet thead tr:nth-child(2) th {
    /* Height of col-letter row: ~24px (2px padding + 11px font + borders) */
    top: 25px;
    border-bottom: 2px solid #dadce0;
  }
  
  .col-header {
    cursor: pointer;
    user-select: none;
    min-width: 80px;
  }
  
  .col-header:hover {
    background: #eef1f5;
  }
  
  .col-header-content {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  
  .col-header-text {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .sort-icon {
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
    color: #5f6368;
  }
  
  .sort-icon-active {
    color: #1a73e8;
  }
  
  /* ── Row number gutter ──────────────────────────────── */
  
  .row-num-header,
  .row-num {
    background: #f8f9fa;
    color: #80868b;
    text-align: center;
    font-size: 11px;
    width: 40px;
    min-width: 40px;
    max-width: 40px;
    padding: 6px 4px;
    user-select: none;
    border-right: 2px solid #dadce0;
  }
  
  /* Keep gutter sticky on horizontal scroll */
  .row-num-header,
  .row-num {
    position: sticky;
    left: 0;
    z-index: 1;
  }
  
  .row-num-header {
    z-index: 3; /* Above both sticky header row and sticky gutter column */
  }
  
  /* Filter toggle button inside the row-number gutter header */
  .filter-toggle {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border: none;
    border-radius: 3px;
    background: transparent;
    color: #80868b;
    cursor: pointer;
    margin: 0 auto;
  }
  
  .filter-toggle:hover {
    background: #e8eaed;
    color: #5f6368;
  }
  
  .filter-toggle-active {
    background: #e8f0fe;
    color: #1a73e8;
  }
  
  .filter-toggle-active:hover {
    background: #d2e3fc;
  }
  
  /* ── Data cells ─────────────────────────────────────── */
  
  .spreadsheet tbody td {
    color: #202124;
  }
  
  /* Subtle alternating row colour for readability */
  .spreadsheet tbody tr:nth-child(even) td:not(.row-num) {
    background: #f8f9fb;
  }
  
  .spreadsheet tbody tr:hover td:not(.row-num) {
    background: #e8f0fe;
  }
  
  .spreadsheet tbody tr:nth-child(even):hover td:not(.row-num) {
    background: #e8f0fe;
  }
  
  /* ── No-results row ────────────────────────────────── */
  
  .no-results {
    text-align: center;
    padding: 24px 16px;
    color: #80868b;
    font-style: italic;
    background: #fff !important;
  }
  
  /* ── Empty state ───────────────────────────────────── */
  
  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 200px;
    color: #80868b;
    background: #fff;
  }
  
  .empty-state p {
    font-size: 14px;
    margin: 0;
  }
  
  /* ── Responsive ────────────────────────────────────── */
  
  @media (max-width: 768px) {
    .spreadsheet {
      font-size: 12px;
    }
    
    .spreadsheet th,
    .spreadsheet td {
      padding: 5px 8px;
    }
    
    .row-num-header,
    .row-num {
      width: 32px;
      min-width: 32px;
      max-width: 32px;
      font-size: 10px;
    }
    
    .filter-field {
      min-width: 80px;
    }
  }
</style>
