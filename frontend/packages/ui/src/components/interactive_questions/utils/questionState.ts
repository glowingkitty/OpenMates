/**
 * frontend/packages/ui/src/components/interactive_questions/utils/questionState.ts
 *
 * State and synchronization utility for InteractiveQuestions.
 * Detects answered questions by scanning chat history for subsequent responses
 * and dispatches responses as standard encrypted user messages.
 *
 * Architecture: Svelte 5 / ProseMirror custom node view synchronization
 */

import { chatSyncService } from "../../../services/chatSyncService";
import type { Message } from "../../../types/chat";
import type { InteractiveQuestionResponse } from "../types";
import { chatDB } from "../../../services/db";

/**
 * Searches the chat history for a subsequent user response containing an interactive response payload
 * with a matching ID. Returns the parsed JSON payload if found, otherwise null.
 */
export function findSubsequentResponse(
  chatHistory: Message[] | undefined | null,
  questionId: string
): InteractiveQuestionResponse | null {
  if (!chatHistory || !Array.isArray(chatHistory)) return null;

  for (let i = chatHistory.length - 1; i >= 0; i--) {
    const msg = chatHistory[i];
    if (msg.role === "user" && msg.content) {
      // Extract code block formatted as interactive_response
      const match = msg.content.match(/```interactive_response\s*([\s\S]*?)\s*```/);
      if (match) {
        try {
          const parsed = JSON.parse(match[1]) as InteractiveQuestionResponse;
          if (parsed && parsed.id === questionId) {
            return parsed;
          }
        } catch (_e) {
          // Ignore parse errors on malformed JSON
        }
      }
    }
  }
  return null;
}

/**
 * Compiles and sends a structured user response back to the active chat session.
 * Dispatches a standard user message containing the conversational text and the json response block.
 */
export async function submitResponse(chatId: string, content: string): Promise<void> {
  const messageId = `${chatId.slice(-10)}-${crypto.randomUUID()}`;
  const message: Message = {
    message_id: messageId,
    chat_id: chatId,
    role: "user",
    created_at: Math.floor(Date.now() / 1000),
    status: "synced", // Set to synced so it is displayed as completed locally
    content: content,
  };

  try {
    // 1. Save the user response message locally in IndexedDB
    await chatDB.saveMessage(message);

    // 2. Increment local chat message version and overall timestamp
    const chat = await chatDB.getChat(chatId);
    if (chat) {
      chat.messages_v = (chat.messages_v || 0) + 1;
      chat.last_edited_overall_timestamp = message.created_at;
      chat.updated_at = Math.floor(Date.now() / 1000);
      await chatDB.updateChat(chat);
    }

    // 3. Dispatch 'messageAdded' event so Svelte's ChatHistory/ActiveChat instantly appends the bubble
    chatSyncService.dispatchEvent(
      new CustomEvent("messageAdded", {
        detail: {
          chatId: chatId,
          message: message,
        },
      })
    );
  } catch (err) {
    console.error("[questionState] Error saving and dispatching response message:", err);
  }

  // 4. Send response message over active WebSocket
  await chatSyncService.sendNewMessage(message);
}
