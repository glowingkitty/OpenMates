<!--
  frontend/packages/ui/src/components/embeds/pdf/PdfSearchEmbedPreview.svelte

  Preview card for the pdf/search skill result embed.
  Shown when the AI executes the pdf.search skill to search for keywords in a PDF.

  Displays:
  - Processing state: PDF icon + "Searching PDF…" subtitle
  - Finished state: PDF icon + filename + match count + query summary
  - Error state: error message

  On click: opens the ORIGINAL uploaded PDF's fullscreen viewer
  (fires 'pdffullscreen' CustomEvent with the upload embed's data),
  NOT a new standalone fullscreen for this skill result.

  Architecture:
  - Mounted by AppSkillUseRenderer.ts when app_id='pdf' and skill_id='search'.
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
    /** Search query used */
    query?: string;
    /** Total number of matches found */
    totalMatches?: number;
    /** Whether results were truncated (>50 matches) */
    truncated?: boolean;
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
    query,
    totalMatches,
    truncated,
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
   * - processing → "Searching PDF…"
   * - finished   → match count + optional truncation note
   * - error      → error message
   */
  let statusText = $derived.by(() => {
    if (status === 'processing') return 'Searching PDF\u2026';
    if (status === 'error') return error || '';
    if (status === 'finished') {
      if (totalMatches !== undefined) {
        if (totalMatches === 0) return query ? `"${query}" \u2014 No matches` : 'No matches';
        const matchStr = totalMatches === 1 ? '1 match' : `${totalMatches} matches`;
        const truncStr = truncated ? ' (first 50 shown)' : '';
        return query ? `"${query}" \u2014 ${matchStr}${truncStr}` : `${matchStr}${truncStr}`;
      }
      return $text('app_skills.pdf.search');
    }
    return '';
  });

  /** Fullscreen enabled when finished */
  let isFullscreenEnabled = $derived(status === 'finished' && !!onFullscreen);
</script>

<UnifiedEmbedPreview
  {id}
  appId="pdf"
  skillId="search"
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
    <div class="pdf-search-preview" class:mobile={isMobileSnippet}>
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
  .pdf-search-preview {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 20px;
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    overflow: hidden;
  }

  .pdf-search-preview.mobile {
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
