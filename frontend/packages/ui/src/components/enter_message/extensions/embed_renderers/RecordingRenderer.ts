// RecordingRenderer.ts
//
// Renderer for audio recording embeds in the TipTap editor.
//
// Handles the 'recording' embed type which is inserted when the user records
// a voice note via the press-and-hold mic button. The embed goes through these
// states (set by insertRecording() in embedHandlers.ts):
//
//   status: 'uploading'    — Audio blob is uploading to the upload server.
//                            blobUrl is set for local audio playback.
//   status: 'transcribing' — Upload done, Mistral Voxtral transcription in progress.
//   status: 'finished'     — Both upload and transcription succeeded.
//                            transcript contains the text, uploadEmbedId is set.
//   status: 'error'        — Either upload or transcription failed.
//
// Two rendering contexts:
//
//   A) Editor context (blobUrl present): The embed is live in the message editor,
//      not yet sent. All attrs (transcript, duration, s3Files, etc.) are in-memory
//      TipTap node attrs populated by embedHandlers. Shows play button + stop button.
//      Fullscreen is editable (transcript can be overridden before send).
//
//   B) Read-only context (blobUrl absent, contentRef set): The embed is in a received
//      or sent message. The in-memory attrs were never serialised (they are rendered:false
//      in Embed.ts). The renderer must load them from EmbedStore using contentRef.
//      This mirrors the pattern used by ImageRenderer.ts.
//
// Events fired (bubble from the content element):
//
//   'cancelrecordingupload'  — Stop button clicked during upload.
//                              Handled by Embed.ts node view which calls
//                              cancelUpload(id) and deletes the node.
//
//   'recordingfullscreen'    — Fullscreen clicked when status is 'finished'.
//                              Handled by MessageInput.svelte → ActiveChat.svelte.
//                              Detail: { transcript, blobUrl, filename, s3Files, aesKey, aesNonce,
//                                        embedId, model, isEditable }
//
//   'retryrecordingtranscription' — Retry button clicked when status is 'error' and
//                                   upload already succeeded (s3Files is present).
//                                   Handled by MessageInput.svelte which calls
//                                   retryTranscription(editor, embedId).
//                                   Detail: { embedId }

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { mount, unmount } from "svelte";
import { get } from "svelte/store";
import RecordingEmbedPreview from "../../../embeds/audio/RecordingEmbedPreview.svelte";
import { authStore } from "../../../../stores/authStore";
import { embedStore } from "../../../../services/embedStore";

// Track mounted Svelte components for cleanup (keyed by the DOM element)
const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

/**
 * Extended attrs type for recording embeds.
 * Fields are populated progressively by insertRecording() and _performRecordingUpload().
 */
interface RecordingEmbedAttrs extends Omit<EmbedNodeAttributes, "status"> {
  /** Upload lifecycle status */
  status: "uploading" | "transcribing" | "finished" | "error";
  /** Local blob URL for immediate audio playback (editor context only, ephemeral) */
  blobUrl?: string;
  /** Error message set on failure */
  uploadError?: string;
  /** Transcript text from Mistral Voxtral */
  transcript?: string;
  /** Formatted duration (e.g. "0:42") */
  duration?: string;
  /** Server-assigned embed_id (populated after upload) */
  uploadEmbedId?: string;
  /** S3 file metadata from upload server */
  s3Files?: Record<string, { s3_key: string; size_bytes: number }>;
  /** S3 base URL */
  s3BaseUrl?: string;
  /** Plaintext AES-256 key (base64) */
  aesKey?: string;
  /** AES-GCM nonce (base64) */
  aesNonce?: string;
  /** Vault-wrapped AES key for server-side skill access */
  vaultWrappedAesKey?: string;
  /** MIME type of the original recording (e.g. 'audio/webm') */
  mimeType?: string;
  /** Transcription model name (e.g. 'voxtral-mini-2602') */
  model?: string;
}

/**
 * Renderer for audio recording embeds.
 * Mounts RecordingEmbedPreview.svelte which shows a compact audio player
 * and transcript preview.
 */
export class RecordingRenderer implements EmbedRenderer {
  type = "recording";

  render(context: EmbedRenderContext): void | Promise<void> {
    const { content } = context;
    const attrs = context.attrs as RecordingEmbedAttrs;

    // -----------------------------------------------------------------------
    // Context A: Editor context — blobUrl is present (in-memory, pre-send).
    // All attrs are live TipTap node attrs; no EmbedStore lookup needed.
    // -----------------------------------------------------------------------
    if (attrs.blobUrl) {
      this._renderRecordingComponent(content, attrs, true);
      return;
    }

    // -----------------------------------------------------------------------
    // Context B: Read-only context — embed is in a received/sent message.
    // The in-memory attrs (s3Files, aesKey, transcript, etc.) were never
    // serialised (rendered:false in Embed.ts). Load from EmbedStore using
    // contentRef, then re-render with the full data.
    //
    // This mirrors the pattern used by ImageRenderer.ts Case 2b.
    // -----------------------------------------------------------------------
    if (attrs.contentRef && attrs.contentRef.startsWith("embed:")) {
      // Show a loading placeholder while fetching from EmbedStore
      content.innerHTML = `<div class="recording-embed-loading" style="display:flex;align-items:center;justify-content:center;min-height:80px;padding:8px;"><div class="loading-spinner" style="width:20px;height:20px;border:2px solid var(--color-grey-20,#eaeaea);border-top-color:var(--color-app-audio,#e05555);border-radius:50%;animation:spin 0.8s linear infinite;"></div></div>`;

      return embedStore
        .get(attrs.contentRef)
        .then(async (embedData) => {
          if (!embedData?.content) {
            // EmbedStore miss — try requesting from server (non-blocking WebSocket)
            console.warn(
              "[RecordingRenderer] EmbedStore miss for read-only recording embed:",
              attrs.contentRef,
            );
            // Show fallback with "no transcript" state so the card is still visible
            const fallbackAttrs: RecordingEmbedAttrs = {
              ...attrs,
              status: "finished",
            };
            this._renderRecordingComponent(content, fallbackAttrs, false);
            return;
          }

          // Decode the TOON/JSON content to extract S3/AES metadata + transcript/duration.
          // The content field holds the TOON-encoded embedContent object stored by
          // sendHandlers.ts (keys: s3_base_url, files, aes_key, aes_nonce, transcript,
          // duration, filename, mime_type, model).
          let parsed: Record<string, unknown> = {};
          const rawContent = embedData.content as string;
          try {
            const { decode: toonDecode } = await import("@toon-format/toon");
            parsed = toonDecode(rawContent) as Record<string, unknown>;
          } catch {
            try {
              parsed = JSON.parse(rawContent);
            } catch {
              console.warn(
                "[RecordingRenderer] Could not parse EmbedStore content for read-only recording embed:",
                attrs.contentRef,
              );
            }
          }

          const s3Files = parsed.files as
            | RecordingEmbedAttrs["s3Files"]
            | undefined;
          const s3BaseUrl = parsed.s3_base_url as string | undefined;
          const aesKey = parsed.aes_key as string | undefined;
          const aesNonce = parsed.aes_nonce as string | undefined;
          const transcript = parsed.transcript as string | undefined;
          const duration = (parsed.duration as string) || attrs.duration;
          const filename = (parsed.filename as string) || attrs.filename;
          const mimeType = (parsed.mime_type as string) || attrs.mimeType;
          const model = (parsed.model as string) || undefined;

          const restoredAttrs: RecordingEmbedAttrs = {
            ...attrs,
            s3Files,
            s3BaseUrl,
            aesKey,
            aesNonce,
            transcript,
            duration,
            filename,
            mimeType,
            model,
            status: "finished",
          };

          this._renderRecordingComponent(content, restoredAttrs, false);

          console.debug(
            "[RecordingRenderer] Restored read-only recording embed from EmbedStore:",
            attrs.contentRef,
            {
              hasTranscript: !!transcript,
              hasDuration: !!duration,
              hasS3Files: !!s3Files,
              model,
            },
          );
        })
        .catch((err) => {
          console.error(
            "[RecordingRenderer] Failed to load read-only recording from EmbedStore:",
            err,
          );
          // Render in degraded state rather than leaving the loading spinner
          const fallbackAttrs: RecordingEmbedAttrs = {
            ...attrs,
            status: "finished",
          };
          this._renderRecordingComponent(content, fallbackAttrs, false);
        });
    }

    // Fallback: no blobUrl and no contentRef — render with whatever attrs we have
    this._renderRecordingComponent(content, attrs, false);
  }

  /**
   * Mounts RecordingEmbedPreview.svelte into the given DOM element.
   * Unmounts any previously mounted instance first (handles re-renders on
   * attr updates such as status transitions).
   *
   * @param content     DOM element to mount the component into.
   * @param attrs       Recording embed attrs (may be fully or partially populated).
   * @param isEditable  True when in editor context (enables transcript editing in fullscreen).
   */
  private _renderRecordingComponent(
    content: HTMLElement,
    attrs: RecordingEmbedAttrs,
    isEditable: boolean,
  ): void {
    // Unmount any existing component on this DOM node before remounting
    const existing = mountedComponents.get(content);
    if (existing) {
      try {
        unmount(existing);
      } catch (e) {
        console.warn(
          "[RecordingRenderer] Error unmounting existing recording preview:",
          e,
        );
      }
    }

    content.innerHTML = "";

    try {
      const handleFullscreen = () => {
        // Bubble 'recordingfullscreen' so ActiveChat.svelte can open a fullscreen
        // transcript viewer / editor.
        // Pass isEditable so the fullscreen component knows whether the transcript
        // can be edited (only in editor context, before the message is sent).
        content.dispatchEvent(
          new CustomEvent("recordingfullscreen", {
            bubbles: true,
            composed: true,
            detail: {
              transcript: attrs.transcript,
              blobUrl: attrs.blobUrl,
              filename: attrs.filename,
              duration: attrs.duration,
              s3Files: attrs.s3Files,
              s3BaseUrl: attrs.s3BaseUrl,
              aesKey: attrs.aesKey,
              aesNonce: attrs.aesNonce,
              embedId: attrs.id,
              model: attrs.model,
              isEditable,
            },
          }),
        );
      };

      const handleStop = () => {
        // Bubble 'cancelrecordingupload' so Embed.ts node view can abort the
        // in-flight fetch and remove the node.
        content.dispatchEvent(
          new CustomEvent("cancelrecordingupload", {
            bubbles: true,
            composed: true,
            detail: { embedId: attrs.id },
          }),
        );
      };

      const handleRetry = () => {
        // Bubble 'retryrecordingtranscription' so MessageInput.svelte can call
        // retryTranscription(editor, embedId) with the live editor reference.
        // This avoids needing an editor reference inside the renderer
        // (EmbedRenderContext does not expose the editor instance).
        content.dispatchEvent(
          new CustomEvent("retryrecordingtranscription", {
            bubbles: true,
            composed: true,
            detail: { embedId: attrs.id },
          }),
        );
      };

      // Read auth state from authStore (same pattern as ImageRenderer.ts)
      const isAuthenticated = get(authStore).isAuthenticated;

      const component = mount(RecordingEmbedPreview, {
        target: content,
        props: {
          id: attrs.id || "",
          filename: attrs.filename,
          status: (attrs.status || "finished") as
            | "uploading"
            | "transcribing"
            | "finished"
            | "error",
          blobUrl: attrs.blobUrl,
          uploadError: attrs.uploadError,
          transcript: attrs.transcript,
          duration: attrs.duration,
          s3Files: attrs.s3Files,
          s3BaseUrl: attrs.s3BaseUrl,
          aesKey: attrs.aesKey,
          aesNonce: attrs.aesNonce,
          model: attrs.model,
          isMobile: false,
          isAuthenticated,
          onFullscreen: handleFullscreen,
          onStop: handleStop,
          // onRetry is only available when upload succeeded (s3Files present)
          // and status is 'error' (transcription failed). Guard prevents showing
          // retry when upload itself failed (no S3 data to retry from).
          onRetry: attrs.s3Files ? handleRetry : undefined,
        },
      });

      mountedComponents.set(content, component);

      console.debug("[RecordingRenderer] Mounted RecordingEmbedPreview:", {
        filename: attrs.filename,
        status: attrs.status,
        hasBlobUrl: !!attrs.blobUrl,
        hasTranscript: !!attrs.transcript,
        hasDuration: !!attrs.duration,
        isEditable,
        model: attrs.model,
      });
    } catch (error) {
      console.error(
        "[RecordingRenderer] Error mounting RecordingEmbedPreview:",
        error,
      );
      content.innerHTML = `<div style="padding:8px;font-size:12px;color:var(--color-grey-50)">Voice note unavailable</div>`;
    }
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    // Delegates to serializeEmbedToMarkdown in serializers.ts via the
    // standard embed serialization path. This method is only used as a
    // fallback in some copy scenarios — the real serialization goes via
    // the switch statement in serializers.ts.
    const extended = attrs as RecordingEmbedAttrs;
    if (attrs.contentRef?.startsWith("embed:")) {
      const embed_id = attrs.contentRef.replace("embed:", "");
      return `\`\`\`json\n${JSON.stringify({ type: "audio-recording", embed_id })}\n\`\`\``;
    }
    // No contentRef yet — not yet uploaded / stored
    return extended.blobUrl
      ? `[Voice note: ${attrs.filename || "recording"}]`
      : "";
  }

  update(context: EmbedRenderContext): boolean {
    // Re-render whenever attrs change (status transitions, transcript arrives, etc.)
    this.render(context);
    return true;
  }
}
