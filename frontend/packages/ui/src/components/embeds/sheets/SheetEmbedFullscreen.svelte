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
  import { restorePIIInText, replacePIIOriginalsWithPlaceholders } from '../../enter_message/services/piiDetectionService';
  import { piiVisibilityStore } from '../../../stores/piiVisibilityStore';
  import type { PIIMapping } from '../../../types/chat';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { replaceEmbedLinksInText, hydrateEmbedLinks, stripEmbedLinks } from '../../../utils/embedLinkUtils';

  /**
   * Props for sheet embed fullscreen
   */
  interface Props {
    /** Standardized raw embed data (decodedContent, attrs, embedData) */
    data: EmbedFullscreenRawData;
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
    /** Direction of navigation ('previous' | 'next') — set transiently during prev/next transitions */
    navigateDirection?: 'previous' | 'next';
    /** Whether to show the "chat" button */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
    /**
     * PII mappings from the parent chat — maps placeholder strings (e.g. "[EMAIL_com]")
     * to original values. When provided and piiRevealed is true, placeholder strings
     * in the table content are replaced with originals for display.
     */
    piiMappings?: PIIMapping[];
    /**
     * Whether PII originals are currently visible.
     * When false (default), placeholder strings like [EMAIL_com] are shown as-is.
     * When true, placeholders are replaced with original values.
     * This is the initial value — the user can toggle locally in fullscreen.
     */
    piiRevealed?: boolean;
    /** Current chat ID — required for piiVisibilityStore.toggle(chatId). See OPE-400. */
    chatId?: string;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
    piiMappings = [],
    piiRevealed = false,
    chatId
  }: Props = $props();

  // ── Extract fields from data.decodedContent (with attrs fallback) ───────────

  let dc = $derived(data.decodedContent);
  let attrs = $derived(data.attrs);
  let tableContent = $derived(
      typeof dc.table === 'string' ? dc.table
      : typeof dc.code === 'string' ? dc.code
      : typeof attrs?.code === 'string' ? attrs.code as string
      : ''
    );
  let title = $derived(
      typeof dc.title === 'string' ? dc.title
      : typeof attrs?.title === 'string' ? attrs.title as string
      : ''
    );
  let rowCount = $derived(
      typeof dc.row_count === 'number' ? dc.row_count
      : typeof dc.rows === 'number' ? dc.rows
      : typeof attrs?.rows === 'number' ? attrs.rows as number
      : 0
    );
  let colCount = $derived(
      typeof dc.col_count === 'number' ? dc.col_count
      : typeof dc.cols === 'number' ? dc.cols
      : typeof attrs?.cols === 'number' ? attrs.cols as number
      : 0
    );

  // Single source of truth: piiRevealed flows down from piiVisibilityStore via
  // the parent (ActiveChat); togglePII() writes back to the same store so the
  // chat header and embed fullscreen stay in sync. See OPE-400.
  /** Whether there are any PII mappings to apply (controls button visibility) */
  let hasPII = $derived(piiMappings.length > 0);

  function togglePII() {
    if (!chatId) return;
    piiVisibilityStore.toggle(chatId);
  }

  /**
   * Apply PII masking to the raw markdown table string before parsing.
   * When piiRevealed is true, restore originals; otherwise keep placeholders.
   */
  let piiProcessedTableContent = $derived.by(() => {
    if (!hasPII || !tableContent) return tableContent;
    if (piiRevealed) {
      return restorePIIInText(tableContent, piiMappings);
    } else {
      return replacePIIOriginalsWithPlaceholders(tableContent, piiMappings);
    }
  });
  
  // Parse table content (with PII masking applied)
  let parsedContent = $derived.by(() => parseSheetEmbedContent(piiProcessedTableContent, { title }));
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
  
  /**
   * Compute per-column pixel widths from content length.
   * Scans all display rows to find the longest value per column,
   * then maps char count → pixels (8px/char) clamped to [80, 320].
   * Applied via <colgroup> so the browser respects fixed widths while
   * still allowing the table to scroll horizontally for wide data.
   */
  let colWidths = $derived.by(() => {
    return parsedTable.headers.map((header, i) => {
      const headerLen = header.content.length;
      const maxDataLen = displayRows.reduce((max, row) => {
        const len = row[i]?.content?.length ?? 0;
        return len > max ? len : max;
      }, 0);
      const chars = Math.max(headerLen, maxDataLen);
      return Math.min(Math.max(chars * 8, 80), 320);
    });
  });

  // Build status text
  let statusText = $derived.by(() => {
    if (actualRowCount === 0 && actualColCount === 0) return '';
    const dims = formatTableDimensions(actualRowCount, actualColCount);
    if (hasActiveFilters && filteredRowCount !== actualRowCount) {
      return `${dims} (${filteredRowCount} shown)`;
    }
    return dims;
  });
  
  const skillIconName = 'table';
  
  // ── Embed inline link hydration ────────────────────────────
  // After the table DOM renders, find placeholder spans and mount
  // EmbedInlineLink Svelte components into them for interactivity.
  let tableContainerEl: HTMLDivElement | undefined = $state(undefined);
  
  $effect(() => {
    // Re-run whenever displayRows or tableContainerEl changes
    void displayRows;
    const cleanup = hydrateEmbedLinks(tableContainerEl);
    return cleanup;
  });
  
  /**
   * Copy table as TSV to clipboard.
   * TSV (tab-separated values) is what Excel and Google Sheets expect on paste.
   * Uses the PII-processed display rows (originals or placeholders per piiRevealed).
   */
  async function handleCopy() {
    try {
      // Strip embed link markdown syntax before export so TSV contains clean text
      const cleanHeaders = parsedTable.headers.map(h => ({ ...h, content: stripEmbedLinks(h.content) }));
      const cleanRows = displayRows.map(row => row.map(cell => ({ ...cell, content: stripEmbedLinks(cell.content) })));
      const tsv = tableToTSV(cleanHeaders, cleanRows);
      const clipResult = await copyToClipboard(tsv);
      if (!clipResult.success) throw new Error(clipResult.error || 'Copy failed');
      console.warn('[SheetEmbedFullscreen] Copied table as TSV to clipboard');
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
      // Strip embed link markdown syntax before export so XLSX contains clean text
      const cleanHeaders = parsedTable.headers.map(h => ({ ...h, content: stripEmbedLinks(h.content) }));
      const cleanRows = displayRows.map(row => row.map(cell => ({ ...cell, content: stripEmbedLinks(cell.content) })));
      const blob = await tableToXlsx(cleanHeaders, cleanRows, sheetName);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${renderTitle || 'table'}.xlsx`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      console.warn('[SheetEmbedFullscreen] Downloaded table as .xlsx');
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
  showSkillIcon={false}

  embedHeaderTitle={renderTitle || $text('embeds.table')}
  embedHeaderSubtitle={statusText}
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="sheet-fullscreen">
      <!-- PII reveal toggle bar — shown when the table contains PII placeholders -->
      {#if hasPII}
        <div class="sheet-pii-bar">
          <button
            data-testid="embed-pii-toggle"
            data-pii-revealed={piiRevealed ? 'true' : 'false'}
            class="pii-toggle-btn"
            class:pii-toggle-active={piiRevealed}
            onclick={togglePII}
            aria-label={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
            title={piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}
          >
            {#if piiRevealed}
              <!-- Eye-off icon: click to hide -->
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
                <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
                <line x1="1" y1="1" x2="23" y2="23"/>
              </svg>
            {:else}
              <!-- Eye icon: click to reveal -->
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                <circle cx="12" cy="12" r="3"/>
              </svg>
            {/if}
            <span>{piiRevealed ? $text('embeds.pii_hide') : $text('embeds.pii_show')}</span>
          </button>
        </div>
      {/if}
      
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
      <div class="spreadsheet-wrapper" bind:this={tableContainerEl}>
        {#if parsedTable.headers.length > 0}
          <table class="spreadsheet">
            <colgroup>
              <!-- Row-number gutter: fixed 40px -->
              <col style="width: 40px; min-width: 40px; max-width: 40px;" />
              {#each colWidths as w}
                <col style="width: {w}px; max-width: {w}px;" />
              {/each}
            </colgroup>
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
                    {@const embedHtml = replaceEmbedLinksInText(cell.content)}
                    {#if embedHtml}
                      <!-- Cell contains embed links — render as HTML with placeholders -->
                      <!-- eslint-disable-next-line svelte/no-at-html-tags -- Content is HTML-escaped via embedLinkUtils.escapeHtml() -->
                      <td>{@html embedHtml}</td>
                    {:else}
                      <td>{cell.content}</td>
                    {/if}
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
     Theme-adaptive: uses CSS custom properties for dark mode.
     ═══════════════════════════════════════════════════════════ */
  
  /* ── Override parent UnifiedEmbedFullscreen backgrounds to sheet bg ── */
  /* The parent overlay, content-area and bottom gradient default to
     var(--color-grey-20) (dark grey). For the spreadsheet look we match
     the page background colour so the table edge aligns cleanly.
     We target the parent classes via :global() from within this scope. */
  .sheet-fullscreen {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow: hidden;
  }
  
  /* Bottom gradient → fade to page background instead of grey */
  :global(.unified-embed-fullscreen-overlay:has(.sheet-fullscreen) .bottom-gradient) {
    background: linear-gradient(to bottom, transparent 0%, var(--color-grey-0) 100%) !important;
  }
  
  /* ── PII toggle bar ──────────────────────────────────── */

  .sheet-pii-bar {
    flex-shrink: 0;
    padding: var(--spacing-3) var(--spacing-6);
    background: var(--color-grey-10);
    border-bottom: 1px solid var(--color-grey-25);
    display: flex;
    align-items: center;
  }

  .pii-toggle-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-3);
    padding: var(--spacing-2) var(--spacing-5);
    border-radius: var(--radius-1);
    border: none;
    background: var(--color-grey-20);
    color: var(--color-font-secondary);
    cursor: pointer;
    font-size: var(--font-size-xxs);
    font-weight: 500;
    transition: background-color var(--duration-fast), color var(--duration-fast);
  }

  .pii-toggle-btn:hover {
    background: var(--color-grey-25);
    color: var(--color-font-primary);
  }

  .pii-toggle-btn.pii-toggle-active {
    background: var(--color-warning-bg);
    color: var(--color-warning);
  }

  .pii-toggle-btn.pii-toggle-active:hover {
    background: var(--color-warning-bg);
    opacity: 0.8;
  }

  /* ── Filter bar ────────────────────────────────────────── */
  
  .filter-bar {
    flex-shrink: 0;
    padding: var(--spacing-3) var(--spacing-6);
    background: var(--color-grey-10);
    border-bottom: 1px solid var(--color-grey-25);
  }
  
  .filter-bar-inner {
    display: flex;
    gap: var(--spacing-3);
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
    padding: var(--spacing-2) var(--spacing-4);
    border: 1px solid var(--color-grey-30);
    border-radius: 3px;
    font-size: var(--font-size-xxs);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-sizing: border-box;
  }
  
  .filter-input:focus {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px rgba(var(--color-primary-rgb, 74, 144, 226), 0.15);
  }
  
  .filter-input::placeholder {
    color: var(--color-font-tertiary);
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
    color: var(--color-error);
    cursor: pointer;
  }
  
  .filter-clear-btn:hover {
    background: var(--color-error-light);
  }
  
  /* ── Spreadsheet wrapper — scrolls both axes ───────────── */
  
  .spreadsheet-wrapper {
    flex: 1;
    overflow: auto;
    /* Top padding to clear the floating top-bar buttons (~70px) */
    padding-top: 70px;
  }
  
  /* ── Table: theme-adaptive, thin grid, no rounding ──────── */
  
  .spreadsheet {
    border-collapse: collapse;
    font-size: var(--font-size-xs);
    line-height: 1.4;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    /* Do NOT set width: 100% — let columns size naturally so wide tables scroll */
    /* white-space is NOT set here — data cells wrap, header cells use nowrap below */
  }
  
  /* Headers never wrap — ellipsis is handled on .col-header-text */
  .spreadsheet thead th {
    white-space: nowrap;
  }
  
  /* All cells: thin grey border on every edge */
  .spreadsheet th,
  .spreadsheet td {
    border: 1px solid var(--color-grey-25);
    padding: var(--spacing-3) var(--spacing-6);
    text-align: left;
    vertical-align: top;
    color: var(--color-font-primary);
  }
  
  /* ── Header rows ─────────────────────────────────────── */
  
  .spreadsheet thead th {
    background: var(--color-grey-10);
    font-weight: 600;
    color: var(--color-font-primary);
    position: sticky;
    z-index: var(--z-index-raised-2);
  }
  
  /* Column letter row (A, B, C...) — sits at the very top */
  .col-letter-row th {
    top: 0;
    border-bottom: 1px solid var(--color-grey-30);
    font-weight: 500;
    font-size: var(--font-size-tiny);
    color: var(--color-font-tertiary);
    padding: var(--spacing-1) var(--spacing-6);
    text-align: center;
  }
  
  .col-letter-gutter {
    /* Sticky in both directions (top + left) */
    z-index: var(--z-index-raised-3) !important;
  }
  
  .col-letter {
    user-select: none;
  }
  
  /* Data header row — offset below the column-letter row */
  .spreadsheet thead tr:nth-child(2) th {
    /* Height of col-letter row: ~24px (2px padding + 11px font + borders) */
    top: 25px;
    border-bottom: 2px solid var(--color-grey-30);
  }
  
  .col-header {
    cursor: pointer;
    user-select: none;
    min-width: 80px;
    max-width: 320px;
  }
  
  .col-header:hover {
    background: var(--color-grey-20);
  }
  
  .col-header-content {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-2);
  }
  
  .col-header-text {
    overflow: hidden;
    text-overflow: ellipsis;
    /* Allow header text to be selected/copied */
    user-select: text;
    -webkit-user-select: text;
    -moz-user-select: text;
    -ms-user-select: text;
  }
  
  .sort-icon {
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
    color: var(--color-font-secondary);
  }
  
  .sort-icon-active {
    color: var(--color-primary);
  }
  
  /* ── Row number gutter ──────────────────────────────── */
  
  .row-num-header,
  .row-num {
    background: var(--color-grey-10);
    color: var(--color-font-tertiary);
    text-align: center;
    font-size: var(--font-size-tiny);
    width: 40px;
    min-width: 40px;
    max-width: 40px;
    padding: var(--spacing-3) var(--spacing-2);
    user-select: none;
    border-right: 2px solid var(--color-grey-30);
  }
  
  /* Keep gutter sticky on horizontal scroll */
  .row-num-header,
  .row-num {
    position: sticky;
    left: 0;
    z-index: var(--z-index-raised);
  }
  
  .row-num-header {
    z-index: var(--z-index-raised-3); /* Above both sticky header row and sticky gutter column */
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
    color: var(--color-font-tertiary);
    cursor: pointer;
    margin: 0 auto;
  }
  
  .filter-toggle:hover {
    background: var(--color-grey-20);
    color: var(--color-font-secondary);
  }
  
  .filter-toggle-active {
    background: rgba(var(--color-primary-rgb, 74, 144, 226), 0.12);
    color: var(--color-primary);
  }
  
  .filter-toggle-active:hover {
    background: rgba(var(--color-primary-rgb, 74, 144, 226), 0.22);
  }
  
  /* ── Data cells ─────────────────────────────────────── */
  
  .spreadsheet tbody td {
    color: var(--color-font-primary);
    /* Allow text selection so users can copy cell content */
    user-select: text;
    -webkit-user-select: text;
    -moz-user-select: text;
    -ms-user-select: text;
    /* Wrap long text — fullscreen has vertical space; don't truncate */
    white-space: normal;
    word-break: break-word;
    max-width: 320px;
  }
  
  /* Subtle alternating row colour for readability */
  .spreadsheet tbody tr:nth-child(even) td:not(.row-num) {
    background: var(--color-grey-10);
  }
  
  .spreadsheet tbody tr:hover td:not(.row-num) {
    background: rgba(var(--color-primary-rgb, 74, 144, 226), 0.07);
  }
  
  .spreadsheet tbody tr:nth-child(even):hover td:not(.row-num) {
    background: rgba(var(--color-primary-rgb, 74, 144, 226), 0.07);
  }
  
  /* ── No-results row ────────────────────────────────── */
  
  .no-results {
    text-align: center;
    padding: var(--spacing-12) var(--spacing-8);
    color: var(--color-font-tertiary);
    font-style: italic;
    background: var(--color-grey-0) !important;
  }
  
  /* ── Empty state ───────────────────────────────────── */
  
  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 200px;
    color: var(--color-font-tertiary);
    background: var(--color-grey-0);
  }
  
  .empty-state p {
    font-size: var(--font-size-small);
    margin: 0;
  }
  
  /* ── Inline embed links inside cells ───────────────── */
  
  .spreadsheet-wrapper :global(.embed-inline-link) {
    white-space: nowrap;
  }
  
  /* ── Responsive ────────────────────────────────────── */
  
  @media (max-width: 768px) {
    .spreadsheet {
      font-size: var(--font-size-xxs);
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
      font-size: null;
    }
    
    .filter-field {
      min-width: 80px;
    }
  }

  /* Dark mode: no overrides needed — base styles use CSS custom properties
     (var(--color-grey-*), var(--color-font-*)) that flip automatically with
     [data-theme="dark"]. */
</style>
