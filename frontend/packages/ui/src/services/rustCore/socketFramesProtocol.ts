/**
 * Request/response shapes and validators for the two shared-core chat-frame ops
 * (`ingest_socket_frames`, `admit_chat`). The Worker passes server frames to the
 * Rust core and returns only the core's counters; frame content never leaves the
 * Worker in a reply. Error codes are the core's fixed set.
 */
export const SOCKET_FRAME_MAX_COUNT = 64;
export const SOCKET_FRAME_MAX_BYTES = 192 * 1024;
const UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;

/** Fixed failure codes of the two ops (core codes, never free text). */
export const SOCKET_FRAME_FAILURES = [
  "invalid_frames", "invalid_chat_id", "local_profile_read_only", "forbidden", "chat_unknown", "chat_key_unavailable",
] as const;
export type SocketFrameFailure = typeof SOCKET_FRAME_FAILURES[number];

/** `queued` is set (appliedSeq null) when the Worker kept the frames because the client was busy. */
export interface SocketFrameSummary { appliedSeq: number | null; changedChats: { chatId: string; messagesV: number }[]; ignored: number; queued?: number }
export interface ChatAdmission { chatId: string; messagesV: number; historyRows: number }

function plain(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && Object.getPrototypeOf(value) === Object.prototype;
}
function closed(value: Record<string, unknown>, keys: string[]): boolean {
  const own = Object.keys(value);
  return own.length === keys.length && keys.every(key => Object.hasOwn(value, key));
}
function counter(value: unknown): value is number { return Number.isSafeInteger(value) && (value as number) >= 0; }

/** Shape check of the `frames` array of an `ingest_socket_frames` request. */
export function validSocketFrames(value: unknown): value is Record<string, unknown>[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > SOCKET_FRAME_MAX_COUNT) return false;
  if (!value.every(frame => plain(frame) && (typeof frame.type === "string" || typeof frame.event === "string"))) return false;
  try { return JSON.stringify(value).length <= SOCKET_FRAME_MAX_BYTES; } catch { return false; }
}
/** Shape check of `{chatId, teamId}` of an `admit_chat` request. */
export function validAdmitChatTarget(chatId: unknown, teamId: unknown): boolean {
  return typeof chatId === "string" && UUID.test(chatId)
    && (teamId === null || typeof teamId === "string" && teamId.length > 0 && teamId.length <= 64 && /^[A-Za-z0-9_-]+$/.test(teamId));
}
export function validSocketFrameSummary(value: unknown): value is SocketFrameSummary {
  const queued = plain(value) && Object.hasOwn(value, "queued");
  return plain(value) && closed(value, queued ? ["appliedSeq", "changedChats", "ignored", "queued"] : ["appliedSeq", "changedChats", "ignored"])
    && (queued ? value.appliedSeq === null && counter(value.queued) : counter(value.appliedSeq)) && counter(value.ignored)
    && Array.isArray(value.changedChats) && value.changedChats.length <= SOCKET_FRAME_MAX_COUNT
    && value.changedChats.every(row => plain(row) && closed(row, ["chatId", "messagesV"]) && typeof row.chatId === "string" && UUID.test(row.chatId) && counter(row.messagesV));
}
export function validChatAdmission(value: unknown): value is ChatAdmission {
  return plain(value) && closed(value, ["chatId", "messagesV", "historyRows"]) && typeof value.chatId === "string" && UUID.test(value.chatId)
    && counter(value.messagesV) && counter(value.historyRows);
}
/** Maps a thrown core code to the fixed failure, or null when it is not one of them. */
export function socketFrameFailure(error: unknown): SocketFrameFailure | null {
  return (SOCKET_FRAME_FAILURES as readonly unknown[]).includes(error) ? error as SocketFrameFailure : null;
}
