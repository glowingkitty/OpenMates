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
import type {
  ChoiceResponse,
  InputResponse,
  InteractiveQuestionPayload,
  InteractiveQuestionResponse,
  RatingResponse,
  SliderResponse,
  SwipeResponse,
} from "../types";
import { chatDB } from "../../../services/db";

const INTERACTIVE_QUESTION_RE = /```interactive_question\s*([\s\S]*?)\s*```/g;

/**
 * Searches the chat history for a subsequent user response containing an interactive response payload
 * with a matching ID. Returns the parsed JSON payload if found, otherwise null.
 */
export function findSubsequentResponse(
  chatHistory: Message[] | undefined | null,
  questionId: string
): InteractiveQuestionResponse | null {
  if (!chatHistory || !Array.isArray(chatHistory)) return null;

  const questionIndex = findLatestQuestionIndex(chatHistory, questionId);

  for (let i = chatHistory.length - 1; i >= 0; i--) {
    if (i <= questionIndex) break;
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

export function formatInteractiveQuestionUserResponse(
  payload: InteractiveQuestionPayload,
  response: InteractiveQuestionResponse
): string {
  const displayText = formatInteractiveQuestionDisplayText(payload, response);
  const jsonBlock = `\`\`\`interactive_response\n${JSON.stringify(response, null, 2)}\n\`\`\``;

  return `${displayText}\n\n${jsonBlock}`;
}

export function isInteractiveQuestionPayload(value: unknown): value is InteractiveQuestionPayload {
  if (!value || typeof value !== "object") return false;
  const payload = value as Partial<InteractiveQuestionPayload>;
  if (typeof payload.id !== "string" || payload.id.trim().length === 0) return false;
  if (payload.type === "choice") return Array.isArray(payload.options) && payload.options.length > 0;
  if (payload.type === "input") return Array.isArray(payload.fields) && payload.fields.length > 0;
  if (payload.type === "slider") return typeof payload.min === "number" && typeof payload.max === "number";
  if (payload.type === "swipe") return Array.isArray(payload.cards) && payload.cards.length > 0;
  if (payload.type === "rating") return typeof payload.max_stars === "number" || payload.max_stars === undefined;
  return false;
}

function findLatestQuestionIndex(chatHistory: Message[], questionId: string): number {
  for (let i = chatHistory.length - 1; i >= 0; i--) {
    const msg = chatHistory[i];
    if (msg.role !== "assistant" || typeof msg.content !== "string") continue;
    if (messageContainsQuestionId(msg.content, questionId)) return i;
  }
  return -1;
}

function messageContainsQuestionId(content: string, questionId: string): boolean {
  INTERACTIVE_QUESTION_RE.lastIndex = 0;
  let match = INTERACTIVE_QUESTION_RE.exec(content);
  while (match) {
    try {
      const parsed = JSON.parse(match[1]) as { id?: unknown };
      if (parsed.id === questionId) return true;
    } catch {
      // Ignore malformed historic question blocks.
    }
    match = INTERACTIVE_QUESTION_RE.exec(content);
  }
  return false;
}

function formatInteractiveQuestionDisplayText(
  payload: InteractiveQuestionPayload,
  response: InteractiveQuestionResponse
): string {
  if (payload.type === "choice") {
    const choiceResponse = response as ChoiceResponse;
    const selectedIds = choiceResponse.selection;
    const customAnswer = choiceResponse.custom_answer?.trim();
    const texts = payload.options
      .filter((option) => selectedIds.includes(option.id))
      .map((option) => {
        if (customAnswer && isCustomChoiceOption(payload, option)) return customAnswer;
        return option.text;
      });
    return payload.multiple ? texts.join("\n") : texts[0] || "";
  }

  if (payload.type === "input") {
    const inputs = (response as InputResponse).inputs;
    return payload.fields
      .map((field) => inputs[field.id] || "")
      .filter(Boolean)
      .join("\n");
  }

  if (payload.type === "slider") {
    const value = (response as SliderResponse).value;
    const label = payload.labels?.[value];
    return label ? `${value} (${label})` : String(value);
  }

  if (payload.type === "swipe") {
    const swipes = (response as SwipeResponse).swipes;
    return payload.cards
      .map((card) => `${card.text}: ${swipes[card.id] || "dislike"}`)
      .join("\n");
  }

  if (payload.type === "rating") {
    const rating = response as RatingResponse;
    const maxStars = payload.max_stars ?? 5;
    return [
      `${rating.rating}/${maxStars}`,
      rating.comment?.trim() || "",
    ].filter(Boolean).join("\n");
  }

  return "";
}

function isCustomChoiceOption(
  payload: Extract<InteractiveQuestionPayload, { type: "choice" }>,
  option: { id: string; text: string }
): boolean {
  if (payload.custom_option_id) return option.id === payload.custom_option_id;
  const normalizedText = option.text.trim().toLowerCase();
  return [
    "i give you my own answer",
    "my own answer",
    "own answer",
    "custom answer",
    "something else",
    "other",
  ].some((pattern) => normalizedText === pattern || normalizedText.includes(pattern));
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
    status: "sending",
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

    // 3. Dispatch 'chatUpdated' event so Svelte's ActiveChat instantly appends the bubble
    chatSyncService.dispatchEvent(
      new CustomEvent("chatUpdated", {
        detail: {
          chat_id: chatId,
          newMessage: message,
          chat: chat || undefined,
        },
      })
    );
  } catch (err) {
    console.error("[questionState] Error saving and dispatching response message:", err);
  }

  // 4. Send response message over active WebSocket
  await chatSyncService.sendNewMessage(message);
}
