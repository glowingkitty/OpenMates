// Image renderer for static SVG images AND user-uploaded images in the message editor.
//
// Handles THREE sub-types of the 'image' embed:
//   1. User-uploaded images (editor context): attrs.src (blob URL) is set.
//      Shows local preview + upload state overlay (uploading/error/finished).
//   2. User-uploaded images (read-only context): attrs.src is absent but S3 data
//      (attrs.s3Files, attrs.aesKey, etc.) is present. Mounts ImageEmbedPreview.svelte
//      which fetches and decrypts the image from S3.
//   3. Static/SVG images (legal documents): attrs.url is set, no upload data.
//
// For uploaded images in editor context (Case 1):
//   - status 'uploading': local blob preview + dimmed overlay + spinner
//   - status 'error': local blob preview + dimmed overlay + error message
//   - status 'finished': local blob preview at full opacity (embed ready to send)
//
// Fullscreen click (uploaded images, status 'finished' only):
//   Clicking the image fires a 'imagefullscreen' CustomEvent (bubbles) on the img
//   element with the embed attrs as detail. MessageInput.svelte catches this and
//   re-dispatches it up to ActiveChat.svelte which mounts UploadedImageFullscreen.

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { mount, unmount } from "svelte";
import ImageEmbedPreview from "../../../embeds/images/ImageEmbedPreview.svelte";

// Track mounted Svelte components for cleanup
const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

/**
 * Extended attrs type for image embeds that includes upload-specific fields.
 * These extra fields are set by insertImage() and _performUpload() in embedHandlers.ts.
 *
 * Uses Omit<> to widen 'status' beyond the base union so that upload-specific
 * states ('uploading') are accepted alongside the standard ones.
 */
interface ImageEmbedAttrs extends Omit<EmbedNodeAttributes, "status"> {
  /** Blob URL for instant local preview while uploading */
  src?: string;
  /** Upload lifecycle: 'uploading' | 'finished' | 'error' */
  status: "uploading" | "processing" | "finished" | "error";
  /** Error message set by _performUpload() on failure */
  uploadError?: string;
  // Upload result fields — populated by _performUpload() on success:
  /** Files variant metadata from server (original, full, preview S3 keys + dims) */
  s3Files?: Record<
    string,
    {
      s3_key: string;
      width: number;
      height: number;
      size_bytes: number;
      format: string;
    }
  >;
  /** S3 base URL for constructing full image URLs */
  s3BaseUrl?: string;
  /** Plaintext AES-256 key (base64) for client-side image decryption */
  aesKey?: string;
  /** AES-GCM nonce (base64) shared across encrypted variants */
  aesNonce?: string;
}

/**
 * Renderer for image embeds in the TipTap editor.
 * Covers both static document images and user-uploaded chat images.
 */
export class ImageRenderer implements EmbedRenderer {
  type = "image";

  render(context: EmbedRenderContext): void {
    const { content } = context;
    const attrs = context.attrs as ImageEmbedAttrs;

    // -----------------------------------------------------------------------
    // Case 1: User-uploaded image in editor context (has src blob URL)
    // -----------------------------------------------------------------------
    if (attrs.src) {
      this._renderUploadedImage(content, attrs);
      return;
    }

    // -----------------------------------------------------------------------
    // Case 2: User-uploaded image in read-only context (src is absent because
    // blob URLs don't survive serialization, but S3 data is present).
    // Mount ImageEmbedPreview.svelte which fetches+decrypts from S3.
    // -----------------------------------------------------------------------
    if (attrs.s3Files && attrs.aesKey) {
      this._renderS3Image(content, attrs);
      return;
    }

    // -----------------------------------------------------------------------
    // Case 3: Static/SVG image (legacy, from legal documents)
    // -----------------------------------------------------------------------
    const imageUrl = (attrs as EmbedNodeAttributes).url;
    const altText = attrs.filename || attrs.title || "Image";

    if (!imageUrl) {
      console.warn(
        "[ImageRenderer] No URL, src, or S3 data for image embed:",
        attrs,
      );
      content.innerHTML =
        '<div class="image-error">Image URL not available</div>';
      return;
    }

    const isSvg = imageUrl.toLowerCase().endsWith(".svg");

    if (isSvg) {
      // SVG images — non-clickable, minimal spacing
      const container = context.container;
      container.style.pointerEvents = "none";
      container.style.cursor = "default";
      container.style.margin = "0";
      container.style.marginBottom = "8px";

      content.innerHTML = `
        <img 
          src="${imageUrl}" 
          alt="${altText}" 
          class="legal-svg-image"
          loading="lazy"
          style="max-width: 100%; height: auto; display: block;"
        />
      `;
    } else {
      content.innerHTML = `
        <div class="image-embed-container">
          <img 
            src="${imageUrl}" 
            alt="${altText}" 
            class="image-embed-img"
            loading="lazy"
            style="max-width: 100%; height: auto; display: block; border-radius: 12px;"
          />
        </div>
      `;
    }
  }

  /** Renders an uploaded image with upload-state overlay. */
  private _renderUploadedImage(
    content: HTMLElement,
    attrs: ImageEmbedAttrs,
  ): void {
    const status = attrs.status || "finished";
    const isUploading = status === "uploading";
    const isError = status === "error";
    const isFinished = status === "finished";
    const opacity = isUploading ? "0.45" : "1";
    // Only allow fullscreen click once the upload is done and S3 data is available
    const isClickable = isFinished && !!attrs.s3Files && !!attrs.aesKey;
    const altText = attrs.filename || "Image";
    const errorMsg = attrs.uploadError || "Upload failed";

    // Build spinner / error icon HTML
    let overlayHtml = "";
    if (isUploading) {
      overlayHtml = `
        <div class="img-upload-overlay">
          <div class="img-upload-spinner"></div>
          <span class="img-upload-label">Uploading\u2026</span>
        </div>`;
    } else if (isError) {
      overlayHtml = `
        <div class="img-upload-overlay img-upload-overlay--error">
          <span class="img-upload-error-icon">!</span>
          <span class="img-upload-label">${errorMsg}</span>
        </div>`;
    }

    content.innerHTML = `
      <div class="img-upload-wrapper${isClickable ? " img-upload-wrapper--clickable" : ""}">
        <img
          src="${attrs.src}"
          alt="${altText}"
          class="img-upload-preview"
          style="
            max-width: 300px;
            max-height: 200px;
            width: auto;
            height: auto;
            display: block;
            border-radius: 20px;
            opacity: ${opacity};
            transition: opacity 0.2s ease;
            object-fit: cover;
            ${isClickable ? "cursor: zoom-in;" : ""}
          "
        />
        ${overlayHtml}
      </div>
      <style>
        .img-upload-wrapper {
          position: relative;
          display: inline-block;
        }
        .img-upload-overlay {
          position: absolute;
          inset: 0;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 6px;
          border-radius: 20px;
          pointer-events: none;
        }
        .img-upload-label {
          font-size: 0.72rem;
          font-weight: 500;
          color: #fff;
          text-shadow: 0 1px 3px rgba(0,0,0,0.6);
          letter-spacing: 0.02em;
        }
        .img-upload-spinner {
          width: 26px;
          height: 26px;
          border: 3px solid rgba(255,255,255,0.4);
          border-top-color: #fff;
          border-radius: 50%;
          animation: img-spin 0.75s linear infinite;
        }
        @keyframes img-spin { to { transform: rotate(360deg); } }
        .img-upload-error-icon {
          width: 26px;
          height: 26px;
          border-radius: 50%;
          background: rgba(220,38,38,0.85);
          color: #fff;
          font-size: 1rem;
          font-weight: 700;
          display: flex;
          align-items: center;
          justify-content: center;
          line-height: 1;
        }
        .img-upload-wrapper--clickable:hover .img-upload-preview {
          opacity: 0.92;
        }
      </style>
    `;

    // Attach fullscreen click handler for finished uploads.
    // Fires a bubbling CustomEvent so MessageInput.svelte can relay it to ActiveChat.
    if (isClickable) {
      const imgEl = content.querySelector(".img-upload-preview");
      if (imgEl) {
        imgEl.addEventListener("click", (e) => {
          e.stopPropagation();
          imgEl.dispatchEvent(
            new CustomEvent("imagefullscreen", {
              bubbles: true,
              composed: true,
              detail: {
                src: attrs.src,
                filename: attrs.filename,
                s3Files: attrs.s3Files,
                s3BaseUrl: attrs.s3BaseUrl,
                aesKey: attrs.aesKey,
                aesNonce: attrs.aesNonce,
              },
            }),
          );
        });
      }
    }
  }

  /**
   * Renders a user-uploaded image in read-only context by mounting ImageEmbedPreview.svelte.
   * Used when attrs.src (blob URL) is absent but S3 data is present — this happens when
   * a sent/received message is rendered in ReadOnlyMessage.svelte and the blob URL from
   * the original upload session has been discarded during serialization.
   */
  private _renderS3Image(content: HTMLElement, attrs: ImageEmbedAttrs): void {
    // Cleanup any previously mounted component on this element
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[ImageRenderer] Error unmounting existing S3 preview:",
          e,
        );
      }
    }

    content.innerHTML = "";

    try {
      const handleFullscreen = () => {
        // Fire imagefullscreen event so ActiveChat.svelte can open UploadedImageFullscreen
        content.dispatchEvent(
          new CustomEvent("imagefullscreen", {
            bubbles: true,
            composed: true,
            detail: {
              src: undefined,
              filename: attrs.filename,
              s3Files: attrs.s3Files,
              s3BaseUrl: attrs.s3BaseUrl,
              aesKey: attrs.aesKey,
              aesNonce: attrs.aesNonce,
            },
          }),
        );
      };

      const component = mount(ImageEmbedPreview, {
        target: content,
        props: {
          id: attrs.id || "",
          filename: attrs.filename,
          status: (attrs.status || "finished") as
            | "uploading"
            | "processing"
            | "finished"
            | "error",
          s3Files: attrs.s3Files,
          s3BaseUrl: attrs.s3BaseUrl,
          aesKey: attrs.aesKey,
          aesNonce: attrs.aesNonce,
          isMobile: false,
          onFullscreen: handleFullscreen,
        },
      });

      mountedComponents.set(content, component);
      console.debug("[ImageRenderer] Mounted ImageEmbedPreview for S3 image:", {
        filename: attrs.filename,
        hasS3Files: !!attrs.s3Files,
      });
    } catch (error) {
      console.error("[ImageRenderer] Error mounting ImageEmbedPreview:", error);
      // Fallback: show a simple placeholder rather than the confusing "URL not available" error
      content.innerHTML = `<div class="image-error-fallback" style="padding:8px;font-size:12px;color:var(--color-grey-50)">Image unavailable</div>`;
    }
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    const extended = attrs as ImageEmbedAttrs;
    const url = attrs.url || extended.src || "";
    const alt = attrs.filename || attrs.title || "";
    return `![${alt}](${url})`;
  }

  update(context: EmbedRenderContext): boolean {
    // Re-render when attrs change (e.g. status transitions uploading → finished → error).
    // For S3 image case, _renderS3Image handles unmounting the old component before mounting.
    this.render(context);
    return true;
  }
}
