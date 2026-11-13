/// <reference lib="es2022.object" />
import {validBrowserCacheScope,validBrowserCachedMetadataRead,validBrowserRetainedRead,validBrowserIncomingCacheUpdate,validBrowserCacheSourceEvidence} from './browserCacheProtocol';
import type {BrowserCacheScope,BrowserCachedMetadataRead,BrowserRetainedRead,BrowserIncomingCacheUpdate,BrowserCacheSourceEvidence} from './browserCacheProtocol';
import type {CheckpointPresentation} from "./savedReadProtocol";
import {validCheckpointPresentation} from "./savedReadProtocol";
import {validCredentialCasScope,validCredentialCasValidation} from "./credentialCasProtocol";
import type {CredentialCasScope,CredentialCasValidation} from "./credentialCasProtocol";
import { validBrowserSealedCredentials } from "./browserCredentialStorage";
import type { BrowserSealedCredentials } from "./browserCredentialStorage";
import { validSendReply } from "./sendProtocol";
import type { SendReply } from "./sendProtocol";
import { validSavedRead, validLocalRead, validReadMessageId, boundedJson } from "./savedReadProtocol";
import type { SavedReadCursor, SavedChatReadback, LocalChatReadback } from "./savedReadProtocol";
/** Inactive browser-core transport contract. Never carry native sessions or raw keys. */
export const RPC_VERSION = 1;
export const MAX_PENDING_REQUESTS = 32;
export const MAX_RPC_BYTES = 16 * 1024;
export const MAX_REQUEST_MS = 30_000;
/** Initial actor plus bounded native storage only; ordinary deadlines stay held. */
export const MAX_INITIAL_SYNC_REQUEST_MS = 300_000;
/** New password KDF admission only; existing RPC deadlines stay unchanged. */
export const MAX_PASSWORD_REQUEST_MS = 90_000;
export const MAX_PASSWORD_BYTES = 16 * 1024;
export const MAX_PASSWORD_RPC_BYTES = MAX_PASSWORD_BYTES + 2048;

export type BrowserPersistence = "memory_only" | "persisted";
export type CoreFailure = "invalid_request" | "unavailable" | "cancelled" | "deadline" | "session_expired" | "reauthentication_required" | "chat_unavailable" | "credential_conflict" | "authentication_failed" | "two_factor_required";

export const MAX_CHAT_MESSAGES = 20;
export const MAX_CHAT_UTF8_BYTES = 256 * 1024;
/** One latest viewing page; never an authoritative full-history/cache snapshot. */
export interface ChatReadback { id: string; title: string; messages: Array<{ id: string; role: string; content: string }>;
  historyComplete: false; piiRestoration: "page_local"; hasMoreBefore: boolean; hasMoreAfter: boolean }

export interface SessionStatus {
  handle: string;
  principal: string;
  generation: number;
  persistence: BrowserPersistence;
  /** Present only on explicit existing-key mode; local cache is not server auth. */
  localReadOnly?: boolean;
}

/** Local profile evidence, captured before the core's fresh server check; never authority. */
export interface ProfileEvidence {
  principal: string;
  encryptedEmail: string;
  userEmailSalt: string;
}

export interface ExistingProfileEvidence {
  principal: string;
  hashedEmail: string | null;
  userEmailSalt: string | null;
}
interface Envelope { version: 1; id: number }
export type CoreRequest = Envelope & (
  | { operation: "login_password"; email: string; password: Uint8Array; tfa: Uint8Array | null; stayLoggedIn?: boolean }
  | { operation: "check_first_session_data";deviceSignals:Record<string,string|null>;deadlineEpochMs:number }
  | { operation: "check_first_session"; key:CryptoKey; profile:ExistingProfileEvidence; persistence:"memory_only";deviceSignals:Record<string,string|null>;deadlineEpochMs:number }
  | { operation: "restore_existing"; key: CryptoKey; profile: ExistingProfileEvidence; persistence: "memory_only" }
  /** Local-only admission of the same key: no server call, cached reads only; `restore_existing` follows on the same Worker. */
  | { operation: "restore_local"; key: CryptoKey; profile: ExistingProfileEvidence; persistence: "memory_only" }
  | { operation: "restore"; key: CryptoKey; profile: ProfileEvidence; persistence: BrowserPersistence }
  | { operation: "rotate_credentials"; handle:string; generation:number; scope:CredentialCasScope }
  | { operation: "prepare_credentials"; handle: string; generation: number }
  | { operation: "validate_credentials"; handle: string; generation: number; snapshot: BrowserSealedCredentials }
  | { operation: "read_local_chat" | "read_local_saved_chat"; handle: string; generation: number; chatId: string; expectedPrincipal: string; encryptedRows: unknown }
  | { operation: "read_local_saved_chat_cursor"; handle: string; generation: number; chatId: string; expectedPrincipal: string; selector: LocalCursorSelector }
  /** Online session: Rust renders its own retained IndexedDB rows (readonly plans) before the server reconcile. */
  | { operation: "read_online_cached_saved_chat"; handle: string; generation: number; chatId: string; expectedPrincipal: string; selector: LocalCursorSelector }
  | { operation: "read_local_checkpoint_summary"; handle:string; generation:number; chatId:string; expectedPrincipal:string; checkpointId:string }
  | { operation: "read_saved_chat_page"; handle: string; generation: number; chatId: string; selector: SavedPageSelector }
  | { operation: "read_saved_chat"; handle: string; generation: number; chatId: string }
  | { operation: "start_new_send"; handle: string; generation: number; text: string }
  | { operation: "start_send"; handle: string; generation: number; chatId: string; text: string }
  | { operation:'store_selected_main_code_embed';handle:string;generation:number;recoveryRequestId:number;embedId:string }
  | { operation: "next_send_event" | "cancel_send" | "close_send"; handle: string; generation: number; operationId: string }
  | { operation: "restore_cached_metadata"; handle:string; generation:number; expectedPrincipal:string; chatIds:string[]; scope:BrowserCacheScope }
  | { operation: "read_cached_chat_items"; handle:string; generation:number; expectedPrincipal:string; chatIds:string[] }
  | { operation: "read_retained_saved_chat"; handle:string; generation:number; expectedPrincipal:string; chatId:string; scope:BrowserCacheScope; selector:SavedPageSelector }
  | { operation:'read_cold_retained_saved_chat'|'read_monitored_retained_saved_chat';handle:string;generation:number;expectedPrincipal:string;chatId:string;scope:BrowserCacheScope;selector:SavedPageSelector;nowSeconds:number;ownedCache?:true;localFirst?:true;profileCache?:true }
  | { operation:'read_cache_monitor_update';handle:string;generation:number;expectedPrincipal:string;monitorId:string;chatId:string;scope:BrowserCacheScope;selector:SavedPageSelector;nowSeconds:number;ownedCache?:true;localFirst?:true;profileCache?:true }
  | { operation:'run_initial_sync';handle:string;generation:number;expectedPrincipal:string }
  | { operation:'start_cache_monitor';handle:string;generation:number;expectedPrincipal:string }
  | { operation:'stop_cache_monitor'|'wait_cache_monitor';handle:string;generation:number;expectedPrincipal:string;monitorId:string }
  | { operation:"set_foreground_recovery";handle:string;generation:number;expectedPrincipal:string;enabled:boolean }
  | { operation: "status"; handle: string; generation: number }
  | { operation: "reconnect_chat"; handle: string; generation: number; chatId: string }
  | { operation: "open_chat"; handle: string; generation: number; chatId: string }
  | { operation: "invalidate" }
  | { operation: "cancel"; requestId: number }
);
export type CoreResponse = Envelope & (
  | { ok: true; status: SessionStatus | null; firstSession?:{httpStatus:number|null;data:Record<string,unknown>|null}; chat?: ChatReadback; savedRead?: SavedChatReadback; localRead?: LocalChatReadback; onlineCachedRead?: LocalChatReadback; checkpointRead?:CheckpointPresentation; cachedMetadata?:BrowserCachedMetadataRead; retainedRead?:BrowserRetainedRead;cacheSourceEvidence?:BrowserCacheSourceEvidence; cacheMonitor?:{id:string;state:'started'|'ready'|'idle'|'closed'}; cacheMonitorId?:string; initialSync?:{receivedMetadataCount:number;storedMetadataCount:number}; cacheUpdate?:BrowserIncomingCacheUpdate; send?: SendReply; snapshot?: BrowserSealedCredentials; credentialCas?:CredentialCasValidation }
  | { ok: false; error: CoreFailure;profileCacheAbsent?:true }
);

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && Object.getPrototypeOf(value) === Object.prototype;
}
function exact(value: Record<string, unknown>, keys: string[]): boolean {
  const own = Object.keys(value);
  return own.length === keys.length && own.every((key) => keys.includes(key));
}
function identifier(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value);
}
function integer(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) > 0;
}
function persistence(value: unknown): value is BrowserPersistence {
  return value === "memory_only" || value === "persisted";
}

function boundedMetadata(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 512;
}

function encryptedEmail(value: unknown): value is string {
  return typeof value === "string" && value.length >= 40 && value.length <= 8192
    && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value);
}

function withinByteCap(strings: string[]): boolean {
  // Reserve more than the complete fixed envelope/numeric overhead. Never
  // stringify an input object (including CryptoKey, getters or native sessions).
  const encoder = new TextEncoder();
  return strings.reduce((bytes, value) => bytes + encoder.encode(value).byteLength, 1024) <= MAX_RPC_BYTES;
}

export function validProfile(value: unknown): value is ProfileEvidence {
  return record(value) && exact(value, ["principal", "encryptedEmail", "userEmailSalt"])
    && identifier(value.principal) && encryptedEmail(value.encryptedEmail) && boundedMetadata(value.userEmailSalt)
    && withinByteCap([value.principal, value.encryptedEmail, value.userEmailSalt]);
}

function closedData(value:Record<string,unknown>,keys:string[]):boolean {
  const own=Reflect.ownKeys(value);
  return own.length===keys.length&&own.every(key=>typeof key==="string"&&keys.includes(key)
    &&Object.getOwnPropertyDescriptor(value,key)?.enumerable===true&&"value"in Object.getOwnPropertyDescriptor(value,key)!);
}
export function validExistingProfile(value: unknown): value is ExistingProfileEvidence {
  return record(value) && closedData(value,["principal","hashedEmail","userEmailSalt"])
    && typeof value.principal==="string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value.principal)
    && [value.hashedEmail,value.userEmailSalt].every(item=>item===null||typeof item==="string"&&new TextEncoder().encode(item).byteLength<=512);
}
export function validStatus(value: unknown): value is SessionStatus {
  return record(value) && (exact(value, ["handle", "principal", "generation", "persistence"])
    || exact(value,["handle","principal","generation","persistence","localReadOnly"]) && typeof value.localReadOnly==="boolean")
    && identifier(value.handle) && identifier(value.principal) && integer(value.generation) && persistence(value.persistence);
}

export function validChat(value: unknown): value is ChatReadback {
  const uuid = (value: unknown) => typeof value === "string" && value.length === 36 && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value);
  if (!record(value) || !exact(value, ["id", "title", "messages", "historyComplete", "piiRestoration", "hasMoreBefore", "hasMoreAfter"]) || !uuid(value.id)
    || value.historyComplete !== false || value.piiRestoration !== "page_local"
    || typeof value.hasMoreBefore !== "boolean" || typeof value.hasMoreAfter !== "boolean"
    || typeof value.title !== "string" || value.title.length > 4096 || !Array.isArray(value.messages)
    || value.messages.length < 1 || value.messages.length > MAX_CHAT_MESSAGES
    || Object.getPrototypeOf(value.messages) !== Array.prototype || Object.keys(value.messages).length !== value.messages.length) return false;
  const encoder = new TextEncoder(); let bytes = 8192 + encoder.encode(value.id as string).byteLength + encoder.encode(value.title).byteLength;
  if (encoder.encode(value.title).byteLength > 4096) return false;
  for (const row of value.messages) {
    if (!record(row) || !exact(row, ["id", "role", "content"]) || !validReadMessageId(row.id)
      || typeof row.role !== "string" || !row.role || row.role.length > 32 || typeof row.content !== "string" || row.content.length > 64 * 1024) return false;
    const role = encoder.encode(row.role).byteLength, content = encoder.encode(row.content).byteLength;
    if (role > 32 || content > 64 * 1024) return false;
    bytes += encoder.encode(row.id as string).byteLength + role + content;
    if (bytes > MAX_CHAT_UTF8_BYTES) return false;
  }
  return bytes <= MAX_CHAT_UTF8_BYTES;
}

/** Fixed, privately owned transfer buffers; no SharedArrayBuffer or hidden tail. */
function passwordBytes(value: unknown, cap: number): value is Uint8Array {
  return value instanceof Uint8Array && Object.getPrototypeOf(value) === Uint8Array.prototype
    && value.buffer instanceof ArrayBuffer && Object.getPrototypeOf(value.buffer) === ArrayBuffer.prototype
    && value.byteOffset === 0 && value.byteLength > 0 && value.byteLength <= cap
    && value.byteLength === value.buffer.byteLength
    && !(value.buffer as ArrayBuffer & {resizable?: boolean}).resizable
    && Object.keys(value).length === value.byteLength;
}
/** Consume request-owned references only. Never stringify credentials or errors.
 * The caller's original UI string is outside this transport's ownership.
 */
export function clearPasswordRequest(value: unknown): void {
  if (typeof value !== "object" || value === null) return;
  if (Object.getOwnPropertyDescriptor(value,"operation")?.value !== "login_password") return;
  for (const key of ["password","tfa"]) {
    const bytes=Object.getOwnPropertyDescriptor(value,key)?.value;
    if (bytes instanceof Uint8Array && bytes.buffer instanceof ArrayBuffer && bytes.byteLength<=(key==="password"?MAX_PASSWORD_BYTES:128)) {
      try { bytes.fill(0); } catch { /* A successful transfer already detached it. */ }
    }
    try { (value as Record<string,unknown>)[key]=key==="tfa"?null:new Uint8Array(0); } catch { /* Caller-owned immutable container. */ }
  }
  try { (value as Record<string,unknown>).email=""; } catch { /* No retained transport reference. */ }
}

/** Release request-owned resource references. CryptoKey bytes are never inspected. */
export function clearExistingKeyRequest(value: unknown): void {
  if(typeof value!=="object"||value===null||!["restore_existing","restore_local","check_first_session"].includes(Object.getOwnPropertyDescriptor(value,"operation")?.value))return;
  for(const name of ["key","profile"]){if(!("value"in (Object.getOwnPropertyDescriptor(value,name)||{})))continue;try{(value as Record<string,unknown>)[name]=null;}catch{/* caller-owned immutable container */}}
}

/** Validate metadata structurally, without serializing a CryptoKey or arbitrary input. */
export function validRequest(value: unknown): value is CoreRequest {
  if (!record(value) || value.version !== RPC_VERSION || !integer(value.id)) return false;
  const base = ["version", "id", "operation"];
  switch (value.operation) {
    case "login_password":
      return (exact(value,[...base,"email","password","tfa"]) || exact(value,[...base,"email","password","tfa","stayLoggedIn"]) && typeof value.stayLoggedIn === "boolean")
        && typeof value.email === "string" && value.email.length > 0
        && new TextEncoder().encode(value.email).byteLength <= 512
        && passwordBytes(value.password,MAX_PASSWORD_BYTES)
        && (value.tfa === null || passwordBytes(value.tfa,128) && value.tfa.buffer !== value.password.buffer)
        && new TextEncoder().encode(value.email).byteLength + value.password.byteLength
          // tfa is null or a Uint8Array already validated by passwordBytes above.
          + (value.tfa === null ? 0 : (value.tfa as Uint8Array).byteLength) + 1024 <= MAX_PASSWORD_RPC_BYTES;

    case "check_first_session_data":
      return closedData(value,[...base,"deviceSignals","deadlineEpochMs"])
        &&Number.isSafeInteger(value.deadlineEpochMs)&&Number(value.deadlineEpochMs)>0&&validFirstSessionSignals(value.deviceSignals);
    case "check_first_session":
      return closedData(value,[...base,"key","profile","persistence","deviceSignals","deadlineEpochMs"])&&value.persistence==='memory_only'
        &&validExistingProfile(value.profile)&&typeof CryptoKey!=='undefined'&&value.key instanceof CryptoKey
        &&Number.isSafeInteger(value.deadlineEpochMs)&&Number(value.deadlineEpochMs)>0&&validFirstSessionSignals(value.deviceSignals);
    case "restore_existing": case "restore_local":
      return closedData(value,[...base,"key","profile","persistence"]) && value.persistence==="memory_only"
        && validExistingProfile(value.profile) && typeof CryptoKey!=="undefined" && value.key instanceof CryptoKey;
    case "restore":
      return exact(value, [...base, "key", "profile", "persistence"])
        && validProfile(value.profile) && persistence(value.persistence)
        && typeof CryptoKey !== "undefined" && value.key instanceof CryptoKey;
    case "set_foreground_recovery":
      return closedData(value,[...base,"handle","generation","expectedPrincipal","enabled"])&&identifier(value.handle)&&integer(value.generation)&&localCursorUuid(value.expectedPrincipal)&&typeof value.enabled==="boolean";
    case 'store_selected_main_code_embed':
      return closedData(value,[...base,'handle','generation','recoveryRequestId','embedId'])&&identifier(value.handle)&&integer(value.generation)
        &&integer(value.recoveryRequestId)&&Number(value.recoveryRequestId)>0&&Number(value.recoveryRequestId)<Number(value.id)&&localCursorUuid(value.embedId);
    case "start_new_send": return closedData(value,[...base,"handle","generation","text"]) && identifier(value.handle) && integer(value.generation)
      && typeof value.text==="string" && value.text.trim().length>0 && new TextEncoder().encode(value.text).byteLength<=8192
      && withinByteCap([value.handle as string,value.text]);
    case "start_send": return exact(value, [...base, "handle", "generation", "chatId", "text"]) && identifier(value.handle) && integer(value.generation)
      && typeof value.chatId === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value.chatId)
      && typeof value.text === "string" && value.text.trim().length > 0 && new TextEncoder().encode(value.text).byteLength <= 8192
      && withinByteCap([value.handle as string, value.chatId, value.text]);
    case "next_send_event": case "cancel_send": case "close_send":
      return exact(value, [...base, "handle", "generation", "operationId"]) && identifier(value.handle) && integer(value.generation)
        && typeof value.operationId === "string" && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value.operationId);
    case "restore_cached_metadata": case "read_cached_chat_items":
      return closedData(value,[...base,'handle','generation','expectedPrincipal','chatIds',...(value.operation==='restore_cached_metadata'?['scope']:[])])
        &&boundedJson(value)&&identifier(value.handle)&&integer(value.generation)&&localCursorUuid(value.expectedPrincipal)
        &&Array.isArray(value.chatIds)&&value.chatIds.length>0&&value.chatIds.length<=20&&value.chatIds.every(localCursorUuid)
        &&new Set(value.chatIds).size===value.chatIds.length&&(value.operation==='read_cached_chat_items'||validBrowserCacheScope(value.scope))&&boundedJson(value);
    case 'run_initial_sync':
      return closedData(value,[...base,'handle','generation','expectedPrincipal'])&&identifier(value.handle)&&integer(value.generation)&&localCursorUuid(value.expectedPrincipal);
    case 'start_cache_monitor':case 'stop_cache_monitor':case 'wait_cache_monitor':
      return closedData(value,[...base,'handle','generation','expectedPrincipal',...(value.operation==='start_cache_monitor'?[]:['monitorId'])])&&(value.operation==='start_cache_monitor'||localCursorUuid(value.monitorId))&&identifier(value.handle)&&integer(value.generation)&&localCursorUuid(value.expectedPrincipal);
    case 'read_cold_retained_saved_chat':case 'read_monitored_retained_saved_chat':case 'read_cache_monitor_update':
      return closedData(value,[...base,'handle','generation','expectedPrincipal','chatId','scope','selector','nowSeconds',...(value.operation==='read_cache_monitor_update'?['monitorId']:[]),...(Object.hasOwn(value,'ownedCache')?['ownedCache']:[]),...(Object.hasOwn(value,'localFirst')?['localFirst']:[]),...(Object.hasOwn(value,'profileCache')?['profileCache']:[])])&&(!Object.hasOwn(value,'profileCache')||value.profileCache===true&&!Object.hasOwn(value,'localFirst')&&value.operation==='read_cold_retained_saved_chat'&&value.ownedCache===true&&record(value.selector)&&value.selector.direction==='latest')&&(!Object.hasOwn(value,'localFirst')||value.localFirst===true&&value.operation==='read_cold_retained_saved_chat'&&value.ownedCache===true&&record(value.selector)&&value.selector.direction==='latest')&&(!Object.hasOwn(value,'ownedCache')||value.ownedCache===true&&value.operation!=='read_monitored_retained_saved_chat')&&(value.operation!=='read_cache_monitor_update'||localCursorUuid(value.monitorId))&&identifier(value.handle)&&integer(value.generation)&&localCursorUuid(value.expectedPrincipal)&&localCursorUuid(value.chatId)&&validBrowserCacheScope(value.scope)&&validSavedPageSelector(value.selector,value.chatId)&&Number.isSafeInteger(value.nowSeconds)&&Number(value.nowSeconds)>=0&&boundedJson(value);
    case "read_retained_saved_chat":
      return closedData(value,[...base,'handle','generation','expectedPrincipal','chatId','scope','selector'])&&identifier(value.handle)&&integer(value.generation)
        &&localCursorUuid(value.expectedPrincipal)&&localCursorUuid(value.chatId)&&validBrowserCacheScope(value.scope)&&validSavedPageSelector(value.selector,value.chatId)&&boundedJson(value);
    case "read_saved_chat_page":
      return closedData(value,[...base,"handle","generation","chatId","selector"])&&identifier(value.handle)&&integer(value.generation)
        &&typeof value.chatId==="string"&&value.chatId.length===36&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value.chatId)
        &&boundedJson(value.selector)&&validSavedPageSelector(value.selector,value.chatId);
    case "read_local_checkpoint_summary":
      return closedData(value,[...base,"handle","generation","chatId","expectedPrincipal","checkpointId"])&&identifier(value.handle)&&integer(value.generation)
        &&localCursorUuid(value.chatId)&&localCursorUuid(value.expectedPrincipal)&&validReadMessageId(value.checkpointId)&&boundedJson(value);
    case "read_local_saved_chat_cursor": case "read_online_cached_saved_chat":
      return closedData(value, [...base,"handle","generation","chatId","expectedPrincipal","selector"])
        && identifier(value.handle) && integer(value.generation)
        && typeof value.chatId === "string" && value.chatId.length === 36 && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value.chatId)
        && typeof value.expectedPrincipal === "string" && value.expectedPrincipal.length === 36 && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value.expectedPrincipal)
        && boundedJson(value.selector) && validLocalCursorSelector(value.selector,value.chatId);
    case "read_local_chat": case "read_local_saved_chat":
      return closedData(value, [...base,"handle","generation","chatId","expectedPrincipal","encryptedRows"])
        && identifier(value.handle) && integer(value.generation)
        && typeof value.chatId === "string" && value.chatId.length === 36 && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value.chatId)
        && typeof value.expectedPrincipal === "string" && value.expectedPrincipal.length === 36 && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value.expectedPrincipal)
        && boundedJson(value.encryptedRows);
    case "read_saved_chat":
    case "reconnect_chat":
    case "open_chat": return exact(value, [...base, "handle", "generation", "chatId"]) && identifier(value.handle) && integer(value.generation)
      && typeof value.chatId === "string" && value.chatId.length === 36 && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value.chatId);
    case "validate_credentials": return exact(value,[...base,"handle","generation","snapshot"]) && identifier(value.handle) && integer(value.generation) && validBrowserSealedCredentials(value.snapshot) && new TextEncoder().encode(JSON.stringify(value.snapshot)).byteLength+1024<=MAX_RPC_BYTES;
    case "rotate_credentials": return exact(value,[...base,"handle","generation","scope"]) && identifier(value.handle) && integer(value.generation) && validCredentialCasScope(value.scope);
    case "prepare_credentials":
    case "status": return exact(value, [...base, "handle", "generation"]) && identifier(value.handle) && integer(value.generation);
    case "invalidate": return exact(value, base);
    case "cancel": return exact(value, [...base, "requestId"]) && integer(value.requestId);
    default: return false;
  }
}

/** Negative stop and original-task return correlation only. Neither frame is
 * HTTP settlement, global drain, auth admission, retry permission or an ACK. */
export interface FirstSessionStop {version:1;id:number;firstSessionStop:{requestId:number};}
export interface FirstSessionTerminal {version:1;id:number;firstSessionTerminal:{requestId:number;state:'returned'};}
export function validFirstSessionStop(value:unknown):value is FirstSessionStop {
 return record(value)&&closedData(value,['version','id','firstSessionStop'])&&value.version===1&&integer(value.id)&&value.id>0
  &&record(value.firstSessionStop)&&closedData(value.firstSessionStop,['requestId'])&&value.firstSessionStop.requestId===value.id;
}
export function validFirstSessionTerminal(value:unknown):value is FirstSessionTerminal {
 return record(value)&&closedData(value,['version','id','firstSessionTerminal'])&&value.version===1&&integer(value.id)&&value.id>0
  &&record(value.firstSessionTerminal)&&closedData(value.firstSessionTerminal,['requestId','state'])&&value.firstSessionTerminal.requestId===value.id&&value.firstSessionTerminal.state==='returned';
}
/** Transport data only: retain the complete server JSON tree, never admission. */
export function validFirstSessionSignals(value:unknown):value is Record<string,string|null>{
 return record(value)&&Object.keys(value).length<=64&&Object.entries(value).every(([key,item])=>new TextEncoder().encode(key).byteLength<=128
  &&(item===null||typeof item==='string'&&new TextEncoder().encode(item).byteLength<=4096))
  &&boundedJson(value)&&new TextEncoder().encode(JSON.stringify(value)).byteLength<=16*1024;
}
export function validFirstSessionData(value:unknown):value is {httpStatus:number|null;data:Record<string,unknown>|null}{
 return record(value)&&exact(value,['httpStatus','data'])&&(value.httpStatus===null||Number.isSafeInteger(value.httpStatus)&&Number(value.httpStatus)>=100&&Number(value.httpStatus)<=599)
  &&(value.data===null||record(value.data)&&boundedJson(value.data))&&boundedJson(value);
}
export function validResponse(value: unknown): value is CoreResponse {
  if (!record(value) || value.version !== RPC_VERSION || !integer(value.id)) return false;
  if(value.ok===true&&'firstSession' in value)return exact(value,['version','id','ok','status','firstSession'])&&(value.status===null||validStatus(value.status))&&validFirstSessionData(value.firstSession);
  if(value.ok===true&&'initialSync' in value)return exact(value,['version','id','ok','status','initialSync'])&&validStatus(value.status)&&value.status.localReadOnly!==true&&record(value.initialSync)&&exact(value.initialSync,['receivedMetadataCount','storedMetadataCount'])&&Number.isSafeInteger(value.initialSync.receivedMetadataCount)&&Number.isSafeInteger(value.initialSync.storedMetadataCount)&&(value.initialSync.receivedMetadataCount as number)>=0&&(value.initialSync.storedMetadataCount as number)>=0&&(value.initialSync.storedMetadataCount as number)<=(value.initialSync.receivedMetadataCount as number);
  if(value.ok===true&&'cacheMonitor' in value)return exact(value,['version','id','ok','status','cacheMonitor'])&&record(value.cacheMonitor)&&exact(value.cacheMonitor,['id','state'])&&localCursorUuid(value.cacheMonitor.id)&&['started','ready','idle','closed'].includes(String(value.cacheMonitor.state))&&(value.cacheMonitor.state==='closed'?value.status===null:validStatus(value.status)&&value.status.localReadOnly!==true);
  if(value.ok===true&&'cacheUpdate' in value)return exact(value,['version','id','ok','status','cacheMonitorId','cacheUpdate'])&&validStatus(value.status)&&value.status.localReadOnly!==true&&localCursorUuid(value.cacheMonitorId)&&validBrowserIncomingCacheUpdate(value.cacheUpdate);
  if(value.ok===true&&'cachedMetadata' in value)return exact(value,['version','id','ok','status','cachedMetadata'])&&validStatus(value.status)&&validBrowserCachedMetadataRead(value.cachedMetadata);
  if(value.ok===true&&'retainedRead' in value)return (exact(value,['version','id','ok','status','retainedRead'])||exact(value,['version','id','ok','status','retainedRead','cacheSourceEvidence'])&&validBrowserCacheSourceEvidence(value.cacheSourceEvidence))&&validStatus(value.status)&&value.status.localReadOnly!==true&&validBrowserRetainedRead(value.retainedRead)&&(value.cacheSourceEvidence===undefined||value.retainedRead.cacheReadKind==='cold');
  if(value.ok===true&&"credentialCas" in value)return exact(value,["version","id","ok","status","credentialCas"])&&validStatus(value.status)&&validCredentialCasValidation(value.credentialCas);
  if (value.ok === true && "snapshot" in value) return exact(value,["version","id","ok","status","snapshot"]) && validStatus(value.status) && validBrowserSealedCredentials(value.snapshot) && value.snapshot.owner===value.status.principal && value.snapshot.generation===value.status.generation;
  if (value.ok === true && "send" in value) return exact(value, ["version", "id", "ok", "status", "send"]) && validSendReply(value.send)
    && (value.send.kind === "started" ? validStatus(value.status) : value.status === null);
  if(value.ok===true&&"checkpointRead" in value){
    if(!exact(value,["version","id","ok","status","checkpointRead"])||!validStatus(value.status)||value.status.localReadOnly!==true||!boundedJson(value.checkpointRead))return false;
    const data=value.checkpointRead;if(!record(data))return false;const row=data.checkpoint;
    // Structural DTO validation only. The pending request checks exact chat/ID.
    return validCheckpointPresentation(data,record(row)?String(row.chatId):value.status.principal,"retained_selected");
  }
  if (value.ok === true && "onlineCachedRead" in value) return exact(value,["version","id","ok","status","onlineCachedRead"])
    && validStatus(value.status) && value.status.localReadOnly !== true && validLocalRead(value.onlineCachedRead, true);
  if (value.ok === true && "localRead" in value) return exact(value,["version","id","ok","status","localRead"])
    && validStatus(value.status) && value.status.localReadOnly === true && validLocalRead(value.localRead);
  if (value.ok === true && "savedRead" in value) return exact(value, ["version", "id", "ok", "status", "savedRead"])
    && validStatus(value.status) && validSavedRead(value.savedRead);
  if (value.ok === true) return "chat" in value
    ? exact(value, ["version", "id", "ok", "status", "chat"]) && validStatus(value.status) && validChat(value.chat)
    : exact(value, ["version", "id", "ok", "status"]) && (value.status === null || validStatus(value.status));
  if(value.ok===false&&Object.hasOwn(value,'profileCacheAbsent'))return exact(value,["version","id","ok","error","profileCacheAbsent"])&&value.error==='chat_unavailable'&&value.profileCacheAbsent===true;
  return value.ok === false && exact(value, ["version", "id", "ok", "error"])
    && ["invalid_request", "unavailable", "cancelled", "deadline", "session_expired", "reauthentication_required", "chat_unavailable", "credential_conflict", "authentication_failed", "two_factor_required"].includes(value.error as string);
}

/** Request-scoped typed Rust local IO callbacks, within the existing RPC lane. */
const LOCAL_CURSOR_CHECKPOINT_ROWS = 128;
function localCursorNonnegativeInteger(value: unknown): value is number { return Number.isSafeInteger(value) && Number(value) >= 0; }
const LOCAL_CURSOR_MIN_PACKET_BYTES = 1024;
export interface LocalCursorBound { createdAt: number; messageId: string | null; open: boolean }
export interface LocalReadPlan { version: 1; kind: "metadata" | "owned_metadata" | "anchor" | "messages"; operationId: string; owner: string; chatId: string;
  maxPacketBytes: number; maxCheckpointRows: number; maxPayloadRows: number; lower: LocalCursorBound | null; upper: LocalCursorBound | null; direction: "next" | "prev"; anchorMessageId?: string }
function localCursorClosed(value: unknown, fields: readonly string[]): value is Record<string, unknown> {
  return record(value) && Object.keys(value).length === fields.length && fields.every(field => Object.hasOwn(value, field));
}
function localCursorIdentifier(value: unknown): value is string { return validReadMessageId(value); }
function localCursorUuid(value: unknown): value is string { return typeof value === "string" && value.length === 36 && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value); }
function validLocalCursorBound(value: unknown): value is LocalCursorBound | null {
  return value === null || localCursorClosed(value, ["createdAt", "messageId", "open"]) && localCursorNonnegativeInteger(value.createdAt)
    && (value.messageId === null || localCursorIdentifier(value.messageId)) && typeof value.open === "boolean";
}
export function parseBrowserLocalReadPlan(encoded: string): LocalReadPlan {
  // Keep the existing whole callback/envelope budget and boundedJson reserve.
  // Rust cannot know the future RPC id: admit its plan with the largest safe
  // request id and final effect number, then check the real envelope at Host.
  if (typeof encoded !== "string" || new TextEncoder().encode(encoded).byteLength > MAX_CHAT_UTF8_BYTES) throw new Error("unavailable");
  const value: unknown = JSON.parse(encoded);
  if (!boundedJson({version:1,id:Number.MAX_SAFE_INTEGER,effectId:4,localReadEffect:value})
    || JSON.stringify(value) !== encoded) throw new Error("unavailable");
  if (!record(value) || !localCursorClosed(value, ["version", "kind", "operationId", "owner", "chatId", "maxPacketBytes", "maxCheckpointRows", "maxPayloadRows", "lower", "upper", "direction", ...(value.kind === "anchor" ? ["anchorMessageId"] : [])])
    || value.version !== 1 || !localCursorUuid(value.operationId) || !localCursorUuid(value.owner) || !localCursorUuid(value.chatId)
    || !localCursorNonnegativeInteger(value.maxPacketBytes) || value.maxPacketBytes < LOCAL_CURSOR_MIN_PACKET_BYTES || value.maxPacketBytes > MAX_CHAT_UTF8_BYTES
    || !localCursorNonnegativeInteger(value.maxPayloadRows) || value.maxPayloadRows > MAX_CHAT_MESSAGES
    || !localCursorNonnegativeInteger(value.maxCheckpointRows) || value.maxCheckpointRows > LOCAL_CURSOR_CHECKPOINT_ROWS
    || !validLocalCursorBound(value.lower) || !validLocalCursorBound(value.upper) || !["next", "prev"].includes(String(value.direction))) throw new Error("unavailable");
  if (value.kind === "metadata" || value.kind === "owned_metadata") {
    if(value.kind==="owned_metadata"&&(value.maxPacketBytes!==262144||value.maxCheckpointRows!==128))throw Error("unavailable");
    if (value.maxPayloadRows !== 0 || value.maxCheckpointRows < 1 || value.direction !== "next" || value.lower !== null || value.upper !== null) throw new Error("unavailable");
  } else if (value.kind === "anchor") {
    if (value.maxPayloadRows !== 1 || value.maxCheckpointRows !== 0 || value.direction !== "next" || value.lower !== null || value.upper !== null || !validReadMessageId(value.anchorMessageId)) throw new Error("unavailable");
  } else if (value.kind === "messages") {
    if (value.maxPayloadRows < 1 || value.maxCheckpointRows !== 0) throw new Error("unavailable");
  } else throw new Error("unavailable");
  return value as unknown as LocalReadPlan;
}
export type LocalCursorSelector = { direction: "latest" } | { direction: "before" | "after"; cursor: SavedReadCursor } | { direction: "around"; anchorMessageId: string };
export function validLocalCursorSelector(value: unknown, chatId: string): value is LocalCursorSelector {
  if (localCursorData(value, ["direction"]) && value.direction === "latest") return true;
  if (localCursorData(value, ["direction", "anchorMessageId"]) && value.direction === "around") return validReadMessageId(value.anchorMessageId);
  if (!localCursorData(value, ["direction", "cursor"]) || !["before", "after"].includes(String(value.direction))) return false;
  const cursor = value.cursor;
  return localCursorData(cursor, ["chatId", "scope", "createdAt", "messageId"]) && cursor.chatId === chatId && localCursorUuid(cursor.chatId)
    && typeof cursor.scope === "string" && cursor.scope.length === 64 && /^[a-f0-9]{64}$/.test(cursor.scope) && localCursorNonnegativeInteger(cursor.createdAt) && localCursorIdentifier(cursor.messageId);
}
export interface LocalCursorEffect { version: 1; id: number; effectId: number; localReadEffect: LocalReadPlan }
export type LocalCursorReply = { version: 1; id: number; effectId: number; localReadReply:
  { ok: true; operationId: string; packet: string } | { ok: false; operationId: string; error: "cancelled" | "unavailable" | "invalidated_snapshot" | "storage_failed" } };
function localCursorData(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return localCursorClosed(value, keys) && Object.values(Object.getOwnPropertyDescriptors(value)).every(item => "value" in item && !item.get && !item.set);
}
export function validLocalCursorEffect(value: unknown): value is LocalCursorEffect {
  if (!localCursorData(value, ["version", "id", "effectId", "localReadEffect"]) || value.version !== 1 || !localCursorNonnegativeInteger(value.id) || value.id < 1
    || !localCursorNonnegativeInteger(value.effectId) || value.effectId < 1 || value.effectId > 4) return false;
  if (!boundedJson(value)) return false;
  try { return JSON.stringify(parseBrowserLocalReadPlan(JSON.stringify(value.localReadEffect))) === JSON.stringify(value.localReadEffect); } catch { return false; }
}
export function validLocalCursorReply(value: unknown): value is LocalCursorReply {
  if (!localCursorData(value, ["version", "id", "effectId", "localReadReply"]) || value.version !== 1 || !localCursorNonnegativeInteger(value.id) || value.id < 1
    || !localCursorNonnegativeInteger(value.effectId) || value.effectId < 1 || value.effectId > 4) return false;
  const reply = value.localReadReply;
  if (localCursorData(reply, ["ok", "operationId", "packet"]) && reply.ok === true && localCursorUuid(reply.operationId)) {
    return typeof reply.packet === "string" && new TextEncoder().encode(reply.packet).byteLength + 8192 <= MAX_CHAT_UTF8_BYTES;
  }
  return localCursorData(reply, ["ok", "operationId", "error"]) && reply.ok === false && localCursorUuid(reply.operationId)
    && ["cancelled", "unavailable", "invalidated_snapshot", "storage_failed"].includes(String(reply.error));
}
/** Per-request handler supplied only by the current existing-profile source. */
export interface LocalCursorEffectHandler {
  current(): void;
  execute(plan: LocalReadPlan, signal: AbortSignal): Promise<string>;
}

export type SavedPageSelector = LocalCursorSelector;
export const validSavedPageSelector = validLocalCursorSelector;

/** Closed callback lifecycle only: Rust owns bounds, split and continuation.
 * Count declared hydration capacity to reject over-budget/replayed callbacks.
 * An omitted older leg is legal; direction comes from each Rust plan.
 */
export type LocalReadSelector=LocalCursorSelector|{direction:"checkpoint_summary";checkpointId:string};
export interface LocalReadPlanState { readonly effects: number; readonly payloadRows: number; readonly lastKind?: LocalReadPlan["kind"]; readonly lastDirection?: "next" | "prev" }
export function advanceLocalReadPlan(state: LocalReadPlanState, plan: LocalReadPlan, selector: LocalReadSelector): LocalReadPlanState {
  if(selector.direction==="checkpoint_summary"){if(state.effects!==0||plan.kind!=="metadata"||plan.maxPayloadRows!==0)throw Error("unavailable");return Object.freeze({effects:1,payloadRows:0,lastKind:plan.kind});}
  const around=selector.direction==="around", effects=state.effects+1, payloadRows=state.payloadRows+plan.maxPayloadRows;
  if(effects>(around?4:2)||payloadRows>MAX_CHAT_MESSAGES)throw Error("unavailable");
  if(effects===1){if(plan.kind!=="metadata")throw Error("unavailable");}
  else if(effects===2){
    if(around){if(plan.kind!=="anchor"||plan.anchorMessageId!==selector.anchorMessageId)throw Error("unavailable");}
    else if(plan.kind!=="messages")throw Error("unavailable");
  }else if(!around||plan.kind!=="messages"||state.lastKind!=="anchor"&&state.lastKind!=="messages"
    ||state.lastKind==="messages"&&(state.lastDirection!=="prev"||plan.direction!=="next"))throw Error("unavailable");
  return Object.freeze({effects,payloadRows,lastKind:plan.kind,...(plan.kind==="messages"?{lastDirection:plan.direction}:{})});
}
