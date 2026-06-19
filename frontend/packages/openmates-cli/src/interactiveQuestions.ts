/**
 * CLI helpers for the OpenMates interactive-question protocol.
 *
 * The CLI renders terminal-native prompts, but it must send the same hidden
 * `interactive_response` fenced JSON that web and Apple use. User-facing output
 * intentionally contains only the selected or entered answer text.
 */

export type InteractiveQuestionType = "choice" | "input" | "slider" | "swipe" | "rating";

export interface InteractiveQuestionOption {
  id: string;
  text: string;
}

export interface InteractiveQuestionField {
  id: string;
  label: string;
  required?: boolean;
}

export interface InteractiveQuestionPayload {
  type: InteractiveQuestionType;
  id: string;
  question: string;
  multiple?: boolean;
  custom_option_id?: string;
  custom_placeholder?: string;
  options?: InteractiveQuestionOption[];
  fields?: InteractiveQuestionField[];
  min?: number;
  max?: number;
  max_stars?: number;
  scale?: number;
  cards?: InteractiveQuestionOption[];
}

export type InteractiveQuestionAnswer = Record<string, unknown>;

export interface FormattedInteractiveAnswer {
  displayText: string;
  messageContent: string;
  responsePayload: Record<string, unknown>;
}

export interface WaitingForUserResult {
  status: "waiting_for_user";
  chat_id: string;
  message_id: string;
  parent_id?: string;
  question: InteractiveQuestionPayload;
}

const INTERACTIVE_QUESTION_RE = /```interactive_question\s*\n([\s\S]*?)\n```/;

export function parseInteractiveQuestionBlock(content: string): InteractiveQuestionPayload | null {
  const match = content.match(INTERACTIVE_QUESTION_RE);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[1]) as InteractiveQuestionPayload;
    return isInteractiveQuestionPayload(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function isInteractiveQuestionPayload(value: unknown): value is InteractiveQuestionPayload {
  if (!value || typeof value !== "object") return false;
  const payload = value as Partial<InteractiveQuestionPayload>;
  if (!isQuestionType(payload.type)) return false;
  if (typeof payload.id !== "string" || payload.id.trim().length === 0) return false;
  if (payload.type === "choice") {
    if (typeof payload.question !== "string" || payload.question.trim().length === 0) return false;
    if (!Array.isArray(payload.options) || payload.options.length === 0) return false;
    if (payload.custom_option_id !== undefined) {
      return typeof payload.custom_option_id === "string"
        && payload.options.some((option) => option.id === payload.custom_option_id);
    }
    return true;
  }
  if (payload.type === "input") return Array.isArray(payload.fields) && payload.fields.length > 0;
  if (payload.type === "slider") {
    return typeof payload.question === "string" && payload.question.trim().length > 0
      && typeof payload.min === "number" && typeof payload.max === "number";
  }
  if (payload.type === "swipe") return Array.isArray(payload.cards) && payload.cards.length > 0;
  if (payload.type === "rating") {
    return typeof payload.question === "string" && payload.question.trim().length > 0
      && (typeof payload.max_stars === "number" || typeof payload.max === "number" || typeof payload.scale === "number");
  }
  return false;
}

function isQuestionType(value: unknown): value is InteractiveQuestionType {
  return value === "choice" || value === "input" || value === "slider" || value === "swipe" || value === "rating";
}

export function formatInteractiveQuestionAnswer(
  question: InteractiveQuestionPayload,
  answer: InteractiveQuestionAnswer,
): FormattedInteractiveAnswer {
  const responsePayload = buildResponsePayload(question, answer);
  const displayText = buildDisplayText(question, answer);
  const protocol = JSON.stringify(responsePayload, null, 2);
  return {
    displayText,
    messageContent: `${displayText}\n\n\`\`\`interactive_response\n${protocol}\n\`\`\``,
    responsePayload,
  };
}

export function toWaitingForUserResult(params: {
  chatId: string;
  messageId: string;
  parentId?: string;
  question: InteractiveQuestionPayload;
}): WaitingForUserResult {
  return {
    status: "waiting_for_user",
    chat_id: params.chatId,
    message_id: params.messageId,
    parent_id: params.parentId,
    question: params.question,
  };
}

function buildResponsePayload(
  question: InteractiveQuestionPayload,
  answer: InteractiveQuestionAnswer,
): Record<string, unknown> {
  return {
    id: question.id,
    ...answer,
  };
}

function buildDisplayText(
  question: InteractiveQuestionPayload,
  answer: InteractiveQuestionAnswer,
): string {
  if (question.type === "choice") {
    const selection = Array.isArray(answer.selection) ? answer.selection.map(String) : [];
    const optionsById = new Map((question.options ?? []).map((option) => [option.id, option.text]));
    const customAnswer = answer.custom_answer == null ? "" : String(answer.custom_answer).trim();
    return selection
      .map((id) => customAnswer && isCustomChoiceOption(question, id) ? customAnswer : optionsById.get(id) ?? id)
      .join(", ");
  }
  if (question.type === "input") {
    const values = answer.inputs && typeof answer.inputs === "object"
      ? answer.inputs as Record<string, unknown>
      : answer.values && typeof answer.values === "object"
        ? answer.values as Record<string, unknown>
        : answer;
    return Object.entries(values)
      .filter(([key]) => key !== "id")
      .map(([, value]) => String(value))
      .filter(Boolean)
      .join("\n");
  }
  if (question.type === "slider") {
    return answer.value == null ? "" : String(answer.value);
  }
  if (question.type === "swipe") {
    const liked = Array.isArray(answer.liked) ? answer.liked.map(String) : [];
    const cardsById = new Map((question.cards ?? []).map((card) => [card.id, card.text]));
    return liked.map((id) => cardsById.get(id) ?? id).join(", ");
  }
  if (question.type === "rating") {
    const rating = answer.rating == null ? "" : String(answer.rating);
    const comment = answer.comment == null ? "" : String(answer.comment).trim();
    return [rating, comment].filter(Boolean).join("\n");
  }
  return "";
}

function isCustomChoiceOption(question: InteractiveQuestionPayload, optionId: string): boolean {
  if (question.custom_option_id) return optionId === question.custom_option_id;
  const optionText = (question.options ?? []).find((option) => option.id === optionId)?.text.trim().toLowerCase() ?? "";
  return [
    "i give you my own answer",
    "my own answer",
    "own answer",
    "custom answer",
    "something else",
    "other",
  ].some((pattern) => optionText === pattern || optionText.includes(pattern));
}
