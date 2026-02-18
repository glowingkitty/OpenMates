import type { Editor } from "@tiptap/core";
import { getLanguageFromFilename } from "./utils"; // Assuming utils are accessible
import { extractEpubCover, getEpubMetadata } from "./utils";
import { resizeImage } from "./utils";
import { generateUUID } from "../../message_parsing/utils";
import { uploadFileToServer } from "./services/uploadService";

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
 * Inserts a generic file or PDF embed into the editor.
 */
export async function insertFile(
  editor: Editor,
  file: File,
  type: "pdf" | "file",
): Promise<void> {
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
 */
export async function insertCodeFile(
  editor: Editor,
  file: File,
): Promise<void> {
  const url = URL.createObjectURL(file);
  const language = getLanguageFromFilename(file.name);

  editor
    .chain()
    .focus()
    .insertContent({
      type: "embed",
      attrs: {
        id: generateUUID(),
        type: "code",
        status: "finished",
        contentRef: null,
        src: url,
        filename: file.name,
        language: language,
      },
    })
    .insertContent(" ") // Add space after
    .run();
  setTimeout(() => {
    editor.commands.focus("end");
  }, 50);
}

/**
 * Inserts an EPUB file embed into the editor.
 */
export async function insertEpub(editor: Editor, file: File): Promise<void> {
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
 * Inserts a recording embed (audio) into the editor.
 */
export function insertRecording(
  editor: Editor,
  url: string,
  filename: string,
  duration: string,
): void {
  editor
    .chain()
    .focus()
    .insertContent([
      {
        type: "embed",
        attrs: {
          id: generateUUID(),
          type: "recording",
          status: "finished",
          contentRef: null,
          src: url,
          filename: filename,
          duration: duration, // Already formatted
        },
      },
      { type: "text", text: " " },
    ])
    .run();
  setTimeout(() => {
    editor.commands.focus("end");
  }, 50);
}

/**
 * Inserts a map embed into the editor.
 */
export function insertMap(
  editor: Editor,
  previewData: { type: string; attrs: Record<string, unknown> },
): void {
  // Convert legacy map data to unified embed format
  const unifiedMapEmbed = {
    type: "embed",
    attrs: {
      id: generateUUID(),
      type: "maps",
      status: "finished",
      contentRef: null,
      ...previewData.attrs, // Spread the existing attributes
    },
  };

  editor.commands.insertContent([unifiedMapEmbed, { type: "text", text: " " }]);
  setTimeout(() => {
    editor.commands.focus("end");
  }, 50);
}
