/** Thin transport validation for the closed shared Rust saved-read DTO. */
const MAX_BYTES = 256 * 1024;
const MAX_ROWS = 20;
const chatText = ["title", "summary", "category", "slug", "activeFocusId", "parentId", "chatVisibility"] as const;
const chatNumbers = ["createdAt", "lastEditedAt", "metadataUpdatedAt"] as const;
const chatFlags = ["isSubChat", "isHidden", "pinned", "hasDraft"] as const;
const chatLists = ["participantUserHashes", "followUpSuggestions"] as const;
const messageText = ["storageId", "sourceMessageId", "clientMessageId", "rawStatus", "senderName", "category", "modelName", "thinkingSignature", "hashedUserId", "userMessageId", "queueMode", "queueDispatchStatus", "queueDispatchMode", "queueDispatchTaskId"] as const;
const messageNumbers = ["thinkingTokenCount", "keyVersion", "queueRevision"] as const;
type NullableFields<K extends readonly string[], T> = { [P in K[number]]: T | null };
export type SavedChatMetadata = { id: string } & NullableFields<typeof chatText, string> & NullableFields<typeof chatNumbers, number>
  & NullableFields<typeof chatFlags, boolean> & NullableFields<typeof chatLists, string[]>;
export type SavedMessageMetadata = { id: string; chatId: string; createdAt: number; hasThinking: boolean | null; embedIds: string[] | null }
  & NullableFields<typeof messageText, string> & NullableFields<typeof messageNumbers, number>;
export interface SavedReadCursor { chatId: string; scope: string; createdAt: number; messageId: string }
export interface SavedChatReadback {
  chat: { id: string; title: string; category: string; messages: Array<{ id: string; role: string; content: string; sender: string; thinking: string; embeds: [] }> };
  chatMetadata: SavedChatMetadata; messageMetadata: SavedMessageMetadata[];
  hasMoreBefore: boolean; hasMoreAfter: boolean; anchorFound: boolean;
  startCursor: SavedReadCursor | null; endCursor: SavedReadCursor | null;
  serverMessageCount: number | null; messagesVersion: number | null;
  oversizedMessage: boolean; oversizedMessageCursor: SavedReadCursor | null;
  payloadBytes: number; piiRestoration: "page_local"; historyComplete: false;
  piiMappingsByMessageId: Record<string, unknown[]>; contentMode: "page_local"; pagesRead: 1;
}
function record(v: unknown): v is Record<string, unknown> { return v !== null && typeof v === "object" && Object.getPrototypeOf(v) === Object.prototype; }
function exact(v: Record<string, unknown>, keys: readonly string[]): boolean { const own = Object.keys(v); return own.length === keys.length && own.every(k => keys.includes(k)); }
function text(v: unknown): v is string { return typeof v === "string" && v.length <= MAX_BYTES; }
function integer(v: unknown): v is number { return Number.isSafeInteger(v) && Number(v) >= 0; }
function uuid(v: unknown): v is string { return typeof v === "string" && v.length === 36 && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(v); }
type Identity = (value: unknown) => value is string;
/** Nonempty opaque UTF-8 read IDs; complete DTO/packet budgets bound size.
 * Preserve exact bytes; shape never grants chat/account authority. */
export function validReadMessageId(v: unknown): v is string {
  if (typeof v !== "string" || v.length === 0) return false;
  // Rust strings contain Unicode scalars. Refuse lone UTF-16 surrogates rather
  // than letting TextEncoder replace them and silently change resource bytes.
  for (let i = 0; i < v.length; i++) {
    const unit = v.charCodeAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = v.charCodeAt(++i);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) return false;
  }
  return true;
}
function nullable(v: unknown, check: (v: unknown) => boolean): boolean { return v === null || check(v); }
function array(v: unknown): v is unknown[] { return Array.isArray(v) && Object.getPrototypeOf(v) === Array.prototype && Object.keys(v).length === v.length; }
function texts(v: unknown): boolean { return array(v) && v.length <= 4096 && v.every(text); }
function cursor(v: unknown, chatId: string, identity: Identity = validReadMessageId): boolean {
  return v === null || record(v) && exact(v, ["chatId", "scope", "createdAt", "messageId"]) && v.chatId === chatId
    && typeof v.scope === "string" && v.scope.length === 64 && /^[a-f0-9]{64}$/i.test(v.scope) && integer(v.createdAt) && identity(v.messageId);
}
/** Bound plain JSON before serializing it; never accept native objects/accessors. */
export function boundedJson(value: unknown): boolean {
  let nodes = 0, units = 0;
  const walk = (v: unknown, depth: number): boolean => {
    if (++nodes > 16384 || depth > 32) return false;
    if (v === null || typeof v === "boolean") return true;
    if (typeof v === "number") return Number.isFinite(v);
    if (typeof v === "string") { units += v.length; return units <= MAX_BYTES; }
    const isArray = array(v);
    if (!record(v) && !isArray) return false;
    const descriptors = Object.getOwnPropertyDescriptors(v);
    return Object.entries(descriptors).every(([key, item]) => {
      if (isArray && key === "length") return true;
      units += key.length;
      return units <= MAX_BYTES && "value" in item && !item.get && !item.set && walk(item.value, depth + 1);
    });
  };
  try { return walk(value, 0) && new TextEncoder().encode(JSON.stringify(value)).byteLength + 8192 <= MAX_BYTES; } catch { return false; }
}
export function validSavedRead(v: unknown): v is SavedChatReadback { return savedReadWithIdentity(v, validReadMessageId); }
function savedReadWithIdentity(v: unknown, identity: Identity): v is SavedChatReadback {
  if (!record(v) || !exact(v, ["chat", "chatMetadata", "messageMetadata", "hasMoreBefore", "hasMoreAfter", "anchorFound", "startCursor", "endCursor", "serverMessageCount", "messagesVersion", "oversizedMessage", "oversizedMessageCursor", "payloadBytes", "piiRestoration", "historyComplete", "piiMappingsByMessageId", "contentMode", "pagesRead"])) return false;
  if (!validSavedReadData(v, identity)) return false;
  const c = v.chat;
  return ["hasMoreBefore", "hasMoreAfter", "anchorFound", "oversizedMessage"].every(k => typeof v[k] === "boolean")
    && ["startCursor", "endCursor", "oversizedMessageCursor"].every(k => cursor(v[k], c.id as string, identity))
    && nullable(v.serverMessageCount, integer) && nullable(v.messagesVersion, integer) && integer(v.payloadBytes) && v.payloadBytes <= MAX_BYTES
    && v.historyComplete === false && v.piiRestoration === "page_local" && v.contentMode === "page_local" && v.pagesRead === 1;
}

/** Closed checkpoint presentation, never ciphertext or a complete inventory.
 * Stored summary placeholders are not restored from arbitrary message mappings.
 */
export const MAX_RETAINED_CHECKPOINTS=128;
export interface CheckpointPresentation {
  source:"local_profile"; coverage:"retained_latest"|"retained_selected"; historyComplete:false; piiRestoration:"stored"; retainedCheckpointCount:number;
  checkpoint:null|{id:string;chatId:string;createdAt:number;compressedUpToTimestamp:number;compressedMessageCount:number;
    summaryState:"loaded"|"missing"|"unavailable"|"not_loaded";summary:string|null;summaryUnavailableReason:"corrupt"|"oversized"|null};
}
export function validCheckpointPresentation(value:unknown,chatId:string,coverage?:CheckpointPresentation["coverage"]):value is CheckpointPresentation{
  if(!record(value)||!boundedJson(value)||!exact(value,["source","coverage","historyComplete","piiRestoration","retainedCheckpointCount","checkpoint"])
    ||value.source!=="local_profile"||!['retained_latest','retained_selected'].includes(String(value.coverage))||coverage!==undefined&&value.coverage!==coverage
    ||value.historyComplete!==false||value.piiRestoration!=="stored"||!integer(value.retainedCheckpointCount)||Number(value.retainedCheckpointCount)>MAX_RETAINED_CHECKPOINTS)return false;
  const row=value.checkpoint;
  if(row===null)return value.coverage==="retained_selected"||value.retainedCheckpointCount===0;
  if(!record(row)||!exact(row,["id","chatId","createdAt","compressedUpToTimestamp","compressedMessageCount","summaryState","summary","summaryUnavailableReason"])
    ||!validReadMessageId(row.id)||row.chatId!==chatId||!uuid(row.chatId)||!integer(row.createdAt)||!integer(row.compressedUpToTimestamp)||!integer(row.compressedMessageCount)||Number(value.retainedCheckpointCount)<1)return false;
  if(row.summaryState==="loaded")return text(row.summary)&&row.summary!==""&&row.summaryUnavailableReason===null;
  return row.summary===null&&(row.summaryState==="unavailable"?['corrupt','oversized'].includes(String(row.summaryUnavailableReason)):
    ['missing','not_loaded'].includes(String(row.summaryState))&&row.summaryUnavailableReason===null);
}

/** Explicit local transport variant; nullable retained boundaries remain unknown.
 * This validates a Rust DTO only and never upgrades its provenance or authority. */
export interface LocalChatReadback {
  source: "local_profile"; readOnly: true; cached: true; fresh: false;
  historyComplete: false; coverage: "retained_only";
  chat: SavedChatReadback["chat"]; hasMoreBefore: boolean | null; hasMoreAfter: boolean | null;
  anchorFound: boolean; startCursor: SavedReadCursor | null; endCursor: SavedReadCursor | null;
  payloadBytes: number; piiRestoration: "page_local";
  checkpointPresentation?: CheckpointPresentation;
  chatMetadata?: SavedChatMetadata; messageMetadata?: SavedMessageMetadata[];
  piiMappingsByMessageId?: Record<string, unknown[]>; contentMode?: "page_local"; pagesRead?: 0;
}
export function validLocalRead(v: unknown, saved?: boolean): v is LocalChatReadback {
  const keys = ["source", "readOnly", "cached", "fresh", "historyComplete", "coverage", "chat", "hasMoreBefore", "hasMoreAfter", "anchorFound", "startCursor", "endCursor", "payloadBytes", "piiRestoration"];
  const extra = ["chatMetadata", "messageMetadata", "piiMappingsByMessageId", "contentMode", "pagesRead", ...(record(v)&&"checkpointPresentation" in v?["checkpointPresentation"]:[])];
  if (!record(v) || !boundedJson(v)) return false;
  const rich = "chatMetadata" in v;
  if (saved !== undefined && rich !== saved || !exact(v, rich ? [...keys, ...extra] : keys)
    || v.source !== "local_profile" || v.readOnly !== true || v.cached !== true || v.fresh !== false
    || v.historyComplete !== false || v.coverage !== "retained_only" || v.piiRestoration !== "page_local"
    || ![v.hasMoreBefore, v.hasMoreAfter].every(item => item === null || typeof item === "boolean")
    || typeof v.anchorFound !== "boolean" || !integer(v.payloadBytes) || v.payloadBytes > MAX_BYTES) return false;
  const c = v.chat;
  if (!record(c) || !exact(c, ["id", "title", "category", "messages"]) || !uuid(c.id)
    || !text(c.title) || new TextEncoder().encode(c.title).byteLength > 4096 || !text(c.category)
    || !array(c.messages) || c.messages.length > MAX_ROWS
    || !cursor(v.startCursor, c.id, validReadMessageId) || !cursor(v.endCursor, c.id, validReadMessageId)) return false;
  const ids = new Set<string>();
  for (const m of c.messages) {
    if (!record(m) || !exact(m, ["id", "role", "content", "sender", "thinking", "embeds"])
      || !validReadMessageId(m.id) || ids.has(m.id) || !text(m.role) || !m.role || new TextEncoder().encode(m.role).byteLength > 32
      || !text(m.content) || new TextEncoder().encode(m.content).byteLength > 64 * 1024
      || !text(m.sender) || !text(m.thinking) || !array(m.embeds) || m.embeds.length !== 0) return false;
    ids.add(m.id);
  }
  if (!rich) return true;
  if ("checkpointPresentation" in v&&!validCheckpointPresentation(v.checkpointPresentation,c.id,"retained_latest"))return false;
  if (v.contentMode !== "page_local" || v.pagesRead !== 0) return false;
  // Reuse metadata/mapping shape validation. The temporary parser-only values
  // never leave this function; the returned local DTO retains nulls and tags.
  return savedReadWithIdentity({chat:c,chatMetadata:v.chatMetadata,messageMetadata:v.messageMetadata,
    piiMappingsByMessageId:v.piiMappingsByMessageId,hasMoreBefore:false,hasMoreAfter:false,
    anchorFound:v.anchorFound,startCursor:v.startCursor,endCursor:v.endCursor,payloadBytes:v.payloadBytes,
    serverMessageCount:null,messagesVersion:null,oversizedMessage:false,oversizedMessageCursor:null,
    historyComplete:false,piiRestoration:"page_local",contentMode:"page_local",pagesRead:1}, validReadMessageId);
}

/** Common data fields only. Each caller separately validates its own exact
 * envelope, source, range/completeness and authority flags. No DTO coercion. */
export type SavedReadData = Pick<SavedChatReadback, "chat"|"chatMetadata"|"messageMetadata"|"piiMappingsByMessageId">;
export function validSavedReadData(v: unknown, identity: Identity = validReadMessageId): v is SavedReadData & Record<string, unknown> {
  if (!record(v) || !boundedJson(v)) return false;
  const c = v.chat;
  if (!record(c) || !exact(c, ["id", "title", "category", "messages"]) || !uuid(c.id) || !text(c.title) || new TextEncoder().encode(c.title).byteLength > 4096 || !text(c.category)
    || !array(c.messages) || c.messages.length > MAX_ROWS || !array(v.messageMetadata) || v.messageMetadata.length !== c.messages.length) return false;
  const h = v.chatMetadata;
  if (!record(h) || !exact(h, ["id", ...chatText, ...chatNumbers, ...chatFlags, ...chatLists]) || h.id !== c.id
    || !chatText.every(k => nullable(h[k], text)) || !chatNumbers.every(k => nullable(h[k], integer))
    || !chatFlags.every(k => nullable(h[k], v => typeof v === "boolean")) || !chatLists.every(k => nullable(h[k], texts))) return false;
  const ids = new Set<string>();
  for (let index = 0; index < c.messages.length; index++) {
    const m = c.messages[index], meta = v.messageMetadata[index];
    if (!record(m) || !exact(m, ["id", "role", "content", "sender", "thinking", "embeds"]) || !identity(m.id) || ids.has(m.id)
      || !text(m.role) || !m.role || new TextEncoder().encode(m.role).byteLength > 32 || !text(m.content) || new TextEncoder().encode(m.content).byteLength > 64 * 1024
      || !text(m.sender) || !text(m.thinking) || !array(m.embeds) || m.embeds.length !== 0) return false;
    ids.add(m.id);
    if (!record(meta) || !exact(meta, ["id", "chatId", "createdAt", "hasThinking", "embedIds", ...messageText, ...messageNumbers])
      || meta.id !== m.id || meta.chatId !== c.id || !integer(meta.createdAt) || !nullable(meta.hasThinking, v => typeof v === "boolean")
      || !nullable(meta.embedIds, texts) || !messageText.every(k => nullable(meta[k], text)) || !messageNumbers.every(k => nullable(meta[k], integer))) return false;
  }
  return record(v.piiMappingsByMessageId) && Object.entries(v.piiMappingsByMessageId).every(([id, maps]) => ids.has(id) && array(maps));
}
