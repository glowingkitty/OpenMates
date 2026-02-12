<!--
  frontend/packages/ui/src/components/embeds/sheets/SheetEmbedFullscreen.svelte
  
  Fullscreen view for Sheet/Table embeds.
  Uses UnifiedEmbedFullscreen as base and provides table-specific content.
  
  Shows:
  - Table title and dimensions in header
  - Full scrollable table
  - Copy as CSV button
  - Basic infos bar at the bottom
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import { 
    parseSheetEmbedContent, 
    formatTableDimensions, 
    markdownTableToCSV
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
  
  // Build skill name for BasicInfosBar
  let skillName = $derived.by(() => {
    if (renderTitle) {
      return renderTitle;
    }
    return $text('embeds.table.text');
  });
  
  // Build status text
  let statusText = $derived.by(() => {
    if (actualRowCount === 0 && actualColCount === 0) return '';
    return formatTableDimensions(actualRowCount, actualColCount);
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
      const csv = markdownTableToCSV(renderMarkdown);
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
   * Download table as CSV file
   */
  async function handleDownloadCSV() {
    try {
      const csv = markdownTableToCSV(renderMarkdown);
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
      </div>
      
      <!-- Table content -->
      <div class="table-wrapper">
        {#if parsedTable.headers.length > 0}
          <table class="fullscreen-table">
            <thead>
              <tr>
                {#each parsedTable.headers as header, i}
                  <th style:text-align={header.align || 'left'}>
                    <span class="col-index">#{i + 1}</span>
                    {header.content}
                  </th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each parsedTable.rows as row}
                <tr>
                  {#each row as cell}
                    <td style:text-align={cell.align || 'left'}>{cell.content}</td>
                  {/each}
                </tr>
              {/each}
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
    display: inline-block;
    font-size: 10px;
    color: var(--color-grey-40, #999);
    margin-right: 6px;
    font-weight: 400;
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
