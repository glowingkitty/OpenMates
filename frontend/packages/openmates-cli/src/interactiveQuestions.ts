/** CLI helpers for the shared interactive-question response protocol. */
export type InteractiveQuestionType = "choice" | "input" | "slider" | "swipe" | "rating";
export interface InteractiveQuestionOption { id: string; text: string; embed_id?: string; embed_ids?: string[] }
export interface InteractiveQuestionField { id: string; label: string; placeholder?: string; required?: boolean }
export interface InteractiveQuestionPayload {
  type: InteractiveQuestionType; id: string; question?: string; multiple?: boolean;
  custom_option_id?: string; custom_placeholder?: string; options?: InteractiveQuestionOption[];
  fields?: InteractiveQuestionField[]; min?: number; max?: number; step?: number; default?: number;
  labels?: Record<number, string>; max_stars?: number; require_comment?: boolean;
  comment_placeholder?: string; scale?: number; cards?: InteractiveQuestionOption[];
}
export type InteractiveQuestionAnswer = Record<string, unknown>;
export interface FormattedInteractiveAnswer { displayText: string; messageContent: string; responsePayload: Record<string, unknown> }
export interface WaitingForUserResult {
  status: "waiting_for_user"; chat_id: string; message_id: string; parent_id?: string; question: InteractiveQuestionPayload;
}
const BLOCK = /```interactive_question\s*\n([\s\S]*?)\n```/;
const CUSTOM = ["i give you my own answer", "my own answer", "own answer", "custom answer", "something else", "other"];
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const nonempty = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const unique = (values: string[]) => [...new Set(values.map(v => v.trim()).filter(Boolean))];
function validOptions(v: unknown): v is InteractiveQuestionOption[] {
  return Array.isArray(v) && v.length > 0 && v.every(o => record(o) && nonempty(o.id) && typeof o.text === "string" &&
    (o.embed_id === undefined || nonempty(o.embed_id)) &&
    (o.embed_ids === undefined || Array.isArray(o.embed_ids) && o.embed_ids.every(nonempty))) &&
    new Set(v.map(o => o.id)).size === v.length;
}
export function parseInteractiveQuestionBlock(content: string): InteractiveQuestionPayload | null {
  const match = content.match(BLOCK);
  if (!match) return null;
  try { const value: unknown = JSON.parse(match[1]); return isInteractiveQuestionPayload(value) ? value : null; }
  catch { return null; }
}
export function isInteractiveQuestionPayload(v: unknown): v is InteractiveQuestionPayload {
  if (!record(v) || !nonempty(v.id)) return false;
  if (["question", "custom_placeholder", "comment_placeholder"].some(key => v[key] !== undefined && typeof v[key] !== "string")) return false;
  if (v.type === "choice") return nonempty(v.question) && validOptions(v.options) &&
    (v.multiple === undefined || typeof v.multiple === "boolean") &&
    (v.custom_option_id === undefined || nonempty(v.custom_option_id) && v.options.some(o => o.id === v.custom_option_id));
  if (v.type === "input") return Array.isArray(v.fields) && v.fields.length > 0 &&
    v.fields.every(f => record(f) && nonempty(f.id) && typeof f.label === "string" &&
      (f.required === undefined || typeof f.required === "boolean")) &&
    new Set(v.fields.map(f => f.id)).size === v.fields.length;
  if (v.type === "slider") return nonempty(v.question) && finite(v.min) && finite(v.max) && v.min <= v.max &&
    (v.step === undefined || finite(v.step) && v.step > 0) &&
    (v.default === undefined || finite(v.default) && v.default >= v.min && v.default <= v.max) &&
    (v.labels === undefined || record(v.labels) && Object.values(v.labels).every(x => typeof x === "string"));
  if (v.type === "swipe") return validOptions(v.cards);
  if (v.type === "rating") {
    const max = v.max_stars ?? v.max ?? v.scale ?? 5;
    return nonempty(v.question) && Number.isInteger(max) && (max as number) > 0 &&
      (v.require_comment === undefined || typeof v.require_comment === "boolean");
  }
  return false;
}
export function isCustomChoiceOption(question: InteractiveQuestionPayload, optionId: string): boolean {
  if (question.custom_option_id) return question.custom_option_id === optionId;
  const text = question.options?.find(o => o.id === optionId)?.text.trim().toLowerCase() ?? "";
  return CUSTOM.some(pattern => text === pattern || text.includes(pattern));
}
function inputValues(answer: InteractiveQuestionAnswer): Record<string, unknown> {
  return record(answer.inputs) ? answer.inputs : record(answer.values) ? answer.values : answer;
}
function swipeValues(answer: InteractiveQuestionAnswer): Record<string, unknown> {
  if (record(answer.swipes)) return answer.swipes;
  const liked = Array.isArray(answer.liked) ? answer.liked : [];
  const disliked = Array.isArray(answer.disliked) ? answer.disliked : [];
  return Object.fromEntries([...liked.map(id => [id, "like"]), ...disliked.map(id => [id, "dislike"])]);
}
/** Undefined means the answer is complete; the TUI separately tracks whether a slider was touched. */
export function validateInteractiveQuestionAnswer(q: InteractiveQuestionPayload, a: InteractiveQuestionAnswer): string | undefined {
  if (!isInteractiveQuestionPayload(q) || !record(a)) return "Invalid question or answer.";
  if (q.type === "choice") {
    const ids = a.selection;
    if (!Array.isArray(ids) || !ids.length || !ids.every(nonempty) || new Set(ids).size !== ids.length ||
      (!q.multiple && ids.length !== 1) || ids.some(id => !q.options!.some(o => o.id === id))) return "Select a valid option.";
    if (ids.some(id => isCustomChoiceOption(q, id)) && !nonempty(a.custom_answer)) return "Enter a custom answer.";
    return undefined;
  }
  if (q.type === "input") {
    const values = inputValues(a);
    if (q.fields!.some(f => f.required && !nonempty(values[f.id]))) return "Fill in every required field.";
    if (q.fields!.some(f => values[f.id] !== undefined && typeof values[f.id] !== "string")) return "Input values must be text.";
    return undefined;
  }
  if (q.type === "slider") {
    if (!finite(a.value) || a.value < q.min! || a.value > q.max!) return "Choose a value within the slider range.";
    const offset = (a.value - q.min!) / (q.step ?? 1);
    if (Math.abs(offset - Math.round(offset)) > 1e-7) return "Choose a value on the slider step.";
    return undefined;
  }
  if (q.type === "swipe") {
    const swipes = swipeValues(a), ids = q.cards!.map(c => c.id);
    if (Object.keys(swipes).length !== ids.length || ids.some(id => swipes[id] !== "like" && swipes[id] !== "dislike"))
      return "Review every card.";
    return undefined;
  }
  const max = q.max_stars ?? q.max ?? q.scale ?? 5;
  if (!Number.isInteger(a.rating) || (a.rating as number) < 1 || (a.rating as number) > max)
    return `Choose a rating from 1 to ${max}.`;
  if (q.require_comment && !nonempty(a.comment)) return "Enter a comment.";
  if (a.comment !== undefined && typeof a.comment !== "string") return "Comment must be text.";
  return undefined;
}
function embedIds(options: InteractiveQuestionOption[], ids: string[]): string[] {
  const selected = new Set(ids);
  return unique(options.filter(o => selected.has(o.id)).flatMap(o => o.embed_ids ?? (o.embed_id ? [o.embed_id] : [])));
}
function formatAnswer(q: InteractiveQuestionPayload, a: InteractiveQuestionAnswer): FormattedInteractiveAnswer {
  let displayText = "";
  let responsePayload: Record<string, unknown> = {id: q.id};
  if (q.type === "choice") {
    const selection = a.selection as string[], custom = typeof a.custom_answer === "string" ? a.custom_answer.trim() : "";
    const texts = q.options!.filter(o => selection.includes(o.id)).map(o => custom && isCustomChoiceOption(q, o.id) ? custom : o.text);
    displayText = q.multiple ? texts.join("\n") : texts[0] ?? "";
    const refs = embedIds(q.options!, selection);
    responsePayload = {id: q.id, selection, ...(custom && selection.some(id => isCustomChoiceOption(q, id)) ? {custom_answer: custom} : {}),
      ...(refs.length ? {embed_ids: refs} : {})};
  } else if (q.type === "input") {
    const source = inputValues(a);
    const inputs = Object.fromEntries(q.fields!.map(f => [f.id, typeof source[f.id] === "string" ? source[f.id] : ""]));
    displayText = q.fields!.map(f => inputs[f.id]).filter(Boolean).join("\n");
    responsePayload = {id: q.id, inputs};
  } else if (q.type === "slider") {
    const value = a.value as number, label = q.labels?.[value];
    displayText = label ? `${value} (${label})` : String(value);
    responsePayload = {id: q.id, value};
  } else if (q.type === "swipe") {
    const swipes = swipeValues(a), refs = embedIds(q.cards!, q.cards!.map(c => c.id));
    displayText = q.cards!.map(c => `${c.text}: ${swipes[c.id]}`).join("\n");
    responsePayload = {id: q.id, swipes, ...(refs.length ? {embed_ids: refs} : {})};
  } else {
    const rating = a.rating as number, max = q.max_stars ?? q.max ?? q.scale ?? 5;
    const comment = typeof a.comment === "string" ? a.comment.trim() : "";
    displayText = [`${rating}/${max}`, comment].filter(Boolean).join("\n");
    responsePayload = {id: q.id, rating, ...(comment ? {comment} : {})};
  }
  return {displayText, responsePayload,
    messageContent: `${displayText}\n\n\`\`\`interactive_response\n${JSON.stringify(responsePayload, null, 2)}\n\`\`\``};
}
export function formatInteractiveQuestionAnswer(q: InteractiveQuestionPayload, a: InteractiveQuestionAnswer): FormattedInteractiveAnswer {
  const error = validateInteractiveQuestionAnswer(q, a);
  if (error) throw new Error(error);
  return formatAnswer(q, a);
}
export function toWaitingForUserResult(params: {
  chatId: string; messageId: string; parentId?: string; question: InteractiveQuestionPayload;
}): WaitingForUserResult {
  return {status: "waiting_for_user", chat_id: params.chatId, message_id: params.messageId,
    parent_id: params.parentId, question: params.question};
}
