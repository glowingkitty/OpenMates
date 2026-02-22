<!--
  frontend/packages/ui/src/components/embeds/pdf/PdfViewEmbedPreview.svelte

  Preview card for the pdf/view skill result embed.
  Shown when the AI executes the pdf.view skill to view specific PDF pages.

  Displays:
  - Processing state: PDF icon + "Viewing pages…" subtitle + skeleton
  - Finished state: PDF icon + filename + page count subtitle
  - Error state: error message

  On click: opens the ORIGINAL uploaded PDF's fullscreen viewer
  (fires 'pdffullscreen' CustomEvent with the upload embed's data),
  NOT a new standalone fullscreen for this skill result.

  Architecture:
  - Mounted by AppSkillUseRenderer.ts when app_id='pdf' and skill_id='view'.
  - onFullscreen callback resolves the original PDF upload embed from EmbedStore
    and fires 'pdffullscreen' so ActiveChat mounts PDFEmbedFullscreen.svelte.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  /** Max display length for filename in the card title */
  const MAX_FILENAME_LENGTH = 30;

  interface Props {
    /** Unique embed ID for this skill-use embed */
    id: string;
    /** Filename of the PDF (from original upload embed) */
    filename?: string;
    /** Total page count of the PDF */
    pageCount?: number;
    /** Pages viewed by this skill call (e.g. [1, 2, 3]) */
    pages?: number[];
    /** Processing status of the skill execution */
    status: 'processing' | 'finished' | 'error';
    /** Error message if skill failed */
    error?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /**
     * Called when the user clicks to open fullscreen.
     * Implemented by AppSkillUseRenderer: resolves original upload embed
     * and fires 'pdffullscreen' CustomEvent.
     */
    onFullscreen?: () => void;
  }

  let {
    id,
    filename,
    pageCount,
    pages,
    status,
    error,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  /**
   * Card title: truncated filename or generic "PDF" fallback.
   */
  let skillName = $derived.by(() => {
    if (!filename) return 'PDF';
    if (filename.length > MAX_FILENAME_LENGTH) {
      const lastDot = filename.lastIndexOf('.');
      if (lastDot > 0) {
        const ext = filename.slice(lastDot);
        const stem = filename.slice(0, lastDot);
        const allowedStem = MAX_FILENAME_LENGTH - ext.length - 1;
        return allowedStem > 0
          ? stem.slice(0, allowedStem) + '\u2026' + ext
          : filename.slice(0, MAX_FILENAME_LENGTH - 1) + '\u2026';
      }
      return filename.slice(0, MAX_FILENAME_LENGTH - 1) + '\u2026';
    }
    return filename;
  });

  /**
   * Card subtitle:
   * - processing → "Viewing…"
   * - finished   → pages viewed description (e.g. "Pages 1–3 · 42 pages")
   * - error      → error message
   */
  let statusText = $derived.by(() => {
    if (status === 'processing') return $text('app_skills.pdf.view.viewing');
    if (status === 'error') return error || '';
    if (status === 'finished') {
      // Show which pages were viewed + total page count
      const pageCountStr = pageCount && pageCount > 0
        ? (pageCount === 1 ? '1 page' : `${pageCount} pages`)
        : '';
      if (pages && pages.length > 0) {
        const sorted = [...pages].sort((a, b) => a - b);
        const pagesStr = sorted.length === 1
          ? `Page ${sorted[0]}`
          : `Pages ${sorted[0]}–${sorted[sorted.length - 1]}`;
        return pageCountStr ? `${pagesStr} \u00B7 ${pageCountStr}` : pagesStr;
      }
      return pageCountStr || $text('app_skills.pdf.view');
    }
    return '';
  });

  /** Fullscreen enabled when finished */
  let isFullscreenEnabled = $derived(status === 'finished' && !!onFullscreen);
</script>

<UnifiedEmbedPreview
  {id}
  appId="pdf"
  skillId="view"
  skillIconName="pdf"
  {status}
  {skillName}
  {isMobile}
  onFullscreen={isFullscreenEnabled ? onFullscreen : undefined}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="pdf-view-preview" class:mobile={isMobileSnippet}>
      <!-- PDF icon -->
      <div class="pdf-icon-container">
        <div class="icon_rounded pdf"></div>
      </div>

      <!-- Filename + status -->
      <div class="pdf-info">
        <span class="pdf-filename" title={filename}>{skillName}</span>
        {#if statusText}
          <span class="pdf-status">{statusText}</span>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .pdf-view-preview {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 20px;
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    overflow: hidden;
  }

  .pdf-view-preview.mobile {
    flex-direction: column;
    align-items: flex-start;
    padding: 12px;
    gap: 8px;
  }

  .pdf-icon-container {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  /* Match PDFEmbedPreview icon sizing */
  .pdf-icon-container .icon_rounded {
    width: 44px;
    height: 44px;
    border-radius: 12px;
    background-size: 22px 22px;
    background-repeat: no-repeat;
    background-position: center;
  }

  .pdf-info {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
    flex: 1;
  }

  .pdf-filename {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-font-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.3;
  }

  .pdf-status {
    font-size: 12px;
    color: var(--color-grey-60, #888);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
