// PdfRenderer.ts
//
// Renderer for PDF upload embeds in the TipTap message editor.
//
// Mounts PDFEmbedPreview.svelte into the embed node view so the user
// sees a status card (filename, page count, upload/OCR progress) while
// the server-side pipeline runs in the background.
//
// Stop button (status 'uploading' only):
//   onStop() → fires 'cancelpdfupload' CustomEvent (bubbles) on the content element
//   → Embed.ts node view listener calls cancelUpload(id) + deletes the node.
//
// Lifecycle:
//   1. User drops/selects PDF → insertPDF() inserts node with status:'uploading'
//   2. Server upload completes → _performPdfUpload() sets status:'processing' + metadata
//   3. Background OCR done → WebSocket embed_update event → status:'finished'
//   4. Node view calls update() on each status transition to re-render the Svelte component

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { mount, unmount } from "svelte";
import PDFEmbedPreview from "../../../embeds/pdf/PDFEmbedPreview.svelte";

// Track mounted Svelte components for cleanup on re-renders
const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

/**
 * Extended attrs shape for PDF embeds — widens 'status' to include 'uploading'
 * (same pattern as ImageEmbedAttrs in ImageRenderer.ts uses Omit<>).
 */
interface PdfEmbedAttrs extends Omit<EmbedNodeAttributes, "status"> {
  /** Upload lifecycle: 'uploading' | 'processing' | 'finished' | 'error' */
  status: "uploading" | "processing" | "finished" | "error";
  /** Number of pages (from upload server's pymupdf extraction) */
  pageCount?: number | null;
  /** Error message set by _performPdfUpload() on failure */
  uploadError?: string;
}

/**
 * Renderer for PDF embeds — mounts PDFEmbedPreview.svelte.
 * Follows the same pattern as ImageRenderer.ts.
 */
export class PdfRenderer implements EmbedRenderer {
  type = "pdf";

  render(context: EmbedRenderContext): void {
    const { content } = context;
    const attrs = context.attrs as PdfEmbedAttrs;

    // Unmount any previously mounted component on this DOM node.
    // This handles status transitions (e.g. uploading → processing → finished).
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn("[PdfRenderer] Error unmounting existing preview:", e);
      }
    }

    content.innerHTML = "";

    try {
      // Stop button handler: fires a bubbling event so Embed.ts node view can
      // cancel the upload (cancelUpload(id)) and delete the node from the editor.
      const handleStop = () => {
        content.dispatchEvent(
          new CustomEvent("cancelpdfupload", {
            bubbles: true,
            composed: true,
            detail: { embedId: attrs.id },
          }),
        );
      };

      const component = mount(PDFEmbedPreview, {
        target: content,
        props: {
          id: attrs.id || "",
          filename: attrs.filename ?? undefined,
          status: (attrs.status || "uploading") as
            | "uploading"
            | "processing"
            | "finished"
            | "error",
          pageCount: attrs.pageCount ?? null,
          uploadError: attrs.uploadError ?? undefined,
          isMobile: false,
          onStop: handleStop,
        },
      });

      mountedComponents.set(content, component);

      console.debug("[PdfRenderer] Mounted PDFEmbedPreview:", {
        filename: attrs.filename,
        status: attrs.status,
        pageCount: attrs.pageCount,
      });
    } catch (error) {
      console.error("[PdfRenderer] Error mounting PDFEmbedPreview:", error);
      content.innerHTML = `<div style="padding:8px;font-size:12px;color:var(--color-grey-50)">PDF unavailable</div>`;
    }
  }

  update(context: EmbedRenderContext): boolean {
    // Re-render on every attr change (status transitions, page count update)
    this.render(context);
    return true;
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    return `[PDF: ${attrs.filename || "file.pdf"}]`;
  }
}
