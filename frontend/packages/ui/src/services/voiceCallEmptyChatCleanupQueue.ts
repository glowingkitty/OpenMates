/**
 * Durable retry for retiring empty voice-call chat shells.
 *
 * A call that ends without any transcript, typed text, title or artifact must
 * not leave an "Untitled chat" behind. The in-call cleanup can be interrupted
 * by a dropped WebSocket, a rejected lifecycle write, a reload or a crash, so
 * every server-issued cleanup authority is persisted here (per account) and
 * retried after reconnects and with bounded backoff. Deletion itself always
 * goes through the conditional server fence in voiceCallEmptyChatCleanup.ts,
 * which re-verifies emptiness atomically; this queue only decides *when* to ask.
 */
import {
  cleanupEmptyVoiceCallChat,
  readEmptyVoiceCallCleanupSnapshot,
  type EmptyVoiceCallCleanupInput,
  type EmptyVoiceCallCleanupSnapshot,
} from './voiceCallEmptyChatCleanup';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';
import { getWorkspaceCacheEpoch } from './workspaceCacheLifecycle';
import { hasPendingPersonalChatTurn } from './personalChatTurnBarrier';
import { parseVoiceCallHistoryEvent, voiceCallLifecycleMessageId } from './voiceCallLifecycleEvent';

const STORAGE_KEY = 'openmates.voiceCallEmptyCleanup.v1';
const MAX_RECORDS = 20;
const MAX_AGE_MS = 24 * 60 * 60_000;
const MAX_ATTEMPTS = 12;
/** A record whose call never reported termination (crash) may belong to a
 * call another tab still runs; that tab refreshes seenAt while it is live. */
// Above the ~1/min timer throttling of hidden tabs.
const UNTERMINATED_GRACE_MS = 150_000;
const LIVE_HEARTBEAT_MS = 10_000;

export interface PendingEmptyCallCleanup {
  owner: string;
  chatId: string;
  cleanupAttemptId: string;
  callId: string | null;
  createdAt: number;
  seenAt: number;
  terminatedAt: number | null;
  attempts: number;
}

export type EmptyCallCleanupOutcome = 'deleted' | 'retained' | 'retry';

export interface EmptyCallCleanupRunSignals {
  isCurrent: () => boolean;
  hasLocalOrdinaryText: boolean;
  hasPendingTurn: () => boolean;
  onSnapshot?: (snapshot: EmptyVoiceCallCleanupSnapshot) => void;
}

const liveChatIds = new Set<string>();
const inFlight = new Set<string>();
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let heartbeat: ReturnType<typeof setInterval> | null = null;

/** Account scope without in-memory epochs, so records survive a reload. */
function ownerScope(): string | null {
  const identity = getWorkspaceCacheIdentity();
  if (!identity) return null;
  const [api, user, team] = identity.split('|');
  // Empty-call cleanup only applies to personal chats.
  return api && user && !team ? `${api}|${user}` : null;
}

function readAll(): PendingEmptyCallCleanup[] {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((row): row is PendingEmptyCallCleanup => !!row && typeof row === 'object'
      && typeof row.owner === 'string' && typeof row.chatId === 'string'
      && typeof row.cleanupAttemptId === 'string' && (row.callId === null || typeof row.callId === 'string')
      && Number.isSafeInteger(row.createdAt) && Number.isSafeInteger(row.seenAt) && Number.isSafeInteger(row.attempts)
      && (row.terminatedAt === null || Number.isSafeInteger(row.terminatedAt)));
  } catch (error) {
    console.warn('[VoiceCallCleanupQueue] Pending cleanup records unreadable; ignoring them', error);
    return [];
  }
}

function writeAll(rows: PendingEmptyCallCleanup[]): void {
  try {
    if (typeof localStorage === 'undefined') return;
    const now = Date.now();
    const kept = rows.filter(row => now - row.createdAt < MAX_AGE_MS && row.attempts < MAX_ATTEMPTS)
      .slice(-MAX_RECORDS);
    if (kept.length) localStorage.setItem(STORAGE_KEY, JSON.stringify(kept));
    else localStorage.removeItem(STORAGE_KEY);
  } catch (error) {
    // Quota/private-mode failure only loses the retry; the in-call path still runs.
    console.warn('[VoiceCallCleanupQueue] Pending cleanup record could not be saved', error);
  }
}

function update(chatId: string, change: (row: PendingEmptyCallCleanup) => PendingEmptyCallCleanup | null): void {
  const rows = readAll();
  const next: PendingEmptyCallCleanup[] = [];
  for (const row of rows) {
    if (row.chatId !== chatId) { next.push(row); continue; }
    const changed = change(row);
    if (changed) next.push(changed);
  }
  writeAll(next);
}

/** Persist the server-issued authority for a brand-new call shell. */
export function rememberEmptyCallCleanup(chatId: string, cleanupAttemptId: string): void {
  const owner = ownerScope();
  if (!owner) return;
  const rows = readAll().filter(row => row.chatId !== chatId);
  const now = Date.now();
  rows.push({ owner, chatId, cleanupAttemptId, callId: null, createdAt: now, seenAt: now, terminatedAt: null, attempts: 0 });
  writeAll(rows);
}

export function noteEmptyCallCleanupCallId(chatId: string, callId: string): void {
  update(chatId, row => ({ ...row, callId }));
}

/** Synchronous so it survives beforeunload hangups. */
export function markEmptyCallCleanupTerminated(chatId: string): void {
  update(chatId, row => ({ ...row, terminatedAt: row.terminatedAt ?? Date.now() }));
}

export function forgetEmptyCallCleanup(chatId: string): void {
  update(chatId, () => null);
}

/** The controller marks the chat it is actively calling in this tab. */
export function setEmptyCallCleanupLive(chatId: string, live: boolean): void {
  if (live) liveChatIds.add(chatId);
  else liveChatIds.delete(chatId);
  if (liveChatIds.size && heartbeat === null) {
    heartbeat = setInterval(() => {
      const now = Date.now();
      writeAll(readAll().map(row => liveChatIds.has(row.chatId) ? { ...row, seenAt: now } : row));
    }, LIVE_HEARTBEAT_MS);
  } else if (!liveChatIds.size && heartbeat !== null) {
    clearInterval(heartbeat);
    heartbeat = null;
  }
}

export function pendingEmptyCallCleanups(): PendingEmptyCallCleanup[] {
  const owner = ownerScope();
  return owner ? readAll().filter(row => row.owner === owner) : [];
}

/** User-authored or durable content means the chat must be kept for good. */
function hasPermanentContent(snapshot: EmptyVoiceCallCleanupSnapshot, callId: string | null): boolean {
  const chat = snapshot.chat;
  if (!chat) return false;
  const lifecycleIds = callId === null ? [] : [
    voiceCallLifecycleMessageId(callId, 'started'), voiceCallLifecycleMessageId(callId, 'ended'),
  ];
  return Boolean(chat.title || chat.encrypted_title || chat.encrypted_chat_summary || chat.pinned || chat.is_shared)
    || (chat.draft_v ?? 0) > 0 || snapshot.artifactCount > 0 || snapshot.hasOrdinaryText
    || snapshot.messages.some(message => !lifecycleIds.includes(message.message_id));
}

/**
 * Wait for the exact lifecycle version, then ask the server to fence and delete.
 * 'retained' means the chat has real content (or is gone) and must not be retried.
 */
export async function runEmptyVoiceCallCleanup(
  base: Omit<EmptyVoiceCallCleanupInput, 'expectedMessagesVersion'>, signals: EmptyCallCleanupRunSignals,
): Promise<EmptyCallCleanupOutcome> {
  if (inFlight.has(base.chatId)) return 'retry';
  inFlight.add(base.chatId);
  try {
    const input: EmptyVoiceCallCleanupInput = { ...base, expectedMessagesVersion: 0 };
    const readSnapshot = async () => {
      const snapshot = await readEmptyVoiceCallCleanupSnapshot(input, {
        hasLocalOrdinaryText: signals.hasLocalOrdinaryText,
        hasPendingTurn: signals.hasPendingTurn(),
        isCurrent: signals.isCurrent,
      });
      signals.onSnapshot?.(snapshot);
      return snapshot;
    };
    let snapshot = await readSnapshot();
    // System-message receipts and their metadata handler complete in separate
    // microtasks. Never ask the server to delete a partial local projection.
    const lifecycleVersion = input.callId === null ? 0 : 2;
    for (let retry = 0; retry < 3 && signals.isCurrent() && snapshot.chat
        && snapshot.chat.messages_v < lifecycleVersion; retry++) {
      await new Promise(resolve => setTimeout(resolve, 250));
      snapshot = await readSnapshot();
    }
    if (!signals.isCurrent()) return 'retry';
    if (snapshot.chat && hasPermanentContent(snapshot, input.callId)) return 'retained';
    if (!snapshot.chat || !Number.isSafeInteger(snapshot.chat.messages_v)
      || snapshot.chat.messages_v < lifecycleVersion) return 'retry';
    input.expectedMessagesVersion = snapshot.chat.messages_v;
    const result = await cleanupEmptyVoiceCallChat(input, readSnapshot);
    if (result.accepted) return 'deleted';
    const after = await readSnapshot();
    return after.chat && hasPermanentContent(after, input.callId) ? 'retained' : 'retry';
  } finally {
    inFlight.delete(base.chatId);
  }
}

/** Complete lifecycle events an interrupted call never persisted (crash/reload),
 * so the server sees the exact started/ended pair it requires. */
async function completeMissingLifecycle(row: PendingEmptyCallCleanup, snapshot: EmptyVoiceCallCleanupSnapshot): Promise<void> {
  if (row.callId === null || !snapshot.chat) return;
  const present = new Set(snapshot.messages.filter(message => {
    const event = parseVoiceCallHistoryEvent(message.content ?? '');
    return event?.call_id === row.callId;
  }).map(message => message.message_id));
  const { recordCallLifecycle } = await import('./voiceCallLifecycle');
  for (const type of ['started', 'ended'] as const) {
    if (present.has(voiceCallLifecycleMessageId(row.callId, type))) continue;
    await recordCallLifecycle({ type, chatId: row.chatId, callId: row.callId, activeElapsedSeconds: 0,
      occurredAt: Math.floor((type === 'started' ? row.createdAt : (row.terminatedAt ?? Date.now())) / 1000) });
  }
}

function scheduleRetry(attempts: number): void {
  if (retryTimer !== null || typeof window === 'undefined') return;
  const delay = Math.min(5 * 60_000, 15_000 * 2 ** Math.max(0, attempts - 1));
  retryTimer = setTimeout(() => {
    retryTimer = null;
    void retryPendingEmptyVoiceCallCleanups();
  }, delay);
}

/** Ask for a backoff retry after an in-call cleanup could not complete yet. */
export function scheduleEmptyVoiceCallCleanupRetry(): void {
  scheduleRetry(1);
}

/** Retry every persisted shell of this account that no live call owns.
 * Called after WebSocket (re)connects; reschedules itself with backoff. */
export async function retryPendingEmptyVoiceCallCleanups(): Promise<void> {
  const identity = getWorkspaceCacheIdentity();
  const epoch = getWorkspaceCacheEpoch();
  const isCurrent = () => Boolean(identity) && identity === getWorkspaceCacheIdentity()
    && epoch === getWorkspaceCacheEpoch();
  let pending = 0;
  let maxAttempts = 0;
  for (const row of pendingEmptyCallCleanups()) {
    if (!isCurrent()) return;
    if (liveChatIds.has(row.chatId) || inFlight.has(row.chatId)) continue;
    if (row.terminatedAt === null && Date.now() - row.seenAt < UNTERMINATED_GRACE_MS) {
      pending++;
      continue;
    }
    update(row.chatId, current => ({ ...current, attempts: current.attempts + 1 }));
    const input = { chatId: row.chatId, cleanupAttemptId: row.cleanupAttemptId, callId: row.callId };
    const signals = { isCurrent, hasLocalOrdinaryText: false,
      hasPendingTurn: () => hasPendingPersonalChatTurn(row.chatId) };
    let outcome: EmptyCallCleanupOutcome;
    try {
      const snapshot = await readEmptyVoiceCallCleanupSnapshot({ ...input, expectedMessagesVersion: 0 },
        { ...signals, hasPendingTurn: signals.hasPendingTurn() });
      if (!snapshot.chat && isCurrent() && !await (await import('./db')).chatDB.getChat(row.chatId)) {
        // Already deleted here or by another device; nothing left to retire.
        outcome = 'retained';
      } else {
        if (snapshot.chat && !hasPermanentContent(snapshot, row.callId)) await completeMissingLifecycle(row, snapshot);
        outcome = await runEmptyVoiceCallCleanup(input, signals);
      }
    } catch (error) {
      console.warn('[VoiceCallCleanupQueue] Empty call cleanup retry failed; will retry', error);
      outcome = 'retry';
    }
    if (outcome === 'retry') {
      pending++;
      maxAttempts = Math.max(maxAttempts, row.attempts + 1);
    } else {
      forgetEmptyCallCleanup(row.chatId);
    }
  }
  if (pending && isCurrent()) scheduleRetry(maxAttempts || 1);
}
