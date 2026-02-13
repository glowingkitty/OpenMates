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
  
  // Parse table content
  let parsedContent = $derived.by(() => parseSheetEmbedContent(tableContent, { title }));
  let renderTitle = $derived(parsedContent.title);
  let parsedTable = $derived(parsedContent.parsedTable);
  
  // Get actual row/col counts
  let actualRowCount = $derived(rowCount > 0 ? rowCount : parsedTable.rowCount);
  let actualColCount = $derived(colCount > 0 ? colCount : parsedTable.colCount);
  
  // Get preview rows
  let previewRows = $derived(parsedTable.rows.slice(0, MAX_PREVIEW_ROWS));
  let hasMoreRows = $derived(parsedTable.rowCount > MAX_PREVIEW_ROWS);
  
  // Build skill name for BasicInfosBar
  let skillName = $derived.by(() => renderTitle || $text('embeds.table.text'));
  
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
      localTableContent = String(c.code || c.table || c.content || '');
      if (c.title) localTitle = String(c.title);
      if (typeof c.rows === 'number') localRowCount = c.rows;
      if (typeof c.cols === 'number') localColCount = c.cols;
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
  
  /* ── Table scroll container ─────────────────────────── */
  
  .table-scroll {
    width: 100%;
    flex: 1;
    overflow-x: auto;
    overflow-y: hidden;
    background: #ffffff;
  }
  
  /* ── Preview table — matches fullscreen spreadsheet style ── */
  
  .preview-table {
    border-collapse: collapse;
    font-size: 11px;
    line-height: 1.3;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    white-space: nowrap;
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
  }
  
  .preview-table td {
    color: #3c4043;
    max-width: 140px;
    overflow: hidden;
    text-overflow: ellipsis;
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
