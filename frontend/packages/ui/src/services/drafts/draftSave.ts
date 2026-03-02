import { debounce, isEqual } from "lodash-es"; // Import isEqual
import { get } from "svelte/store";
import { chatDB } from "../db";
import { webSocketService } from "../websocketService";
import {
  websocketStatus,
  type WebSocketStatus,
} from "../../stores/websocketStatusStore";
import type { Chat, TiptapJSON, OfflineChange } from "../../types/chat";
import { draftEditorUIState, initialDraftEditorState } from "./draftState"; // Renamed import
import { LOCAL_CHAT_LIST_CHANGED_EVENT } from "./draftConstants";
import { getEditorInstance, clearEditorAndResetDraftState } from "./draftCore";
import { chatSyncService } from "../chatSyncService"; // Import the new service
import { tipTapToCanonicalMarkdown } from "../../message_parsing/serializers"; // Import markdown converter
import { encryptWithMasterKey, decryptWithMasterKey } from "../cryptoService"; // Import encryption functions
import { extractUrlFromJsonEmbedBlock } from "../../components/enter_message/services/urlMetadataService"; // For URL extraction
import { chatMetadataCache } from "../chatMetadataCache"; // For cache invalidation
import { authStore } from "../../stores/authStore"; // Import auth store to check authentication status
import { isPublicChat } from "../../demo_chats/convertToChat"; // Import to detect demo/legal chats
import {
  saveSessionStorageDraft,
  deleteSessionStorageDraft,
  getSessionStorageDraftPreview,
} from "./sessionStorageDraftService"; // Import sessionStorage draft service
import { modelsMetadata } from "../../data/modelsMetadata"; // For model name lookup
import { matesMetadata } from "../../data/matesMetadata"; // For mate name lookup
import { appSkillsStore } from "../../stores/appSkillsStore"; // For skill/focus/memory name lookup

/**
 * Convert a name to hyphenated format for mention display.
 * e.g., "Claude 4.5 Opus" -> "Claude-4.5-Opus"
 */
function toHyphenatedName(name: string): string {
  return name.replace(/\s+/g, "-");
}

/**
 * Capitalize first letter of each word for display.
 * e.g., "get-docs" -> "Get-Docs"
 */
function capitalizeWords(str: string): string {
  return str
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join("-");
}

/**
 * Convert backend mention syntax to human-readable display names.
 * This ensures draft previews show "@Claude-4.5-Opus" instead of "@ai-model:claude-4-sonnet"
 *
 * Supported mention formats:
 * - @ai-model:{model_id} -> @Model-Name (e.g., @Claude-4.5-Opus)
 * - @mate:{mate_id} -> @MateName (e.g., @Sophia)
 * - @skill:{app_id}:{skill_id} -> @App-Skill-Name (e.g., @Code-Get-Docs)
 * - @focus:{app_id}:{focus_id} -> @App-Focus-Name (e.g., @Web-Research)
 * - @memory:{app_id}:{memory_id}:{type} -> @App-Memory-Name (e.g., @Code-Projects)
 */
function convertMentionSyntaxToDisplayName(text: string): string {
  // Replace @ai-model:{id} with @Model-Name
  text = text.replace(/@ai-model:([^\s]+)/g, (match, modelId) => {
    const model = modelsMetadata.find((m) => m.id === modelId);
    if (model) {
      return `@${toHyphenatedName(model.name)}`;
    }
    return match; // Keep original if model not found
  });

  // Replace @mate:{id} with @MateName
  text = text.replace(/@mate:([^\s]+)/g, (match, mateId) => {
    const mate = matesMetadata.find((m) => m.id === mateId);
    if (mate) {
      // Use first search name (the actual name like "Sophia")
      const displayName = capitalizeWords(mate.search_names[0] || mate.id);
      return `@${displayName}`;
    }
    return match; // Keep original if mate not found
  });

  // Replace @skill:{app_id}:{skill_id} with @App-Skill-Name
  text = text.replace(/@skill:([^:]+):([^\s]+)/g, (match, appId, skillId) => {
    const apps = appSkillsStore.apps;
    const app = apps[appId];
    if (app) {
      const skill = app.skills.find((s) => s.id === skillId);
      if (skill) {
        const appDisplayName = capitalizeWords(appId);
        const skillDisplayName = capitalizeWords(skillId.replace(/_/g, "-"));
        return `@${appDisplayName}-${skillDisplayName}`;
      }
    }
    return match; // Keep original if not found
  });

  // Replace @focus:{app_id}:{focus_id} with @App-Focus-Name
  text = text.replace(/@focus:([^:]+):([^\s]+)/g, (match, appId, focusId) => {
    const apps = appSkillsStore.apps;
    const app = apps[appId];
    if (app) {
      const focusMode = app.focus_modes.find((f) => f.id === focusId);
      if (focusMode) {
        const appDisplayName = capitalizeWords(appId);
        const focusDisplayName = capitalizeWords(focusId.replace(/_/g, "-"));
        return `@${appDisplayName}-${focusDisplayName}`;
      }
    }
    return match; // Keep original if not found
  });

  // Replace @memory:{app_id}:{memory_id}:{type} with @App-Memory-Name
  text = text.replace(
    /@memory:([^:]+):([^:]+):([^\s]+)/g,
    (match, appId, memoryId) => {
      const apps = appSkillsStore.apps;
      const app = apps[appId];
      if (app) {
        const memory = app.settings_and_memories.find((m) => m.id === memoryId);
        if (memory) {
          const appDisplayName = capitalizeWords(appId);
          const memoryDisplayName = capitalizeWords(
            memoryId.replace(/_/g, "-"),
          );
          return `@${appDisplayName}-${memoryDisplayName}`;
        }
      }
      return match; // Keep original if not found
    },
  );

  return text;
}

/**
 * Generate a preview text from markdown content for chat list display
 * This mirrors the logic in Chat.svelte's extractDisplayTextFromMarkdown function
 * @param markdown The markdown content to generate a preview from
 * @param maxLength Maximum length of the preview (default: 100 characters)
 * @returns Truncated preview text suitable for display
 */
/**
 * Convert a single TipTap embed node to a human-readable token for display.
 * Returns a token like "[Image]", "[Video]", "[Location]", etc.
 *
 * For nodes with contentRef (already stored in EmbedStore), the type is derived
 * from the embed reference JSON. For unserialized nodes (still uploading / demo mode),
 * the type comes from the node's attrs.type field.
 */
function embedNodeToDisplayToken(attrs: Record<string, unknown>): string {
  const type = (attrs.type as string) ?? "";
  const contentRef = attrs.contentRef as string | null | undefined;

  if (contentRef?.startsWith("embed:")) {
    // Serialized embed — type is already known from attrs
    // Map internal type names to user-facing tokens
    if (type === "web-website") return "[Website]";
    if (type === "videos-video") return "[Video]";
    if (type === "code-code") return "[Code]";
    if (type === "maps") return "[Location]";
    if (type === "image") return "[Image]";
    if (type === "audio") return "[Audio]";
    if (type === "recording") return "[Recording]";
    if (type === "pdf") return "[PDF]";
    if (type === "file") return "[File]";
    if (type === "book") return "[Book]";
    if (type) return `[${type}]`;
  } else {
    // Unserialized embed (still uploading, demo mode, or no contentRef yet)
    // Also covers preview embeds (contentRef starts with "preview:") which
    // are created for unauthenticated users — these share the same type values
    // as serialized embeds (e.g. "code-code"), so we handle both here.
    if (type === "image") return "[Image]";
    if (type === "audio") return "[Audio]";
    if (type === "recording") return "[Recording]";
    if (type === "videos-video") return "[Video]";
    if (type === "pdf") return "[PDF]";
    if (type === "file") return "[File]";
    if (type === "code" || type === "code-code") return "[Code]";
    if (type === "book") return "[Book]";
    if (type) return `[${type}]`;
  }

  return "";
}

/**
 * Walk a TipTap JSON document in document order and produce a flat array of
 * preview tokens — preserving the exact sequence of text and embeds as the user
 * composed them. This is the single source of truth for draft preview generation.
 *
 * WHY: The previous approach serialised TipTap → markdown (which drops unserialized
 * embeds such as uploading images that have no contentRef), then appended embed tokens
 * at the END. This broke the order: "[Image] [Image] [Image] describe the images"
 * would render as "describe the images [Image] [Image] [Image]" in the chat list.
 *
 * This function fixes the problem by walking the document tree in order and emitting
 * tokens for both text content and embeds at their correct positions.
 */
function buildPreviewTokensFromTiptap(doc: unknown): string[] {
  if (!doc || typeof doc !== "object") return [];
  const root = doc as Record<string, unknown>;
  const tokens: string[] = [];

  // Process a paragraph node: walk its children in order
  function processParagraph(node: Record<string, unknown>) {
    const children =
      (node.content as Record<string, unknown>[] | undefined) ?? [];
    for (const child of children) {
      const childType = child.type as string;

      if (childType === "text") {
        // Collect text, applying mention conversion
        const rawText = (child.text as string) ?? "";
        const converted = convertMentionSyntaxToDisplayName(rawText);
        if (converted.trim()) tokens.push(converted.trim());
      } else if (childType === "embed") {
        // Embed inside a paragraph (inline embed) — emit a token
        const attrs = (child.attrs ?? {}) as Record<string, unknown>;
        const token = embedNodeToDisplayToken(attrs);
        if (token) tokens.push(token);
      } else if (childType === "aiModelMention") {
        // @ai-model mention nodes — look up the human-readable model name
        const attrs = (child.attrs ?? {}) as Record<string, unknown>;
        const modelId = (attrs.modelId as string) ?? "";
        // Use the already-imported modelsMetadata (imported at the top of draftSave.ts)
        const model = modelsMetadata.find((m) => m.id === modelId);
        if (model) {
          tokens.push(`@${model.name.replace(/\s+/g, "-")}`);
        } else if (modelId) {
          tokens.push(`@ai-model:${modelId}`);
        }
      } else if (childType === "mate") {
        const attrs = (child.attrs ?? {}) as Record<string, unknown>;
        const mateName = (attrs.name as string) ?? "";
        if (mateName) tokens.push(`@${mateName}`);
      } else if (childType === "genericMention") {
        const attrs = (child.attrs ?? {}) as Record<string, unknown>;
        const syntax = (attrs.mentionSyntax as string) ?? "";
        // Convert mention syntax to display name (e.g. @skill:app:id → @App-Skill)
        if (syntax) tokens.push(convertMentionSyntaxToDisplayName(syntax));
      } else if (childType === "hardBreak") {
        // Treat a hard break as a space between tokens
        tokens.push(" ");
      }
    }
  }

  // Walk top-level nodes in document order
  const topLevel =
    (root.content as Record<string, unknown>[] | undefined) ?? [];
  for (const node of topLevel) {
    const nodeType = node.type as string;

    if (nodeType === "paragraph") {
      processParagraph(node);
    } else if (nodeType === "embed") {
      // Top-level embed (shouldn't be common but handle defensively)
      const attrs = (node.attrs ?? {}) as Record<string, unknown>;
      const token = embedNodeToDisplayToken(attrs);
      if (token) tokens.push(token);
    } else if (nodeType === "heading") {
      // Extract text from headings
      const children =
        (node.content as Record<string, unknown>[] | undefined) ?? [];
      const text = children
        .filter((c) => c.type === "text")
        .map((c) => (c.text as string) ?? "")
        .join("")
        .trim();
      if (text) tokens.push(text);
    } else if (nodeType === "bulletList" || nodeType === "orderedList") {
      // Extract first item text from lists for preview
      const items =
        (node.content as Record<string, unknown>[] | undefined) ?? [];
      for (const item of items) {
        const itemChildren =
          (item.content as Record<string, unknown>[] | undefined) ?? [];
        for (const child of itemChildren) {
          if (child.type === "paragraph") {
            processParagraph(child);
          }
        }
      }
    } else if (nodeType === "blockquote") {
      // Extract text from blockquotes
      const children =
        (node.content as Record<string, unknown>[] | undefined) ?? [];
      for (const child of children) {
        if ((child as Record<string, unknown>).type === "paragraph") {
          processParagraph(child as Record<string, unknown>);
        }
      }
    }
    // Code blocks (codeBlock nodes) are skipped intentionally —
    // the serialized markdown representation handles them in the fallback path.
  }

  return tokens;
}

/**
 * Apply code-block and embed-reference replacements to a markdown string,
 * returning a human-readable preview line. Used as fallback when no TipTap JSON
 * is available, and to handle serialized embed references (json/json_embed blocks)
 * that the document-order walk converts via embedNodeToDisplayToken.
 */
function processMarkdownForPreview(markdown: string): string {
  let displayText = convertMentionSyntaxToDisplayName(markdown);

  // Replace legacy json_embed code blocks with their URLs
  displayText = displayText.replace(
    /```json_embed\n([\s\S]*?)\n```/g,
    (match) => {
      const url = extractUrlFromJsonEmbedBlock(match);
      return url ? ` ${url} ` : match;
    },
  );

  // Replace serialized embed reference blocks (```json\n{...}\n```) with tokens
  displayText = displayText.replace(
    /```json\n([\s\S]*?)\n```/g,
    (match, jsonContent) => {
      try {
        const parsed = JSON.parse(jsonContent.trim());
        const type = parsed?.type;
        if (type === "location") return " [Location] ";
        if (type === "video") return " [Video] ";
        if (type === "website") return " [Website] ";
        if (type === "image") return " [Image] ";
        if (type === "code") return " [Code] ";
        if (type) return ` [${type}] `;
      } catch {
        // Not valid JSON — fall through
      }
      return match;
    },
  );

  // Replace remaining code blocks with a placeholder
  displayText = displayText.replace(
    /```(\w*)\n([\s\S]*?)\n```/g,
    (match, language, codeContent) => {
      const trimmedCode = codeContent.trim();
      if (trimmedCode) {
        const firstLine = trimmedCode.split("\n")[0].trim();
        return ` [Code: ${firstLine.substring(0, 30)}${firstLine.length > 30 ? "..." : ""}] `;
      }
      return language ? ` [${language} code] ` : " [code] ";
    },
  );

  return displayText;
}

function generateDraftPreview(
  markdown: string,
  maxLength: number = 100,
  tiptapJSON?: unknown,
): string {
  // CRITICAL: When TipTap JSON is available, always use a document-order walk to build
  // the preview. This is the ONLY way to guarantee that embeds and text appear in the
  // correct order in the chat list. The previous approach (markdown → text, then append
  // embed tokens) broke order: images uploaded before text would appear AFTER the text
  // in the preview, e.g. "[Image] [Image] describe it" → "describe it [Image] [Image]".
  if (tiptapJSON) {
    try {
      const tokens = buildPreviewTokensFromTiptap(tiptapJSON);
      if (tokens.length === 0) return "";

      // Join tokens with a single space and clean up whitespace
      const cleanedText = tokens.join(" ").replace(/\s+/g, " ").trim();
      if (!cleanedText) return "";

      return cleanedText.length > maxLength
        ? cleanedText.substring(0, maxLength) + "..."
        : cleanedText;
    } catch (error) {
      console.error(
        "[DraftService] Error building preview from TipTap JSON, falling back to markdown:",
        error,
      );
      // Fall through to markdown-based fallback below
    }
  }

  // Fallback: markdown-only path (used when no TipTap JSON is provided,
  // e.g. when reading encrypted drafts from the database without the live editor).
  if (!markdown) return "";

  try {
    const displayText = processMarkdownForPreview(markdown);
    const cleanedText = displayText.replace(/\s+/g, " ").trim();
    return cleanedText.length > maxLength
      ? cleanedText.substring(0, maxLength) + "..."
      : cleanedText;
  } catch (error) {
    console.error("[DraftService] Error generating draft preview:", error);
    return markdown.length > maxLength
      ? markdown.substring(0, maxLength) + "..."
      : markdown;
  }
}

/**
 * Deletes the draft for the current chat and, if the chat becomes empty (no messages),
 * deletes the chat as well. Handles local DB operations and server communication.
 */
export async function clearCurrentDraft() {
  // Export this function
  const editor = getEditorInstance(); // Keep reference to editor for the finally block
  if (!getEditorInstance()) {
    // Check against the live getter in case it's cleared elsewhere
    console.error(
      "[DraftService] Cannot clear/delete draft, editor instance not available at start.",
    );
    // If no editor, can't do much with it, but might still proceed with DB ops if chatId is known
  }

  const isAuthenticated = get(authStore).isAuthenticated;
  const currentState = get(draftEditorUIState);
  const currentChatId = currentState.currentChatId;

  if (!currentChatId) {
    console.info(
      "[DraftService] No current chat ID to clear/delete draft for.",
    );
    if (editor)
      clearEditorAndResetDraftState(false); // Reset editor if it exists
    else draftEditorUIState.set(initialDraftEditorState); // Else, just reset state
    return;
  }

  // CRITICAL: Handle non-authenticated users with sessionStorage
  if (!isAuthenticated) {
    console.info(
      `[DraftService] Deleting sessionStorage draft for chat ID: ${currentChatId}`,
    );
    deleteSessionStorageDraft(currentChatId);

    // Update state
    draftEditorUIState.update((s) => ({
      ...s,
      currentUserDraftVersion: 0,
      hasUnsavedChanges: false,
      lastSavedContentMarkdown: null,
    }));

    // Dispatch event for UI updates
    window.dispatchEvent(
      new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
        detail: { chat_id: currentChatId, draftDeleted: true },
      }),
    );

    // Clear editor content
    if (editor) {
      editor.chain().clearContent(false).run();
    }

    return; // Exit early for non-authenticated users
  }

  console.info(
    `[DraftService] Attempting to delete draft for chat ID: ${currentChatId}`,
  );

  try {
    // 1. Check if a draft actually exists before attempting to delete.
    const chatBeforeDraftDeletion = await chatDB.getChat(currentChatId);

    if (
      chatBeforeDraftDeletion &&
      (chatBeforeDraftDeletion.encrypted_draft_md ||
        (chatBeforeDraftDeletion.draft_v &&
          chatBeforeDraftDeletion.draft_v > 0))
    ) {
      console.info(
        `[DraftService] Draft found for chat ${currentChatId}. Requesting deletion via chatSyncService.`,
      );
      // Inform the server to delete the draft
      // chatSyncService.sendDeleteDraft handles online/offline queuing internally
      await chatSyncService.sendDeleteDraft(currentChatId); // This will also dispatch 'chatUpdated' with 'draft_deleted'
    } else {
      console.info(
        `[DraftService] No draft found locally for chat ${currentChatId}. Skipping server deletion call. Will clear local draft state if any.`,
      );
      // Even if no draft to delete on server, ensure local state is clean.
      // chatDB.clearCurrentUserChatDraft will ensure draft_json is null and draft_v is 0 or handled appropriately.
      // This is important if there was a local draft that wasn't synced or if state is inconsistent.
      const clearedChat = await chatDB.clearCurrentUserChatDraft(currentChatId);
      if (clearedChat) {
        console.debug(
          `[DraftService] Optimistically cleared local draft remnants for chat ${currentChatId}`,
        );
        // CRITICAL: Invalidate cache before dispatching event to ensure UI components fetch fresh data
        // This prevents stale draft previews from appearing in the chat list
        chatMetadataCache.invalidateChat(currentChatId);
        console.debug(
          "[DraftService] Invalidated cache for chat:",
          currentChatId,
        );
        // Dispatch an event similar to what sendDeleteDraft would do for UI consistency
        window.dispatchEvent(
          new CustomEvent("chatUpdated", {
            detail: { chat_id: currentChatId, type: "draft_deleted" },
          }),
        );
      }
    }

    // Update UI state for the draft (version, unsaved changes)
    // No need to update currentUserDraftVersion here if the chat context might change or be cleared.
    // If chat remains, its draft is gone. If chat is deleted, context is cleared.
    // hasUnsavedChanges should be false.
    draftEditorUIState.update((s) => {
      if (s.currentChatId === currentChatId) {
        // If the current chat context is still the one whose draft was deleted
        return {
          ...s,
          currentUserDraftVersion: 0,
          hasUnsavedChanges: false,
          lastSavedContentMarkdown: null, // Reset last saved content
        };
      }
      return s; // Otherwise, no change to this specific part of the state
    });

    // Dispatch event for UI lists to update (e.g., remove draft indicator)
    // The 'chatUpdated' event from sendDeleteDraft might cover this, or a more specific one here.
    window.dispatchEvent(
      new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
        detail: { chat_id: currentChatId, draftDeleted: true },
      }),
    );

    // 2. Check if the chat itself should be deleted
    const chat = await chatDB.getChat(currentChatId); // Re-fetch chat state
    // Check if the chat has any messages by fetching them
    const messages = await chatDB.getMessagesForChat(currentChatId);
    if (chat && (!messages || messages.length === 0)) {
      console.info(
        `[DraftService] Chat ${currentChatId} has no messages after draft deletion. Attempting to delete chat.`,
      );

      // Delete from IndexedDB first (also cleans up associated embeds)
      console.debug(
        `[DraftService] Deleting chat from IndexedDB: ${currentChatId}`,
      );
      const { deletedEmbedIds } = await chatDB.deleteChat(currentChatId);
      console.debug(
        `[DraftService] Chat deleted from IndexedDB: ${currentChatId}, cleaned up ${deletedEmbedIds.length} embeds`,
      );

      // Dispatch chatDeleted event AFTER deletion to update UI components
      console.debug(
        `[DraftService] Dispatching chatDeleted event for UI update: ${currentChatId}`,
      );
      chatSyncService.dispatchEvent(
        new CustomEvent("chatDeleted", { detail: { chat_id: currentChatId } }),
      );
      console.debug(
        `[DraftService] chatDeleted event dispatched for chat: ${currentChatId}`,
      );

      // Send delete request to server (includes embed IDs to delete)
      await chatSyncService.sendDeleteChat(currentChatId, deletedEmbedIds);
      console.info(
        `[DraftService] Initiated deletion of empty chat ${currentChatId} with ${deletedEmbedIds.length} embed deletions.`,
      );

      // When chat is deleted, draft state (including currentChatId) should be fully reset.
      // The 'chatDeleted' event handler in UI (e.g., Chats.svelte) should manage selecting a new chat.
      // clearEditorAndResetDraftState will set currentChatId to null.
      clearEditorAndResetDraftState(false);
    } else if (!chat) {
      console.warn(
        `[DraftService] Chat ${currentChatId} was not found after deleting its draft. Ensuring UI is reset.`,
      );
      clearEditorAndResetDraftState(false); // Reset editor and draft UI state
    }
    // If chat exists and has messages, do nothing further to the chat itself.
    // The editor content for this chat should be cleared in the finally block.
  } catch (error) {
    console.error(
      `[DraftService] Error deleting draft or chat for ${currentChatId}:`,
      error,
    );
    draftEditorUIState.update((s) => ({ ...s, hasUnsavedChanges: true }));
  } finally {
    // This block ensures the editor UI is in a consistent state.
    const finalEditorState = get(draftEditorUIState);
    const liveEditorInstance = getEditorInstance(); // Get current editor instance

    if (finalEditorState.currentChatId === currentChatId) {
      // If the context is still the (now draft-less) chat
      if (liveEditorInstance) {
        console.debug(
          `[DraftService] Draft deleted for chat ${currentChatId}, clearing editor content.`,
        );
        liveEditorInstance.chain().clearContent(false).run(); // Clear content
        // Optionally set to an initial placeholder if desired, but clearContent is usually enough
        // liveEditorInstance.chain().setContent(getInitialContent(), false).run();
      }
    } else if (!finalEditorState.currentChatId) {
      // If currentChatId became null (e.g., chat deleted and state reset by clearEditorAndResetDraftState)
      // The editor should have been cleared by clearEditorAndResetDraftState.
      // If liveEditorInstance still exists and is not empty, clear it.
      if (liveEditorInstance && !liveEditorInstance.isEmpty) {
        console.debug(
          "[DraftService] Chat context cleared, ensuring editor is empty.",
        );
        liveEditorInstance.chain().clearContent(false).run();
      }
    }
    // If currentChatId changed to something else, that context switch (setCurrentChatContext) would handle editor content.
  }
}

// Flag: when a save is skipped because another is in-progress, this is set so
// the finally block knows to schedule a follow-up save with the latest content.
// This prevents the race condition where fast typing during a slow save (encryption)
// causes the debounce to fire, get dropped by the isSaveInProgress guard, and the
// latest content is never persisted.
let resaveNeeded = false;

/**
 * Saves the current editor content as a draft.
 * If content is empty, it triggers the modified clearCurrentDraft (which now deletes).
 * Handles local DB update and server communication (online/offline).
 */
export const saveDraftDebounced = debounce(
  async (chatIdFromMessageInput?: string) => {
    const editor = getEditorInstance();
    if (!editor) {
      console.error(
        "[DraftService] Cannot save draft, editor instance not available.",
      );
      return;
    }

    const isAuthenticated = get(authStore).isAuthenticated;
    const currentState = get(draftEditorUIState);

    // Check save lock to prevent duplicate chat creation from concurrent saves.
    // Instead of silently dropping the save (which loses the latest content),
    // set resaveNeeded so the in-progress save's finally block will schedule
    // a follow-up save that captures the current editor state.
    if (currentState.isSaveInProgress) {
      resaveNeeded = true;
      console.debug(
        "[DraftService] Save already in progress, marked resaveNeeded=true so latest content will be saved after current save completes",
      );
      return;
    }

    let currentChatIdForOperation = currentState.currentChatId;

    // CRITICAL: Don't save drafts for incognito chats
    // Check if the current chat is an incognito chat
    if (currentChatIdForOperation) {
      const { incognitoChatService } = await import("../incognitoChatService");
      try {
        const incognitoChat = await incognitoChatService.getChat(
          currentChatIdForOperation,
        );
        if (incognitoChat?.is_incognito) {
          console.debug(
            `[DraftService] Skipping draft save for incognito chat ${currentChatIdForOperation} - drafts are not saved for incognito chats`,
          );
          return; // Don't save drafts for incognito chats
        }
      } catch (error) {
        // Not an incognito chat, continue normally
      }
    }

    // Also check if incognito mode is enabled and we're about to create a new chat
    // In that case, don't create the chat from draft - incognito chats are created on message send, not draft save
    const { incognitoMode } = await import("../../stores/incognitoModeStore");
    const isIncognitoEnabled = incognitoMode.get();
    if (isIncognitoEnabled && !currentChatIdForOperation) {
      console.debug(
        `[DraftService] Incognito mode enabled but no chat ID yet - will create incognito chat on message send, not on draft save`,
      );
      // Don't create chat from draft in incognito mode - chat will be created when message is sent
      // Just update the draft state to track the content, but don't persist it
      draftEditorUIState.update((s) => ({
        ...s,
        hasUnsavedChanges: false, // Mark as "saved" in memory, but not persisted
        lastSavedContentMarkdown: contentMarkdown, // Store for comparison
      }));
      return;
    }

    // CRITICAL: Handle non-authenticated users with sessionStorage
    // For non-authenticated users, save drafts to sessionStorage as cleartext
    if (!isAuthenticated) {
      // CRITICAL: Prevent draft deletion during context switching
      // When switching chats, the editor might be temporarily empty while loading the new chat's draft
      if (currentState.isSwitchingContext) {
        console.debug(
          "[DraftService] Context switch in progress, skipping draft save/deletion to prevent data loss",
        );
        return;
      }

      // Determine chat ID for sessionStorage draft
      // CRITICAL: For demo chats, always prioritize the draft state's currentChatId to ensure separate drafts per demo chat
      // The draft state is updated synchronously in setCurrentChatContext when switching chats, so it's more reliable
      // Only use chatIdFromMessageInput if the state doesn't have a chat ID yet (e.g., new chat creation)
      // This ensures that when switching between demo chats, each chat maintains its own separate draft
      if (currentState.currentChatId) {
        // Always use the draft state's currentChatId for demo chats to ensure separate drafts
        // This prevents overwriting one demo chat's draft when typing in another demo chat
        currentChatIdForOperation = currentState.currentChatId;
        console.debug(
          "[DraftService] Using draft state chat ID for non-authenticated user:",
          {
            chatId: currentChatIdForOperation,
            propChatId: chatIdFromMessageInput,
            isDemoChat:
              currentChatIdForOperation.startsWith("demo-") ||
              currentChatIdForOperation.startsWith("legal-"),
          },
        );
      } else if (chatIdFromMessageInput) {
        // Fallback to prop if state doesn't have a chat ID (e.g., new chat creation)
        currentChatIdForOperation = chatIdFromMessageInput;
        console.debug(
          "[DraftService] Using prop chat ID for non-authenticated user (state has no chat ID):",
          currentChatIdForOperation,
        );

        // Update draft state with the prop's chat ID to keep them in sync
        draftEditorUIState.update((s) => ({
          ...s,
          currentChatId: currentChatIdForOperation,
        }));
      } else {
        // No chat ID available - generate a new one for new chats
        // This ensures new chats created by non-authenticated users get a chat ID
        currentChatIdForOperation = crypto.randomUUID();
        console.debug(
          "[DraftService] Generated new chat ID for non-authenticated user draft:",
          currentChatIdForOperation,
        );

        // Update draft state with the new chat ID
        draftEditorUIState.update((s) => ({
          ...s,
          currentChatId: currentChatIdForOperation,
          newlyCreatedChatIdToSelect: currentChatIdForOperation,
        }));
      }

      const contentJSON = editor.getJSON() as TiptapJSON;

      // CRITICAL: Only delete draft if we're sure the editor is actually empty
      // AND we're not in the middle of a context switch
      // AND the chat ID matches the current context (to prevent deleting wrong chat's draft)
      // AND we're not switching to a demo chat (which might have no draft initially)
      // NOTE: We only check editor.isEmpty here, NOT isContentEmptyExceptMention.
      // isContentEmptyExceptMention is for SENDING (where a lone mention isn't a valid message),
      // but for DRAFTS, a mention alone IS valid content that should be saved.
      if (editor.isEmpty) {
        // CRITICAL: Never delete drafts during context switches - this prevents deleting the wrong chat's draft
        // when switching between demo chats. The isSwitchingContext flag is set for 200ms after setCurrentChatContext,
        // which should be enough time for the context switch to complete.
        if (currentState.isSwitchingContext) {
          console.debug(
            "[DraftService] Editor empty but context switch in progress - skipping deletion to prevent data loss:",
            {
              chatIdForOperation: currentChatIdForOperation,
              currentStateChatId: currentState.currentChatId,
              isSwitchingContext: currentState.isSwitchingContext,
            },
          );
          return;
        }

        // Double-check: Only delete if the chat ID matches the current context
        // This prevents deleting the wrong chat's draft during rapid switching
        if (currentChatIdForOperation === currentState.currentChatId) {
          console.info(
            "[DraftService] Editor content is empty for non-authenticated user, deleting sessionStorage draft:",
            {
              chatId: currentChatIdForOperation,
              isDemoChat:
                currentChatIdForOperation?.startsWith("demo-") ||
                currentChatIdForOperation?.startsWith("legal-"),
            },
          );
          deleteSessionStorageDraft(currentChatIdForOperation);

          // Update state
          draftEditorUIState.update((s) => ({
            ...s,
            hasUnsavedChanges: false,
            lastSavedContentMarkdown: null,
          }));

          // Dispatch event for UI updates
          window.dispatchEvent(
            new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
              detail: {
                chat_id: currentChatIdForOperation,
                draftDeleted: true,
              },
            }),
          );
        } else {
          console.debug(
            "[DraftService] Editor empty but context mismatch - skipping deletion to prevent data loss:",
            {
              chatIdForOperation: currentChatIdForOperation,
              currentStateChatId: currentState.currentChatId,
            },
          );
        }
        return;
      }

      // Convert TipTap content to markdown for storage
      const contentMarkdown = tipTapToCanonicalMarkdown(contentJSON);

      // Check if content has changed
      if (
        currentState.currentChatId === currentChatIdForOperation &&
        currentState.lastSavedContentMarkdown &&
        contentMarkdown === currentState.lastSavedContentMarkdown
      ) {
        console.info(
          `[DraftService] Draft content for chat ${currentChatIdForOperation} is unchanged (non-authenticated). Skipping save.`,
        );
        return;
      }

      // Generate preview text from markdown for chat list display
      // Pass contentJSON so unserialized embed nodes (e.g. uploading images) are shown
      const previewText = generateDraftPreview(
        contentMarkdown,
        100,
        contentJSON,
      );

      // Save to sessionStorage (cleartext, no encryption)
      saveSessionStorageDraft(
        currentChatIdForOperation,
        contentJSON,
        previewText,
      );

      // Update state
      draftEditorUIState.update((s) => ({
        ...s,
        currentChatId: currentChatIdForOperation,
        hasUnsavedChanges: false,
        lastSavedContentMarkdown: contentMarkdown,
      }));

      // Dispatch event for UI updates (chat list refresh)
      window.dispatchEvent(
        new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
          detail: { chat_id: currentChatIdForOperation },
        }),
      );

      console.debug(
        "[DraftService] Saved draft to sessionStorage for non-authenticated user:",
        {
          chatId: currentChatIdForOperation,
          markdownLength: contentMarkdown.length,
        },
      );

      return; // Exit early for non-authenticated users
    }

    // Continue with authenticated user flow (IndexedDB + encryption)

    // Determine the definitive chat ID for this operation.
    // Priority:
    // 1. If internal state (currentState.currentChatId) is null (e.g., after chat deletion/reset),
    //    then any chatIdFromMessageInput is stale, and we must create a new chat.
    // 2. If internal state is not null, and chatIdFromMessageInput differs, align with MessageInput.
    // 3. Otherwise, use the existing currentState.currentChatId.
    if (chatIdFromMessageInput) {
      if (currentState.currentChatId === null) {
        // If MessageInput provides a chat ID but our state doesn't have one,
        // we should use the MessageInput's chat ID instead of creating a new chat
        console.info(
          `[DraftService] MessageInput has chatId (${chatIdFromMessageInput}) but draft context is null. Using MessageInput's chatId.`,
        );
        currentChatIdForOperation = chatIdFromMessageInput;
        // Update the draft state to use the MessageInput's chat ID
        draftEditorUIState.update((s) => ({
          ...s,
          currentChatId: chatIdFromMessageInput,
          currentUserDraftVersion: 0, // Reset version as we're setting a new context
          lastSavedContentMarkdown: null, // Reset last saved content
          newlyCreatedChatIdToSelect: null,
        }));
      } else if (chatIdFromMessageInput !== currentState.currentChatId) {
        // MessageInput's context is different, and internal state is not null.
        // Align draft service's context with MessageInput.
        console.info(
          `[DraftService] Aligning draft operation context with MessageInput: ${chatIdFromMessageInput}. Previous draft state context: ${currentState.currentChatId}`,
        );
        draftEditorUIState.update((s) => ({
          ...s,
          currentChatId: chatIdFromMessageInput,
          currentUserDraftVersion: 0, // Reset version, as we are switching context
          lastSavedContentMarkdown: null, // Reset last saved, content will be compared anew
          newlyCreatedChatIdToSelect: null,
        }));
        currentChatIdForOperation = chatIdFromMessageInput;
      }
      // If chatIdFromMessageInput is present and matches currentState.currentChatId,
      // currentChatIdForOperation is already correctly set from currentState.currentChatId.
    } else {
      // No chatIdFromMessageInput provided, use internal state
      currentChatIdForOperation = currentState.currentChatId;

      // If both internal state and MessageInput have no chat ID, we need to create a new chat
      if (currentChatIdForOperation === null) {
        console.info(
          `[DraftService] Both internal state and MessageInput have no chat ID. Will create new chat for draft.`,
        );
        // currentChatIdForOperation will remain null, which will trigger new chat creation below
      }
    }
    // Now currentChatIdForOperation is the one to use.
    // If chatIdFromMessageInput was null, currentChatIdForOperation remains what was in the state.

    // CRITICAL: Check if we're saving a draft to a demo/legal chat (public chat)
    // If so, we MUST generate a new UUID for the chat so it becomes a regular chat
    // This ensures the chat can't be identified as demo/legal later
    if (currentChatIdForOperation && isPublicChat(currentChatIdForOperation)) {
      const oldChatId = currentChatIdForOperation;
      currentChatIdForOperation = crypto.randomUUID();
      console.info(
        `[DraftService] 🔄 Converting public chat ${oldChatId} to regular chat ${currentChatIdForOperation} - user created draft in demo/legal chat`,
      );

      // Update draft state to use the new chat ID
      draftEditorUIState.update((s) => ({
        ...s,
        currentChatId: currentChatIdForOperation,
        newlyCreatedChatIdToSelect: currentChatIdForOperation,
      }));
    }

    const contentJSON = editor.getJSON() as TiptapJSON;

    // Convert TipTap content to markdown for storage
    const contentMarkdown = tipTapToCanonicalMarkdown(contentJSON);

    // Generate preview text from markdown for chat list display
    // Pass contentJSON so unserialized embed nodes (e.g. uploading images) are shown
    const previewText = generateDraftPreview(contentMarkdown, 100, contentJSON);

    // CRITICAL FIX: await encryptWithMasterKey since it's async to prevent TypeError when calling substring
    const encryptedMarkdown = await encryptWithMasterKey(contentMarkdown);
    const encryptedPreview = previewText
      ? await encryptWithMasterKey(previewText)
      : null;

    if (!encryptedMarkdown) {
      console.error(
        "[DraftService] Failed to encrypt draft content - master key not available",
      );
      draftEditorUIState.update((s) => ({ ...s, hasUnsavedChanges: true }));
      return;
    }

    // Debug logging for draft updates
    console.log("💾 [DraftService] Saving draft as encrypted markdown:", {
      chatId: currentChatIdForOperation,
      cleartext: contentMarkdown,
      cleartextLength: contentMarkdown.length,
      encrypted: encryptedMarkdown.substring(0, 100) + "...",
      encryptedLength: encryptedMarkdown.length,
      previewText: previewText,
      previewLength: previewText?.length || 0,
      encryptedPreview: encryptedPreview
        ? encryptedPreview.substring(0, 50) + "..."
        : null,
      encryptedPreviewLength: encryptedPreview?.length || 0,
      tiptapJSON: contentJSON,
    });

    // If content is empty, treat as clearing/deleting the draft
    // NOTE: We only check editor.isEmpty here, NOT isContentEmptyExceptMention.
    // isContentEmptyExceptMention is for SENDING (where a lone mention isn't a valid message),
    // but for DRAFTS, a mention alone IS valid content that should be saved.
    // The user might be in the middle of composing a message after selecting a model mention.
    if (editor.isEmpty) {
      console.info(
        "[DraftService] Editor content is empty. Triggering draft deletion process.",
      );
      if (currentChatIdForOperation) {
        // Check the resolved ID
        // clearCurrentDraft reads from draftEditorUIState, which we've just updated if necessary.
        await clearCurrentDraft(); // This will also handle resetting lastSavedContentJSON
      } else {
        // If no chat context, just reset the UI editor and state
        clearEditorAndResetDraftState(false); // This should also reset lastSavedContentJSON via draftCore
      }
      return;
    }

    // Check if content has actually changed compared to the last saved version for this chat
    if (
      currentState.currentChatId === currentChatIdForOperation &&
      currentState.lastSavedContentMarkdown &&
      contentMarkdown === currentState.lastSavedContentMarkdown
    ) {
      console.info(
        `[DraftService] Draft content for chat ${currentChatIdForOperation} is unchanged. Skipping save.`,
      );
      // Ensure hasUnsavedChanges is false if content matches last save
      if (currentState.hasUnsavedChanges) {
        draftEditorUIState.update((s) => ({ ...s, hasUnsavedChanges: false }));
      }
      return;
    }

    // Saving non-empty, changed content
    // CRITICAL: Acquire save lock to prevent race conditions that create duplicate chats
    draftEditorUIState.update((s) => ({
      ...s,
      hasUnsavedChanges: true,
      isSaveInProgress: true,
    }));

    let userDraft: Chat | null = null;
    let versionBeforeSave = 0;

    try {
      if (!currentChatIdForOperation) {
        console.info(
          `[DraftService] Creating new chat for draft. currentChatIdForOperation is falsy: ${currentChatIdForOperation}`,
        );
        try {
          // CRITICAL: Don't create incognito chats from drafts
          // Incognito chats are created when the first message is sent, not when drafts are saved
          // Create regular chat in IndexedDB
          console.debug(
            `[DraftService] About to call createNewChatWithCurrentUserDraft with encryptedMarkdown length: ${encryptedMarkdown?.length}, encryptedPreview length: ${encryptedPreview?.length}`,
          );
          const newChat = await chatDB.createNewChatWithCurrentUserDraft(
            encryptedMarkdown,
            encryptedPreview,
          );

          console.debug(
            `[DraftService] createNewChatWithCurrentUserDraft returned:`,
            {
              chatId: newChat.chat_id,
              draftVersion: newChat.draft_v,
              hasEncryptedDraftMd: !!newChat.encrypted_draft_md,
              hasEncryptedDraftPreview: !!newChat.encrypted_draft_preview,
            },
          );
          currentChatIdForOperation = newChat.chat_id; // Update for subsequent use in this function
          userDraft = newChat;
          draftEditorUIState.update((s) => ({
            ...s,
            currentChatId: currentChatIdForOperation, // This is now the ID of the new chat
            currentUserDraftVersion: userDraft.draft_v,
            newlyCreatedChatIdToSelect: currentChatIdForOperation, // Signal UI to select this new chat
            hasUnsavedChanges: false,
            lastSavedContentMarkdown: contentMarkdown, // Store cleartext markdown for comparison
            isSaveInProgress: false, // Release lock on success
          }));
          console.info(
            `[DraftService] Created new local chat ${currentChatIdForOperation} with encrypted draft. Version: ${userDraft.draft_v}. Updated lastSavedContentMarkdown.`,
          );
        } catch (error) {
          console.error(
            `[DraftService] Error creating new chat for draft:`,
            error,
          );
          // If chat creation fails, we can't save the draft
          draftEditorUIState.update((s) => ({
            ...s,
            hasUnsavedChanges: true,
            isSaveInProgress: false,
          }));
          return;
        }
      } else {
        // Check if chat exists in database or incognito service before deciding whether to create or update
        let existingChat: Chat | null = null;
        let isIncognitoChat = false;

        // First check if it's an incognito chat
        const { incognitoChatService } =
          await import("../incognitoChatService");
        try {
          existingChat = await incognitoChatService.getChat(
            currentChatIdForOperation,
          );
          if (existingChat) {
            isIncognitoChat = true;
          }
        } catch (error) {
          // Not an incognito chat or error - continue to check IndexedDB
        }

        // If not found in incognito service, check IndexedDB
        if (!existingChat) {
          try {
            existingChat = await chatDB.getChat(currentChatIdForOperation);
          } catch (error) {
            console.error(
              `[DraftService] Error during database lookup for chat ${currentChatIdForOperation}:`,
              error,
            );
            draftEditorUIState.update((s) => ({
              ...s,
              hasUnsavedChanges: true,
              isSaveInProgress: false,
            }));
            return;
          }
        }

        if (!existingChat) {
          // CRITICAL FIX: Chat ID exists in state but not in IndexedDB
          // This can happen after login when state is restored but DB is cleared
          // Instead of creating a new chat with a DIFFERENT random UUID (which causes duplicate chats),
          // create a chat using the EXISTING ID from state
          console.warn(
            `[DraftService] Chat ${currentChatIdForOperation} not found in local DB. Creating chat with the SAME ID to prevent duplicates.`,
          );
          try {
            // Create a chat object with the EXISTING ID (not a new random UUID)
            const nowTimestamp = Math.floor(Date.now() / 1000);
            const chatToCreate: Chat = {
              chat_id: currentChatIdForOperation, // USE THE EXISTING ID!
              encrypted_title: null,
              messages_v: 0,
              title_v: 0,
              draft_v: 1,
              encrypted_draft_md: encryptedMarkdown,
              encrypted_draft_preview: encryptedPreview,
              last_edited_overall_timestamp: nowTimestamp,
              unread_count: 0,
              created_at: nowTimestamp,
              updated_at: nowTimestamp,
            };

            // Save directly to IndexedDB using addChat (not createNewChatWithCurrentUserDraft which generates a new UUID)
            await chatDB.addChat(chatToCreate);
            userDraft = chatToCreate;

            draftEditorUIState.update((s) => ({
              ...s,
              // Keep the same currentChatId - DO NOT change it
              currentUserDraftVersion: userDraft.draft_v,
              newlyCreatedChatIdToSelect: currentChatIdForOperation, // Signal UI to select this chat
              hasUnsavedChanges: false,
              lastSavedContentMarkdown: contentMarkdown,
              isSaveInProgress: false, // Release lock on success
            }));
            console.info(
              `[DraftService] Created chat ${currentChatIdForOperation} (using existing ID) with encrypted draft. Version: ${userDraft.draft_v}`,
            );
          } catch (error) {
            console.error(
              `[DraftService] Error creating chat with existing ID ${currentChatIdForOperation}:`,
              error,
            );
            draftEditorUIState.update((s) => ({
              ...s,
              hasUnsavedChanges: true,
              isSaveInProgress: false,
            }));
            return;
          }
        } else {
          // Chat exists - update it normally
          // CRITICAL: Don't save drafts for incognito chats
          if (isIncognitoChat) {
            console.debug(
              `[DraftService] Skipping draft update for incognito chat ${currentChatIdForOperation} - drafts are not saved for incognito chats`,
            );
            // Just update the draft state in memory, but don't persist
            draftEditorUIState.update((s) => ({
              ...s,
              hasUnsavedChanges: false,
              lastSavedContentMarkdown: contentMarkdown,
              isSaveInProgress: false, // Release lock
            }));
            return;
          }

          // Update regular chat draft in IndexedDB
          console.info(
            `[DraftService] Updating existing draft for chat ${currentChatIdForOperation}`,
          );
          versionBeforeSave = existingChat.draft_v || 0;
          userDraft = await chatDB.saveCurrentUserChatDraft(
            currentChatIdForOperation,
            encryptedMarkdown,
            encryptedPreview,
          );
          if (userDraft) {
            // currentChatId in state should already be currentChatIdForOperation due to earlier update or initial state
            draftEditorUIState.update((s) => ({
              ...s,
              currentUserDraftVersion: userDraft.draft_v,
              hasUnsavedChanges: false,
              lastSavedContentMarkdown: contentMarkdown, // Store cleartext markdown for comparison
              isSaveInProgress: false, // Release lock on success
            }));
            console.info(
              `[DraftService] Saved encrypted draft locally for chat ${currentChatIdForOperation}, new version: ${userDraft.draft_v}. Updated lastSavedContentMarkdown.`,
            );
          } else {
            console.error(
              `[DraftService] Failed to save draft locally for chat ${currentChatIdForOperation}.`,
            );
            draftEditorUIState.update((s) => ({
              ...s,
              hasUnsavedChanges: true,
              isSaveInProgress: false,
            }));
            return; // Stop if local save failed
          }
        }
      }

      if (!userDraft || !currentChatIdForOperation) {
        console.error(
          "[DraftService] Critical error: UserDraft object or ID is null after local save attempt.",
        );
        draftEditorUIState.update((s) => ({
          ...s,
          hasUnsavedChanges: true,
          isSaveInProgress: false,
        }));
        return;
      }

      // Invalidate cache directly (important for when Chats component is unmounted)
      console.debug(
        `[DraftService] Invalidating cache for updated draft in chat: ${currentChatIdForOperation}`,
      );
      chatMetadataCache.invalidateChat(currentChatIdForOperation);

      // Dispatch event for UI lists to update
      window.dispatchEvent(
        new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, {
          detail: { chat_id: currentChatIdForOperation },
        }),
      );

      // Send to server or queue if offline (send encrypted markdown to server)
      // NOTE: Local storage with encrypted content has already been completed above
      const wsStatus = get(websocketStatus);
      if (wsStatus.status === "connected") {
        try {
          // Send encrypted markdown and preview to server for synchronization
          // The sendUpdateDraft function will NOT save to local database - that's already done above with encryption
          await chatSyncService.sendUpdateDraft(
            currentChatIdForOperation,
            encryptedMarkdown,
            encryptedPreview,
          );
          console.info(
            `[DraftService] Successfully sent encrypted draft to server for chat ${currentChatIdForOperation}.`,
          );
        } catch (wsError) {
          console.error(
            `[DraftService] Error sending draft update via WS for chat ${currentChatIdForOperation}:`,
            wsError,
          );
          draftEditorUIState.update((s) => ({
            ...s,
            hasUnsavedChanges: true,
            isSaveInProgress: false,
          }));
        }
      } else {
        console.info(
          `[DraftService] WebSocket status is '${wsStatus.status}', not 'connected'. Queuing draft update for chat ${currentChatIdForOperation}.`,
        );
        const offlineChange: Omit<OfflineChange, "change_id"> = {
          chat_id: currentChatIdForOperation,
          type: "draft",
          value: contentMarkdown, // Send cleartext markdown to server when online
          version_before_edit: versionBeforeSave,
        };
        await chatSyncService.queueOfflineChange(offlineChange);
        draftEditorUIState.update((s) => ({
          ...s,
          hasUnsavedChanges: true,
          isSaveInProgress: false,
        }));
      }
    } finally {
      // CRITICAL: Ensure save lock is always released, even if an unexpected error occurs
      draftEditorUIState.update((s) => ({ ...s, isSaveInProgress: false }));

      // If another save was requested while this one was in progress, schedule
      // a follow-up save with a short delay to capture the latest editor content.
      // This prevents content loss when the user types during a slow save (encryption).
      if (resaveNeeded) {
        resaveNeeded = false;
        console.debug(
          "[DraftService] Executing follow-up save for content that arrived during previous save",
        );
        // Short delay to let the state update propagate, then re-trigger the debounced save.
        // Using setTimeout instead of calling saveDraftDebounced directly to avoid
        // re-entering while the finally block is still executing.
        setTimeout(() => {
          const followUpEditor = getEditorInstance();
          if (followUpEditor && !followUpEditor.isDestroyed) {
            saveDraftDebounced(chatIdFromMessageInput);
          }
        }, 100);
      }
    }
  },
  1200,
);

/**
 * Triggers the debounced save/clear function. Called on editor updates.
 * CRITICAL: For non-authenticated users, prefer using draft state's currentChatId
 * to avoid race conditions when switching chats quickly.
 */
export function triggerSaveDraft(chatIdFromMessageInput?: string) {
  const editor = getEditorInstance();
  if (!editor) return;

  // CRITICAL: For non-authenticated users, check if we're switching context
  // If so, skip the save to prevent deleting the wrong chat's draft
  const currentState = get(draftEditorUIState);
  if (!get(authStore).isAuthenticated && currentState.isSwitchingContext) {
    console.debug(
      "[DraftService] Context switch in progress, skipping triggerSaveDraft to prevent data loss",
    );
    return;
  }

  saveDraftDebounced(chatIdFromMessageInput);
}

/**
 * Immediately flushes any pending debounced save/clear operations.
 * Called on blur, visibilitychange, beforeunload.
 */
export function flushSaveDraft() {
  const editor = getEditorInstance();
  if (!editor) return;
  console.info("[DraftService] Flushing draft operation.");
  saveDraftDebounced.flush();
}

/**
 * Deletes the current chat.
 * This is a more explicit delete action than just clearing a draft.
 */
export async function deleteCurrentChat() {
  const currentState = get(draftEditorUIState); // Use renamed store
  const chatIdToDelete = currentState.currentChatId;

  if (!chatIdToDelete) {
    console.warn("[DraftService] No current chat selected to delete.");
    return;
  }

  console.info(`[DraftService] Attempting to delete chat: ${chatIdToDelete}`);

  try {
    // Optimistically clear editor and reset UI state FIRST, so user sees immediate effect.
    // clearEditorAndResetDraftState will set currentChatId to null.
    clearEditorAndResetDraftState(false);

    // Delete from IndexedDB first (also cleans up associated embeds)
    console.debug(
      `[DraftService] Deleting chat from IndexedDB: ${chatIdToDelete}`,
    );
    const { deletedEmbedIds } = await chatDB.deleteChat(chatIdToDelete);
    console.debug(
      `[DraftService] Chat deleted from IndexedDB: ${chatIdToDelete}, cleaned up ${deletedEmbedIds.length} embeds`,
    );

    // Dispatch chatDeleted event AFTER deletion to update UI components
    console.debug(
      `[DraftService] Dispatching chatDeleted event for UI update: ${chatIdToDelete}`,
    );
    chatSyncService.dispatchEvent(
      new CustomEvent("chatDeleted", { detail: { chat_id: chatIdToDelete } }),
    );
    console.debug(
      `[DraftService] chatDeleted event dispatched for chat: ${chatIdToDelete}`,
    );

    // Send delete request to server (includes embed IDs to delete)
    await chatSyncService.sendDeleteChat(chatIdToDelete, deletedEmbedIds);
    console.info(
      `[DraftService] Sent delete_chat request for ${chatIdToDelete} with ${deletedEmbedIds.length} embed deletions.`,
    );
    // UI list update is handled by chatDeleted event dispatched above
  } catch (error) {
    console.error(
      `[DraftService] Error deleting chat ${chatIdToDelete}:`,
      error,
    );
    // Handle error, maybe revert UI state if needed, though optimistic clear already happened.
    // If server fails, sync on reconnect should resolve.
    // For now, we assume the optimistic local clear is acceptable UX.
    // To be more robust, one might re-fetch chat list or show error.
  }
}
