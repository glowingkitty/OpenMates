<!--
  frontend/packages/ui/src/components/embeds/pdf/PDFEmbedFullscreen.svelte

  Fullscreen info panel for user-uploaded PDF embeds shown in the message input editor.

  Triggered when the user clicks a finished PDF embed card in the editor.

  Displays:
  - PDF icon and filename as the main content
  - Page count and processing status
  - Close button (via UnifiedEmbedFullscreen)

  Architecture:
  - Mounted by ActiveChat.svelte in response to the 'pdffullscreen' CustomEvent.
  - PdfRenderer.ts dispatches that event from the onFullscreen prop passed to
    PDFEmbedPreview.svelte, which is only shown when status === 'finished'.
  - PDF content decryption for inline rendering is not implemented here because
    the plaintext AES key is never stored client-side (zero-knowledge design).
    The pdf.view skill handles visual analysis server-side via Vault Transit.
  - A full "render PDF in browser" path would require a server-side download
    endpoint that unwraps the Vault key and serves decrypted bytes. That is a
    future enhancement — tracked separately.

  Event chain (triggered on embed card click):
    PDFEmbedPreview.svelte (onFullscreen prop)
    → PdfRenderer.ts (dispatches 'pdffullscreen' CustomEvent on content element)
    → MessageInput.svelte (re-dispatches via Svelte dispatch('pdffullscreen'))
    → ActiveChat.svelte (handlePdfFullscreen → showPdfEmbedFullscreen = true)
    → this component is mounted
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';

  /** Max display length for the filename in the bottom bar title (chars) */
  const MAX_FILENAME_LENGTH = 40;

  interface Props {
    /** Original filename of the uploaded PDF */
    filename?: string;
    /** Number of pages in the PDF (from embed metadata) */
    pageCount?: number | null;
    /** Close handler */
    onClose: () => void;
  }

  let {
    filename = 'document.pdf',
    pageCount,
    onClose,
  }: Props = $props();

  // -------------------------------------------------------------------------
  // Info bar: truncated filename + page count subtitle
  // -------------------------------------------------------------------------

  /**
   * Truncate filename for bottom bar (mirrors PDFEmbedPreview.svelte logic).
   */
  let infoBarTitle = $derived.by(() => {
    if (!filename) return 'PDF';
    if (filename.length <= MAX_FILENAME_LENGTH) return filename;
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
  });

  /**
   * Info bar subtitle: page count when known, otherwise generic "PDF".
   */
  let infoBarSubtitle = $derived.by(() => {
    if (pageCount && pageCount > 0) {
      return pageCount === 1 ? '1 page' : `${pageCount} pages`;
    }
    return $text('app_skills.pdf.view');
  });
</script>

<UnifiedEmbedFullscreen
  appId="pdf"
  skillId="view"
  skillIconName="pdf"
  skillName={infoBarTitle}
  customStatusText={infoBarSubtitle}
  showStatus={true}
  showSkillIcon={false}
  showShare={false}
  title=""
  {onClose}
>
  {#snippet content()}
    <div class="pdf-info-fullscreen">
      <!-- Large PDF icon -->
      <div class="pdf-icon-wrapper">
        <div class="icon_rounded pdf large"></div>
      </div>

      <!-- Filename -->
      <h2 class="pdf-filename" title={filename}>{infoBarTitle}</h2>

      <!-- Page count -->
      {#if pageCount && pageCount > 0}
        <p class="pdf-pages">{infoBarSubtitle}</p>
      {/if}

      <!-- Hint about AI interaction -->
      <p class="pdf-hint">
        Ask the AI to read, search, or view pages of this PDF.
      </p>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ==========================================================================
     Main container: centered content inside fullscreen area
     ========================================================================== */

  .pdf-info-fullscreen {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 100%;
    /* Fill height while leaving room for top/bottom bars */
    min-height: 300px;
    padding: 60px 40px 80px;
    box-sizing: border-box;
    gap: 16px;
    text-align: center;
  }

  /* ==========================================================================
     Large PDF icon
     ========================================================================== */

  .pdf-icon-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 8px;
  }

  .icon_rounded.large {
    width: 80px;
    height: 80px;
    border-radius: 20px;
    background-size: 40px 40px;
    background-repeat: no-repeat;
    background-position: center;
  }

  /* ==========================================================================
     Text content
     ========================================================================== */

  .pdf-filename {
    font-size: 20px;
    font-weight: 600;
    color: var(--color-font-primary);
    margin: 0;
    word-break: break-word;
    max-width: 600px;
  }

  .pdf-pages {
    font-size: 15px;
    color: var(--color-grey-60, #888);
    margin: 0;
  }

  .pdf-hint {
    font-size: 14px;
    color: var(--color-grey-50, #999);
    margin: 8px 0 0;
    max-width: 380px;
    line-height: 1.5;
  }

  /* ==========================================================================
     Dark mode
     ========================================================================== */

  :global(.dark) .pdf-filename {
    color: var(--color-font-primary-dark, #e0e0e0);
  }

  :global(.dark) .pdf-pages,
  :global(.dark) .pdf-hint {
    color: var(--color-grey-40, #999);
  }
</style>
