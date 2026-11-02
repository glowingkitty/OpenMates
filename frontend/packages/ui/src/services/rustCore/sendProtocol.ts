/** Closed projection of existing SDK StreamUpdate, never a second reducer. */
import { boundedJson } from "./savedReadProtocol";
type IDs = { chat_id: string; message_id: string };
export type SendUpdate = { Started: IDs & { expects_reply: boolean } } | { Submitted: IDs } | { Admitted: IDs }
  | { Content: { content: string; thinking: string; mate: string } } | { Completed: IDs & { content: string } }
  | { Status: string } | { Consent: { request_id: string; items: unknown[] } };
export type SendEvent = { type: "update"; update: SendUpdate } | { type: "completed"; chatId: string }
  | { type: "error"; error: "cancelled" | "session_expired" | "unavailable"; mayHaveSubmitted: true };
export type SendTerminalDisposition = Readonly<{ operationId:string; receiptId:string; scopeEpoch:number;
  outcome:"completed"|"cancelled"|"uncertain"|"backpressure"|"session_expired"|"unavailable";canContinueParent:boolean;originalTurnSettled:boolean }>;
export type SendReply = { operationId: string; kind: "started" | "cancel_requested" }
  | {operationId:string;kind:"closed";terminal?:SendTerminalDisposition}
  | { operationId: string; kind: "event"; event: SendEvent | null; terminal?: SendTerminalDisposition };
function record(v: unknown): v is Record<string, unknown> { return typeof v === "object" && v !== null && Object.getPrototypeOf(v) === Object.prototype; }
function exact(v: Record<string, unknown>, keys: string[]): boolean { const own = Object.keys(v); return own.length === keys.length && own.every(k => keys.includes(k)); }
function uuid(v: unknown): v is string { return typeof v === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(v); }
function text(v: unknown, cap: number): v is string { return typeof v === "string" && v.length <= cap && new TextEncoder().encode(v).byteLength <= cap; }
export function validSendEvent(v: unknown, chatId?: string): v is SendEvent {
  if (!record(v) || !boundedJson(v)) return false;
  if (v.type === "error") return exact(v, ["type", "error", "mayHaveSubmitted"]) && v.mayHaveSubmitted === true && ["cancelled", "session_expired", "unavailable"].includes(v.error as string);
  if (v.type === "completed") return exact(v, ["type", "chatId"]) && uuid(v.chatId) && (chatId === undefined || v.chatId === chatId);
  if (v.type !== "update" || !exact(v, ["type", "update"]) || !record(v.update) || Object.keys(v.update).length !== 1) return false;
  const [kind, payload] = Object.entries(v.update)[0];
  if (kind === "Status") return text(payload, 4096);
  if (!record(payload)) return false;
  if (kind === "Content") return exact(payload, ["content", "thinking", "mate"]) && text(payload.content, 64*1024) && text(payload.thinking, 64*1024) && text(payload.mate, 4096);
  if (kind === "Consent") return exact(payload, ["request_id", "items"]) && text(payload.request_id, 128) && Array.isArray(payload.items) && payload.items.length <= 64
    && payload.items.every(item => record(item) && exact(item, ["id", "title", "description", "status", "category", "fields"])
      && text(item.id, 128) && text(item.status, 4096) && text(item.title, 64*1024) && text(item.description, 64*1024) && text(item.category, 4096));
  const fields = kind === "Started" ? ["chat_id", "message_id", "expects_reply"] : kind === "Completed" ? ["chat_id", "message_id", "content"] : ["chat_id", "message_id"];
  return ["Started", "Submitted", "Admitted", "Completed"].includes(kind) && exact(payload, fields) && uuid(payload.chat_id) && uuid(payload.message_id)
    && (chatId === undefined || payload.chat_id === chatId) && (kind !== "Started" || typeof payload.expects_reply === "boolean") && (kind !== "Completed" || text(payload.content, 64*1024));
}
export function validSendTerminalDisposition(v:unknown):v is SendTerminalDisposition {
  return record(v)&&exact(v,["operationId","receiptId","scopeEpoch","outcome","canContinueParent","originalTurnSettled"])
    &&uuid(v.operationId)&&uuid(v.receiptId)&&Number.isSafeInteger(v.scopeEpoch)&&(v.scopeEpoch as number)>=0
    &&["completed","cancelled","uncertain","backpressure","session_expired","unavailable"].includes(v.outcome as string)
    &&typeof v.canContinueParent==="boolean"&&v.canContinueParent===(v.outcome==="completed"||v.outcome==="cancelled"||v.outcome==="uncertain"||v.outcome==="backpressure")
    &&typeof v.originalTurnSettled==="boolean"&&v.originalTurnSettled===(v.outcome==="completed"||v.outcome==="cancelled"||v.outcome==="backpressure");
}
export function validSendReply(v: unknown): v is SendReply {
  if (!record(v) || !uuid(v.operationId)) return false;
  return v.kind === "event" ? (exact(v, ["operationId", "kind", "event"]) || exact(v,["operationId","kind","event","terminal"]))
      && (v.event === null || validSendEvent(v.event))
      && (v.terminal===undefined || validSendTerminalDisposition(v.terminal)&&v.terminal.operationId===v.operationId
        &&(v.event===null||record(v.event)&&v.event.type!=="update"))
    : v.kind==="closed" ? (exact(v,["operationId","kind"])||exact(v,["operationId","kind","terminal"]))
      &&(v.terminal===undefined||validSendTerminalDisposition(v.terminal)&&v.terminal.operationId===v.operationId)
    : ["started", "cancel_requested"].includes(v.kind as string) && exact(v, ["operationId", "kind"]);
}
