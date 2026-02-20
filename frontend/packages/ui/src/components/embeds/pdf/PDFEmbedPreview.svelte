<!--
  frontend/packages/ui/src/components/embeds/pdf/PDFEmbedPreview.svelte

  Preview card for user-uploaded PDF embeds shown in the message input editor.

  Lifecycle states:
  - 'uploading'   → file is being uploaded to the server (credit charge + encryption)
  - 'processing'  → upload complete, background OCR is running (Mistral + pymupdf)
  - 'finished'    → OCR complete (delivered via WebSocket embed_update)
  - 'error'       → upload or processing failure

  Displays:
  - PDF icon (via CSS icon class 'pdf')
  - Truncated filename as card title
  - Subtitle: upload/processing status or page count on completion

  Architecture:
  - Mounts inside the TipTap editor via PdfRenderer.ts (the same pattern as
    ImageEmbedPreview.svelte mounted via ImageRenderer.ts).
  - Uses UnifiedEmbedPreview for layout, status bar, and the 3D hover effect.
  - showSkillIcon=false — the PDF icon is shown by the InlinePreviewBase CSS
    class, not as an app skill icon.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';

  /** Max display length for the filename in the card title (chars) */
  const MAX_FILENAME_LENGTH = 30;

  interface Props {
    /** Unique embed ID */
    id: string;
    /** Original filename of the uploaded PDF */
    filename?: string;
    /** Current embed status */
    status: 'uploading' | 'processing' | 'finished' | 'error';
    /** Number of pages (available after successful upload) */
    pageCount?: number | null;
    /** Error message shown when status is 'error' */
    uploadError?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Called when the user clicks the stop button during upload */
    onStop?: () => void;
  }

  let {
    id,
    filename,
    status: statusProp,
    pageCount,
    uploadError,
    isMobile = false,
    onStop,
  }: Props = $props();

  let status = $derived(statusProp);

  /**
   * Map upload-specific status to the UnifiedEmbedPreview status union.
   * 'uploading' → 'processing' (shows the animated spinner in the card).
   */
  let unifiedStatus = $derived(
    status === 'uploading'
      ? 'processing'
      : (status as 'processing' | 'finished' | 'error'),
  );

  /**
   * Card title: truncated filename.
   * Falls back to a generic "PDF" label if no filename is set.
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
   * Card subtitle (customStatusText):
   * - 'uploading'  → "Uploading…"
   * - 'processing' → "Reading PDF…"  (OCR + screenshot generation running)
   * - 'finished'   → "42 pages" (or plain "PDF" if page count unavailable)
   * - 'error'      → error message
   */
  let statusText = $derived.by(() => {
    if (status === 'uploading') return 'Uploading\u2026';
    if (status === 'error') return uploadError || 'Upload failed';
    if (status === 'processing') return 'Reading PDF\u2026';
    if (status === 'finished') {
      if (pageCount && pageCount > 0) {
        return pageCount === 1 ? '1 page' : `${pageCount} pages`;
      }
      return 'PDF';
    }
    return '';
  });

  /** Show the stop button only during active upload (not during OCR processing) */
  let showStop = $derived(status === 'uploading' && !!onStop);
</script>

<UnifiedEmbedPreview
  {id}
  appId="pdf"
  skillId="read"
  skillIconName="pdf"
  status={unifiedStatus}
  {skillName}
  {isMobile}
  onStop={showStop ? onStop : undefined}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="pdf-preview" class:mobile={isMobileSnippet}>
      <!-- PDF icon using the existing CSS icon system -->
      <div class="pdf-icon-container">
        <div class="icon_rounded pdf"></div>
      </div>

      <!-- Filename + status detail -->
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
  .pdf-preview {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 20px;
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    overflow: hidden;
  }

  .pdf-preview.mobile {
    flex-direction: column;
    align-items: flex-start;
    padding: 12px;
    gap: 8px;
  }

  /* Large PDF icon circle */
  .pdf-icon-container {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  /* Override inline preview base icon size for the embed preview context */
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
