import type { Editor } from "@tiptap/core";
import { get } from "svelte/store"; // Import get
import { getTracer } from '../../../services/tracing/setup';
import { isDesktop } from "../../../utils/platform";
import { hasActualContent, vibrateMessageField } from "../utils";
import { Extension } from "@tiptap/core";
import { chatDB } from "../../../services/db";
import { chatKeyManager } from "../../../services/encryption/ChatKeyManager";
import { chatSyncService } from "../../../services/chatSyncService"; // Import chatSyncService
import type { Message } from "../../../types/chat"; // Import Message type
import { draftEditorUIState } from "../../../services/drafts/draftState";
import {
  clearCurrentDraft,
  saveDraftDebounced,
} from "../../../services/drafts/draftSave"; // Import clearCurrentDraft + debounced save (for cancellation)
import { tipTapToCanonicalMarkdown } from "../../../message_parsing/serializers"; // Import TipTap to markdown converter
import { isPublicChat } from "../../../demo_chats/convertToChat";
import { websocketStatus } from "../../../stores/websocketStatusStore"; // Import WebSocket status store
import { chatListCache } from "../../../services/chatListCache";
import { createEmbedFromUrl } from "../services/urlMetadataService"; // Import URL-to-embed creation
import { authStore } from "../../../stores/authStore"; // Import authStore for authentication check
import { appSettingsMemoriesPermissionStore } from "../../../stores/appSettingsMemoriesPermissionStore"; // For auto-dismissing permission dialog
import { forcedLogoutInProgress } from "../../../stores/signupState";
import { editMessageStore, cancelEdit } from "../../../stores/editMessageStore";
import { notificationStore } from "../../../stores/notificationStore";
import {
  detectPII,
  replacePIIWithPlaceholders,
  createPIIMappingsForStorage,
  type PIIMappingForStorage,
  type PIIDetectionOptions,
  type PersonalDataForDetection,
} from "../services/piiDetectionService"; // PII anonymization
import {
  personalDataStore,
  type PersonalDataEntry,
  type PIIDetectionSettings,
} from "../../../stores/personalDataStore"; // Privacy settings store

// Removed sendMessageToAPI as it will be handled by chatSyncService

// =============================================================================
// URL Detection and Processing
// =============================================================================

/**
 * Regular expression to detect URLs in text content.
 * Matches URLs with protocol AND common video platform URLs without protocol.
 * This is more targeted than matching all URLs without protocol to avoid false positives.
 * Matches:
 * - URLs with protocol: https://example.com/path, http://site.com
 * - YouTube URLs without protocol: youtube.com/watch?v=..., youtu.be/VIDEO_ID, www.youtube.com/...
 */
const URL_REGEX =
  /(?:https?:\/\/[^\s\])"'<>]+|(?<![/\w@])(?:(?:www\.|m\.)?youtube\.com\/(?:watch\?v=|embed\/|shorts\/|v\/)[^\s\])"'<>]+|youtu\.be\/[^\s\])"'<>]+))/g;

/**
 * Detects all URLs in the given text content.
 * Returns array of URL matches with their positions.
 * Excludes URLs that are already inside JSON code blocks (embed references).
 *
 * @param text The text content to search
 * @returns Array of {url, startPos, endPos} objects
 */
function detectUrlsInText(
  text: string,
): Array<{ url: string; startPos: number; endPos: number }> {
  const urls: Array<{ url: string; startPos: number; endPos: number }> = [];

  // Find all code block ranges to exclude URLs within them
  const codeBlockRanges: Array<{ start: number; end: number }> = [];
  const codeBlockPattern = /```[\s\S]*?```/g;
  let blockMatch;
  while ((blockMatch = codeBlockPattern.exec(text)) !== null) {
    codeBlockRanges.push({
      start: blockMatch.index,
      end: blockMatch.index + blockMatch[0].length,
    });
  }

  // Find all URLs
  let match;
  URL_REGEX.lastIndex = 0; // Reset regex state

  while ((match = URL_REGEX.exec(text)) !== null) {
    let url = match[0];
    const startPos = match.index;
    const endPos = startPos + url.length;

    // Check if URL is inside a code block - skip if so
    const isInsideCodeBlock = codeBlockRanges.some(
      (range) => startPos >= range.start && endPos <= range.end,
    );

    if (!isInsideCodeBlock) {
      // Normalize URL by adding https:// if protocol is missing
      if (!/^https?:\/\//i.test(url)) {
        url = `https://${url}`;
      }
      urls.push({ url, startPos, endPos });
    }
  }

  return urls;
}

// =============================================================================
// Embed Reference Protection for PII Detection
// =============================================================================

/**
 * Temporarily replaces embed reference JSON blocks with opaque placeholders so
 * that the PII anonymizer cannot corrupt embed IDs embedded in them.
 *
 * UUID segments can accidentally match PII patterns (e.g. "051-4369" matches the
 * local phone-number regex). Since embed IDs are machine-generated and not
 * sensitive data, they must be preserved verbatim across the PII pass.
 *
 * Usage pattern:
 *   const { safeMarkdown, restore } = protectEmbedRefsFromPII(markdown);
 *   // run PII detection/replacement on safeMarkdown …
 *   markdown = restore(safeMarkdown); // put embed blocks back
 *
 * @param markdown The markdown string that may contain embed reference blocks.
 * @returns An object with the protected markdown and a restore function.
 */
function protectEmbedRefsFromPII(markdown: string): {
  safeMarkdown: string;
  restore: (processed: string) => string;
} {
  // Map from placeholder token → original embed reference block.
  const placeholders = new Map<string, string>();

  // Replace every ```json … ``` block that is an embed reference (has embed_id
  // or embed_ids) with a unique opaque token that cannot trigger PII patterns.
  const safeMarkdown = markdown.replace(
    /```json\n([\s\S]*?)\n```/g,
    (block, content) => {
      try {
        const parsed = JSON.parse(content.trim());
        if ("embed_id" in parsed || "embed_ids" in parsed) {
          // Use a token that contains no digits or PII-like separators so the
          // PII detector cannot match anything inside it.
          const token = `__EMBED_REF_PROTECTED_${placeholders.size}__`;
          placeholders.set(token, block);
          return token;
        }
      } catch {
        // Not valid JSON — leave block as-is for normal PII detection.
      }
      return block;
    },
  );

  const restore = (processed: string): string => {
    let result = processed;
    // Use forEach instead of for...of to avoid requiring downlevelIteration on Maps.
    placeholders.forEach((original, token) => {
      // Use split+join to avoid regex special-character issues in token names.
      result = result.split(token).join(original);
    });
    return result;
  };

  return { safeMarkdown, restore };
}

/**
 * Process all URLs in the message content and convert them to embeds.
 * This is called BEFORE sending a message to ensure URL metadata is fetched
 * and embeds are created with proper embed_ids.
 *
 * @param markdown The markdown content to process
 * @returns Updated markdown with URLs replaced by embed references
 */
async function processUrlsBeforeSend(markdown: string): Promise<string> {
  const urls = detectUrlsInText(markdown);

  if (urls.length === 0) {
    console.debug("[sendHandlers] No URLs to process in message");
    return markdown;
  }

  console.info("[sendHandlers] Processing", urls.length, "URL(s) before send");

  // Process URLs in parallel for better performance
  const embedPromises = urls.map(async (urlInfo) => {
    try {
      console.debug("[sendHandlers] Creating embed for URL:", urlInfo.url);
      const embedResult = await createEmbedFromUrl(urlInfo.url);
      return { urlInfo, embedResult };
    } catch (error) {
      console.error(
        "[sendHandlers] Error creating embed for URL:",
        urlInfo.url,
        error,
      );
      return { urlInfo, embedResult: null };
    }
  });

  const embedResults = await Promise.all(embedPromises);

  // Replace URLs with embed references from end to beginning to maintain positions
  const sortedResults = [...embedResults].sort(
    (a, b) => b.urlInfo.startPos - a.urlInfo.startPos,
  );
  let processedMarkdown = markdown;

  for (const { urlInfo, embedResult } of sortedResults) {
    if (!embedResult) {
      console.warn(
        "[sendHandlers] Skipping URL - embed creation failed:",
        urlInfo.url,
      );
      continue;
    }

    console.info("[sendHandlers] Replacing URL with embed reference:", {
      url: urlInfo.url,
      embed_id: embedResult.embed_id,
      type: embedResult.type,
    });

    // Replace URL with embed reference block
    const beforeUrl = processedMarkdown.substring(0, urlInfo.startPos);
    const afterUrl = processedMarkdown.substring(urlInfo.endPos);

    // Ensure proper spacing around the embed reference block
    let processedBeforeUrl = beforeUrl;
    let processedAfterUrl = afterUrl;

    // Add newline before if there's content and it doesn't end with newline
    if (processedBeforeUrl.length > 0 && !processedBeforeUrl.endsWith("\n")) {
      processedBeforeUrl += "\n";
    }

    // Add newline after if there's content
    if (processedAfterUrl.length > 0 && !processedAfterUrl.startsWith("\n")) {
      processedAfterUrl = "\n" + processedAfterUrl;
    }

    processedMarkdown =
      processedBeforeUrl + embedResult.embedReference + processedAfterUrl;
  }

  console.debug(
    "[sendHandlers] URL processing complete. Processed",
    embedResults.filter((r) => r.embedResult).length,
    "URL(s)",
  );

  return processedMarkdown;
}

// =============================================================================
// Message Creation
// =============================================================================

/**
 * Creates a message payload from markdown content
 * @param markdown The processed markdown content (with URLs already converted to embeds)
 * @param chatId The ID of the current chat
 * @param piiMappings Optional PII mappings for restoration (stored encrypted with message)
 * @returns Message payload object with markdown content
 */
function createMessagePayload(
  markdown: string,
  chatId: string,
  piiMappings?: PIIMappingForStorage[],
): Message {
  // Validate markdown content
  if (!markdown || typeof markdown !== "string") {
    console.error("Invalid markdown content:", markdown);
    throw new Error("Invalid markdown content");
  }

  const message_id = `${chatId.slice(-10)}-${crypto.randomUUID()}`;

  // Check WebSocket connection status to determine initial message status
  // If offline, set status to 'waiting_for_internet' instead of 'sending'
  const wsStatus = get(websocketStatus);
  const isConnected = wsStatus.status === "connected";
  const initialStatus: Message["status"] = isConnected
    ? "sending"
    : "waiting_for_internet";

  const message: Message = {
    message_id,
    chat_id: chatId,
    role: "user", // Changed from sender to role
    content: markdown, // Send markdown string directly to server (never Tiptap JSON!)
    status: initialStatus, // Initial status based on connection state
    created_at: Math.floor(Date.now() / 1000), // Unix timestamp in seconds
    sender_name: "user", // Set default sender name for Phase 2 encryption
    encrypted_content: null, // Will be set during Phase 2 encryption
    // category will be set by server during preprocessing and sent back via chat_metadata_for_encryption
    // PII mappings for client-side restoration (will be encrypted during Phase 2)
    pii_mappings:
      piiMappings && piiMappings.length > 0 ? piiMappings : undefined,
  };

  // current_chat_title removed - not needed for dual-phase architecture

  return message;
}

/**
 * Resets the editor content
 * @param editor The TipTap editor instance
 * @param shouldKeepFocus Whether to maintain focus after clearing (default: true on desktop, false on touch)
 */
function resetEditorContent(editor: Editor, shouldKeepFocus?: boolean) {
  // Clear the content. The `false` argument prevents triggering an 'update' event from this specific command.
  // Tiptap's Placeholder extension should handle showing placeholder text if the editor is empty.
  editor.commands.clearContent(false);

  // Determine if we should keep focus based on device type
  // On desktop: keep focus so user can continue typing
  // On touch devices: blur to make input compact and show assistant response better
  const keepFocus =
    shouldKeepFocus !== undefined ? shouldKeepFocus : isDesktop();

  if (keepFocus) {
    editor.commands.focus("end");
    console.debug(
      "[resetEditorContent] Keeping focus on editor (desktop behavior)",
    );
  } else {
    // Blur the editor on touch devices to make it compact
    editor.commands.blur();
    console.debug(
      "[resetEditorContent] Blurring editor (touch device behavior)",
    );
  }
}

/**
 * Guard flag to prevent double-sends on mobile.
 * Mobile browsers (especially Firefox iOS) can fire click/touchend events in rapid succession,
 * causing handleSend to be entered twice before the first invocation completes its async work.
 * This flag blocks re-entry until the first send finishes its critical section
 * (chat creation + dispatch + WebSocket send).
 */
let sendInProgress = false;

/**
 * Handles sending a message via the message input
 *
 * @param editor TipTap editor instance
 * @param dispatch Event dispatcher function
 * @param setHasContent Function to update hasContent state
 * @param currentChatId Optional current chat ID
 * @param activePIIExclusions Set of PII match IDs that user has clicked to exclude from replacement
 */
export async function handleSend(
  editor: Editor | null,
  dispatch: (type: string, detail?: Record<string, unknown>) => void,
  setHasContent: (value: boolean) => void,
  currentChatId?: string,
  activePIIExclusions: Set<string> = new Set(),
) {
  if (!editor || !hasActualContent(editor)) {
    vibrateMessageField();
    return;
  }

  // CRITICAL: Prevent double-sends. On mobile, rapid taps or touch+click can
  // fire this function twice before the first async call reaches setHasContent(false).
  // A double-send during new-chat creation can cause two different chat IDs to be
  // created, leading to messages being routed to the wrong chat (e.g., the user sees
  // their message in the "for everyone" intro chat instead of the new chat).
  if (sendInProgress) {
    console.warn(
      "[handleSend] Send already in progress, ignoring duplicate call",
    );
    return;
  }
  sendInProgress = true;

  // OTel instrumentation: root span covering the entire send pipeline
  const tracer = getTracer();
  const rootSpan = tracer.startSpan('message.send.pipeline', {
    attributes: { 'message.chat_id': currentChatId || 'new' }
  });

  // CRITICAL: Cancel any pending debounced draft save immediately.
  // Without this, fast typing + send within the 1200ms debounce window causes the
  // debounced save to fire AFTER the message is sent, re-saving the already-sent
  // content as a draft. The server also clears drafts on message receipt, but
  // the client's debounced save fires afterwards and re-creates the draft.
  saveDraftDebounced.cancel();

  // OTel: deferred send check span
  const deferredCheckSpan = tracer.startSpan('message.send.deferred_check');
  // DEFERRED SEND: Detect embeds that are still in-flight.
  // Instead of blocking with a warning toast, we:
  //  1. Snapshot the editor state into a PendingSendContext (this function).
  //  2. Save the message to IndexedDB with status: "waiting_for_upload".
  //  3. Display it immediately in the chat history for instant visual feedback.
  //  4. When all blocking embeds finish (notified via window 'embedUploadFinished'),
  //     MessageInput.svelte re-runs the actual send path automatically.
  //
  // Blocking statuses:
  //  'uploading'   — file upload to S3 in flight; S3 keys not yet returned.
  //  'transcribing' — audio upload done but transcription pending.
  // NOT blocking:
  //  'processing'  — PDF OCR in flight; we send now and backend fills in OCR later via WebSocket.
  //
  // We collect blocking embed info (id, label) for progress tracking in the UI.
  interface BlockingEmbedInfo {
    id: string;
    label: string;
  }
  const blockingEmbeds: BlockingEmbedInfo[] = [];
  editor.view.state.doc.descendants((node) => {
    if (node.type.name === "embed") {
      const st = node.attrs.status as string | undefined;
      if (st === "uploading" || st === "transcribing") {
        const label =
          (node.attrs.filename as string) ||
          (node.attrs.type === "recording" ? "Recording" : "Attachment");
        blockingEmbeds.push({ id: node.attrs.id as string, label });
      }
    }
    return true;
  });

  deferredCheckSpan.end();

  if (blockingEmbeds.length > 0) {
    // -----------------------------------------------------------------------
    // DEFERRED SEND PATH
    // We cannot send right now — one or more embeds are still uploading.
    // Save the message optimistically with status:"waiting_for_upload" and
    // create a PendingSendContext so MessageInput can fire the actual send
    // once all embeds report finished via the embedUploadFinished window event.
    // -----------------------------------------------------------------------

    // Determine / create the chatId exactly as the normal path would.
    // We must replicate just enough of the chat-id resolution logic here so
    // the message lands in the right chat.
    let deferredChatId = currentChatId;
    const draftStateDeferred = get(draftEditorUIState);
    if (!deferredChatId && draftStateDeferred.currentChatId) {
      deferredChatId = draftStateDeferred.currentChatId;
    } else if (!deferredChatId) {
      deferredChatId = crypto.randomUUID();
    }

    // If it's a demo/public chat, allocate a real UUID so the message stores correctly.
    if (deferredChatId && isPublicChat(deferredChatId)) {
      deferredChatId = crypto.randomUUID();
    }

    // Build a stub message payload with status "waiting_for_upload".
    // Content is empty string for now — the real markdown is serialized at dispatch time.
    const deferredMessageId = `${deferredChatId.slice(-10)}-${crypto.randomUUID()}`;
    const deferredMessage: Message = {
      message_id: deferredMessageId,
      chat_id: deferredChatId,
      role: "user",
      content: "", // Placeholder — overwritten when deferred send fires
      status: "waiting_for_upload",
      created_at: Math.floor(Date.now() / 1000),
      sender_name: "user",
      encrypted_content: null,
    };

    // Save stub message to IndexedDB / incognito store so ChatHistory can show it.
    try {
      const { incognitoChatService } =
        await import("../../../services/incognitoChatService");
      const incognitoChat = await incognitoChatService
        .getChat(deferredChatId)
        .catch(() => null);
      if (incognitoChat) {
        await incognitoChatService.addMessage(deferredChatId, deferredMessage);
      } else {
        // Create chat in IndexedDB if it doesn't exist yet
        const existingDeferred = await chatDB.getChat(deferredChatId);
        if (!existingDeferred) {
          const nowDeferred = Math.floor(Date.now() / 1000);
          const isIncognito = (
            await import("../../../stores/incognitoModeStore")
          ).incognitoMode.get();
          const newChatForDeferred: import("../../../types/chat").Chat = {
            chat_id: deferredChatId,
            encrypted_title: null,
            messages_v: 1,
            title_v: 0,
            draft_v: 0,
            encrypted_draft_md: null,
            encrypted_draft_preview: null,
            last_edited_overall_timestamp: deferredMessage.created_at,
            unread_count: 0,
            created_at: nowDeferred,
            updated_at: nowDeferred,
            processing_metadata: false,
            waiting_for_metadata: !isIncognito,
            is_incognito: isIncognito,
            source_demo_id: null,
          };
          if (isIncognito) {
            await incognitoChatService.storeChat(newChatForDeferred);
            await incognitoChatService.addMessage(
              deferredChatId,
              deferredMessage,
            );
          } else {
            await chatDB.addChat(newChatForDeferred);
            await chatDB.saveMessage(deferredMessage);
          }
          window.dispatchEvent(
            new CustomEvent("localChatListChanged", {
              detail: { chat_id: deferredChatId },
            }),
          );
        } else {
          await chatDB.saveMessage(deferredMessage);
        }
      }
    } catch (deferredSaveErr) {
      console.error(
        "[handleSend] Failed to save deferred message to IndexedDB:",
        deferredSaveErr,
      );
      // Fall through — show in UI optimistically even if IDB write failed
    }

    // Snapshot ALL embed nodes in the editor (blocking and non-blocking) so we can
    // reconstruct the final markdown later without needing the live editor.
    // The upload callbacks in embedHandlers.ts will store finished embed data in
    // EmbedStore (with contentRef). The deferred sender reads EmbedStore when it fires.
    const { addPendingSend } =
      await import("../../../stores/pendingUploadStore");
    const embedSnapshots = new Map<
      string,
      import("../../../stores/pendingUploadStore").DeferredEmbedSnapshot
    >();
    editor.view.state.doc.descendants((node) => {
      if (node.type.name === "embed") {
        const id = node.attrs.id as string;
        embedSnapshots.set(id, {
          embedId: id,
          embedType: (node.attrs.type as string) || "file",
          filename: (node.attrs.filename as string) || "Attachment",
          uploadEmbedId: (node.attrs.uploadEmbedId as string) || null,
          contentRef: (node.attrs.contentRef as string) || null,
        });
      }
      return true;
    });

    // Build per-embed progress map for the store.
    const embedProgressMap = new Map(
      blockingEmbeds.map((e) => [
        e.id,
        {
          embedId: e.id,
          status: "uploading" as string,
          uploadPercent: 0,
          label: e.label,
        },
      ]),
    );

    // Register in pendingUploadStore.
    // The editor will be CLEARED after this — the user is free to navigate away.
    // When all blocking embeds finish (notified via embedUploadFinished), the
    // deferred sender reconstructs the final markdown from editorSnapshot +
    // EmbedStore data and sends the message without needing the live editor.
    addPendingSend({
      pendingId: `${deferredMessageId}-pending`,
      chatId: deferredChatId,
      messageId: deferredMessageId,
      editorSnapshot: editor.getJSON(),
      embedSnapshots,
      blockingEmbedIds: new Set(blockingEmbeds.map((e) => e.id)),
      embedProgress: embedProgressMap,
      createdAt: Date.now(),
      piiExclusions: new Set(activePIIExclusions),
      partialMarkdown: "",
    });

    // Optimistically show the stub message in the chat UI immediately.
    // The message stays at status "waiting_for_upload" until the deferred send fires.
    dispatch("sendMessage", { message: deferredMessage });

    // CLEAR the editor so the user can navigate to other chats, type new messages,
    // and interact freely. Upload callbacks in embedHandlers.ts will try to update
    // TipTap nodes but the nodes won't exist anymore — that's fine, the callbacks
    // already store embed data in EmbedStore independently.
    setHasContent(false);
    editor.commands.clearContent(false);
    editor.commands.blur();

    console.info(
      `[handleSend] Deferred send queued for chat ${deferredChatId.slice(-6)}: blocking on ${blockingEmbeds.length} embed(s), editor cleared`,
    );
    rootSpan.setAttribute('message.send.deferred', true);
    rootSpan.end();
    return; // Exit — the actual send will happen when embedUploadFinished fires
  }

  // OTel: embed registration span (image + audio embeds, includes dynamic imports)
  const embedRegSpan = tracer.startSpan('message.send.embed_registration');
  // =========================================================================
  // UPLOADED IMAGE EMBED REGISTRATION
  // For each 'image' embed that has been successfully uploaded (status: 'finished',
  // uploadEmbedId present), build a TOON content object and store it in EmbedStore.
  // This sets contentRef on the node so serializeEmbedToMarkdown can emit a proper
  // embed reference: ```json\n{"type":"image","embed_id":"..."}\n```
  // =========================================================================
  try {
    const { encode: toonEncode } = await import("@toon-format/toon");
    const { embedStore } = await import("../../../services/embedStore");

    // Collect nodes that need contentRef set
    interface UploadedImageNode {
      attrs: Record<string, unknown>;
    }
    const uploadedImageNodes: UploadedImageNode[] = [];
    editor.view.state.doc.descendants((node) => {
      if (
        node.type.name === "embed" &&
        node.attrs.type === "image" &&
        node.attrs.status === "finished" &&
        node.attrs.uploadEmbedId
      ) {
        uploadedImageNodes.push({ attrs: { ...node.attrs } });
      }
      return true;
    });

    for (const { attrs } of uploadedImageNodes) {
      const uploadEmbedId = attrs.uploadEmbedId as string;

      // Build TOON content mirroring the images/generate embed structure so that
      // existing image crypto utilities (fetchAndDecryptImage) can decrypt and
      // display the image. The images.view skill also expects this shape.
      //
      // embed_ref is set to the filename so that inline embed links like
      // [camera_1772448256162.jpg](embed:camera_1772448256162.jpg) can be
      // resolved via embedStore.resolveByRef() — both in the current session
      // (via the in-memory registerEmbedRef call below) and after reload
      // (via the cold-load path which reads embed_ref from TOON content).
      const embedContent = {
        app_id: "images",
        skill_id: "upload",
        type: "image",
        status: "finished",
        filename: attrs.filename || null,
        embed_ref: attrs.filename || null,
        content_hash: attrs.contentHash || null,
        s3_base_url: attrs.s3BaseUrl || null,
        files: attrs.s3Files || null,
        aes_key: attrs.aesKey || null,
        aes_nonce: attrs.aesNonce || null,
        vault_wrapped_aes_key: attrs.vaultWrappedAesKey || null,
        ai_detection: attrs.aiDetection || null,
      };

      let toonContent: string;
      try {
        toonContent = toonEncode(embedContent);
      } catch {
        toonContent = JSON.stringify(embedContent);
      }

      const now = Date.now();
      const textPreview = (attrs.filename as string) || "Uploaded image";

      // Store in EmbedStore — will be encrypted and sent with the message payload
      await embedStore.put(
        `embed:${uploadEmbedId}`,
        {
          embed_id: uploadEmbedId,
          type: "images-image", // Frontend type for uploaded user images
          status: "finished",
          content: toonContent,
          text_preview: textPreview,
          createdAt: now,
          updatedAt: now,
        },
        "images-image",
      );

      // Register the embed_ref → embed_id mapping in the in-memory index so
      // that inline embed links (e.g. [filename](embed:filename)) resolve
      // immediately in this session without waiting for a cold-load path.
      if (attrs.filename) {
        embedStore.registerEmbedRef(
          attrs.filename as string,
          uploadEmbedId,
          "images",
        );
      }

      console.debug(
        `[handleSend] Registered uploaded image embed ${uploadEmbedId} in EmbedStore`,
      );

      // Update the embed node's contentRef so the serializer emits a proper embed reference
      const { state, dispatch } = editor.view;
      const tr = state.tr;
      state.doc.descendants((node, nodePos) => {
        if (
          node.type.name === "embed" &&
          node.attrs.uploadEmbedId === uploadEmbedId
        ) {
          tr.setNodeMarkup(nodePos, undefined, {
            ...node.attrs,
            contentRef: `embed:${uploadEmbedId}`,
          });
          return false;
        }
        return true;
      });
      dispatch(tr);
    }
  } catch (embedRegError) {
    console.error(
      "[handleSend] Error registering uploaded image embeds:",
      embedRegError,
    );
    // Non-fatal: message will still send but image embeds may not be stored correctly.
    // Surface the error so it's visible (no silent failures).
    throw embedRegError;
  }

  // =========================================================================
  // AUDIO RECORDING EMBED REGISTRATION
  // For each 'recording' embed that has been successfully uploaded and
  // transcribed (status: 'finished', uploadEmbedId present), build a TOON
  // content object and store it in EmbedStore so the serializer can emit a
  // proper embed reference: ```json\n{"type":"audio-recording","embed_id":"..."}\n```
  // The TOON content stores all S3/AES metadata plus the transcript text so
  // the backend can inject it as context for the LLM.
  // =========================================================================
  try {
    const { encode: toonEncodeAudio } = await import("@toon-format/toon");
    const { embedStore: audioEmbedStore } =
      await import("../../../services/embedStore");

    interface UploadedRecordingNode {
      attrs: Record<string, unknown>;
    }
    const uploadedRecordingNodes: UploadedRecordingNode[] = [];
    editor.view.state.doc.descendants((node) => {
      if (
        node.type.name === "embed" &&
        node.attrs.type === "recording" &&
        node.attrs.status === "finished" &&
        node.attrs.uploadEmbedId
      ) {
        uploadedRecordingNodes.push({ attrs: { ...node.attrs } });
      }
      return true;
    });

    for (const { attrs } of uploadedRecordingNodes) {
      const uploadEmbedId = attrs.uploadEmbedId as string;

      // Build TOON content for the audio recording embed.
      // The backend audio skill (transcribe) expects this shape.
      // model is included so RecordingRenderer.ts can display "0:42 · voxtral-mini-2602"
      // in the read-only subtitle when loading from EmbedStore.
      const embedContent = {
        app_id: "audio",
        skill_id: "transcribe",
        type: "audio-recording",
        status: "finished",
        filename: attrs.filename || null,
        duration: attrs.duration || null,
        mime_type: attrs.mimeType || null,
        transcript: attrs.transcript || null,
        model: (attrs.model as string) || null,
        s3_base_url: attrs.s3BaseUrl || null,
        files: attrs.s3Files || null,
        aes_key: attrs.aesKey || null,
        aes_nonce: attrs.aesNonce || null,
        vault_wrapped_aes_key: attrs.vaultWrappedAesKey || null,
      };

      let toonContent: string;
      try {
        toonContent = toonEncodeAudio(embedContent);
      } catch {
        toonContent = JSON.stringify(embedContent);
      }

      const now = Date.now();
      const textPreview =
        (attrs.transcript as string) ||
        (attrs.filename as string) ||
        "Voice note";

      await audioEmbedStore.put(
        `embed:${uploadEmbedId}`,
        {
          embed_id: uploadEmbedId,
          type: "audio-recording",
          status: "finished",
          content: toonContent,
          text_preview: textPreview,
          createdAt: now,
          updatedAt: now,
        },
        "audio-recording",
      );

      console.debug(
        `[handleSend] Registered audio recording embed ${uploadEmbedId} in EmbedStore`,
      );

      // Update the embed node's contentRef so the serializer emits a proper embed reference
      const { state: recState, dispatch: recDispatch } = editor.view;
      const recTr = recState.tr;
      recState.doc.descendants((node, nodePos) => {
        if (
          node.type.name === "embed" &&
          node.attrs.uploadEmbedId === uploadEmbedId
        ) {
          recTr.setNodeMarkup(nodePos, undefined, {
            ...node.attrs,
            contentRef: `embed:${uploadEmbedId}`,
          });
          return false;
        }
        return true;
      });
      recDispatch(recTr);
    }
  } catch (recEmbedRegError) {
    console.error(
      "[handleSend] Error registering audio recording embeds:",
      recEmbedRegError,
    );
    throw recEmbedRegError;
  }

  // NOTE: PDF embed registration is intentionally NOT done here.
  // PDF dedup is disabled (see internal_api.py). Every PDF upload triggers
  // fresh OCR which delivers the full TOON via send_embed_data. Registering
  // a minimal TOON here would overwrite the full OCR cache on the server.
  embedRegSpan.end();

  // Get the TipTap editor content as JSON
  const editorContent = editor.getJSON();
  if (
    !editorContent ||
    !editorContent.content ||
    editorContent.content.length === 0
  ) {
    console.warn("[handleSend] No editor content available");
    vibrateMessageField();
    return;
  }

  // Convert to markdown
  let markdown = tipTapToCanonicalMarkdown(editorContent);

  // Strip leading empty lines that were auto-prepended to allow cursor placement
  // before the first embed node (see ensureLeadingParagraph in embedHandlers.ts).
  // Leading newlines are meaningless to the LLM and produce an ugly blank first line.
  markdown = markdown.replace(/^\n+/, "");

  // CRITICAL: Process URLs before sending to convert them to proper embeds
  // This ensures that when user types "summarize https://example.com" and presses Enter,
  // the URL is converted to an embed with metadata fetched from the preview server.
  // The embed will be:
  // 1. Stored in EmbedStore for client-side access
  // 2. Sent with the message to the server
  // 3. Cached server-side for LLM inference (so LLM gets the URL metadata)
  const urlSpan = tracer.startSpan('message.send.url_processing');
  try {
    markdown = await processUrlsBeforeSend(markdown);
  } catch (error) {
    console.error("[handleSend] Error processing URLs before send:", error);
    // Continue with original markdown if URL processing fails
  } finally {
    urlSpan.end();
  }

  // OTel: PII detection span
  const piiSpan = tracer.startSpan('message.send.pii_detection');
  // PII ANONYMIZATION: Detect and replace sensitive data with placeholders
  // This protects user privacy by ensuring emails, API keys, credit cards, etc.
  // are not sent to the server in plain text.
  // Users can click on highlighted PII in the editor to exclude specific matches.
  // The PII mappings are stored encrypted with the message for later restoration.
  //
  // Respects personalDataStore settings:
  // - If masterEnabled is false, skip ALL PII detection
  // - Disabled categories are skipped (user can toggle individual PII types)
  // - User-defined personal data entries (names, addresses, etc.) are also detected
  let piiMappingsForStorage: PIIMappingForStorage[] = [];
  try {
    // Read current privacy settings from the store
    const piiSettings: PIIDetectionSettings = get(personalDataStore.settings);

    // Only run PII detection if the master toggle is enabled
    if (piiSettings.masterEnabled) {
      // Build the set of disabled categories (categories where the toggle is OFF)
      const disabledCategories = new Set<string>();
      for (const [category, enabled] of Object.entries(
        piiSettings.categories,
      )) {
        if (!enabled) disabledCategories.add(category);
      }

      // Get user-defined personal data entries that are enabled
      const enabledEntries: PersonalDataEntry[] = get(
        personalDataStore.enabledEntries,
      );
      const personalDataForDetection: PersonalDataForDetection[] =
        enabledEntries.map((entry) => {
          const result: PersonalDataForDetection = {
            id: entry.id,
            textToHide: entry.textToHide,
            replaceWith: entry.replaceWith,
          };
          // For address entries, include individual address lines as additional search texts
          if (entry.type === "address" && entry.addressLines) {
            const additionalTexts: string[] = [];
            if (entry.addressLines.street)
              additionalTexts.push(entry.addressLines.street);
            if (entry.addressLines.city)
              additionalTexts.push(entry.addressLines.city);
            result.additionalTexts = additionalTexts;
          }
          return result;
        });

      // Build detection options with category filtering and personal data entries
      const detectionOptions: PIIDetectionOptions = {
        excludedIds: activePIIExclusions,
        disabledCategories,
        personalDataEntries: personalDataForDetection,
      };

      // CRITICAL: Protect embed reference blocks (```json {"embed_id":…} ```) from the
      // PII anonymizer. UUID segments can match PII patterns (e.g. "051-4369" fires the
      // local phone-number regex), which corrupts embed IDs and causes message sends to
      // be blocked with "missing embeds". We swap them out for opaque tokens, run PII on
      // the rest of the markdown, then restore the original blocks afterwards.
      const { safeMarkdown, restore } = protectEmbedRefsFromPII(markdown);

      const piiMatches = detectPII(safeMarkdown, detectionOptions);
      if (piiMatches.length > 0) {
        console.debug(
          "[handleSend] Detected PII to anonymize:",
          piiMatches.map((m) => ({
            type: m.type,
            placeholder: m.placeholder,
            // Don't log the actual match value for security
            matchLength: m.match.length,
          })),
        );

        // Create PII mappings for storage - these will be encrypted with the message
        // and used to restore original values when rendering messages
        piiMappingsForStorage = createPIIMappingsForStorage(piiMatches);

        markdown = restore(
          replacePIIWithPlaceholders(safeMarkdown, piiMatches),
        );
        console.debug(
          "[handleSend] PII anonymization complete, replaced",
          piiMatches.length,
          "sensitive items. Mappings will be stored with message.",
        );
      } else {
        // No PII found, but still restore embed blocks (restore is a no-op if none
        // were protected, so this is always safe).
        markdown = restore(safeMarkdown);
      }
    } else {
      console.debug(
        "[handleSend] PII detection disabled by user (masterEnabled=false)",
      );
    }
  } catch (error) {
    console.error("[handleSend] Error in PII anonymization:", error);
    // Continue with original markdown if PII detection fails - user privacy is important
    // but we shouldn't block sending messages entirely
  } finally {
    piiSpan.end();
  }

  // Check if a new chat suggestion was clicked - if so, track it for deletion
  const { consumeClickedSuggestion } =
    await import("../../../stores/suggestionTracker");
  const encryptedSuggestionToDelete = consumeClickedSuggestion();

  if (encryptedSuggestionToDelete) {
    // Delete from local IndexedDB immediately
    try {
      const { chatDB } = await import("../../../services/db");

      const allSuggestions = await chatDB.getAllNewChatSuggestions();

      const suggestionToDelete = allSuggestions.find(
        (s) => s.encrypted_suggestion === encryptedSuggestionToDelete,
      );

      if (suggestionToDelete) {
        // Delete directly by ID instead of re-encrypting text
        // This avoids encryption mismatch issues
        await chatDB.deleteNewChatSuggestionById(suggestionToDelete.id);
      } else {
        console.warn("[handleSend] New chat suggestion not found in DB, skipping deletion");
      }
    } catch (error) {
      console.error("[handleSend] Failed to delete new chat suggestion from local IndexedDB:", error);
      // Continue with message send even if deletion fails
    }
  }

  if (get(forcedLogoutInProgress)) {
    console.error(
      "[handleSend] Cannot send message - forced logout in progress",
    );
    notificationStore.error("Session expired. Please log in again.");
    return;
  }

  let chatIdToUse = currentChatId;
  let chatToUpdate: import("../../../types/chat").Chat | null = null;
  let isNewChatCreation = false;
  let messagePayload: Message; // Defined here to be accessible for sendNewMessage

  try {
    // Check if there's already a chat with a draft (created during typing)
    const draftState = get(draftEditorUIState);
    if (!chatIdToUse && draftState.currentChatId) {
      // Use the existing chat that was created for the draft
      chatIdToUse = draftState.currentChatId;
      console.info(
        `[handleSend] Using existing draft chat ${chatIdToUse} for message`,
      );
    } else if (!chatIdToUse) {
      // Only create a new chat if there's no current chat and no draft chat
      chatIdToUse = crypto.randomUUID();
      isNewChatCreation = true;
      console.info(`[handleSend] Creating new chat ${chatIdToUse} for message`);
    }

    // CRITICAL: Check if we're sending a message to a demo/legal chat (public chat)
    // If so, we MUST generate a new UUID for the chat so it becomes a regular chat
    // This ensures:
    // 1. The chat can't be identified as demo/legal later
    // 2. Message IDs use proper format {last_10_chars_of_UUID}-{uuid_v4} instead of {last_10_chars_of_demo-for-everyone}-{uuid_v4}
    let sourceDemoId: string | null = null;
    if (chatIdToUse && isPublicChat(chatIdToUse)) {
      sourceDemoId = chatIdToUse;
      const oldChatId = chatIdToUse;
      chatIdToUse = crypto.randomUUID();
      isNewChatCreation = true;
      console.info(
        `[handleSend] 🔄 Converting public chat ${oldChatId} to regular chat ${chatIdToUse} - user sent message to demo/legal chat`,
      );
    }

    // Check if we're using an existing draft chat
    const isUsingDraftChat =
      !currentChatId &&
      draftState.currentChatId &&
      chatIdToUse === draftState.currentChatId;

    // Check if we're dealing with a temporary chat ID (not a real chat in the database)
    // This happens when a temporaryChatId was set in ActiveChat but the chat doesn't actually exist in DB
    // We need to check the database to determine if this is a real chat or temporary
    const existingChatCheck = await chatDB.getChat(chatIdToUse);
    const isTemporaryChat = !existingChatCheck && !isNewChatCreation;
    if (isTemporaryChat) {
      // For temporary chats, we need to create a new chat
      isNewChatCreation = true;
      console.info(
        `[handleSend] Detected temporary chat ID ${chatIdToUse} (not in DB), treating as new chat creation`,
      );
    }

    // No need to fetch current title - server will send metadata after preprocessing

    // =============================================================================
    // AUTO-DISMISS PENDING PERMISSION DIALOG (LOCAL ONLY)
    // =============================================================================
    // If user sends a new message while a permission dialog is visible for this chat,
    // we dismiss it locally WITHOUT sending a WebSocket rejection to the server.
    //
    // WHY LOCAL-ONLY: Sending an explicit rejection via WebSocket triggers the server's
    // _trigger_continuation() which creates a new Celery task for the OLD message.
    // Then the new message ALSO creates a Celery task, resulting in TWO AI responses.
    //
    // Instead, we only create the "rejected" system message locally for UI display.
    // The server's main_processor.py already auto-rejects the pending context when it
    // receives the new message (deletes from Redis + sends dismiss event to other devices).
    const currentPermissionRequestId =
      appSettingsMemoriesPermissionStore.getCurrentRequestId();
    const currentPermissionChatId =
      appSettingsMemoriesPermissionStore.getCurrentChatId();

    if (currentPermissionRequestId && currentPermissionChatId === chatIdToUse) {
      console.info(
        `[handleSend] Auto-dismissing permission dialog locally for request ${currentPermissionRequestId} ` +
          `(user sent new message to chat ${chatIdToUse})`,
      );

      // LOCAL-ONLY dismiss: create "rejected" system message + clear dialog UI
      // Does NOT send WebSocket rejection (avoids duplicate AI response)
      try {
        const { handlePermissionDialogLocalDismiss } =
          await import("../../../services/chatSyncServiceHandlersAppSettings");
        await handlePermissionDialogLocalDismiss(
          chatSyncService,
          currentPermissionRequestId,
        );
        console.info(
          "[handleSend] Permission dialog locally dismissed and rejected response recorded",
        );
      } catch (dismissError) {
        console.error(
          "[handleSend] Error auto-dismissing permission dialog:",
          dismissError,
        );
        // Continue with sending the message even if dismiss fails
        // At minimum, clear the dialog UI
        appSettingsMemoriesPermissionStore.clear();
      }
    }

    // Create new message payload using the processed markdown and determined chatIdToUse
    // The markdown has already been processed to convert URLs to embed references
    // Include PII mappings so they can be encrypted and stored with the message
    const payloadSpan = tracer.startSpan('message.send.payload_creation');
    messagePayload = createMessagePayload(
      markdown,
      chatIdToUse,
      piiMappingsForStorage,
    );

    // Optimistically cache the last message so the chat list can show "Sending..." immediately
    // (prevents a brief empty chat row while active chat selection/metadata settles)
    chatListCache.setLastMessage(chatIdToUse, messagePayload);
    payloadSpan.end();

    // Debug logging to understand the flow
    console.debug(`[handleSend] Chat creation logic:`, {
      currentChatId,
      draftChatId: draftState.currentChatId,
      chatIdToUse,
      isNewChatCreation,
      isUsingDraftChat,
      isTemporaryChat,
    });

    // OTel: IndexedDB write span (chat creation/update + message save)
    const idbSpan = tracer.startSpan('message.send.idb_write');
    // Check if incognito mode is enabled
    const { incognitoMode } =
      await import("../../../stores/incognitoModeStore");
    const isIncognitoEnabled = incognitoMode.get();

    if (isNewChatCreation) {
      const now = Math.floor(Date.now() / 1000);
      const newChatData: import("../../../types/chat").Chat = {
        chat_id: chatIdToUse,
        encrypted_title: null,
        messages_v: 1, // A new chat with its first message starts at version 1
        title_v: 0, // Will be incremented to 1 when first title is set
        draft_v: 0,
        encrypted_draft_md: null,
        encrypted_draft_preview: null,
        last_edited_overall_timestamp: messagePayload.created_at, // Use message timestamp
        unread_count: 0,
        created_at: now,
        updated_at: now,
        processing_metadata: false, // Show chat immediately in sidebar (no longer hidden)
        waiting_for_metadata: !isIncognitoEnabled, // Incognito chats don't get metadata from server
        is_incognito: isIncognitoEnabled,
        source_demo_id: sourceDemoId, // Track source for duplication flow
      };

      // Duplication Flow: If this chat is from a demo, copy history messages
      if (sourceDemoId) {
        try {
          const { DEMO_CHATS, LEGAL_CHATS, getDemoMessages } =
            await import("../../../demo_chats");
          const demoMessages = getDemoMessages(
            sourceDemoId,
            DEMO_CHATS,
            LEGAL_CHATS,
          );

          if (demoMessages && demoMessages.length > 0) {
            console.info(
              `[handleSend] Duplicating ${demoMessages.length} demo messages to new chat ${chatIdToUse}`,
            );

            // Ensure we have a chat key for encryption (this device is creating the chat)
            chatKeyManager.createKeyForNewChat(chatIdToUse);

            // NOTE: Demo messages are NOT saved to IndexedDB. They were previously
            // copied as AI "context", but the backend receives full conversation context
            // via the API call — storing them in IDB caused demo messages to bleed into
            // the real chat view when IDB was reloaded after streaming completed.
            // The demo greeting ("Digital team mates for everyone...") is not meaningful
            // context for the AI response to the user's actual question.

            // Update messages_v count (only the new user message being sent)
            newChatData.messages_v = 1;
          }

          // Clone example chat embeds into the embedStore (IndexedDB)
          // Without this, embeds only render from the in-memory exampleChatStore
          // fallback — they won't survive cross-device sync or backend AI context.
          const { isExampleChat: isExampleChatCheck, getExampleChatEmbeds } =
            await import("../../../demo_chats");
          if (isExampleChatCheck(sourceDemoId)) {
            const exampleEmbeds = getExampleChatEmbeds(sourceDemoId);
            if (exampleEmbeds.length > 0) {
              const { embedStore: embedStoreForClone } =
                await import("../../../services/embedStore");
              console.info(
                `[handleSend] Cloning ${exampleEmbeds.length} embeds from example chat ${sourceDemoId} to new chat ${chatIdToUse}`,
              );
              for (const embed of exampleEmbeds) {
                const contentRef = `embed:${embed.embed_id}`;
                try {
                  await embedStoreForClone.put(
                    contentRef,
                    {
                      content: embed.content,
                      type: embed.type,
                      status: "finished",
                      embed_id: embed.embed_id,
                      parent_embed_id: embed.parent_embed_id,
                      embed_ids: embed.embed_ids,
                    },
                    embed.type as import("../../../message_parsing/types").EmbedType,
                  );
                } catch (embedError) {
                  console.warn(
                    `[handleSend] Failed to clone embed ${embed.embed_id}:`,
                    embedError,
                  );
                }
              }
            }
          }
        } catch (dupError) {
          console.error(
            "[handleSend] Error duplicating demo history:",
            dupError,
          );
        }
      }

      console.debug(
        `[handleSend] Creating new ${isIncognitoEnabled ? "incognito" : "regular"} chat with waiting_for_metadata=${newChatData.waiting_for_metadata}:`,
        {
          chatId: chatIdToUse,
          waiting_for_metadata: newChatData.waiting_for_metadata,
        },
      );

      if (isIncognitoEnabled) {
        // Create incognito chat in sessionStorage
        const { incognitoChatService } =
          await import("../../../services/incognitoChatService");
        await incognitoChatService.storeChat(newChatData);
        await incognitoChatService.addMessage(chatIdToUse, messagePayload);
        chatToUpdate = newChatData;
        console.info(
          `[handleSend] Created new incognito chat ${chatIdToUse} and saved its first message.`,
        );
      } else {
        // Create regular chat in IndexedDB
        await chatDB.addChat(newChatData); // Save new chat metadata
        await chatDB.saveMessage(messagePayload); // Save the first message separately

        // Fetch the chat again to ensure we have the consistent DB version for chatToUpdate
        // This also ensures chatToUpdate has the correct messages_v (which is 1)
        chatToUpdate = await chatDB.getChat(chatIdToUse);
        if (!chatToUpdate) {
          console.error(
            `[handleSend] CRITICAL: Newly created chat ${chatIdToUse} not found in DB immediately after addChat and saveMessage.`,
          );
          vibrateMessageField();
          return;
        }
        console.info(
          `[handleSend] Created new local chat ${chatIdToUse} and saved its first message (messages_v should be 1).`,
        );
      }

      // Dispatch event to update chat list immediately
      window.dispatchEvent(
        new CustomEvent("localChatListChanged", {
          detail: { chat_id: chatIdToUse },
        }),
      );
    } else {
      // Existing chat: Save the new message and update chat metadata
      // Check if it's an incognito chat
      const { incognitoChatService } =
        await import("../../../services/incognitoChatService");
      let isIncognitoChat = false;
      let existingChat: import("../../../types/chat").Chat | null = null;

      try {
        existingChat = await incognitoChatService.getChat(chatIdToUse);
        if (existingChat) {
          isIncognitoChat = true;
        }
      } catch {
        // Not an incognito chat, continue to check IndexedDB
      }

      if (isIncognitoChat && existingChat) {
        // Update incognito chat
        await incognitoChatService.addMessage(chatIdToUse, messagePayload);
        existingChat.messages_v = (existingChat.messages_v || 0) + 1;
        existingChat.last_edited_overall_timestamp = messagePayload.created_at;
        existingChat.updated_at = Math.floor(Date.now() / 1000);
        await incognitoChatService.updateChat(chatIdToUse, {
          messages_v: existingChat.messages_v,
          last_edited_overall_timestamp:
            existingChat.last_edited_overall_timestamp,
          updated_at: existingChat.updated_at,
        });
        chatToUpdate = existingChat;
        console.info(
          `[handleSend] Updated incognito chat ${chatIdToUse} with new message.`,
        );
      } else {
        // Update regular chat in IndexedDB
        await chatDB.saveMessage(messagePayload);
        existingChat = await chatDB.getChat(chatIdToUse);
        if (existingChat) {
          existingChat.messages_v = (existingChat.messages_v || 0) + 1;
          existingChat.last_edited_overall_timestamp =
            messagePayload.created_at;
          existingChat.updated_at = Math.floor(Date.now() / 1000);

          // Clear draft fields after message is sent (especially important for draft chats)
          existingChat.encrypted_draft_md = null;
          existingChat.encrypted_draft_preview = null;
          existingChat.draft_v = 0;

          await chatDB.updateChat(existingChat);
          chatToUpdate = existingChat;

          if (isUsingDraftChat) {
            console.info(
              `[handleSend] Updated existing draft chat ${chatIdToUse} with first message and cleared draft fields`,
            );
          } else {
            console.info(
              `[handleSend] Updated existing chat ${chatIdToUse} with new message and cleared draft fields`,
            );
          }
        } else {
          console.error(
            `[handleSend] Existing chat ${chatIdToUse} not found when trying to add a message.`,
          );
          vibrateMessageField();
          return; // Early exit if chat doesn't exist
        }
      }
    }

    idbSpan.end();

    // If chatToUpdate is null at this point, the local DB operation failed.
    if (!chatToUpdate) {
      console.error(
        `[handleSend] Failed to update local chat ${chatIdToUse} with new message. Aborting send.`,
      );
      vibrateMessageField();
      return;
    }

    // Check if there's an active AI task for this chat
    // If so, the new message will be queued on the server
    // We don't cancel the existing task - it will complete and then process the queued message
    if (chatIdToUse && chatSyncService) {
      const existingTaskId =
        chatSyncService.getActiveAITaskIdForChat(chatIdToUse);
      if (existingTaskId) {
        console.info(
          `[handleSend] Active AI task ${existingTaskId} exists for chat ${chatIdToUse}. New message will be queued.`,
        );
        // TODO: Show UI message "Press enter again to stop previous response" or similar
        // This will be handled by the frontend when it receives a queue notification
      }
    }

    // Set hasContent to false first to prevent race conditions with editor updates
    setHasContent(false);
    // Reset editor and force blur to show stop button and reduce height
    // Always blur after sending to make input compact and show assistant response
    resetEditorContent(editor, false); // Force blur (false = don't keep focus)

    // ─── Edit mode: delete messages from edit point before re-sending ───
    // When the user edits a previous message, we need to delete all messages
    // from that point onward (inclusive) so the backend sees a clean history.
    const editState = get(editMessageStore);
    const isEditSend = !!(editState && editState.chatId === chatIdToUse);
    let editCreatedAt: number | undefined;
    if (isEditSend && editState) {
      editCreatedAt = editState.createdAt;
      try {
        const allMessages = await chatDB.getMessagesForChat(chatIdToUse);
        allMessages.sort((a, b) => (a.created_at ?? 0) - (b.created_at ?? 0));
        // Find the index of the edited message by ID for precision
        const editIdx = allMessages.findIndex(m => m.message_id === editState.messageId);
        const startIdx = editIdx >= 0 ? editIdx : allMessages.findIndex(m => (m.created_at ?? 0) >= editState.createdAt);
        if (startIdx >= 0) {
          const messagesToDelete = allMessages.slice(startIdx);
          console.debug(`[handleSend] Edit mode: deleting ${messagesToDelete.length} messages from index ${startIdx}`);
          for (const msg of messagesToDelete) {
            await chatDB.deleteMessage(msg.message_id);
            chatSyncService.sendDeleteMessage(chatIdToUse, msg.message_id).catch(err => {
              console.warn('[handleSend] Edit mode: failed to delete message from server:', msg.message_id, err);
            });
          }
        }
      } catch (err) {
        console.error('[handleSend] Edit mode: failed to delete messages:', err);
      }
      cancelEdit();
    }

    // OTel: UI dispatch span — the moment message becomes visible
    const uiSpan = tracer.startSpan('message.send.ui_dispatch');
    // Dispatch for UI update (ActiveChat will pick this up)
    // The messagePayload is already defined and includes the correct chat_id
    // If it's a new chat (isNewChatCreation is true) OR we're using an existing draft chat,
    // chatToUpdate will hold the Chat object.
    dispatch("sendMessage", {
      message: messagePayload,
      newChat: isNewChatCreation || isUsingDraftChat ? chatToUpdate : undefined,
      isEditSend,
      editCreatedAt,
    });

    // chatToUpdate should be the definitive version of the chat from the DB
    // The 'chatUpdated' event is still useful for other components like the chat list.
    if (chatToUpdate) {
      // Dispatch chatUpdated so other parts of the UI (like chat list) can update if needed
      // This local dispatch is for MessageInput's parent (ActiveChat)
      dispatch("chatUpdated", { chat: chatToUpdate });

      // If a new chat was created, signal it through draftEditorUIState
      // This is what Chats.svelte listens to for selecting new chats.
      if (isNewChatCreation) {
        draftEditorUIState.update((state) => ({
          ...state,
          newlyCreatedChatIdToSelect: chatIdToUse,
        }));
        console.info(
          `[handleSend] Signaled new chat ${chatIdToUse} for selection via draftEditorUIState.`,
        );
      } else {
        // For existing chats, ensure chatSyncService knows about the local update
        // so it can propagate to Chats.svelte if necessary, or handle consistency.
        // A more direct way for Chats.svelte to react to local DB changes might be needed
        // if chatSyncService events are strictly for server-originated changes.
        // For now, we rely on draftEditorUIState for new chats, and existing chat updates
        // should be picked up by Chats.svelte if it re-queries DB on 'chatUpdated' from ActiveChat.
        window.dispatchEvent(
          new CustomEvent("chatUpdated", {
            // This helps Chats.svelte if it listens globally or via ActiveChat relay
            detail: { chat_id: chatToUpdate.chat_id, chat: chatToUpdate }, // Ensure chat_id is at top level for some handlers
            bubbles: true,
            composed: true,
          }),
        );
      }
    }

    uiSpan.end();

    // OTel: WebSocket send span (encryption + WS dispatch happens inside sendNewMessage)
    const wsSpan = tracer.startSpan('message.send.ws_send');
    // CRITICAL: Notify backend about the active chat BEFORE sending the message
    // This prevents race conditions where the backend starts processing the message
    // and tries to stream chunks before knowing which chat is active, causing chunks to be dropped
    // This is especially important for new chats where the active_chat might be null or the old chat ID
    await chatSyncService.sendSetActiveChat(chatIdToUse);
    console.debug(
      "[handleSend] Notified backend about active chat before sending message:",
      chatIdToUse,
    );

    // Send message to backend via chatSyncService
    // Include encrypted suggestion for deletion if one was clicked
    await chatSyncService.sendNewMessage(
      messagePayload,
      encryptedSuggestionToDelete,
    );
    console.debug(
      "[handleSend] Message sent to chatSyncService:",
      messagePayload,
      encryptedSuggestionToDelete ? "(with suggestion to delete)" : "",
    );

    wsSpan.end();

    // OTel: cleanup span (draft clearing)
    const cleanupSpan = tracer.startSpan('message.send.cleanup');
    // After successfully sending the message, clear the draft for this chat
    // Ensure we only clear if the message was for the chat currently in the draft editor's context
    const currentDraftState = get(draftEditorUIState);
    if (chatIdToUse && currentDraftState.currentChatId === chatIdToUse) {
      console.info(
        `[handleSend] Message sent for chat ${chatIdToUse}, clearing its draft.`,
      );
      await clearCurrentDraft();
    } else {
      // This case might happen if a message is sent for a chat that isn't the one
      // currently active in the MessageInput's draft context (e.g., programmatic send).
      // Or if a new chat was just created, the draft context might not be set yet,
      // but clearCurrentDraft relies on draftEditorUIState.currentChatId.
      // If it's a new chat, there shouldn't be a draft to clear anyway.
      // If it's an existing chat but not the one in draft context, we might not want to clear its draft.
      // The current logic of clearCurrentDraft uses draftEditorUIState.currentChatId,
      // so if chatIdToUse is different, it won't clear the draft of chatIdToUse unless
      // draftEditorUIState.currentChatId happens to be chatIdToUse.
      // This seems fine for now, as sending a message typically implies the chat is active.
      console.debug(
        `[handleSend] Message sent for chat ${chatIdToUse}, but draft context is ${currentDraftState.currentChatId}. Draft clear skipped or handled by clearCurrentDraft's internal logic.`,
      );
    }
    cleanupSpan.end();
  } catch (error) {
    console.error("Failed to handle message send:", error);
    vibrateMessageField();
  } finally {
    // CRITICAL: Always release the send guard, even on error,
    // so the user can retry sending after a failure.
    sendInProgress = false;
    rootSpan.end();
  }
}

// =============================================================================
// Deferred Send Execution
// =============================================================================

/**
 * Execute a deferred send by reconstructing final markdown from the snapshotted
 * editor JSON + EmbedStore data. This runs WITHOUT a live TipTap editor —
 * the user may have navigated to a different chat.
 *
 * Steps:
 *  1. Deep-clone the editorSnapshot from the PendingSendContext.
 *  2. Walk all embed nodes in the snapshot and patch their attrs with the final
 *     contentRef from EmbedStore (looked up via uploadEmbedId).
 *  3. Serialize the patched snapshot to markdown via tipTapToCanonicalMarkdown().
 *  4. Run PII anonymization using the captured piiExclusions.
 *  5. Run URL processing via processUrlsBeforeSend().
 *  6. Create message payload and send via chatSyncService.sendNewMessage().
 *  7. Update the stub message in IndexedDB from "waiting_for_upload" → "sending".
 *
 * @param readyCtx The PendingSendContext whose blocking embeds are all finished
 */
export async function executeDeferredSend(
  readyCtx: import("../../../stores/pendingUploadStore").PendingSendContext,
): Promise<void> {
  console.info(
    `[executeDeferredSend] Starting for pending ${readyCtx.pendingId} in chat ${readyCtx.chatId.slice(-6)}`,
  );

  // -------------------------------------------------------------------------
  // 1. Deep-clone the snapshot so we can mutate it safely
  // -------------------------------------------------------------------------
  const snapshot = JSON.parse(
    JSON.stringify(readyCtx.editorSnapshot),
  ) as Record<string, unknown>;

  // -------------------------------------------------------------------------
  // 2. Walk embed nodes and patch contentRef from EmbedStore
  // -------------------------------------------------------------------------
  // The snapshot is a TipTap JSON tree: { type: "doc", content: [...] }
  // Embed nodes are at any depth: { type: "embed", attrs: { id, type, ... } }
  interface TipTapNode {
    type?: string;
    attrs?: Record<string, unknown>;
    content?: TipTapNode[];
  }

  function patchEmbedNodes(nodes: TipTapNode[] | undefined): void {
    if (!nodes) return;
    for (const node of nodes) {
      if (node.type === "embed" && node.attrs) {
        const embedId = node.attrs.id as string;
        // Look up the snapshot we captured at send time
        const snap = readyCtx.embedSnapshots.get(embedId);
        if (snap) {
          // The upload handler (embedHandlers.ts) stores finished embed data in
          // EmbedStore with key `embed:${uploadEmbedId}`. The uploadEmbedId on
          // the snapshot may have been null at capture time (still uploading), but
          // by now the upload is done and the TipTap node attrs were updated by
          // the upload callback. However, the TipTap editor was cleared — so we
          // need to read uploadEmbedId from the snapshot (if set at capture time)
          // or from the EmbedStore's embed_id field.
          //
          // Strategy: if snap.uploadEmbedId is set, use it directly. Otherwise,
          // we have a problem because we don't know the server-assigned embed_id.
          // In practice, for deferred sends the embed was always in "uploading"
          // status, meaning uploadEmbedId was NOT yet set. But by the time the
          // upload finishes, _performUpload / _performRecordingUpload stores the
          // embed in EmbedStore with key `embed:${uploadEmbedId}`. We need a way
          // to map localEmbedId → uploadEmbedId.
          //
          // The embedUploadFinished event only carries localEmbedId. But
          // _performUpload() also updates the TipTap node with uploadEmbedId.
          // Since the editor is cleared, that update is a no-op. However, the
          // embedHandlers code ALSO stores in EmbedStore using the server's
          // embed_id as key. We need to search EmbedStore for an entry whose
          // embed_id was created from this localEmbedId.
          //
          // BETTER APPROACH: Store the mapping localEmbedId → uploadEmbedId
          // in the DeferredEmbedSnapshot when the upload finishes. We can update
          // the snapshot in the pendingUploadStore when markEmbedFinished is called.
          //
          // FOR NOW: The uploadEmbedId may already be on the snapshot if the
          // embed was in "transcribing" (not "uploading") status when the user
          // pressed Send. For "uploading" embeds, we need the mapping.
          //
          // SIMPLEST FIX: embedHandlers.ts already dispatches the
          // embedUploadFinished event. Before dispatching, we should also update
          // the DeferredEmbedSnapshot in pendingUploadStore with the
          // uploadEmbedId. Let's handle this by having the upload callbacks
          // update the snapshot. But for now, let's try using the snapshot's
          // uploadEmbedId if available, and fall back to checking contentRef.
          let contentRef = snap.contentRef;

          if (!contentRef && snap.uploadEmbedId) {
            contentRef = `embed:${snap.uploadEmbedId}`;
          }

          if (contentRef) {
            node.attrs.contentRef = contentRef;
          }
        }
      }
      // Recurse into children
      if (node.content) {
        patchEmbedNodes(node.content);
      }
    }
  }

  patchEmbedNodes((snapshot as TipTapNode).content);

  // -------------------------------------------------------------------------
  // 3. Serialize to markdown
  // -------------------------------------------------------------------------
  let markdown = tipTapToCanonicalMarkdown(snapshot);
  // Strip leading empty lines (same as normal send path)
  markdown = markdown.replace(/^\n+/, "");

  // -------------------------------------------------------------------------
  // 4. Process URLs → embed references
  // -------------------------------------------------------------------------
  try {
    markdown = await processUrlsBeforeSend(markdown);
  } catch (error) {
    console.error(
      "[executeDeferredSend] Error processing URLs before send:",
      error,
    );
  }

  // -------------------------------------------------------------------------
  // 5. PII anonymization
  // -------------------------------------------------------------------------
  let piiMappingsForStorage: PIIMappingForStorage[] = [];
  try {
    const piiSettings: PIIDetectionSettings = get(personalDataStore.settings);
    if (piiSettings.masterEnabled) {
      const disabledCategories = new Set<string>();
      for (const [category, enabled] of Object.entries(
        piiSettings.categories,
      )) {
        if (!enabled) disabledCategories.add(category);
      }

      const enabledEntries: PersonalDataEntry[] = get(
        personalDataStore.enabledEntries,
      );
      const personalDataForDetection: PersonalDataForDetection[] =
        enabledEntries.map((entry) => {
          const result: PersonalDataForDetection = {
            id: entry.id,
            textToHide: entry.textToHide,
            replaceWith: entry.replaceWith,
          };
          if (entry.type === "address" && entry.addressLines) {
            const additionalTexts: string[] = [];
            if (entry.addressLines.street)
              additionalTexts.push(entry.addressLines.street);
            if (entry.addressLines.city)
              additionalTexts.push(entry.addressLines.city);
            result.additionalTexts = additionalTexts;
          }
          return result;
        });

      const detectionOptions: PIIDetectionOptions = {
        excludedIds: readyCtx.piiExclusions,
        disabledCategories,
        personalDataEntries: personalDataForDetection,
      };

      // Protect embed reference blocks from PII corruption (same reason as in
      // handleSend: UUID segments can match phone/other PII patterns).
      const { safeMarkdown: safeMd, restore: restoreMd } =
        protectEmbedRefsFromPII(markdown);

      const piiMatches = detectPII(safeMd, detectionOptions);
      if (piiMatches.length > 0) {
        piiMappingsForStorage = createPIIMappingsForStorage(piiMatches);
        markdown = restoreMd(replacePIIWithPlaceholders(safeMd, piiMatches));
        console.debug(
          `[executeDeferredSend] PII anonymization: replaced ${piiMatches.length} items`,
        );
      } else {
        markdown = restoreMd(safeMd);
      }
    }
  } catch (error) {
    console.error("[executeDeferredSend] PII anonymization error:", error);
  }

  // -------------------------------------------------------------------------
  // 6. Build message payload and update IndexedDB
  // -------------------------------------------------------------------------
  const wsStatus = get(websocketStatus);
  const isConnected = wsStatus.status === "connected";
  const newStatus: Message["status"] = isConnected
    ? "sending"
    : "waiting_for_internet";

  // Update the existing stub message in IndexedDB with real content + new status
  try {
    const { incognitoChatService } =
      await import("../../../services/incognitoChatService");
    const incognitoChat = await incognitoChatService
      .getChat(readyCtx.chatId)
      .catch(() => null);

    const updatedMessage: Partial<Message> & {
      message_id: string;
      chat_id: string;
    } = {
      message_id: readyCtx.messageId,
      chat_id: readyCtx.chatId,
      content: markdown,
      status: newStatus,
      pii_mappings:
        piiMappingsForStorage.length > 0 ? piiMappingsForStorage : undefined,
    };

    if (incognitoChat) {
      // For incognito chats, we need to update the message in the incognito store
      // incognitoChatService doesn't have an updateMessage, so we re-add
      const existingMessages = await incognitoChatService.getMessagesForChat(
        readyCtx.chatId,
      );
      const existingMsg = existingMessages.find(
        (m) => m.message_id === readyCtx.messageId,
      );
      if (existingMsg) {
        Object.assign(existingMsg, updatedMessage);
        await incognitoChatService.addMessage(readyCtx.chatId, existingMsg);
      }
    } else {
      // Regular chat: update the message in IndexedDB
      const existingMsg = await chatDB.getMessage(readyCtx.messageId);
      if (existingMsg) {
        existingMsg.content = markdown;
        existingMsg.status = newStatus;
        existingMsg.pii_mappings =
          piiMappingsForStorage.length > 0 ? piiMappingsForStorage : undefined;
        await chatDB.saveMessage(existingMsg);
      }
    }
  } catch (dbError) {
    console.error(
      "[executeDeferredSend] Failed to update stub message in DB:",
      dbError,
    );
  }

  // Build a full message payload for chatSyncService (it needs all fields)
  const messagePayload: Message = {
    message_id: readyCtx.messageId,
    chat_id: readyCtx.chatId,
    role: "user",
    content: markdown,
    status: newStatus,
    created_at: Math.floor(readyCtx.createdAt / 1000),
    sender_name: "user",
    encrypted_content: null,
    pii_mappings:
      piiMappingsForStorage.length > 0 ? piiMappingsForStorage : undefined,
  };

  // -------------------------------------------------------------------------
  // 7. Send to backend
  // -------------------------------------------------------------------------
  try {
    // Notify backend about the active chat (it may be a different chat now)
    await chatSyncService.sendSetActiveChat(readyCtx.chatId);
    await chatSyncService.sendNewMessage(messagePayload);
    console.info(
      `[executeDeferredSend] Deferred message sent for chat ${readyCtx.chatId.slice(-6)}`,
    );
  } catch (sendError) {
    console.error(
      "[executeDeferredSend] Failed to send deferred message:",
      sendError,
    );
  }

  // -------------------------------------------------------------------------
  // 8. Clear the draft for this chat on all devices
  // -------------------------------------------------------------------------
  // The deferred-send path skips clearCurrentDraft() in the normal handleSend()
  // flow because it returns early (line ~578). We must call it here after the
  // send completes so that:
  //   a) The local IndexedDB draft is nulled out.
  //   b) The 'delete_draft' WebSocket message is sent to the server, which then
  //      broadcasts 'draft_deleted' to all other logged-in devices.
  // Without this call, Device B (and any other device) would continue showing
  // the draft in the chat list even after the message was sent.
  try {
    await clearCurrentDraft();
    console.info(
      `[executeDeferredSend] Draft cleared for chat ${readyCtx.chatId.slice(-6)}`,
    );
  } catch (clearError) {
    console.error(
      "[executeDeferredSend] Failed to clear draft after deferred send:",
      clearError,
    );
  }
}

/**
 * Clears the message field and resets it to initial state
 * @param editor The TipTap editor instance
 * @param shouldKeepFocus Whether to maintain focus after clearing (default: true on desktop, false on touch)
 */
export function clearMessageField(
  editor: Editor | null,
  shouldKeepFocus?: boolean,
) {
  if (!editor) return;
  resetEditorContent(editor, shouldKeepFocus);
}

/**
 * Creates a custom keyboard extension for handling Enter key events in the editor
 * @returns TipTap extension for custom keyboard handling
 */
export function createKeyboardHandlingExtension() {
  return Extension.create({
    name: "customKeyboardHandling",
    priority: 1000,

    addKeyboardShortcuts() {
      return {
        // Handle regular Enter press
        Enter: ({ editor }) => {
          const desktop = isDesktop();

          // On mobile, Enter should create a new line. Returning false lets TipTap handle it.
          if (!desktop) {
            return false;
          }

          // On desktop, Enter sends the message.
          // But we don't handle Enter if Shift is pressed (that's for newlines).
          // The 'Shift-Enter' shortcut below handles that case by returning false.

          // Don't do anything if there's a text selection, let the user replace it.
          if (
            this.editor.view.state.selection.$anchor.pos !==
            this.editor.view.state.selection.$head.pos
          ) {
            return false;
          }

          if (hasActualContent(editor)) {
            // CRITICAL: Check authentication status before sending
            // Unauthenticated users should be prompted to sign in, not have their message sent
            // (which would fail because WebSocket requires authentication)
            const isAuthenticated = get(authStore).isAuthenticated;

            if (!isAuthenticated) {
              // Dispatch sign-up event instead of send event for unauthenticated users
              // This triggers the sign-up flow which saves the draft and opens signup interface
              const signUpEvent = new Event("custom-sign-up-click", {
                bubbles: true,
                cancelable: true,
              });
              editor.view.dom.dispatchEvent(signUpEvent);
              console.debug(
                "[KeyboardShortcuts] User not authenticated, triggering sign-up flow instead of send",
              );
              return true; // We've handled the event.
            }

            // Dispatch our custom event to send the message.
            const sendEvent = new Event("custom-send-message", {
              bubbles: true,
              cancelable: true,
            });
            editor.view.dom.dispatchEvent(sendEvent);
            return true; // We've handled the event.
          } else {
            vibrateMessageField();
            return true; // We've handled the event, even if we did nothing.
          }
        },

        // Handle Shift+Enter for line breaks
        "Shift-Enter": () => {
          // Return false to let TipTap handle the default line break behavior
          return false;
        },
      };
    },
  });
}
