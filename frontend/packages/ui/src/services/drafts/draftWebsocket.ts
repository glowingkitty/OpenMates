import { get } from "svelte/store";
import { chatDB } from "../db";
import { webSocketService } from "../websocketService";
import { chatMetadataCache } from "../chatMetadataCache";
import type { Chat, TiptapJSON } from "../../types/chat"; // Adjusted path, TiptapJSON might be from here or draftTypes
import { getInitialContent } from "../../components/enter_message/utils"; // Adjusted path
import { draftEditorUIState } from "./draftState"; // Renamed store
import { decryptWithMasterKey } from "../cryptoService"; // Import decryption
import { parse_message } from "../../message_parsing/parse_message"; // Import parser
import type {
  DraftEditorState, // Renamed type
  ServerChatDraftUpdatedEventPayload, // Updated payload type
  DraftConflictPayload,
  ChatDetailsServerResponse, // Added for specific server response type
} from "./draftTypes";
import { LOCAL_CHAT_LIST_CHANGED_EVENT } from "./draftConstants";
import { getEditorInstance } from "./draftCore";

// --- WebSocket Handlers ---

const handleDraftUpdated = async (
  payload: ServerChatDraftUpdatedEventPayload,
) => {
  // Use get for synchronous access to avoid async issues within update
  const currentEditorState = get(draftEditorUIState);

  if (!currentEditorState) {
    console.error(
      "[DraftService] Could not get current draft editor state in handleDraftUpdated.",
    );
    return;
  }

  const { chat_id, data, versions, last_edited_overall_timestamp } = payload;
  const { encrypted_draft_md } = data;
  const { draft_v: newUserDraftVersion } = versions; // Corrected: ChatComponentVersions uses draft_v

  console.info(
    `[DraftService] Received chat_draft_updated for chat_id: ${chat_id}. New version: ${newUserDraftVersion}. Payload:`,
    payload,
  );

  let dbOperationSuccess = false;

  // Update the user's draft directly within the Chat object in IndexedDB
  try {
    const chat = await chatDB.getChat(chat_id);
    if (chat) {
      chat.encrypted_draft_md = encrypted_draft_md; // from payload.data
      // Note: encrypted_draft_preview is not included in ServerChatDraftUpdatedEventPayload
      // It will be generated/updated separately if needed
      chat.draft_v = newUserDraftVersion; // from payload.versions (corrected)
      // CRITICAL: Don't update last_edited_overall_timestamp from draft updates
      // Only messages should update this timestamp for proper sorting
      // Chats with drafts will appear at the top via sorting logic, but won't affect message-based sorting
      // chat.last_edited_overall_timestamp = last_edited_overall_timestamp; // REMOVED
      chat.updated_at = last_edited_overall_timestamp; // Keep updated_at for internal tracking

      await chatDB.updateChat(chat);
      console.info(
        `[DraftService] Updated chat ${chat_id} with new draft in DB. Version: ${newUserDraftVersion}`,
      );
      // Invalidate metadata cache since draft content changed
      chatMetadataCache.invalidateChat(chat_id);
      dbOperationSuccess = true;
    } else {
      console.warn(
        `[DraftService] Chat ${chat_id} not found in DB to update draft from WebSocket.`,
      );
      // If the chat doesn't exist, we cannot update its draft.
      // This might indicate a race condition or an issue where a draft update arrives for a deleted/non-existent chat.
    }
  } catch (dbError) {
    console.error(
      `[DraftService] Error updating chat with draft in DB for chat ${chat_id}:`,
      dbError,
    );
  }

  // Relevance Check: Is this update for the draft currently being edited in the UI?
  if (currentEditorState.currentChatId === chat_id) {
    console.info(
      `[DraftService] Confirmed update for current draft UI (chat_id: ${chat_id}). New version: ${newUserDraftVersion}`,
    );

    // Update the Svelte store state for the editor UI
    draftEditorUIState.update((currentState) => {
      // Check relevance again in case state changed during async DB ops
      if (currentState.currentChatId === chat_id) {
        const newState: DraftEditorState = {
          ...currentState,
          currentUserDraftVersion: newUserDraftVersion, // Use newUserDraftVersion from payload
          hasUnsavedChanges: false, // Mark changes as saved/confirmed from server
        };
        console.debug(
          "[DraftService] draftEditorUIState WILL BE UPDATED. Chat ID:",
          chat_id,
          "New State:",
          newState,
        );
        return newState;
      }
      console.warn(
        `[DraftService] Editor state changed during async DB op for chat_draft_updated. Ignoring UI state update. Payload:`,
        payload,
      );
      return currentState;
    });

    // Optionally, update the Tiptap editor instance directly if it's the active chat
    // This is usually handled by reactive Svelte bindings to the draft content store,
    // but if direct manipulation is needed:
    const editorInstance = getEditorInstance();
    if (editorInstance && editorInstance.isEditable) {
      // Decrypt the draft content first
      let decryptedDraftContent: TiptapJSON | null = null;
      if (encrypted_draft_md) {
        try {
          const decryptedMarkdown =
            await decryptWithMasterKey(encrypted_draft_md);
          if (decryptedMarkdown) {
            // Parse markdown back to TipTap JSON
            decryptedDraftContent = parse_message(decryptedMarkdown, "write", {
              unifiedParsingEnabled: true,
            });
          }
        } catch (error) {
          console.error(
            "[DraftService] Error decrypting draft content for editor update:",
            error,
          );
        }
      }

      // Check if editor content needs updating (e.g., if this update came from another device)
      const currentEditorContent = editorInstance.getJSON();
      if (
        JSON.stringify(currentEditorContent) !==
        JSON.stringify(decryptedDraftContent)
      ) {
        console.debug(
          `[DraftService] Updating Tiptap editor content for active chat ${chat_id} from WebSocket.`,
        );
        editorInstance
          .chain()
          .setContent(decryptedDraftContent || getInitialContent(), false)
          .run();
      }
    }
  } else {
    // Update is for a non-active chat (e.g., updated on another device by this same user)
    console.info(
      `[DraftService] Received chat_draft_updated for non-active chat (chat_id: ${chat_id}). DB already updated.`,
    );
  }

  if (dbOperationSuccess) {
    console.debug(
      "[DraftService] Dispatching local chat list changed event after handling chat_draft_updated WS.",
    );
    // This event might trigger UI refresh for chat list items if they display draft snippets.
    window.dispatchEvent(
      new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail: { chat_id } }),
    );
  }
};

const handleDraftConflict = (payload: DraftConflictPayload) => {
  // payload.chat_id is the server's composite ID
  draftEditorUIState.update((currentState) => {
    console.warn(
      `[DraftService] Received draft_conflict event. Server Chat ID: ${payload.chat_id}`,
    );

    // Only handle if conflict is for the current draft (match by chat_id)
    if (currentState.currentChatId === payload.chat_id) {
      console.error(
        `[DraftService] Draft conflict for current draft (Chat ID: ${payload.chat_id}). Fetching latest state...`,
      );
      // Server expects the composite chat_id to fetch details
      if (payload.chat_id) {
        webSocketService.sendMessage("get_chat_details", {
          chat_id: payload.chat_id,
        });
      } else {
        // This case should ideally not happen if server sends composite chat_id on conflict
        console.error(
          "[DraftService] Cannot fetch chat details for conflict: Server composite chat_id missing in payload.",
        );
      }
      return currentState; // Keep current state, handleChatDetails will update
    } else {
      console.info(
        `[DraftService] Received draft_conflict for different context (current: ${currentState.currentChatId}, conflict: ${payload.chat_id}). Ignoring.`,
      );
      return currentState;
    }
  });
};

// Handler for receiving full chat details after conflict or other request
const handleChatDetails = async (payload: ChatDetailsServerResponse) => {
  // Changed Chat to ChatDetailsServerResponse
  console.info(`[DraftService] Received chat_details:`, payload); // payload is of type ChatDetailsServerResponse
  let dbOperationSuccess = false;
  try {
    // The payload for 'chat_details' might still be based on the old 'Chat' type.
    // We need to adapt it to the new structure: separate Chat and UserChatDraft.

    // 1. Update Chat entity in IndexedDB, including draft fields
    // Decrypt title if present
    const decryptedTitle = payload.encrypted_title
      ? await decryptWithMasterKey(payload.encrypted_title)
      : null;

    const chatToUpdate: Chat = {
      chat_id: payload.chat_id,
      title: decryptedTitle,
      encrypted_title: payload.encrypted_title ?? null,
      messages_v: payload.messages_v ?? 0,
      title_v: payload.title_v ?? 0,
      encrypted_draft_md: payload.encrypted_draft_md, // Encrypted draft content from payload
      draft_v: payload.draft_v ?? 0, // Draft version from payload
      last_edited_overall_timestamp:
        payload.last_edited_overall_timestamp ?? Math.floor(Date.now() / 1000),
      unread_count: payload.unread_count ?? 0,
      created_at: payload.created_at ?? Math.floor(Date.now() / 1000),
      updated_at: payload.updated_at ?? Math.floor(Date.now() / 1000),
    };

    await chatDB.addOrUpdateChatWithFullData(chatToUpdate, []);
    dbOperationSuccess = true;
    console.info(
      `[DraftService] Updated/Added chat ${payload.chat_id} (including draft) in DB from chat_details.`,
    );

    // Section for separate UserChatDraft update is removed as draft is part of Chat object.

    // 2. Update draftEditorUIState and editor if this is the currently active chat
    // Decrypt draft content before the update callback (since callbacks can't be async)
    let decryptedDraftContent: TiptapJSON = getInitialContent();
    if (payload.encrypted_draft_md) {
      try {
        const decryptedMarkdown = await decryptWithMasterKey(
          payload.encrypted_draft_md,
        );
        if (decryptedMarkdown) {
          // Parse markdown back to TipTap JSON
          decryptedDraftContent = parse_message(decryptedMarkdown, "write", {
            unifiedParsingEnabled: true,
          });
        }
      } catch (error) {
        console.error(
          "[DraftService] Error decrypting draft content from chat_details:",
          error,
        );
      }
    }

    draftEditorUIState.update((currentState) => {
      if (currentState.currentChatId === payload.chat_id) {
        console.info(
          `[DraftService] Updating current draft context with fetched details for chat ${payload.chat_id}`,
        );
        const editorInstance = getEditorInstance();
        if (editorInstance) {
          console.debug(
            "[DraftService] Setting editor content from chat_details:",
            decryptedDraftContent,
          );
          editorInstance.chain().setContent(decryptedDraftContent, false).run();
          // Do NOT auto-focus the editor - user must manually click to focus
          // This prevents unwanted focus when receiving draft updates from websocket
          console.debug(
            "[DraftService] Skipped auto-focus after websocket draft update - user must click to focus",
          );
        }
        return {
          ...currentState,
          currentUserDraftVersion: payload.draft_v ?? 0, // Use user's draft version
          hasUnsavedChanges: false,
        };
      }
      return currentState;
    });
  } catch (error) {
    console.error("[DraftService] Error handling chat_details:", error);
  }

  // Dispatch event after successful DB operation from WS handler
  if (dbOperationSuccess) {
    console.debug(
      "[DraftService] Dispatching local chat list changed event after handling chat_details WS message.",
    );
    window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT));
  }
};

let handleWsOpen: (() => void) | null = null;
let handlersRegistered = false; // Prevent duplicate registration

/**
 * Handle the 'draft_versions_response' message sent by the server after a
 * 'get_draft_versions' request. Compares server-side draft_v for each chat
 * against the local IndexedDB value. If the server reports draft_v == 0 for a
 * chat that has a local draft, the draft was deleted on another device while
 * this device was offline — clear it locally.
 *
 * This is the core of reconnect-reconciliation: it ensures that sent messages
 * (which delete the draft on the server) propagate back to devices that were
 * offline when the deletion happened.
 */
const handleDraftVersionsResponse = async (payload: {
  versions: Record<string, number>;
}) => {
  const versions = payload?.versions;
  if (!versions || typeof versions !== "object") {
    console.warn(
      "[DraftService] draft_versions_response: invalid payload",
      payload,
    );
    return;
  }

  const chatIdsToReconcile = Object.keys(versions);
  if (chatIdsToReconcile.length === 0) return;

  console.info(
    `[DraftService] draft_versions_response: reconciling ${chatIdsToReconcile.length} chat(s).`,
  );

  let anyCleared = false;

  for (const chat_id of chatIdsToReconcile) {
    const serverDraftV = versions[chat_id] ?? 0;

    if (serverDraftV !== 0) {
      // Server still has a draft (or a newer one). The normal sync flow
      // (initial_sync / phased_sync) will handle delivering updated content.
      // We do not need to act here.
      continue;
    }

    // Server says draft_v == 0 → the draft was deleted (e.g., message was sent
    // on another device while this one was offline). Clear the local draft.
    try {
      const chat = await chatDB.getChat(chat_id);
      if (chat && chat.encrypted_draft_md) {
        // Only clear if we actually have a local draft (avoid no-op writes)
        chat.encrypted_draft_md = null;
        chat.encrypted_draft_preview = null;
        chat.draft_v = 0;
        chat.updated_at = Math.floor(Date.now() / 1000);

        await chatDB.updateChat(chat);
        chatMetadataCache.invalidateChat(chat_id);
        anyCleared = true;

        console.info(
          `[DraftService] Cleared stale local draft for chat ${chat_id} ` +
            `(server draft_v=0, was offline when draft was deleted).`,
        );
      }
    } catch (err) {
      console.error(
        `[DraftService] Error clearing stale draft for chat ${chat_id}:`,
        err,
      );
    }
  }

  if (anyCleared) {
    // Refresh the chat list so the "Draft: …" labels disappear immediately.
    window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT));
  }
};

export function registerWebSocketHandlers() {
  // CRITICAL FIX: Prevent duplicate handler registration
  // This can happen due to HMR (Hot Module Reload) during development
  // or multiple instances being created accidentally
  if (handlersRegistered) {
    console.warn(
      "[DraftService] Handlers already registered, skipping duplicate registration",
    );
    return;
  }

  handlersRegistered = true;
  console.info("[DraftService] Registering WebSocket handlers.");
  webSocketService.on("draft_updated", handleDraftUpdated);
  webSocketService.on("draft_conflict", handleDraftConflict);
  webSocketService.on("chat_details", handleChatDetails);
  webSocketService.on("draft_versions_response", handleDraftVersionsResponse);

  // Listen for WebSocket reconnect/open and re-sync current draft.
  // On reconnect we do two things:
  //   1. Request latest details for the currently visible chat (existing behaviour).
  //   2. Reconcile all chats with a local draft by asking the server for their
  //      current draft_v. Any chat where the server says draft_v==0 had its draft
  //      deleted on another device while this device was offline — we clear it locally.
  handleWsOpen = async () => {
    const state = get(draftEditorUIState); // Use renamed store

    // ── 1. Refresh the currently active chat ────────────────────────────────
    if (state.currentChatId) {
      try {
        console.info(
          `[DraftService] WebSocket reconnected. Requesting latest details for active chat: ${state.currentChatId}`,
        );
        webSocketService.sendMessage("get_chat_details", {
          chat_id: state.currentChatId,
        });
      } catch (error) {
        console.error(
          `[DraftService] Error processing active chat ${state.currentChatId} on WebSocket open:`,
          error,
        );
      }
    }

    // ── 2. Draft reconciliation for all locally-drafty chats ────────────────
    // Collect all chats that have a local draft (encrypted_draft_md != null).
    // Ask the server for the current draft_v of each. The response handler
    // (handleDraftVersionsResponse) will clear any whose server draft_v is 0.
    try {
      // OPE-216: Prefer in-memory cache to avoid redundant IDB reads on reconnect.
      // Fall back to IDB only if cache is empty (cold boot / first load).
      const { chatListCache } = await import("../chatListCache");
      const allChats =
        chatListCache.getCache() ?? (await chatDB.getAllChats());
      const draftyChats = allChats.filter(
        (c) => c.encrypted_draft_md && (c.draft_v ?? 0) > 0,
      );

      if (draftyChats.length > 0) {
        const chatVersionsPayload = draftyChats.map((c) => ({
          chat_id: c.chat_id,
          client_draft_v: c.draft_v ?? 0,
        }));

        console.info(
          `[DraftService] WebSocket reconnected. Sending get_draft_versions ` +
            `for ${draftyChats.length} locally-drafty chat(s) to reconcile stale drafts.`,
        );
        webSocketService.sendMessage("get_draft_versions", {
          chats: chatVersionsPayload,
        });
      }
    } catch (reconError) {
      // Non-critical — if reconciliation fails, the UI will self-heal on next
      // phased_sync or when the user navigates to the affected chat.
      console.error(
        "[DraftService] Error during reconnect draft reconciliation:",
        reconError,
      );
    }
  };
  webSocketService.on("open", handleWsOpen);
}

export function unregisterWebSocketHandlers() {
  if (!handlersRegistered) {
    // Handlers were never registered, nothing to clean up
    return;
  }

  handlersRegistered = false;
  console.info("[DraftService] Unregistering WebSocket handlers.");
  webSocketService.off("draft_updated", handleDraftUpdated);
  webSocketService.off("draft_conflict", handleDraftConflict);
  webSocketService.off("chat_details", handleChatDetails);
  webSocketService.off("draft_versions_response", handleDraftVersionsResponse);
  if (handleWsOpen) {
    webSocketService.off("open", handleWsOpen);
    handleWsOpen = null;
  }
}
