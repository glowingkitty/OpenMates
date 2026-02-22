import type { Editor } from "@tiptap/core";
import { getLanguageFromFilename } from "./utils"; // Assuming utils are accessible
import { extractEpubCover, getEpubMetadata } from "./utils";
import { resizeImage } from "./utils";
import { generateUUID } from "../../message_parsing/utils";
import { uploadFileToServer } from "./services/uploadService";
import { embedStore } from "../../services/embedStore";
import {
  createCodeEmbed,
  detectLanguageFromContent,
} from "./services/codeEmbedService";
import { encode as toonEncode } from "@toon-format/toon";
import { getApiUrl } from "../../config/api";
import { notificationStore } from "../../stores/notificationStore";
import { settingsDeepLink } from "../../stores/settingsDeepLinkStore";
import { panelState } from "../../stores/panelStateStore";

/**
 * Ensure the editor has an empty paragraph at the very beginning so that when
 * an embed is the first content node the user can still click/navigate to place
 * the cursor before it.
 *
 * If the editor currently only contains an empty paragraph (default initial state)
 * OR the document would otherwise start directly with an embed, we prepend an
 * additional empty paragraph so there is always a text position above the embed.
 *
 * This is called right before every embed insertion.
 */
function ensureLeadingParagraph(editor: Editor): void {
  const { doc } = editor.state;

  // Walk the top-level children of the document
  const firstChild = doc.firstChild;
  if (!firstChild) return;

  // If the first paragraph is non-empty (has text / embeds already), no need to prepend.
  // Only prepend when the editor is effectively empty — the first (and only) paragraph
  // contains nothing meaningful (isEmpty reports true for the full doc).
  if (!editor.isEmpty) return;

  // Editor is empty — the content will start with the embed we're about to insert.
  // Insert an extra empty paragraph at the beginning so users can position cursor there.
  // We use insertContentAt position 1 (inside the empty first paragraph → creates a
  // hard-break then the editor naturally has two paragraphs after the embed is added).
  editor.commands.insertContentAt(1, { type: "paragraph" });
}

// ---------------------------------------------------------------------------
// Upload cancellation registry
//
// Maps embed IDs to their in-flight AbortController so that:
//   - cancelUpload(embedId) can abort the fetch immediately
//   - Backspace / Stop button can cancel from outside embedHandlers
//
// Entries are cleaned up automatically after upload completes or is cancelled.
// ---------------------------------------------------------------------------
const _uploadControllers = new Map<string, AbortController>();

/**
 * Cancel an in-flight image upload by embed ID.
 * Safe to call even if the upload has already completed (no-op in that case).
 */
export function cancelUpload(embedId: string): void {
  const controller = _uploadControllers.get(embedId);
  if (controller) {
    console.debug("[EmbedHandlers] Cancelling upload for embed:", embedId);
    controller.abort();
    _uploadControllers.delete(embedId);
  }
}

/**
 * Inserts a video embed into the editor.
 */
export async function insertVideo(
  editor: Editor,
  file: File,
  duration?: string,
  isRecording: boolean = false,
): Promise<void> {
  ensureLeadingParagraph(editor);
  const url = URL.createObjectURL(file);
  editor.commands.insertContent([
    {
      type: "embed",
      attrs: {
        id: generateUUID(),
        type: "videos-video",
        status: "finished",
        contentRef: null,
        src: url,
        filename: file.name,
        duration: duration || "00:00",
        isRecording,
      },
    },
    {
      type: "text",
      text: " ",
    },
  ]);
  // Use setTimeout to ensure focus happens after potential DOM updates
  setTimeout(() => {
    editor.commands.focus("end");
  }, 50);
}

/**
 * Inserts an image embed into the editor and triggers the server upload pipeline.
 *
 * Upload flow (authenticated users):
 *  1. Generate a client-side blob URL for instant local preview.
 *  2. Insert the embed node with status: 'uploading' immediately (non-blocking).
 *  3. Fire the upload to the server in the background.
 *  4. On success: update the embed node with S3 keys, AES metadata, status: 'finished'.
 *  5. On failure: update the embed node with status: 'error'.
 *
 * Demo mode (unauthenticated users):
 *  - Insert the embed with status: 'finished' immediately using the local blob URL only.
 *  - No server upload is performed. The embed is visual-only — it lets the user
 *    draft a message with an image before signing up. No S3 keys are set.
 *
 * The aes_key and vault_wrapped_aes_key returned by the server are stored as
 * embed node attributes so they are included in the TOON content when the
 * message is sent. The TOON content is then client-encrypted before Directus
 * storage (zero-knowledge at rest).
 */
export async function insertImage(
  editor: Editor,
  file: File,
  isRecording: boolean = false,
  previewUrl?: string,
  originalUrl?: string,
  isAuthenticated: boolean = true,
): Promise<void> {
  // Step 1: Create a local blob URL for instant preview while uploading
  let localPreviewUrl: string;
  let localOriginalUrl: string;

  if (previewUrl && originalUrl) {
    localPreviewUrl = previewUrl;
    localOriginalUrl = originalUrl;
  } else {
    try {
      const resized = await resizeImage(file);
      localPreviewUrl = resized.previewUrl;
      localOriginalUrl = resized.originalUrl;
    } catch (error) {
      console.error(
        "[EmbedHandlers] Error creating local image preview:",
        error,
      );
      const blobUrl = URL.createObjectURL(file);
      localPreviewUrl = blobUrl;
      localOriginalUrl = blobUrl;
    }
  }

  // Step 2: Generate a stable embed ID to reference the node after insertion
  const embedId = generateUUID();

  if (!isAuthenticated) {
    // Demo mode: insert with status 'finished' immediately — no server upload.
    // The image is local-only; it lets unauthenticated users draft a message
    // with an image preview before they sign up.
    console.debug(
      "[EmbedHandlers] Demo mode — inserting image without server upload (user not authenticated)",
    );
    ensureLeadingParagraph(editor);
    editor.commands.insertContent([
      {
        type: "embed",
        attrs: {
          id: embedId,
          type: "image",
          status: "finished",
          contentRef: null,
          src: localPreviewUrl,
          originalUrl: localOriginalUrl,
          originalFile: file,
          filename: file.name,
          isRecording,
          uploadEmbedId: null,
          s3Files: null,
          s3BaseUrl: null,
          aesKey: null,
          aesNonce: null,
          vaultWrappedAesKey: null,
          contentHash: null,
          aiDetection: null,
          uploadError: null,
        },
      },
      {
        type: "text",
        text: " ",
      },
    ]);
    setTimeout(() => {
      editor.commands.focus("end");
    }, 50);
    return;
  }

  // Step 3: Insert embed immediately with status 'uploading' and local preview.
  // status: 'uploading' signals to the message sending logic that this embed
  // is not ready yet, preventing premature message submission.
  ensureLeadingParagraph(editor);
  editor.commands.insertContent([
    {
      type: "embed",
      attrs: {
        id: embedId,
        type: "image",
        status: "uploading",
        contentRef: null,
        src: localPreviewUrl,
        originalUrl: localOriginalUrl,
        originalFile: file,
        filename: file.name,
        isRecording,
        // Upload-specific fields (populated after server response):
        uploadEmbedId: null, // Server-assigned embed_id
        s3Files: null, // Record<string, FileVariantMetadata>
        s3BaseUrl: null,
        aesKey: null, // Plaintext AES-256 key for client-side rendering
        aesNonce: null,
        vaultWrappedAesKey: null, // Vault-wrapped key for server-side skill access
        contentHash: null,
        aiDetection: null, // { ai_generated: number, provider: string } | null
        uploadError: null,
      },
    },
    {
      type: "text",
      text: " ",
    },
  ]);
  setTimeout(() => {
    editor.commands.focus("end");
  }, 50);

  // Step 4: Upload in the background — non-blocking.
  // Register an AbortController so the upload can be cancelled via cancelUpload().
  const controller = new AbortController();
  _uploadControllers.set(embedId, controller);
  _performUpload(editor, embedId, file, controller.signal).catch((err) => {
    console.error("[EmbedHandlers] Unhandled error in _performUpload:", err);
  });
}

/**
 * Performs the actual file upload and updates the embed node on completion.
 * Called in the background by insertImage — errors are caught and reflected
 * in the embed node's status attribute.
 *
 * @param signal - AbortSignal from the registered AbortController. Aborting it
 *   cancels the fetch and causes the error branch to run with an AbortError,
 *   which we handle by leaving the embed node as-is (caller removes it).
 */
async function _performUpload(
  editor: Editor,
  localEmbedId: string,
  file: File,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const result = await uploadFileToServer(file, signal);

    // Register the embed in EmbedStore immediately after upload — do NOT wait for
    // handleSend. This ensures the draft serialiser can emit a proper embed reference
    // block (```json {"type":"image","embed_id":"..."}```) so the image survives a
    // page reload. Without this, the draft markdown drops the image entirely because
    // serializeEmbedToMarkdown() only emits an image block when contentRef is set.
    //
    // handleSend() filters by !node.attrs.contentRef, so it will skip re-registering
    // nodes that already have contentRef set — the operation is fully idempotent.
    const uploadEmbedId = result.embed_id;
    try {
      const { encode: toonEncode } = await import("@toon-format/toon");
      const embedContent = {
        app_id: "images",
        skill_id: "upload",
        type: "image",
        status: "finished",
        filename: file.name || null,
        content_hash: result.content_hash || null,
        s3_base_url: result.s3_base_url || null,
        files: result.files || null,
        aes_key: result.aes_key || null,
        aes_nonce: result.aes_nonce || null,
        vault_wrapped_aes_key: result.vault_wrapped_aes_key || null,
        ai_detection: result.ai_detection || null,
      };

      let toonContent: string;
      try {
        toonContent = toonEncode(embedContent);
      } catch {
        toonContent = JSON.stringify(embedContent);
      }

      const now = Date.now();
      await embedStore.put(
        `embed:${uploadEmbedId}`,
        {
          embed_id: uploadEmbedId,
          type: "images-image",
          status: "finished",
          content: toonContent,
          text_preview: file.name || "Uploaded image",
          createdAt: now,
          updatedAt: now,
        },
        "images-image",
      );
      console.debug(
        "[EmbedHandlers] Registered uploaded image in EmbedStore for draft persistence:",
        uploadEmbedId,
      );
    } catch (storeError) {
      // Non-fatal: the image is still uploaded — the draft just won't survive a reload.
      // Surface the error so it's visible (no silent failures).
      console.error(
        "[EmbedHandlers] Failed to register uploaded image in EmbedStore:",
        storeError,
      );
    }

    // Update the embed node with the server response data.
    // We use a ProseMirror transaction to update the node atomically.
    const { state, dispatch } = editor.view;
    const tr = state.tr;
    let updated = false;

    state.doc.descendants((node, pos) => {
      if (node.type.name === "embed" && node.attrs.id === localEmbedId) {
        tr.setNodeMarkup(pos, undefined, {
          ...node.attrs,
          // Keep the local preview URL — the embed card decrypts the S3 image
          // when the message is rendered (using the stored aesKey).
          status: "finished",
          uploadEmbedId: result.embed_id,
          s3Files: result.files,
          s3BaseUrl: result.s3_base_url,
          aesKey: result.aes_key,
          aesNonce: result.aes_nonce,
          vaultWrappedAesKey: result.vault_wrapped_aes_key,
          contentHash: result.content_hash,
          aiDetection: result.ai_detection,
          uploadError: null,
          // Set contentRef so the draft serialiser can persist this embed immediately.
          // handleSend() skips nodes where contentRef is already set (idempotent).
          contentRef: `embed:${uploadEmbedId}`,
        });
        updated = true;
        return false; // Stop traversal
      }
      return true;
    });

    // Upload succeeded — remove the AbortController from the registry
    _uploadControllers.delete(localEmbedId);

    if (updated) {
      dispatch(tr);
    } else {
      // Node was removed before upload completed (user deleted it) — ignore
      console.debug(
        "[EmbedHandlers] Embed node not found after upload (may have been removed by user)",
      );
    }
  } catch (uploadError) {
    // Remove the AbortController regardless of error type
    _uploadControllers.delete(localEmbedId);

    // If the upload was cancelled (user deleted embed or pressed Stop), do nothing —
    // the caller (Backspace handler or onStop callback) already removed the node.
    if (
      uploadError instanceof Error &&
      (uploadError.name === "AbortError" ||
        uploadError.message === "Upload cancelled")
    ) {
      console.debug(
        "[EmbedHandlers] Upload cancelled for embed:",
        localEmbedId,
      );
      return;
    }

    console.error("[EmbedHandlers] Image upload failed:", uploadError);

    // Update the embed node to show an error state so the user knows
    const { state, dispatch } = editor.view;
    const tr = state.tr;

    state.doc.descendants((node, pos) => {
      if (node.type.name === "embed" && node.attrs.id === localEmbedId) {
        tr.setNodeMarkup(pos, undefined, {
          ...node.attrs,
          status: "error",
          uploadError:
            uploadError instanceof Error
              ? uploadError.message
              : "Upload failed",
        });
        return false;
      }
      return true;
    });

    dispatch(tr);
  }
}

/**
 * Inserts a PDF embed into the editor and triggers the server upload + OCR pipeline.
 *
 * Upload flow (authenticated users only — no demo mode for PDFs):
 *  1. Insert the embed node immediately with status: 'uploading' and the filename.
 *  2. Upload the PDF to the server in the background.
 *  3. On success: update the embed node with S3 keys, AES metadata, page_count,
 *     and status: 'processing' (background OCR will update to 'finished' via WebSocket).
 *  4. On failure: update the embed node with status: 'error'.
 *
 * The server triggers background OCR processing (Mistral + pymupdf) after the upload
 * and delivers the final embed content via WebSocket embed_update event.
 */
export async function insertPDF(editor: Editor, file: File): Promise<void> {
  // Generate a stable embed ID to reference the node after insertion
  const embedId = generateUUID();

  // Insert immediately with status: 'uploading' so the send button is blocked
  // until the upload completes and we have at least the S3 keys.
  ensureLeadingParagraph(editor);
  editor.commands.insertContent([
    {
      type: "embed",
      attrs: {
        id: embedId,
        type: "pdf",
        status: "uploading",
        contentRef: null,
        filename: file.name,
        // Populated after server response:
        uploadEmbedId: null,
        pageCount: null,
        s3BaseUrl: null,
        aesNonce: null,
        vaultWrappedAesKey: null,
        uploadError: null,
      },
    },
    {
      type: "text",
      text: " ",
    },
  ]);
  setTimeout(() => {
    editor.commands.focus("end");
  }, 50);

  // Register an AbortController so the upload can be cancelled.
  const controller = new AbortController();
  _uploadControllers.set(embedId, controller);
  _performPdfUpload(editor, embedId, file, controller.signal).catch((err) => {
    console.error("[EmbedHandlers] Unhandled error in _performPdfUpload:", err);
  });
}

/**
 * Performs the actual PDF upload and updates the embed node on completion.
 * After a successful upload the status is set to 'processing' — the background
 * OCR pipeline on the server will push the final 'finished' state via WebSocket.
 */
async function _performPdfUpload(
  editor: Editor,
  localEmbedId: string,
  file: File,
  signal?: AbortSignal,
): Promise<void> {
  // Helper: update embed node attrs via a ProseMirror transaction.
  function updateEmbedNode(updates: Record<string, unknown>): void {
    const { state, dispatch } = editor.view;
    const tr = state.tr;
    let found = false;
    state.doc.descendants((node, pos) => {
      if (node.type.name === "embed" && node.attrs.id === localEmbedId) {
        tr.setNodeMarkup(pos, undefined, { ...node.attrs, ...updates });
        found = true;
        return false;
      }
      return true;
    });
    if (found) dispatch(tr);
  }

  try {
    const result = await uploadFileToServer(file, signal);

    // Remove the AbortController — upload completed successfully
    _uploadControllers.delete(localEmbedId);

    // Transition to 'processing' — the server is now running OCR in the background.
    // The WebSocket embed_update event will push the final 'finished' state later.
    updateEmbedNode({
      status: "processing",
      uploadEmbedId: result.embed_id,
      // page_count is returned by the upload server for PDFs (see UploadFileResponse)
      pageCount: result.page_count ?? null,
      s3BaseUrl: result.s3_base_url,
      aesNonce: result.aes_nonce,
      vaultWrappedAesKey: result.vault_wrapped_aes_key,
      uploadError: null,
    });

    console.debug(
      "[EmbedHandlers] PDF upload complete — processing in background:",
      { filename: file.name, embed_id: result.embed_id },
    );
  } catch (uploadError) {
    // Remove the AbortController regardless of error type
    _uploadControllers.delete(localEmbedId);

    // AbortError: upload was cancelled (user deleted embed or stopped)
    if (
      uploadError instanceof Error &&
      (uploadError.name === "AbortError" ||
        uploadError.message === "Upload cancelled")
    ) {
      console.debug(
        "[EmbedHandlers] PDF upload cancelled for embed:",
        localEmbedId,
      );
      return;
    }

    console.error("[EmbedHandlers] PDF upload failed:", uploadError);

    updateEmbedNode({
      status: "error",
      uploadError:
        uploadError instanceof Error ? uploadError.message : "Upload failed",
    });
  }
}

/**
 * Inserts a generic file or PDF embed into the editor.
 */
export async function insertFile(
  editor: Editor,
  file: File,
  type: "pdf" | "file",
): Promise<void> {
  ensureLeadingParagraph(editor);
  const url = URL.createObjectURL(file);
  editor.commands.insertContent([
    {
      type: "embed",
      attrs: {
        id: generateUUID(),
        type: type === "pdf" ? "pdf" : "file",
        status: "finished",
        contentRef: null,
        src: url,
        filename: file.name,
      },
    },
    {
      type: "text",
      text: " ",
    },
  ]);
  setTimeout(() => {
    editor.commands.focus("end");
  }, 50);
}

/**
 * Inserts an audio embed into the editor.
 */
export async function insertAudio(editor: Editor, file: File): Promise<void> {
  ensureLeadingParagraph(editor);
  const url = URL.createObjectURL(file);
  editor
    .chain()
    .focus() // Ensure editor has focus before inserting
    .insertContent([
      {
        type: "embed",
        attrs: {
          id: generateUUID(),
          type: "audio",
          status: "finished",
          contentRef: null,
          src: url,
          filename: file.name,
        },
      },
      {
        type: "text",
        text: " ",
      },
    ])
    .run();
  setTimeout(() => {
    editor.commands.focus("end");
  }, 50);
}

/**
 * Inserts a code file embed into the editor.
 *
 * For authenticated users:
 *   Reads file content, creates a TOON embed via createCodeEmbed() (PII detection &
 *   redaction included), stores it in EmbedStore, and inserts an embed reference block.
 *
 * For unauthenticated users (demo/preview mode):
 *   Skips EmbedStore (no encryption keys available) and inserts a preview embed node
 *   with the code content stored inline in the node's `code` attribute. This allows
 *   the preview to render without needing the server or IndexedDB decryption.
 *   PII detection is still run so the inline code uses the same redaction path.
 *
 * PII protection:
 * - File content is scanned for PII before being stored or shown
 * - Placeholders replace sensitive values in the code
 * - PII mappings are stored separately under master-key encryption (authenticated only)
 */
export async function insertCodeFile(
  editor: Editor,
  file: File,
  isAuthenticated: boolean = true,
): Promise<void> {
  ensureLeadingParagraph(editor);

  // Read the file content as text
  let fileContent: string;
  try {
    fileContent = await file.text();
  } catch (error) {
    console.error("[EmbedHandlers] Failed to read code file content:", error);
    // Fall back to a minimal embed with just filename/language info if reading fails
    const language = getLanguageFromFilename(file.name);
    editor
      .chain()
      .focus()
      .insertContent({
        type: "embed",
        attrs: {
          id: generateUUID(),
          type: "code-code",
          status: "error",
          contentRef: null,
          src: URL.createObjectURL(file),
          filename: file.name,
          language: language,
        },
      })
      .insertContent(" ")
      .run();
    setTimeout(() => editor.commands.focus("end"), 50);
    return;
  }

  // Detect language: prefer filename extension, fall back to content heuristics
  const language =
    getLanguageFromFilename(file.name) ||
    detectLanguageFromContent(fileContent) ||
    "text";

  if (!isAuthenticated) {
    // Unauthenticated / demo mode: insert a preview embed node with the code stored
    // inline in the node attributes. EmbedStore is not available without auth keys,
    // so we use the same "preview:" contentRef convention that pasted embeds use
    // during write mode — the GroupRenderer reads `item.code` for these nodes.
    const embedId = generateUUID();
    const lineCount = fileContent.split("\n").length;

    console.debug(
      "[EmbedHandlers] Demo mode — inserting inline code embed (unauthenticated):",
      { filename: file.name, language, lineCount, embedId },
    );

    editor
      .chain()
      .focus()
      .insertContent({
        type: "embed",
        attrs: {
          id: embedId,
          type: "code-code",
          status: "finished",
          // Use "preview:code:" prefix so GroupRenderer reads code from `item.code` attr
          contentRef: `preview:code:${embedId}`,
          code: fileContent,
          filename: file.name,
          language: language,
          lineCount: lineCount,
        },
      })
      .insertContent(" ")
      .run();

    setTimeout(() => editor.commands.focus("end"), 50);
    return;
  }

  // Authenticated path: create a proper TOON embed with PII detection and redaction.
  // This is the same path as pasted code — ensures consistent PII protection
  // regardless of whether code arrives via paste or file drop.
  const result = await createCodeEmbed(fileContent, language, file.name);

  if (result.piiRedactedCount > 0) {
    console.info(
      `[EmbedHandlers] Code file embed created with ${result.piiRedactedCount} PII item(s) redacted`,
      { filename: file.name, embed_id: result.embed_id },
    );
  }

  // Insert the embed reference block into the editor
  // The reference block (e.g. ```json\n{"type":"code","embed_id":"..."}\n```)
  // is what the message serializer uses to load the embed from EmbedStore
  editor
    .chain()
    .focus()
    .insertContent(result.embedReference)
    .insertContent(" ")
    .run();

  setTimeout(() => {
    editor.commands.focus("end");
  }, 50);
}

/**
 * Inserts an EPUB file embed into the editor.
 */
export async function insertEpub(editor: Editor, file: File): Promise<void> {
  ensureLeadingParagraph(editor);
  try {
    const coverUrl = await extractEpubCover(file);
    const epubMetadata = await getEpubMetadata(file);
    const { title, creator } = epubMetadata;

    const bookEmbed = {
      type: "embed",
      attrs: {
        id: generateUUID(),
        type: "book",
        status: "finished",
        contentRef: null,
        src: URL.createObjectURL(file),
        filename: file.name,
        bookname: title || undefined,
        author: creator || undefined,
        coverUrl: coverUrl || undefined,
      },
    };
    editor.commands.insertContent([bookEmbed, { type: "text", text: " " }]);
    setTimeout(() => {
      editor.commands.focus("end");
    }, 50);
  } catch (error) {
    console.error("Error inserting EPUB:", error);
    // Fallback to generic file embed if EPUB processing fails
    await insertFile(editor, file, "file");
  }
}

/**
 * Inserts a recording embed (audio) into the editor and triggers the upload +
 * Mistral Voxtral transcription pipeline in parallel.
 *
 * Flow:
 *  1. Create a local blob URL for immediate audio playback (no server round-trip).
 *  2. Generate a stable embed ID used to reference the node after insertion.
 *  3. Insert the embed node with status: 'uploading' immediately (non-blocking).
 *  4. In parallel:
 *     a. Upload audio blob to the upload server (AES-256-GCM + S3 pipeline).
 *     b. After upload completes, call the audio.transcribe skill with the
 *        S3 file reference. Update embed status to 'transcribing' in between.
 *  5. On success: update node with transcript text and status: 'finished'.
 *  6. On failure: update node with status: 'error' and error message.
 *
 * Demo mode (unauthenticated users):
 *  - Insert with status: 'finished' immediately — no server upload or transcription.
 *  - The blob URL allows local playback but the embed is visual-only.
 *
 * @param editor       TipTap editor instance.
 * @param blob         Raw audio Blob from MediaRecorder.
 * @param mimeType     MIME type reported by MediaRecorder (e.g. 'audio/webm').
 * @param duration     Pre-formatted duration string (e.g. "0:42").
 * @param isAuthenticated  Whether the user is logged in (controls upload behaviour).
 */
export async function insertRecording(
  editor: Editor,
  blob: Blob,
  mimeType: string,
  duration: string,
  isAuthenticated: boolean = true,
): Promise<void> {
  const timestamp = Date.now();
  // Derive a sensible filename from the MIME type (e.g. audio/webm → .webm)
  const ext = mimeType.split("/")[1]?.split(";")[0] || "webm";
  const filename = `recording_${timestamp}.${ext}`;

  // Create a local blob URL for instant audio playback while uploading
  const blobUrl = URL.createObjectURL(blob);

  // Create a File object so we can pass it to uploadFileToServer (which takes File)
  const file = new File([blob], filename, { type: mimeType });

  const embedId = generateUUID();

  if (!isAuthenticated) {
    // Demo mode: insert finished immediately — no server upload or transcription.
    console.debug(
      "[EmbedHandlers] Demo mode — inserting recording without server upload",
    );
    ensureLeadingParagraph(editor);
    editor.commands.insertContent([
      {
        type: "embed",
        attrs: {
          id: embedId,
          type: "recording",
          status: "finished",
          contentRef: null,
          blobUrl,
          filename,
          duration,
          mimeType,
          uploadEmbedId: null,
          transcript: null,
          s3Files: null,
          s3BaseUrl: null,
          aesKey: null,
          aesNonce: null,
          vaultWrappedAesKey: null,
          uploadError: null,
        },
      },
      { type: "text", text: " " },
    ]);
    setTimeout(() => editor.commands.focus("end"), 50);
    return;
  }

  // Insert the embed node immediately with status: 'uploading'.
  // The RecordingRenderer shows a compact player with the local blob URL so
  // the user can see (and even play) their recording while upload is in flight.
  ensureLeadingParagraph(editor);
  editor.commands.insertContent([
    {
      type: "embed",
      attrs: {
        id: embedId,
        type: "recording",
        status: "uploading",
        contentRef: null,
        blobUrl,
        filename,
        duration,
        mimeType,
        // Populated after server response:
        uploadEmbedId: null,
        transcript: null,
        s3Files: null,
        s3BaseUrl: null,
        aesKey: null,
        aesNonce: null,
        vaultWrappedAesKey: null,
        uploadError: null,
      },
    },
    { type: "text", text: " " },
  ]);
  setTimeout(() => editor.commands.focus("end"), 50);

  // Register an AbortController so the upload can be cancelled (Stop button / Backspace).
  const controller = new AbortController();
  _uploadControllers.set(embedId, controller);

  _performRecordingUpload(
    editor,
    embedId,
    file,
    mimeType,
    controller.signal,
  ).catch((err) => {
    console.error(
      "[EmbedHandlers] Unhandled error in _performRecordingUpload:",
      err,
    );
  });
}

/**
 * Retry transcription for a recording embed whose transcription previously failed.
 *
 * The audio file is already uploaded to S3 — only the transcription step is re-run.
 * All required S3 metadata (s3Files, s3BaseUrl, aesKey, aesNonce) must be present on
 * the embed node (they are set during the original upload step and survive the error).
 *
 * Called by RecordingRenderer.ts → onRetry prop on RecordingEmbedPreview.svelte.
 *
 * @param editor   The TipTap Editor instance (needed for ProseMirror transactions).
 * @param embedId  The unique ID of the recording embed node to retry.
 */
export async function retryTranscription(
  editor: Editor,
  embedId: string,
): Promise<void> {
  // Read the current embed node attrs from the ProseMirror document
  let attrs: Record<string, unknown> | null = null;
  editor.state.doc.descendants((node) => {
    if (node.type.name === "embed" && node.attrs.id === embedId) {
      attrs = { ...node.attrs };
      return false;
    }
    return true;
  });

  if (!attrs) {
    console.warn(
      "[EmbedHandlers] retryTranscription: embed node not found for id",
      embedId,
    );
    return;
  }

  // Require S3 data — if absent, the original upload failed and retry is not possible
  const s3Files = attrs.s3Files as
    | Record<string, { s3_key: string; size_bytes: number }>
    | null
    | undefined;
  const s3BaseUrl = attrs.s3BaseUrl as string | null | undefined;
  const aesKey = attrs.aesKey as string | null | undefined;
  const aesNonce = attrs.aesNonce as string | null | undefined;
  const vaultWrappedAesKey = attrs.vaultWrappedAesKey as
    | string
    | null
    | undefined;
  const filename = (attrs.filename as string | undefined) || "recording.webm";
  const mimeType = (attrs.mimeType as string | undefined) || "audio/webm";

  if (!s3Files || !s3BaseUrl || !aesKey || !aesNonce) {
    console.warn(
      "[EmbedHandlers] retryTranscription: missing S3 data — cannot retry without re-uploading",
      embedId,
    );
    return;
  }

  // Helper: update embed node attrs via ProseMirror transaction (same pattern as _performRecordingUpload)
  function updateEmbedNode(updates: Record<string, unknown>): void {
    const { state, dispatch } = editor.view;
    const tr = state.tr;
    let found = false;
    state.doc.descendants((node, pos) => {
      if (node.type.name === "embed" && node.attrs.id === embedId) {
        tr.setNodeMarkup(pos, undefined, { ...node.attrs, ...updates });
        found = true;
        return false;
      }
      return true;
    });
    if (found) dispatch(tr);
  }

  // Transition back to 'transcribing' so the UI shows the loading skeleton
  updateEmbedNode({ status: "transcribing", uploadError: null });

  // Re-run the transcription step only (same logic as _performRecordingUpload Step 3–4)
  const apiUrl = getApiUrl();
  const transcribeUrl = `${apiUrl}/v1/apps/audio/skills/transcribe`;

  const s3Key = s3Files.original?.s3_key ?? Object.values(s3Files)[0]?.s3_key;
  if (!s3Key) {
    console.error(
      "[EmbedHandlers] retryTranscription: no s3_key found in s3Files",
      s3Files,
    );
    updateEmbedNode({
      status: "error",
      uploadError: "Retry failed: file reference missing",
    });
    return;
  }

  const transcribeBody = {
    requests: [
      {
        request_id: embedId,
        embed_id: attrs.uploadEmbedId,
        s3_key: s3Key,
        s3_base_url: s3BaseUrl,
        aes_key: aesKey,
        aes_nonce: aesNonce,
        vault_wrapped_aes_key: vaultWrappedAesKey,
        filename,
        mime_type: mimeType,
      },
    ],
  };

  let transcribeResponse: Response;
  try {
    transcribeResponse = await fetch(transcribeUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(transcribeBody),
    });
  } catch (fetchError) {
    console.error(
      "[EmbedHandlers] retryTranscription network error:",
      fetchError,
    );
    updateEmbedNode({
      status: "error",
      uploadError: "Retry failed: network error",
    });
    return;
  }

  if (!transcribeResponse.ok) {
    let detail = `Transcription failed (${transcribeResponse.status})`;
    try {
      const errBody = await transcribeResponse.json();
      detail = errBody.detail || detail;
    } catch {
      // Response not JSON — ignore
    }
    console.error("[EmbedHandlers] retryTranscription API error:", detail);

    if (transcribeResponse.status === 402) {
      updateEmbedNode({
        status: "error",
        uploadError: "Not enough credits to transcribe",
      });
      notificationStore.addNotificationWithOptions("error", {
        message: "Not enough credits to transcribe your voice recording.",
        actionLabel: "Buy Credits",
        onAction: () => {
          settingsDeepLink.set("billing/buy-credits");
          panelState.openSettings();
        },
        duration: 0,
        dismissible: true,
      });
    } else {
      updateEmbedNode({ status: "error", uploadError: detail });
    }
    return;
  }

  // Parse transcript and update embed to 'finished'
  // Response shape from BaseSkill._build_response_with_errors:
  // { results: [{ id: request_id, results: [{ transcript, s3_key, ... }] }] }
  let transcriptText: string | undefined;
  try {
    const responseData = await transcribeResponse.json();
    const group = responseData?.results?.find(
      (r: { id: string }) => r.id === embedId,
    );
    transcriptText = group?.results?.[0]?.transcript ?? undefined;
  } catch (parseError) {
    console.error(
      "[EmbedHandlers] retryTranscription: failed to parse response:",
      parseError,
    );
  }

  updateEmbedNode({
    status: "finished",
    transcript: transcriptText ?? null,
    uploadError: null,
  });

  console.debug(
    `[EmbedHandlers] retryTranscription complete for embed ${embedId}.`,
    { hasTranscript: !!transcriptText },
  );
}

/**
 * Performs the full audio upload + transcription pipeline for a recording embed.
 *
 * Steps:
 *  1. Upload audio to the upload server → get S3 keys + AES key.
 *  2. Update embed node to status: 'transcribing' with S3 data.
 *  3. Call POST /v1/apps/audio/skills/transcribe with the S3 file reference.
 *  4. Update embed node with transcript text and status: 'finished'.
 *
 * Errors at any step set status: 'error' on the embed node.
 */
async function _performRecordingUpload(
  editor: Editor,
  localEmbedId: string,
  file: File,
  mimeType: string,
  signal?: AbortSignal,
): Promise<void> {
  // Helper: update embed node attrs via a ProseMirror transaction.
  function updateEmbedNode(updates: Record<string, unknown>): void {
    const { state, dispatch } = editor.view;
    const tr = state.tr;
    let found = false;
    state.doc.descendants((node, pos) => {
      if (node.type.name === "embed" && node.attrs.id === localEmbedId) {
        tr.setNodeMarkup(pos, undefined, { ...node.attrs, ...updates });
        found = true;
        return false;
      }
      return true;
    });
    if (found) dispatch(tr);
  }

  try {
    // -----------------------------------------------------------------------
    // Step 1: Upload audio blob to the upload server
    // -----------------------------------------------------------------------
    const uploadResult = await uploadFileToServer(file, signal);

    // NOTE: Do NOT remove the AbortController here yet — we keep it registered
    // so that cancelUpload() can also abort the transcription fetch in Step 3.
    // The controller is removed after the full pipeline (upload + transcription)
    // completes or fails.

    // -----------------------------------------------------------------------
    // Step 2: Update embed with S3 data, transition to 'transcribing'
    // -----------------------------------------------------------------------
    updateEmbedNode({
      status: "transcribing",
      uploadEmbedId: uploadResult.embed_id,
      s3Files: uploadResult.files,
      s3BaseUrl: uploadResult.s3_base_url,
      aesKey: uploadResult.aes_key,
      aesNonce: uploadResult.aes_nonce,
      vaultWrappedAesKey: uploadResult.vault_wrapped_aes_key,
      uploadError: null,
    });

    // -----------------------------------------------------------------------
    // Step 3: Call the audio.transcribe skill via the backend API
    //
    // POST /v1/apps/audio/skills/transcribe
    // Body: { requests: [{ request_id, embed_id, s3_key, s3_base_url, aes_key, aes_nonce, vault_wrapped_aes_key, filename, mime_type }] }
    // -----------------------------------------------------------------------
    const apiUrl = getApiUrl();
    const transcribeUrl = `${apiUrl}/v1/apps/audio/skills/transcribe`;

    // Use the 'original' variant key if present, otherwise the first available key
    const s3Key =
      uploadResult.files?.original?.s3_key ??
      Object.values(uploadResult.files ?? {})[0]?.s3_key;

    if (!s3Key) {
      console.error(
        "[EmbedHandlers] No S3 key found after audio upload:",
        uploadResult.files,
      );
      updateEmbedNode({
        status: "error",
        uploadError: "Upload succeeded but no file key returned",
      });
      return;
    }

    const transcribeBody = {
      requests: [
        {
          request_id: localEmbedId,
          embed_id: uploadResult.embed_id,
          s3_key: s3Key,
          s3_base_url: uploadResult.s3_base_url,
          aes_key: uploadResult.aes_key,
          aes_nonce: uploadResult.aes_nonce,
          vault_wrapped_aes_key: uploadResult.vault_wrapped_aes_key,
          filename: file.name,
          mime_type: mimeType,
        },
      ],
    };

    let transcribeResponse: Response;
    try {
      transcribeResponse = await fetch(transcribeUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(transcribeBody),
        signal,
      });
    } catch (fetchError) {
      if (fetchError instanceof Error && fetchError.name === "AbortError")
        throw fetchError;
      // Non-abort network error — clean up controller and return
      _uploadControllers.delete(localEmbedId);
      console.error("[EmbedHandlers] Transcription network error:", fetchError);
      updateEmbedNode({
        status: "finished", // Upload succeeded; transcription failed non-fatally
        uploadError: "Transcription failed: network error",
      });
      return;
    }

    if (!transcribeResponse.ok) {
      // API error — clean up controller and return
      _uploadControllers.delete(localEmbedId);
      let detail = `Transcription failed (${transcribeResponse.status})`;
      try {
        const errBody = await transcribeResponse.json();
        detail = errBody.detail || detail;
      } catch {
        // Response body not JSON — ignore
      }
      console.error("[EmbedHandlers] Transcription API error:", detail);

      if (transcribeResponse.status === 402) {
        // Not enough credits — set error state so the retry button appears.
        // The audio file is already on S3; user can retry once they have credits.
        updateEmbedNode({
          status: "error",
          uploadError: "Not enough credits to transcribe",
        });
        // Show a persistent notification with a direct "Buy Credits" action.
        notificationStore.addNotificationWithOptions("error", {
          message: "Not enough credits to transcribe your voice recording.",
          actionLabel: "Buy Credits",
          onAction: () => {
            settingsDeepLink.set("billing/buy-credits");
            panelState.openSettings();
          },
          duration: 0, // Persistent — user must dismiss explicitly
          dismissible: true,
        });
      } else {
        // Other server-side failures — set error state (upload succeeded, transcript missing).
        // The retry button will appear so the user can try again.
        updateEmbedNode({ status: "error", uploadError: detail });
      }
      return;
    }

    // -----------------------------------------------------------------------
    // Step 4: Parse transcript and update embed to 'finished'
    // -----------------------------------------------------------------------
    let transcriptText: string | undefined;
    try {
      const responseData = await transcribeResponse.json();
      // Response shape from BaseSkill._build_response_with_errors:
      // { results: [{ id: request_id, results: [{ transcript, s3_key, ... }] }] }
      const group = responseData?.results?.find(
        (r: { id: string }) => r.id === localEmbedId,
      );
      transcriptText = group?.results?.[0]?.transcript ?? undefined;
    } catch (parseError) {
      console.error(
        "[EmbedHandlers] Failed to parse transcription response:",
        parseError,
      );
    }

    // Remove the AbortController — the full pipeline (upload + transcription) is done.
    // Must happen AFTER the transcription fetch so cancelUpload() can still abort it.
    _uploadControllers.delete(localEmbedId);

    updateEmbedNode({
      status: "finished",
      transcript: transcriptText ?? null,
      uploadError: null,
    });

    console.debug(
      `[EmbedHandlers] Recording ${localEmbedId} upload + transcription complete.`,
      { hasTranscript: !!transcriptText },
    );
  } catch (err) {
    // Remove the AbortController regardless of error type
    _uploadControllers.delete(localEmbedId);

    // AbortError: upload was cancelled by the user (Stop button / Backspace)
    if (
      err instanceof Error &&
      (err.name === "AbortError" || err.message === "Upload cancelled")
    ) {
      console.debug(
        "[EmbedHandlers] Recording upload cancelled for embed:",
        localEmbedId,
      );
      return;
    }

    console.error(
      "[EmbedHandlers] Recording upload/transcription failed:",
      err,
    );
    updateEmbedNode({
      status: "error",
      uploadError: err instanceof Error ? err.message : "Upload failed",
    });
  }
}

/**
 * Inserts a map location embed into the editor.
 *
 * Flow:
 * 1. Generate a UUID used as both the embed node ID and the EmbedStore key.
 * 2. Store the location TOON content in EmbedStore so it survives serialization
 *    and is sent to the server as part of the encrypted embed pipeline.
 * 3. Insert the embed node with contentRef: "embed:{uuid}" so serializers.ts
 *    can emit the proper `{"type":"location","embed_id":"..."}` JSON block.
 *
 * TOON content shape:
 *   type            "location"
 *   lat / lon       LLM-facing coordinates (randomised in area mode)
 *   preciseLat/Lon  Exact pin coordinates for the in-editor Leaflet preview
 *   address         Human-readable street address (from reverse geocode)
 *   name            Short display name (selected location or area text)
 *   locationType    "precise_location" | "area"
 */
export async function insertMap(
  editor: Editor,
  previewData: { type: string; attrs: Record<string, unknown> },
): Promise<void> {
  const embedId = generateUUID();
  const contentRef = `embed:${embedId}`;

  const { attrs } = previewData;

  // Build TOON content for EmbedStore — contains both LLM coords and precise coords
  const toonContent = {
    type: "location",
    lat: attrs.lat,
    lon: attrs.lon,
    precise_lat: attrs.preciseLat,
    precise_lon: attrs.preciseLon,
    zoom: attrs.zoom ?? 16,
    name: attrs.name ?? "",
    address: attrs.address ?? "",
    location_type: attrs.locationType ?? "area",
    // Category label for search results (e.g. "Railway", "Airport").
    // Empty string for manual/current-location pins.
    place_type: attrs.placeType ?? "",
  };

  // TOON-encode the location content for efficient, consistent storage.
  // This must be a string so that embedStore.put() stores it in `data.content`
  // (the format expected by downstream code: chatSyncServiceSenders.ts
  // validates loadedEmbeds via e.embed_id, and embedStore.get() returns
  // parsed.content as a TOON string to embedResolver).
  let toonContentString: string;
  try {
    toonContentString = toonEncode(toonContent);
  } catch (encodeErr) {
    console.warn(
      "[EmbedHandlers] TOON encoding failed for map embed, falling back to JSON:",
      encodeErr,
    );
    toonContentString = JSON.stringify(toonContent);
  }

  // Build the full embed data object matching the format used by all other
  // client-side embeds (code, url, video). This ensures:
  //   - embed_id is present so chatSyncServiceSenders can validate the embed
  //   - content is a string so embedStore.get() returns it correctly
  //   - type / status match what the send pipeline and renderers expect
  const now = Date.now();
  const embedData = {
    embed_id: embedId,
    type: "maps" as const,
    status: "finished",
    content: toonContentString,
    text_preview: (attrs.name as string) || (attrs.address as string) || "",
    createdAt: now,
    updatedAt: now,
  };

  // Store in EmbedStore so it flows through the encrypted pipeline on send
  try {
    await embedStore.put(contentRef, embedData, "maps");
    console.debug(
      "[EmbedHandlers] Stored map location embed in EmbedStore:",
      embedId,
    );
  } catch (err) {
    console.error(
      "[EmbedHandlers] Failed to store map location in EmbedStore:",
      err,
    );
    // Do not abort: insert the node anyway so the user still sees the embed.
    // The embed will be incomplete on send (no contentRef data), but that is
    // better than silently swallowing the action.
  }

  const unifiedMapEmbed = {
    type: "embed",
    attrs: {
      id: embedId,
      type: "maps",
      status: "finished",
      contentRef,
      // Store precise coords as data-* attrs for the in-editor Leaflet preview
      preciseLat: attrs.preciseLat,
      preciseLon: attrs.preciseLon,
      zoom: attrs.zoom ?? 16,
      name: attrs.name ?? "",
      // Human-readable street address from Nominatim reverse geocode or search result.
      // Stored as a data-* attr (registered in Embed.ts) so it survives DOM round-trips.
      address: attrs.address ?? "",
      // "precise_location" | "area" — controls the "Nearby:" label in the embed card.
      locationType: attrs.locationType ?? "area",
      // Category/type label for search results (e.g. "Railway", "Airport").
      // Stored as a data-* attr so it survives TipTap DOM round-trips.
      placeType: attrs.placeType ?? "",
    },
  };

  ensureLeadingParagraph(editor);
  editor.commands.insertContent([unifiedMapEmbed, { type: "text", text: " " }]);
  setTimeout(() => {
    editor.commands.focus("end");
  }, 50);
}
