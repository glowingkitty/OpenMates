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
// Events fired (bubble from the content element):
//
//   'cancelrecordingupload'  — Stop button clicked during upload.
//                              Handled by Embed.ts node view which calls
//                              cancelUpload(id) and deletes the node.
//
//   'recordingfullscreen'    — Fullscreen clicked when status is 'finished'.
//                              Handled by MessageInput.svelte → ActiveChat.svelte.
//                              Detail: { transcript, blobUrl, filename, s3Files, aesKey, aesNonce }

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { mount, unmount } from "svelte";
import RecordingEmbedPreview from "../../../embeds/audio/RecordingEmbedPreview.svelte";

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
}

/**
 * Renderer for audio recording embeds.
 * Mounts RecordingEmbedPreview.svelte which shows a compact audio player
 * and transcript preview.
 */
export class RecordingRenderer implements EmbedRenderer {
  type = "recording";

  render(context: EmbedRenderContext): void {
    const { content } = context;
    const attrs = context.attrs as RecordingEmbedAttrs;

    this._renderRecordingComponent(content, attrs);
  }

  /**
   * Mounts RecordingEmbedPreview.svelte into the given DOM element.
   * Unmounts any previously mounted instance first (handles re-renders on
   * attr updates such as status transitions).
   */
  private _renderRecordingComponent(
    content: HTMLElement,
    attrs: RecordingEmbedAttrs,
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
          isMobile: false,
          isAuthenticated: true,
          onFullscreen: handleFullscreen,
          onStop: handleStop,
        },
      });

      mountedComponents.set(content, component);

      console.debug("[RecordingRenderer] Mounted RecordingEmbedPreview:", {
        filename: attrs.filename,
        status: attrs.status,
        hasBlobUrl: !!attrs.blobUrl,
        hasTranscript: !!attrs.transcript,
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
