<!--
  frontend/packages/ui/src/components/embeds/sheets/SheetEmbedPreview.svelte
  
  Preview component for Sheet/Table embeds.
  Uses UnifiedEmbedPreview as base and provides table-specific details content.
  
  Details content structure:
  - Processing: "Generating..." placeholder
  - Finished: Preview of first few rows of the table
  - Error: Empty placeholder with table icon
  
  Sizes:
  - Desktop: 300x200px
  - Mobile: 150x290px
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
  
  // Local reactive state for embed data - can be updated via onEmbedDataUpdated callback
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
  
  // Parse table content to extract markdown and metadata
  let parsedContent = $derived.by(() => parseSheetEmbedContent(tableContent, { title }));
  let renderTitle = $derived(parsedContent.title);
  let parsedTable = $derived(parsedContent.parsedTable);
  
  // Get actual row/col counts from parsed table if not provided
  let actualRowCount = $derived(rowCount > 0 ? rowCount : parsedTable.rowCount);
  let actualColCount = $derived(colCount > 0 ? colCount : parsedTable.colCount);
  
  // Get preview rows (first MAX_PREVIEW_ROWS rows)
  let previewRows = $derived(parsedTable.rows.slice(0, MAX_PREVIEW_ROWS));
  let hasMoreRows = $derived(parsedTable.rowCount > MAX_PREVIEW_ROWS);
  
  // Build skill name for BasicInfosBar
  let skillName = $derived.by(() => {
    if (renderTitle) {
      return renderTitle;
    }
    return $text('embeds.table.text');
  });
  
  // Build status text: dimensions
  let statusText = $derived.by(() => {
    if (actualRowCount === 0 && actualColCount === 0) return '';
    return formatTableDimensions(actualRowCount, actualColCount);
  });
  
  // Icon for tables
  const skillIconName = 'table';
  
  /**
   * Handle embed data updates from server
   * Updates local state when embed status changes
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    console.debug('[SheetEmbedPreview] Received embed data update:', {
      embedId: id,
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    // Update status
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
    }
    
    // Update content from decoded TOON
    if (data.decodedContent) {
      const content = data.decodedContent;
      localTableContent = content.code || content.table || content.content || '';
      if (content.title) {
        localTitle = content.title;
      }
      if (typeof content.rows === 'number') {
        localRowCount = content.rows;
      }
      if (typeof content.cols === 'number') {
        localColCount = content.cols;
      }
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
        <!-- Processing state: show skeleton -->
        <div class="skeleton-table">
          <div class="skeleton-row header">
            <div class="skeleton-cell"></div>
            <div class="skeleton-cell"></div>
            <div class="skeleton-cell"></div>
          </div>
          <div class="skeleton-row">
            <div class="skeleton-cell"></div>
            <div class="skeleton-cell"></div>
            <div class="skeleton-cell"></div>
          </div>
          <div class="skeleton-row">
            <div class="skeleton-cell"></div>
            <div class="skeleton-cell"></div>
            <div class="skeleton-cell"></div>
          </div>
        </div>
      {:else if status === 'finished' && parsedTable.headers.length > 0}
        <!-- Finished state: show table preview -->
        <div class="table-container">
          <table class="preview-table">
            <thead>
              <tr>
                {#each parsedTable.headers as header}
                  <th style:text-align={header.align || 'left'}>{header.content}</th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each previewRows as row}
                <tr>
                  {#each row as cell}
                    <td style:text-align={cell.align || 'left'}>{cell.content}</td>
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
  .sheet-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 8px;
    box-sizing: border-box;
  }
  
  .sheet-preview.mobile {
    padding: 6px;
  }
  
  /* Skeleton loading state */
  .skeleton-table {
    display: flex;
    flex-direction: column;
    gap: 4px;
    width: 100%;
  }
  
  .skeleton-row {
    display: flex;
    gap: 4px;
  }
  
  .skeleton-row.header .skeleton-cell {
    background: var(--color-grey-25, #e5e5e5);
  }
  
  .skeleton-cell {
    flex: 1;
    height: 20px;
    background: var(--color-grey-15, #f0f0f0);
    border-radius: 4px;
    animation: pulse 1.5s ease-in-out infinite;
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }
  
  /* Table preview */
  .table-container {
    width: 100%;
    overflow: hidden;
    border-radius: 6px;
    border: 1px solid var(--color-grey-20, #eaeaea);
    background: var(--color-grey-5, #fafafa);
  }
  
  .preview-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
    line-height: 1.3;
  }
  
  .preview-table th,
  .preview-table td {
    padding: 6px 8px;
    border-bottom: 1px solid var(--color-grey-15, #f0f0f0);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100px;
  }
  
  .preview-table th {
    background: var(--color-grey-15, #f0f0f0);
    font-weight: 600;
    color: var(--color-grey-80, #333);
  }
  
  .preview-table td {
    color: var(--color-grey-70, #444);
  }
  
  .preview-table tbody tr:last-child td {
    border-bottom: none;
  }
  
  .more-rows td {
    text-align: center !important;
    padding: 4px 8px;
    background: var(--color-grey-10, #f5f5f5);
  }
  
  .more-indicator {
    color: var(--color-grey-50, #888);
    font-size: 10px;
    font-style: italic;
  }
  
  /* Empty state */
  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    min-height: 80px;
  }
  
  .empty-icon {
    font-size: 32px;
    opacity: 0.5;
  }
  
  /* Mobile adjustments */
  .mobile .preview-table {
    font-size: 10px;
  }
  
  .mobile .preview-table th,
  .mobile .preview-table td {
    padding: 4px 6px;
    max-width: 60px;
  }
  
  /* Dark mode support */
  :global(.dark) .table-container {
    background: var(--color-grey-90, #1a1a1a);
    border-color: var(--color-grey-80, #333);
  }
  
  :global(.dark) .preview-table th {
    background: var(--color-grey-85, #252525);
    color: var(--color-grey-20, #eaeaea);
  }
  
  :global(.dark) .preview-table td {
    color: var(--color-grey-30, #d0d0d0);
  }
  
  :global(.dark) .preview-table th,
  :global(.dark) .preview-table td {
    border-bottom-color: var(--color-grey-80, #333);
  }
  
  :global(.dark) .skeleton-cell {
    background: var(--color-grey-80, #333);
  }
  
  :global(.dark) .skeleton-row.header .skeleton-cell {
    background: var(--color-grey-75, #404040);
  }
  
  :global(.dark) .more-rows td {
    background: var(--color-grey-85, #252525);
  }
  
  :global(.dark) .more-indicator {
    color: var(--color-grey-50, #888);
  }
</style>
