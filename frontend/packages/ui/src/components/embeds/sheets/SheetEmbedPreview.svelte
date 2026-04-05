<!--
  frontend/packages/ui/src/components/embeds/sheets/SheetEmbedPreview.svelte
  
  Preview component for Sheet/Table embeds.
  Uses UnifiedEmbedPreview as base and provides table-specific details content.
  
  Design: Matches the fullscreen Excel/Google Sheets style
  - Always white background regardless of dark mode
  - Thin grey grid lines, light header row
  - Horizontal scroll for wide tables (no squeezing columns)
  - Shows first few preview rows with "+N more rows" indicator
  
  Details content structure:
  - Processing: "Generating..." placeholder
  - Finished: Preview of first few rows of the table
  - Error: Empty placeholder with table icon
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { parseSheetEmbedContent, formatTableDimensions } from './sheetEmbedContent';
  import { restorePIIInText, replacePIIOriginalsWithPlaceholders } from '../../enter_message/services/piiDetectionService';
  import { stripEmbedLinks } from '../../../utils/embedLinkUtils';
  import { embedPIIStore } from '../../../stores/embedPIIStore';
  
  /**
   * Props for sheet embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Table title */
    title?: string;
    /** Number of rows in the table */
    rowCount?: number;
    /** Number of columns in the table */
    colCount?: number;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
    /** Table content (markdown format) */
    tableContent?: string;
  }
  
  let {
    id,
    title: titleProp,
    rowCount: rowCountProp = 0,
    colCount: colCountProp = 0,
    status: statusProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen,
    tableContent: tableContentProp = ''
  }: Props = $props();
  
  // Local reactive state — can be updated via onEmbedDataUpdated callback
  let localTableContent = $state<string>('');
  let localTitle = $state<string | undefined>(undefined);
  let localRowCount = $state<number>(0);
  let localColCount = $state<number>(0);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localTaskId = $state<string | undefined>(undefined);

  // Track whether the store has resolved a terminal status for this embed.
  // Once handleEmbedDataUpdated receives "finished"/"error", the $effect must NOT
  // revert to statusProp (which may still be "processing" from the HTML attribute).
  let storeResolved = $state(false);

  // Initialize local state from props — but only when the store hasn't resolved yet.
  $effect(() => {
    if (!storeResolved) {
      localTableContent = tableContentProp || '';
      localTitle = titleProp;
      localRowCount = rowCountProp || 0;
      localColCount = colCountProp || 0;
      localStatus = statusProp || 'processing';
      localTaskId = taskIdProp;
    }
  });
  
  // Use local state as source of truth
  let tableContent = $derived(localTableContent);
  let title = $derived(localTitle);
  let rowCount = $derived(localRowCount);
  let colCount = $derived(localColCount);
  let status = $derived(localStatus);
  let taskId = $derived(localTaskId);
  
  // Maximum rows to show in preview
  // Large variant (400px container) shows more rows to fill the taller space
  const MAX_PREVIEW_ROWS_STANDARD = 4;
  const MAX_PREVIEW_ROWS_LARGE = 8;

  // isLargePreview is set reactively from the snippet param (isLarge)
  let isLargePreview = $state(false);
  let maxPreviewRows = $derived(isLargePreview ? MAX_PREVIEW_ROWS_LARGE : MAX_PREVIEW_ROWS_STANDARD);
  
  // Subscribe to the global embed PII store to get the current chat's PII state.
  // This allows the preview to reactively apply PII masking without needing
  // to receive props from the parent (previews are mounted imperatively via mount()).
  let embedPIIState = $state({ mappings: [] as import('../../../types/chat').PIIMapping[], revealed: false });
  $effect(() => {
    const unsub = embedPIIStore.subscribe((state) => { embedPIIState = state; });
    return unsub;
  });

  /**
   * Apply PII masking to the raw markdown table string before parsing.
   * Mirrors the same logic in SheetEmbedFullscreen.
   */
  let piiProcessedTableContent = $derived.by(() => {
    const { mappings, revealed } = embedPIIState;
    if (!mappings.length || !tableContent) return tableContent;
    if (revealed) {
      return restorePIIInText(tableContent, mappings);
    } else {
      return replacePIIOriginalsWithPlaceholders(tableContent, mappings);
    }
  });

  // Parse table content (with PII masking applied)
  let parsedContent = $derived.by(() => parseSheetEmbedContent(piiProcessedTableContent, { title }));
  let renderTitle = $derived(parsedContent.title);
  let parsedTable = $derived(parsedContent.parsedTable);
  
  // Get actual row/col counts
  let actualRowCount = $derived(rowCount > 0 ? rowCount : parsedTable.rowCount);
  let actualColCount = $derived(colCount > 0 ? colCount : parsedTable.colCount);
  
  // Get preview rows
  let previewRows = $derived(parsedTable.rows.slice(0, maxPreviewRows));
  let hasMoreRows = $derived(parsedTable.rowCount > maxPreviewRows);
  
  /**
   * Compute per-column pixel widths from content length.
   * Scans header + preview rows to find the longest value per column,
   * then maps char count → pixels (8px/char) clamped to [60, 200].
   * Replaces the old table-layout:fixed equal-split approach.
   */
  let colWidths = $derived.by(() => {
    return parsedTable.headers.map((header, i) => {
      const headerLen = header.content.length;
      const maxDataLen = previewRows.reduce((max, row) => {
        const len = row[i]?.content?.length ?? 0;
        return len > max ? len : max;
      }, 0);
      const chars = Math.max(headerLen, maxDataLen);
      return Math.min(Math.max(chars * 8, 60), 200);
    });
  });

  /**
   * Limit visible columns in the preview so no column is squeezed unreadable.
   * Standard preview card is ~260px wide (300px card - padding/border).
   * In large preview mode, we measure the actual container width to show more columns.
   * We greedily include columns whose cumulative width fits, then show "+N cols".
   */
  const PREVIEW_CARD_WIDTH_STANDARD = 260;
  let measuredContainerWidth = $state(0);
  let columnBudget = $derived(
    isLargePreview && measuredContainerWidth > 0
      ? measuredContainerWidth - 20
      : PREVIEW_CARD_WIDTH_STANDARD
  );
  let visibleColCount = $derived.by(() => {
    let budget = columnBudget;
    let count = 0;
    for (const w of colWidths) {
      if (budget - w < 0 && count > 0) break;
      budget -= w;
      count++;
    }
    return Math.max(count, 1);
  });
  let hiddenColCount = $derived(parsedTable.headers.length - visibleColCount);
  let visibleColWidths = $derived(colWidths.slice(0, visibleColCount));
  let visibleHeaders = $derived(parsedTable.headers.slice(0, visibleColCount));

  // Build skill name for BasicInfosBar
  let skillName = $derived.by(() => renderTitle || $text('embeds.table'));
  
  // Build status text: dimensions
  let statusText = $derived.by(() => {
    if (actualRowCount === 0 && actualColCount === 0) return '';
    return formatTableDimensions(actualRowCount, actualColCount);
  });
  
  const skillIconName = 'table';
  
  /**
   * Handle embed data updates from server
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
      // Mark store-resolved for terminal statuses so $effect won't revert on re-render
      if (data.status !== 'processing') {
        storeResolved = true;
      }
    }
    
    if (data.decodedContent) {
      const c = data.decodedContent;
      // TOON content uses 'table' field; legacy/fallback uses 'code'
      localTableContent = String(c.table || c.code || c.content || '');
      if (c.title) localTitle = String(c.title);
      // TOON content uses row_count/col_count; legacy uses rows/cols
      if (typeof c.row_count === 'number') localRowCount = c.row_count;
      else if (typeof c.rows === 'number') localRowCount = c.rows;
      if (typeof c.col_count === 'number') localColCount = c.col_count;
      else if (typeof c.cols === 'number') localColCount = c.cols;
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="sheets"
  skillId="sheet"
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileSnippet, isLarge: isLargeSnippet })}
    {(isLargePreview = isLargeSnippet, undefined)}
    <div class="sheet-preview" class:mobile={isMobileSnippet} bind:clientWidth={measuredContainerWidth}>
      {#if status === 'processing'}
        <!-- Skeleton loading -->
        <div class="skeleton-table">
          <div class="skeleton-row header">
            <div class="skeleton-cell"></div>
            <div class="skeleton-cell"></div>
            <div class="skeleton-cell"></div>
          </div>
          <div class="skeleton-row"><div class="skeleton-cell"></div><div class="skeleton-cell"></div><div class="skeleton-cell"></div></div>
          <div class="skeleton-row"><div class="skeleton-cell"></div><div class="skeleton-cell"></div><div class="skeleton-cell"></div></div>
        </div>
      {:else if status === 'finished' && parsedTable.headers.length > 0}
        <!-- Table preview — scrolls horizontally for wide tables -->
        <div class="table-scroll">
          <table class="preview-table" class:large-desktop={isLargeSnippet && !isMobileSnippet}>
            <colgroup>
              {#each visibleColWidths as w}
                <col style="width: {w}px; max-width: {w}px;" />
              {/each}
            </colgroup>
            <thead>
              <tr>
                {#each visibleHeaders as header}
                  <th>{header.content}</th>
                {/each}
                {#if hiddenColCount > 0}
                  <th class="more-cols-header">+{hiddenColCount}</th>
                {/if}
              </tr>
            </thead>
            <tbody>
              {#each previewRows as row}
                <tr>
                  {#each row.slice(0, visibleColCount) as cell}
                    <td>{stripEmbedLinks(cell.content)}</td>
                  {/each}
                  {#if hiddenColCount > 0}
                    <td class="more-cols-cell"></td>
                  {/if}
                </tr>
              {/each}
              {#if hasMoreRows}
                <tr class="more-rows">
                  <td colspan={visibleColCount + (hiddenColCount > 0 ? 1 : 0)}>
                    <span class="more-indicator">+{parsedTable.rowCount - maxPreviewRows} more rows</span>
                  </td>
                </tr>
              {/if}
            </tbody>
          </table>
        </div>
      {:else}
        <!-- Error or empty state -->
        <div class="empty-state">
          <span class="empty-icon">📊</span>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ═══════════════════════════════════════════════════════════
     Sheet Preview — compact Excel-like table, theme-adaptive.
     Uses CSS custom properties so dark mode renders correctly.
     ═══════════════════════════════════════════════════════════ */
  
  .sheet-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 0;
    box-sizing: border-box;
  }
  
  /* ── Skeleton loading ────────────────────────────────── */
  
  .skeleton-table {
    display: flex;
    flex-direction: column;
    gap: 3px;
    width: 100%;
    padding: var(--spacing-3);
    box-sizing: border-box;
    background: var(--color-grey-0);
  }
  
  .skeleton-row {
    display: flex;
    gap: 3px;
  }
  
  .skeleton-row.header .skeleton-cell {
    background: var(--color-grey-30);
  }
  
  .skeleton-cell {
    flex: 1;
    height: 18px;
    background: var(--color-grey-20);
    border-radius: 2px;
    animation: pulse 1.5s ease-in-out infinite;
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }
  
  /* ── Table scroll container — overflow hidden, no scrollbar ──
     Preview is a static snapshot. Only fullscreen can scroll. */
  
  .table-scroll {
    width: 100%;
    flex: 1;
    overflow: hidden;
  }
  
  /* ── Preview table — edge-to-edge, fills available width ── */
  
  .preview-table {
    border-collapse: collapse;
    font-size: var(--font-size-tiny);
    line-height: 1.3;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    /* Auto-layout: colgroup widths drive column sizing, not equal-split fixed.
       min-width:100% fills the container; max-content lets wide tables overflow
       (the table-scroll wrapper clips them without a visible scrollbar). */
    width: max-content;
    min-width: 100%;
    table-layout: auto;
    margin-top: 15px;
  }

  .preview-table.large-desktop {
    font-size: var(--font-size-xs);
  }
  
  .preview-table th,
  .preview-table td {
    border: 1px solid var(--color-grey-25);
    padding: var(--spacing-2) var(--spacing-4);
    text-align: left;
    color: var(--color-font-primary);
  }
  
  .preview-table th {
    background: var(--color-grey-10);
    font-weight: 600;
    color: var(--color-font-primary);
    border-bottom: 2px solid var(--color-grey-30);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .preview-table td {
    color: var(--color-font-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .preview-table tbody tr:nth-child(even) td {
    background: var(--color-grey-10);
  }
  
  .preview-table tbody tr:last-child td {
    border-bottom: none;
  }
  
  /* ── More columns indicator ─────────────────────────── */

  .more-cols-header,
  .more-cols-cell {
    width: 28px;
    min-width: 28px;
    max-width: 28px;
    padding: var(--spacing-2) var(--spacing-2);
    text-align: center;
    white-space: nowrap;
  }

  .more-cols-header {
    background: var(--color-grey-10);
    color: var(--color-font-tertiary);
    font-size: var(--font-size-micro);
    font-weight: 600;
    letter-spacing: 0.02em;
    border-left: 2px solid var(--color-grey-30);
  }

  .more-cols-cell {
    background: var(--color-grey-10);
    border-left: 2px solid var(--color-grey-30);
  }

  /* ── More rows indicator ────────────────────────────── */
  
  .more-rows td {
    text-align: center !important;
    padding: 3px 8px;
    background: var(--color-grey-10) !important;
    border-top: 1px solid var(--color-grey-25);
  }
  
  .more-indicator {
    color: var(--color-font-tertiary);
    font-size: null;
    font-style: italic;
  }
  
  /* ── Empty state ───────────────────────────────────── */
  
  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    min-height: 80px;
    background: var(--color-grey-0);
  }
  
  .empty-icon {
    font-size: var(--font-size-xxxl);
    opacity: 0.5;
  }
  
  /* ── Mobile ────────────────────────────────────────── */
  
  .mobile .preview-table {
    font-size: null;
  }
  
  .mobile .preview-table th,
  .mobile .preview-table td {
    padding: 3px 6px;
    max-width: 80px;
  }

  /* ══════════════════════════════════════════════════════════
     Dark mode — spreadsheet-style dark (see screenshot)
     Background: near-black, header: dark grey, green accents.
     Uses CSS custom properties so values stay in sync with the
     theme system (vars flip automatically in [data-theme="dark"]).
     ══════════════════════════════════════════════════════════ */

  :global(.dark) .skeleton-table {
    background: var(--color-grey-10);
  }

  :global(.dark) .skeleton-row.header .skeleton-cell {
    background: var(--color-grey-30);
  }

  :global(.dark) .skeleton-cell {
    background: var(--color-grey-20);
  }

  :global(.dark) .preview-table th,
  :global(.dark) .preview-table td {
    border-color: var(--color-grey-30);
    color: var(--color-grey-80);
  }

  :global(.dark) .preview-table th {
    background: var(--color-grey-25);
    color: var(--color-grey-80);
    font-weight: 700;
    border-bottom-color: var(--color-grey-40);
  }

  :global(.dark) .preview-table td {
    color: var(--color-grey-80);
  }

  :global(.dark) .preview-table tbody tr:nth-child(even) td {
    background: var(--color-grey-20);
  }

  :global(.dark) .more-rows td {
    background: var(--color-grey-25) !important;
    border-top-color: var(--color-grey-30);
  }

  :global(.dark) .more-indicator {
    color: var(--color-grey-50);
  }

  :global(.dark) .empty-state {
    background: var(--color-grey-10);
  }
</style>
