// Image renderer for static SVG images AND user-uploaded images in the message editor.
//
// Handles THREE sub-types of the 'image' embed:
//   1. User-uploaded images (editor context): attrs.src (blob URL) is set.
//      Mounts ImageEmbedPreview.svelte passing src, so the card shows the local blob
//      preview. Status shown as subtitle ("Uploading…", "Upload failed", etc.).
//   2. User-uploaded images (read-only context): attrs.src is absent but S3 data
//      (attrs.s3Files, attrs.aesKey, etc.) is present. Mounts ImageEmbedPreview.svelte
//      which fetches and decrypts the image from S3.
//   3. Static/SVG images (legal documents): attrs.url is set, no upload data.
//
// Cases 1 and 2 both use _renderImageComponent() which mounts ImageEmbedPreview.svelte.
//
// Stop button (Case 1, status 'uploading' only):
//   onStop() → fires 'cancelimageupload' CustomEvent (bubbles) on content element
//   → Embed.ts node view listener calls cancelUpload(id) + deletes the node.
//
// Fullscreen click (Case 1 finished, Case 2):
//   onFullscreen() → fires 'imagefullscreen' CustomEvent (bubbles) on content element
//   → MessageInput.svelte re-dispatches to ActiveChat.svelte → UploadedImageFullscreen.

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { mount, unmount } from "svelte";
import { get } from "svelte/store";
import ImageEmbedPreview from "../../../embeds/images/ImageEmbedPreview.svelte";
import { authStore } from "../../../../stores/authStore";
import { embedStore } from "../../../../services/embedStore";

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
  /** Original File object (ephemeral, only available in editor context during upload session) */
  originalFile?: File;
}

/**
 * Renderer for image embeds in the TipTap editor.
 * Covers both static document images and user-uploaded chat images.
 */
export class ImageRenderer implements EmbedRenderer {
  type = "image";

  render(context: EmbedRenderContext): void | Promise<void> {
    const { content } = context;
    const attrs = context.attrs as ImageEmbedAttrs;

    // -----------------------------------------------------------------------
    // Cases 1 & 2: User-uploaded image — editor context (has src blob URL)
    // OR read-only context (src absent, S3 data present).
    // Both cases mount ImageEmbedPreview.svelte; it handles the rendering
    // logic internally based on which props are set.
    // -----------------------------------------------------------------------
    if (attrs.src || (attrs.s3Files && attrs.aesKey)) {
      this._renderImageComponent(content, attrs);
      return;
    }

    // -----------------------------------------------------------------------
    // Case 2b: Restored draft node — contentRef is set (embed:{id}) but
    // s3Files/aesKey are absent because they were stored as rendered:false
    // attrs (never serialised). Load the S3/AES metadata from EmbedStore
    // and re-render once the data is available.
    //
    // This happens when the user uploads an image, doesn't send, then
    // reloads the page. The draft restores the embed node with only
    // contentRef; _performUpload registered the full embed in EmbedStore
    // before setting contentRef so we can retrieve the data here.
    // -----------------------------------------------------------------------
    if (
      attrs.contentRef &&
      attrs.contentRef.startsWith("embed:") &&
      !attrs.url
    ) {
      const embedId = attrs.contentRef.replace("embed:", "");
      // Show a loading spinner while we fetch from EmbedStore
      content.innerHTML =
        '<div class="image-embed-loading" style="display:flex;align-items:center;justify-content:center;min-height:80px;"><div class="loading-spinner" style="width:24px;height:24px;border:2px solid var(--color-grey-20,#eaeaea);border-top-color:var(--color-primary-50,#5b8dd9);border-radius:50%;animation:spin 0.8s linear infinite;"></div></div>';

      return embedStore
        .get(attrs.contentRef)
        .then(async (embedData) => {
          if (!embedData?.content) {
            // EmbedStore miss — image cannot be restored (e.g. different device/browser)
            console.warn(
              "[ImageRenderer] EmbedStore miss for restored draft image:",
              embedId,
            );
            content.innerHTML =
              '<div class="image-error" style="padding:8px;font-size:12px;color:var(--color-grey-50)">Image unavailable (reload the page)</div>';
            return;
          }
          // Decode the TOON/JSON content stored by _performUpload to extract S3/AES metadata.
          // The content field holds the TOON-encoded embedContent object whose top-level
          // fields are: s3_base_url, files, aes_key, aes_nonce, filename, etc.
          let parsed: Record<string, unknown> = {};
          const rawContent = embedData.content as string;
          try {
            // Try TOON decode first (the primary storage format)
            const { decode: toonDecode } = await import("@toon-format/toon");
            parsed = toonDecode(rawContent) as Record<string, unknown>;
          } catch {
            // Fall back to JSON (used when toonEncode itself failed at storage time)
            try {
              parsed = JSON.parse(rawContent);
            } catch {
              console.warn(
                "[ImageRenderer] Could not parse EmbedStore content for restored draft image:",
                embedId,
              );
            }
          }

          const s3Files = parsed.files as
            | ImageEmbedAttrs["s3Files"]
            | undefined;
          const s3BaseUrl = parsed.s3_base_url as string | undefined;
          const aesKey = parsed.aes_key as string | undefined;
          const aesNonce = parsed.aes_nonce as string | undefined;
          const filename = (parsed.filename as string) || attrs.filename;

          if (!s3Files || !aesKey || !s3BaseUrl) {
            console.warn(
              "[ImageRenderer] EmbedStore entry missing S3 data for restored draft image:",
              embedId,
              parsed,
            );
            content.innerHTML =
              '<div class="image-error" style="padding:8px;font-size:12px;color:var(--color-grey-50)">Image unavailable</div>';
            return;
          }

          // Re-render with full S3 data from EmbedStore
          const restoredAttrs: ImageEmbedAttrs = {
            ...attrs,
            s3Files,
            s3BaseUrl,
            aesKey,
            aesNonce,
            filename: filename || undefined,
            status: "finished",
          };
          this._renderImageComponent(content, restoredAttrs);
          console.debug(
            "[ImageRenderer] Restored draft image embed from EmbedStore:",
            embedId,
          );
        })
        .catch((err) => {
          console.error(
            "[ImageRenderer] Failed to load restored draft image from EmbedStore:",
            err,
          );
          content.innerHTML =
            '<div class="image-error" style="padding:8px;font-size:12px;color:var(--color-grey-50)">Image unavailable</div>';
        });
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

  /**
   * Mounts ImageEmbedPreview.svelte for a user-uploaded image.
   *
   * Covers both contexts:
   *   - Editor context: attrs.src (blob URL) is set. The component shows the local
   *     preview image with uploading/error overlays as appropriate.
   *   - Read-only context: attrs.src is absent but S3 data is present. The component
   *     lazy-fetches and decrypts the image from S3.
   *
   * Cleans up any previously mounted Svelte component before mounting a new one
   * to handle status-change re-renders (e.g. uploading → finished).
   */
  private _renderImageComponent(
    content: HTMLElement,
    attrs: ImageEmbedAttrs,
  ): void {
    // Unmount any existing component on this DOM node
    const existingComponent = mountedComponents.get(content);
    if (existingComponent) {
      try {
        unmount(existingComponent);
      } catch (e) {
        console.warn(
          "[ImageRenderer] Error unmounting existing image preview:",
          e,
        );
      }
    }

    content.innerHTML = "";

    try {
      const handleFullscreen = () => {
        // Bubble imagefullscreen event so ActiveChat.svelte can open UploadedImageFullscreen.
        // Use the blob URL (src) when available (editor context), otherwise undefined
        // (read-only context — ActiveChat will fetch from S3 for the fullscreen view).
        // Include auth state + file metadata so the fullscreen can show the correct subtitle.
        const fullscreenIsAuthenticated = get(authStore).isAuthenticated;
        const fullscreenFileSize = attrs.originalFile?.size;
        const fullscreenFileType = attrs.originalFile?.type;
        content.dispatchEvent(
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
              isAuthenticated: fullscreenIsAuthenticated,
              fileSize: fullscreenFileSize,
              fileType: fullscreenFileType,
            },
          }),
        );
      };

      // Stop button handler: fires a bubbling event so the Embed.ts node view
      // can cancel the upload and delete the node (it has access to getPos/editor).
      const handleStop = () => {
        content.dispatchEvent(
          new CustomEvent("cancelimageupload", {
            bubbles: true,
            composed: true,
            detail: { embedId: attrs.id },
          }),
        );
      };

      // Read authentication state to show appropriate subtitle
      // (file type + size when authenticated, "Login to upload…" when not)
      const isAuthenticated = get(authStore).isAuthenticated;

      // Derive file size and MIME type from the original File object if available
      const fileSize = attrs.originalFile?.size;
      const fileType = attrs.originalFile?.type;

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
          src: attrs.src,
          uploadError: attrs.uploadError,
          s3Files: attrs.s3Files,
          s3BaseUrl: attrs.s3BaseUrl,
          aesKey: attrs.aesKey,
          aesNonce: attrs.aesNonce,
          isMobile: false,
          isAuthenticated,
          fileSize,
          fileType,
          onFullscreen: handleFullscreen,
          onStop: handleStop,
        },
      });

      mountedComponents.set(content, component);
      console.debug("[ImageRenderer] Mounted ImageEmbedPreview:", {
        filename: attrs.filename,
        status: attrs.status,
        hasSrc: !!attrs.src,
        hasS3Files: !!attrs.s3Files,
      });
    } catch (error) {
      console.error("[ImageRenderer] Error mounting ImageEmbedPreview:", error);
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
