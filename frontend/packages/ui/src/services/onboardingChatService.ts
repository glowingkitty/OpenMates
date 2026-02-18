// frontend/packages/ui/src/services/onboardingChatService.ts
//
// Service for creating the onboarding chat after user signup.
// Creates a new encrypted chat with a pre-built welcome message from Suki,
// the onboarding/support mate. The welcome message is a static i18n string
// (not AI-generated) so it's free, instant, and fully localized.
//
// The chat is created with the 'openmates-welcome' focus mode pre-activated,
// which guides Suki's AI responses through the onboarding conversation flow.

import { get } from "svelte/store";
import { text } from "../i18n/translations";
import {
  generateChatKey,
  encryptChatKeyWithMasterKey,
  encryptWithChatKey,
  encryptArrayWithChatKey,
} from "./cryptoService";
import { addChat } from "./db/chatCrudOperations";
import { saveMessage } from "./db/messageOperations";
import { chatDB } from "./db";
import type { Chat, Message } from "../types/chat";

/**
 * Category identifier for the onboarding/support mate (Suki).
 * Must match the category in mates.yml and matesMetadata.ts.
 */
const ONBOARDING_CATEGORY = "onboarding_support";

/**
 * Focus mode ID for the onboarding welcome flow.
 * Format: "{app_id}-{focus_id}" as used by the focus mode system.
 */
const ONBOARDING_FOCUS_ID = "openmates-welcome";

/**
 * Creates the onboarding chat with Suki's welcome message.
 *
 * This function:
 * 1. Generates a new chat with standard E2E encryption (chat key + master key)
 * 2. Creates a pre-built assistant welcome message from i18n
 * 3. Pre-activates the onboarding focus mode on the chat
 * 4. Includes follow-up suggestion chips
 * 5. Saves everything to IndexedDB
 *
 * The welcome message is NOT charged to the user since it's a static template,
 * not an AI-generated response.
 *
 * @param username - The user's display name (injected into the welcome message)
 * @returns The chat_id of the created onboarding chat, or null if creation failed
 */
export async function createOnboardingChat(
  username: string,
): Promise<string | null> {
  try {
    const $text = get(text);
    if (!$text) {
      console.error("[OnboardingChat] Translation store not available");
      return null;
    }

    // --- Generate chat ID and encryption key ---
    const chatId = crypto.randomUUID();
    const chatKey = generateChatKey();
    const encryptedChatKey = await encryptChatKeyWithMasterKey(chatKey);

    if (!encryptedChatKey) {
      console.error(
        "[OnboardingChat] Failed to encrypt chat key — master key may be missing",
      );
      return null;
    }

    // --- Build the welcome message content ---
    const welcomeContent = $text("onboarding.welcome_message", {
      username: username || "there",
    });

    // Verify the translation resolved (not a missing placeholder)
    if (welcomeContent.startsWith("[T:")) {
      console.error("[OnboardingChat] Welcome message translation not found");
      return null;
    }

    // --- Encrypt message fields ---
    const encryptedContent = await encryptWithChatKey(welcomeContent, chatKey);
    const encryptedCategory = await encryptWithChatKey(
      ONBOARDING_CATEGORY,
      chatKey,
    );
    const encryptedSenderName = await encryptWithChatKey("Suki", chatKey);

    // --- Build the message ---
    const now = Math.floor(Date.now() / 1000);
    const messageId = `${chatId.slice(-10)}-${crypto.randomUUID()}`;

    const message: Message = {
      message_id: messageId,
      chat_id: chatId,
      role: "assistant",
      created_at: now,
      status: "synced",
      encrypted_content: encryptedContent,
      encrypted_category: encryptedCategory,
      encrypted_sender_name: encryptedSenderName,
    };

    // --- Encrypt chat-level fields ---
    const encryptedActiveFocusId = await encryptWithChatKey(
      ONBOARDING_FOCUS_ID,
      chatKey,
    );

    // Encrypt follow-up suggestions
    const suggestions = [
      $text("onboarding.follow_up_1"),
      $text("onboarding.follow_up_2"),
      $text("onboarding.follow_up_3"),
      $text("onboarding.follow_up_4"),
    ];
    const encryptedSuggestions = await encryptArrayWithChatKey(
      suggestions,
      chatKey,
    );

    // Encrypt icon (compass for onboarding)
    const encryptedIcon = await encryptWithChatKey("compass", chatKey);

    // --- Build the chat object ---
    const chat: Chat = {
      chat_id: chatId,
      encrypted_title: null, // Title will be generated after first user message
      encrypted_chat_key: encryptedChatKey,
      messages_v: 1,
      title_v: 0,
      draft_v: 0,
      last_edited_overall_timestamp: now,
      unread_count: 0,
      created_at: now,
      updated_at: now,
      encrypted_active_focus_id: encryptedActiveFocusId,
      encrypted_follow_up_request_suggestions: encryptedSuggestions,
      encrypted_icon: encryptedIcon,
      encrypted_category: encryptedCategory,
    };

    // --- Cache the chat key before saving (addChat needs it for encryption) ---
    const dbInstance = chatDB;
    await dbInstance.init();
    dbInstance.setChatKey(chatId, chatKey);

    // --- Save to IndexedDB ---
    await addChat(dbInstance, chat);
    await saveMessage(dbInstance, message);

    console.debug(
      `[OnboardingChat] Created onboarding chat ${chatId} with welcome message ${messageId}`,
    );

    // Dispatch event so the chat list updates
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("localChatListChanged"));
    }

    return chatId;
  } catch (error) {
    console.error("[OnboardingChat] Failed to create onboarding chat:", error);
    return null;
  }
}

/**
 * Check if an onboarding chat already exists in IndexedDB.
 * Prevents duplicate creation on page refresh during signup.
 *
 * Uses a simple heuristic: checks if any recent chat has the onboarding
 * focus mode active. This is lightweight and avoids scanning all chats.
 *
 * @returns true if an onboarding chat likely exists
 */
export async function hasOnboardingChat(): Promise<boolean> {
  try {
    const dbInstance = chatDB;
    await dbInstance.init();

    // Get all chats and check for the onboarding focus mode
    // This is only called once after signup, so the overhead is acceptable
    const allChats = await dbInstance.getAllChats();
    if (!allChats || allChats.length === 0) return false;

    for (const chat of allChats) {
      if (chat.encrypted_active_focus_id) {
        try {
          const chatKey = dbInstance.getChatKey(chat.chat_id);
          if (!chatKey) continue;

          // Dynamically import to avoid circular dependency
          const { decryptWithChatKey } = await import("./cryptoService");
          const focusId = await decryptWithChatKey(
            chat.encrypted_active_focus_id,
            chatKey,
          );
          if (focusId === ONBOARDING_FOCUS_ID) {
            return true;
          }
        } catch {
          // Decryption failed — skip this chat
          continue;
        }
      }
    }

    return false;
  } catch (error) {
    console.error(
      "[OnboardingChat] Error checking for existing onboarding chat:",
      error,
    );
    return false;
  }
}
