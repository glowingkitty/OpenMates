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
    onFullscreen?: () => void;
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
  
  // Initialize local state from props
  $effect(() => {
    localTableContent = tableContentProp || '';
    localTitle = titleProp;
    localRowCount = rowCountProp || 0;
    localColCount = colCountProp || 0;
    localStatus = statusProp || 'processing';
    localTaskId = taskIdProp;
  });
  
  // Use local state as source of truth
  let tableContent = $derived(localTableContent);
  let title = $derived(localTitle);
  let rowCount = $derived(localRowCount);
  let colCount = $derived(localColCount);
  let status = $derived(localStatus);
  let taskId = $derived(localTaskId);
  
  // Maximum rows to show in preview
  const MAX_PREVIEW_ROWS = 4;
  
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
  let previewRows = $derived(parsedTable.rows.slice(0, MAX_PREVIEW_ROWS));
  let hasMoreRows = $derived(parsedTable.rowCount > MAX_PREVIEW_ROWS);
  
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
    console.debug('[SheetEmbedPreview] Received embed data update:', {
      embedId: id,
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
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
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="sheet-preview" class:mobile={isMobileSnippet}>
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
          <table class="preview-table">
            <thead>
              <tr>
                {#each parsedTable.headers as header}
                  <th>{header.content}</th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each previewRows as row}
                <tr>
                  {#each row as cell}
                    <td>{cell.content}</td>
                  {/each}
                </tr>
              {/each}
              {#if hasMoreRows}
                <tr class="more-rows">
                  <td colspan={actualColCount}>
                    <span class="more-indicator">+{parsedTable.rowCount - MAX_PREVIEW_ROWS} more rows</span>
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
     Sheet Preview — compact Excel-like table, always white.
     ═══════════════════════════════════════════════════════════ */
  
  .sheet-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 0;
    box-sizing: border-box;
    background: #ffffff;
  }
  
  /* ── Skeleton loading ────────────────────────────────── */
  
  .skeleton-table {
    display: flex;
    flex-direction: column;
    gap: 3px;
    width: 100%;
    padding: 6px;
    box-sizing: border-box;
    background: #fff;
  }
  
  .skeleton-row {
    display: flex;
    gap: 3px;
  }
  
  .skeleton-row.header .skeleton-cell {
    background: #e8e8e8;
  }
  
  .skeleton-cell {
    flex: 1;
    height: 18px;
    background: #f0f0f0;
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
    background: #ffffff;
  }
  
  /* ── Preview table — edge-to-edge, fills available width ── */
  
  .preview-table {
    border-collapse: collapse;
    font-size: 11px;
    line-height: 1.3;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    width: 100%;
    table-layout: fixed;
    background: #ffffff;
  }
  
  .preview-table th,
  .preview-table td {
    border: 1px solid #e2e2e2;
    padding: 4px 8px;
    text-align: left;
    color: #202124;
  }
  
  .preview-table th {
    background: #f8f9fa;
    font-weight: 600;
    color: #202124;
    border-bottom: 2px solid #dadce0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .preview-table td {
    color: #3c4043;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  
  .preview-table tbody tr:nth-child(even) td {
    background: #f8f9fb;
  }
  
  .preview-table tbody tr:last-child td {
    border-bottom: none;
  }
  
  /* ── More rows indicator ────────────────────────────── */
  
  .more-rows td {
    text-align: center !important;
    padding: 3px 8px;
    background: #f8f9fa !important;
    border-top: 1px solid #e2e2e2;
  }
  
  .more-indicator {
    color: #80868b;
    font-size: 10px;
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
    background: #fff;
  }
  
  .empty-icon {
    font-size: 32px;
    opacity: 0.5;
  }
  
  /* ── Mobile ────────────────────────────────────────── */
  
  .mobile .preview-table {
    font-size: 10px;
  }
  
  .mobile .preview-table th,
  .mobile .preview-table td {
    padding: 3px 6px;
    max-width: 80px;
  }
</style>
