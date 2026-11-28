/**
 * Opt-in Rust history source for ActiveChat's saved-chat open path.
 *
 * Default builds never install a source, so `readRustChatHistoryWindow` returns
 * null and ActiveChat keeps its TypeScript/IndexedDB path unchanged. The
 * VITE_OPENMATES_RUST_CORE web build installs the Rust core source
 * (apps/web_app/src/lib/rustCore/rustChatHistoryBootstrap.ts); Rust then reads
 * and decrypts the opened chat and the unchanged UI renders the mapped rows.
 *
 * Cache-first (TS parity): the source renders the existing retained IndexedDB
 * rows through the Rust Worker and hands back a `reconcile` server read that
 * ActiveChat runs in the background under the same short/partial-window rule as
 * its TS IndexedDB path. A cache miss reads the server directly.
 *
 * The flag build declares the source synchronously at page setup
 * (`declareRustChatHistorySource`) so the first deep-link open waits for the
 * Rust source instead of racing its dynamic import.
 *
 * Fallback contract: only a typed `RustHistoryRefusal` returns null (TS path).
 * Every other failure is logged with a fixed code and rethrown. Logs and the
 * <html data-rust-core-history> marker carry fixed codes only, never content.
 */
import type { Chat } from "../../types/chat";
import type { MessageWindowResult } from "../db/messageOperations";
import { RustHistoryRefusal } from "./savedChatMessageRows";
import type { SavedPageSelector } from "./protocol";

/** One Rust-owned history page and how it was obtained. */
export interface RustHistoryRead {
  window: MessageWindowResult;
  /** `cache`: retained IndexedDB rows decrypted by Rust; `server`: canonical server page. */
  source: "cache" | "server";
  /** Background Rust server read for a cached page; null for a server page. */
  reconcile: (() => Promise<MessageWindowResult>) | null;
}

export interface RustChatHistorySource {
  /** Rust read of one saved chat page (latest, or around an anchor). */
  readWindow(input: { chatId: string; anchorMessageId: string | null }): Promise<RustHistoryRead>;
  /** Rust canonical server page for a chained selector (older/newer via an opaque cursor, or around an anchor). */
  readPage(input: { chatId: string; selector: SavedPageSelector }): Promise<MessageWindowResult>;
}

let installed: RustChatHistorySource | null = null;
let declared: Promise<void> | null = null;

/** Called only from the flag-gated web bootstrap. Returns an uninstaller. */
export function installRustChatHistorySource(source: RustChatHistorySource): () => void {
  installed = source;
  return () => { if (installed === source) installed = null; };
}

/**
 * Flag build only: a source is being installed (dynamic import in flight).
 * Reads wait for it; a failed or opted-out install leaves no source (TS path).
 */
export function declareRustChatHistorySource(ready: Promise<unknown>): void {
  const settled: Promise<void> = ready.then(() => undefined, () => undefined)
    .finally(() => { if (declared === settled) declared = null; });
  declared = settled;
}

/** The chat id shape the core's read requests accept (see `localCursorUuid` in protocol.ts). */
const CORE_CHAT_ID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;

/** Schedule ahead only for an explicitly ordinary owned saved row. */
export function canPreparePersonalLatestHistory(chat: Chat, ownerId: string | null | undefined): boolean {
  return !!ownerId && chat.user_id === ownerId && CORE_CHAT_ID.test(chat.chat_id) &&
    Number.isSafeInteger(chat.messages_v) && chat.messages_v > 0 &&
    typeof chat.encrypted_chat_key === "string" && chat.encrypted_chat_key.length > 0 &&
    chat.is_hidden === false && chat.is_hidden_candidate === false &&
    !chat.team_id && !chat.chat_visibility && !chat.is_incognito && !chat.is_anonymous &&
    !chat.is_shared && !chat.is_shared_by_others && !chat.parent_id && !chat.is_sub_chat &&
    !chat.encrypted_draft_md && !chat.encrypted_draft_preview && !chat.draft_v &&
    !chat.waiting_for_metadata && !chat.processing_metadata;
}

/** Observe rejection while metadata is in flight; leave the original result
 * intact so the current, classified selection receives the same denial. */
export function preparePersonalLatestHistory(chat: Chat): Promise<RustHistoryRead | null> {
  const result = readRustChatHistoryWindow(chat, {
    anchorMessageId: null, activeTeamId: null, localInitialPending: false,
  });
  void result.catch(() => undefined);
  return result;
}

const FIXED_CODE = /^[a-z_]{1,40}$/;
export function rustFailureCode(error: unknown): string {
  return error instanceof Error && FIXED_CODE.test(error.message) ? error.message : "other";
}

function mark(state: string): void {
  if (typeof document !== "undefined") document.documentElement.dataset.rustCoreHistory = state;
}

function refuseUnownedChat(chat: Chat, activeTeamId: string | null): void {
  if (chat.team_id || activeTeamId) throw new RustHistoryRefusal("team_chat");
  if (chat.is_shared_by_others) throw new RustHistoryRefusal("shared_chat");
  if (!(Number(chat.messages_v ?? 0) > 0)) throw new RustHistoryRefusal("unsynced_chat");
  if (!CORE_CHAT_ID.test(chat.chat_id)) throw new RustHistoryRefusal("local_fixture_chat");
}

/**
 * Rust-owned follow-up page (older paging, anchor/around reads). Null when no
 * source is installed or Rust refused this chat shape; the caller then keeps
 * its TypeScript fetch ONLY for that refusal. Any other failure is rethrown.
 */
export async function readRustChatHistoryPage(chat: Chat, input: {
  selector: SavedPageSelector; activeTeamId: string | null;
}): Promise<MessageWindowResult | null> {
  if (!installed && declared) await declared;
  const source = installed;
  if (!source) return null;
  try {
    refuseUnownedChat(chat, input.activeTeamId);
    const window = await source.readPage({ chatId: chat.chat_id, selector: input.selector });
    mark(`rust-page:${window.messages.length}`);
    if (typeof document !== "undefined") document.documentElement.dataset.rustCoreHistoryPage = String(window.messages.length);
    return window;
  } catch (error) {
    if (error instanceof RustHistoryRefusal) {
      mark(`refused:${error.code}`);
      console.info("[RustCore] saved chat page refused:", error.code);
      return null;
    }
    const code = rustFailureCode(error);
    // Server unreachable (offline boot or server-check backoff): older pages come from
    // the encrypted local cache instead, as before this read moved to Rust.
    if (code === "unavailable" || code === "deadline") {
      mark(`offline:${code}`);
      console.warn("[RustCore] saved chat page needs the server; reading the local cache:", code);
      return null;
    }
    mark(`error:${code}`);
    console.error("[RustCore] saved chat page failed:", code);
    throw error;
  }
}

/**
 * Rust-owned window for an authenticated saved chat, or null when no source is
 * installed or Rust explicitly refused this chat shape.
 */
export async function readRustChatHistoryWindow(chat: Chat, input: {
  anchorMessageId: string | null; activeTeamId: string | null; localInitialPending: boolean;
  serverClassifiedSaved?: boolean;
}): Promise<RustHistoryRead | null> {
  const started = typeof performance !== "undefined" ? performance.now() : 0;
  if (!installed && declared) await declared;
  const source = installed;
  if (!source) return null;
  if (typeof performance !== "undefined") performance.mark("openmates:rust:history-request", { startTime: started });
  try {
    if (chat.team_id || input.activeTeamId) throw new RustHistoryRefusal("team_chat");
    if (chat.is_shared_by_others) throw new RustHistoryRefusal("shared_chat");
    // A chat this client is still creating is not server-readable yet; its
    // optimistic local rows stay with the TS send path.
    if (input.localInitialPending || (!input.serverClassifiedSaved && !(Number(chat.messages_v ?? 0) > 0))) throw new RustHistoryRefusal("unsynced_chat");
    // The core addresses saved chats by UUID. Only local E2E fixture chats carry another id; they
    // exist in this browser alone, so there is no server copy for the core to read either.
    if (!CORE_CHAT_ID.test(chat.chat_id)) throw new RustHistoryRefusal("local_fixture_chat");
    const result = await source.readWindow({ chatId: chat.chat_id, anchorMessageId: input.anchorMessageId });
    mark(`rust:${result.window.messages.length}`);
    if (typeof document !== "undefined") document.documentElement.dataset.rustCoreHistorySource = result.source;
    if (typeof performance !== "undefined") {
      performance.measure("openmates:rust-history-read", { start: started, end: performance.now() });
    }
    return result;
  } catch (error) {
    if (error instanceof RustHistoryRefusal) {
      mark(`refused:${error.code}`);
      console.info("[RustCore] saved chat history refused:", error.code);
      return null;
    }
    const code = rustFailureCode(error);
    mark(`error:${code}`);
    console.error("[RustCore] saved chat history failed:", code);
    throw error;
  }
}
