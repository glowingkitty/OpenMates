<!--
  frontend/packages/ui/src/components/embeds/pdf/PdfReadEmbedPreview.svelte

  Preview card for the pdf/read skill result embed.
  Shown when the AI executes the pdf.read skill to read text from specific pages.

  Displays:
  - Processing state: PDF icon + "Reading…" subtitle
  - Finished state: PDF icon + filename + pages read summary
  - Error state: error message

  On click: opens the ORIGINAL uploaded PDF's fullscreen viewer
  (fires 'pdffullscreen' CustomEvent with the upload embed's data),
  NOT a new standalone fullscreen for this skill result.

  Architecture:
  - Mounted by AppSkillUseRenderer.ts when app_id='pdf' and skill_id='read'.
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
    /** Pages returned by the read skill */
    pagesReturned?: number[];
    /** Pages skipped due to token budget */
    pagesSkipped?: number[];
    /** Total page count of the PDF */
    pageCount?: number;
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
    pagesReturned,
    pagesSkipped,
    pageCount,
    status,
    error,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  /**
   * i18n skill name shown in the BasicInfosBar header line (e.g. "Read" / "Lesen").
   * This is always the skill name — never the filename — per the embed card convention.
   */
  let skillName = $derived($text('app_skills.pdf.read.skill_name'));

  /**
   * Truncated filename or generic "PDF" fallback — shown in the card body details area.
   */
  let displayFilename = $derived.by(() => {
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
   * - processing → "Reading PDF…"
   * - finished   → pages read + optional skipped info
   * - error      → error message
   */
  let statusText = $derived.by(() => {
    if (status === 'processing') return $text('app_skills.pdf.view.processing');
    if (status === 'error') return error || '';
    if (status === 'finished') {
      // Show pages read summary
      const readCount = pagesReturned?.length ?? 0;
      const skippedCount = pagesSkipped?.length ?? 0;
      const pageCountStr = pageCount && pageCount > 0
        ? (pageCount === 1 ? '1 page' : `${pageCount} pages`)
        : '';

      if (readCount > 0) {
        const sorted = [...(pagesReturned ?? [])].sort((a, b) => a - b);
        const pagesStr = readCount === 1
          ? `Page ${sorted[0]} read`
          : `${readCount} pages read`;
        const skippedStr = skippedCount > 0 ? ` · ${skippedCount} skipped` : '';
        const totalStr = pageCountStr ? ` · ${pageCountStr}` : '';
        return `${pagesStr}${skippedStr}${totalStr}`;
      }
      return pageCountStr || $text('app_skills.pdf.read');
    }
    return '';
  });

  /** Fullscreen enabled when finished (skill result is ready) */
  let isFullscreenEnabled = $derived(status === 'finished' && !!onFullscreen);
</script>

<!--
  showSkillIcon defaults to true — the book.svg icon is rendered in BasicInfosBar
  by UnifiedEmbedPreview. The details snippet provides text-only content
  (filename + status), following the same pattern as WebSearchEmbedPreview.
-->
<UnifiedEmbedPreview
  {id}
  appId="pdf"
  skillId="read"
  skillIconName="book"
  {status}
  {skillName}
  {isMobile}
  onFullscreen={isFullscreenEnabled ? onFullscreen : undefined}
  showStatus={true}
  customStatusText={statusText}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="pdf-read-details" class:mobile={isMobileSnippet}>
      <!-- Filename shown in the card body (not the header) -->
      <div class="pdf-name">{displayFilename}</div>
      <!-- Status subtitle -->
      {#if statusText}
        <div class="pdf-status-text">{statusText}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .pdf-read-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
    justify-content: center;
  }

  .pdf-read-details.mobile {
    justify-content: flex-start;
  }

  .pdf-name {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }

  .pdf-read-details.mobile .pdf-name {
    font-size: 14px;
  }

  .pdf-status-text {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .pdf-read-details.mobile .pdf-status-text {
    font-size: 12px;
  }

  /* Skill icon: book.svg for pdf.read (registered here per WebSearch pattern) */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="book"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/book.svg');
    mask-image: url('@openmates/ui/static/icons/book.svg');
  }

  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="book"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/book.svg');
    mask-image: url('@openmates/ui/static/icons/book.svg');
  }
</style>
