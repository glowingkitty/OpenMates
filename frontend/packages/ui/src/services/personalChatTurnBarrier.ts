import { registerWorkspaceCacheClear } from './workspaceCacheLifecycle';

/** In-memory ordering for personal encrypted turns. While the predecessor's reply
 * runs, a follower proceeds once that turn's admission was accepted (admitted
 * version) and the server queues it behind the run. Once the reply has ended, the
 * server no longer queues: the follower waits for the predecessor's terminal
 * persistence, whose encrypted assistant row advances messages_v. */
type TurnResult = { version: number } | { error: Error };

export interface PersonalChatTurn {
  readonly chatId: string;
  readonly messageId: string;
  readonly predecessor: Promise<TurnResult> | null;
  readonly done: Promise<TurnResult>;
  /** Settles when the server accepted this turn's admission (its committed
   * version is then the next turn's expected version) or when the turn settles. */
  readonly admitted: Promise<TurnResult>;
  /** The turn reserved before this one in the same chat, if still pending then. */
  readonly predecessorTurn: PersonalChatTurn | null;
  /** The server's AI task for this turn ended; its reply may still be persisting. */
  replyEnded: boolean;
  turnId: string | null;
  /** Epoch-zero admission: the reply persists through legacy storage, not sealed recovery. */
  legacy: boolean;
  settled: boolean;
  resolve: (result: TurnResult) => void;
  resolveAdmitted: (result: TurnResult) => void;
}

const tails = new Map<string, PersonalChatTurn>();
const turns = new Map<string, PersonalChatTurn>();
const settledVersions = new Map<string, number>();
/** Followers waiting on an ended reply's persistence, woken when a new AI task
 * (e.g. a focus-mode continuation) starts in the chat and the server queues again. */
const runRestartWaiters = new Map<string, Set<() => void>>();

/** Accept only authenticated server versions; optimistic local counts never enter here. */
export function observePersonalChatCanonicalVersion(chatId: string, version: number): void {
  if ((!settledVersions.has(chatId) && !tails.has(chatId)) || !Number.isSafeInteger(version) || version < 0) return;
  settledVersions.set(chatId, Math.max(settledVersions.get(chatId) ?? 0, version));
}

/** Includes reservations that have not reached their durable preflight journal. */
export function hasPendingPersonalChatTurn(chatId: string): boolean {
  return [...turns.values()].some(turn => turn.chatId === chatId);
}

/** A bound preflight must finish through sealed recovery, including on Stop.
 * LEGACY (epoch-zero) admissions have no recovery job; their reply must use
 * legacy storage, whose ACK is what settles the turn for the next send. */
export function hasRecoveryBoundPersonalChatMessage(chatId: string, messageId: string): boolean {
  const turn = turns.get(key(chatId, messageId));
  return !!turn?.turnId && !turn.legacy;
}

/** Record the server's LEGACY preflight ACK for this bound turn. */
export function markPersonalChatTurnLegacy(turn: PersonalChatTurn): void {
  turn.legacy = true;
}

function key(chatId: string, messageId: string): string {
  return `${chatId}:${messageId}`;
}

export function reservePersonalChatTurn(chatId: string, messageId: string): PersonalChatTurn {
  const identity = key(chatId, messageId);
  const existing = turns.get(identity);
  if (existing) return existing;
  let resolve!: (result: TurnResult) => void;
  const done = new Promise<TurnResult>((settle) => { resolve = settle; });
  let resolveAdmitted!: (result: TurnResult) => void;
  const admitted = new Promise<TurnResult>((settleAdmitted) => { resolveAdmitted = settleAdmitted; });
  const predecessorTurn = tails.get(chatId) ?? null;
  const turn: PersonalChatTurn = {
    chatId, messageId, admitted, resolveAdmitted, predecessorTurn, replyEnded: false,
    predecessor: predecessorTurn?.admitted
      ?? (settledVersions.has(chatId) ? Promise.resolve({ version: settledVersions.get(chatId)! }) : null),
    done, turnId: null, legacy: false, settled: false, resolve,
  };
  tails.set(chatId, turn);
  turns.set(identity, turn);
  return turn;
}

export async function awaitPersonalChatPredecessor(turn: PersonalChatTurn): Promise<number | null> {
  if (!turn.predecessor) return null;
  let result = await turn.predecessor;
  const prior = turn.predecessorTurn;
  if ('version' in result && prior && !prior.settled && prior.replyEnded) {
    // The reply ended but its encrypted row is not stored yet: the server would
    // check this turn against a version that the pending row is about to move.
    let wake!: () => void;
    const restarted = new Promise<null>((resolveRestart) => { wake = () => resolveRestart(null); });
    const waiters = runRestartWaiters.get(turn.chatId) ?? new Set<() => void>();
    waiters.add(wake);
    runRestartWaiters.set(turn.chatId, waiters);
    try {
      result = (await Promise.race([prior.done, restarted])) ?? result;
    } finally {
      waiters.delete(wake);
      if (!waiters.size) runRestartWaiters.delete(turn.chatId);
    }
  }
  if ('error' in result) throw Object.defineProperty(new Error('The previous encrypted reply has not been saved. Retry this message after recovery.'), 'cause', { value: result.error, configurable: true, writable: true });
  // Another device (or a queued CLI send) may have committed rows after the
  // predecessor: the newest authenticated server version is the expected one.
  return Math.max(result.version, settledVersions.get(turn.chatId) ?? 0);
}

/** Record the server-accepted admission: `version` is the committed messages_v
 * of this turn's user row, which a queued follower must send as its expected version. */
export function admitPersonalChatTurn(turn: PersonalChatTurn, version: number): void {
  if (turn.settled || !Number.isSafeInteger(version) || version < 0) return;
  turn.resolveAdmitted({ version });
}

/** The server's AI task for this user message ended (completed or stopped). */
export function markPersonalChatReplyEnded(chatId: string, messageId: string): void {
  const turn = turns.get(key(chatId, messageId));
  if (turn && !turn.settled) turn.replyEnded = true;
}

/** A new AI task started in the chat: the server queues followers behind it again. */
export function markPersonalChatReplyRunning(chatId: string): void {
  for (const turn of turns.values()) if (turn.chatId === chatId) turn.replyEnded = false;
  for (const wake of runRestartWaiters.get(chatId) ?? []) wake();
}

export function bindPersonalChatTurn(turn: PersonalChatTurn, turnId: string): void {
  if (turn.settled) throw new Error('Cannot bind a settled encrypted chat turn.');
  if (turn.turnId && turn.turnId !== turnId) throw new Error('Encrypted chat turn identity changed.');
  turn.turnId = turnId;
}

function settle(turn: PersonalChatTurn, result: TurnResult): void {
  if (turn.settled) return;
  turn.settled = true;
  if ('version' in result) {
    settledVersions.set(turn.chatId, Math.max(settledVersions.get(turn.chatId) ?? 0, result.version));
  } else settledVersions.delete(turn.chatId);
  turn.resolve(result);
  turn.resolveAdmitted(result);
  turns.delete(key(turn.chatId, turn.messageId));
  if (tails.get(turn.chatId) === turn) tails.delete(turn.chatId);
}

export function completePersonalChatTurn(chatId: string, turnId: string, version: number): boolean {
  if (!Number.isSafeInteger(version) || version < 0) return false;
  for (const turn of turns.values()) {
    if (turn.chatId === chatId && turn.turnId === turnId) {
      settle(turn, { version });
      return true;
    }
  }
  return false;
}

/** Legacy storage ACKs identify the user message, not the preflight turn ID.
 * Call only after verifying its exact assistant row in canonical persistence. */
export function completePersonalChatMessage(chatId: string, messageId: string, version: number): boolean {
  if (!Number.isSafeInteger(version) || version < 0) return false;
  const turn = turns.get(key(chatId, messageId));
  if (!turn) return false;
  settle(turn, { version });
  return true;
}

export function failPersonalChatTurn(turn: PersonalChatTurn, error: unknown): void {
  settle(turn, { error: error instanceof Error ? error : new Error('Encrypted chat turn was not sent.') });
}

export function failMatchingPersonalChatTurn(chatId: string, turnId: string, error: unknown): boolean {
  for (const turn of turns.values()) {
    if (turn.chatId === chatId && turn.turnId === turnId) {
      failPersonalChatTurn(turn, error);
      return true;
    }
  }
  return false;
}

export function failPersonalChatMessage(chatId: string, messageId: string, error: unknown): void {
  const turn = turns.get(key(chatId, messageId));
  if (turn) failPersonalChatTurn(turn, error);
}

export function clearPersonalChatTurnBarriers(): void {
  for (const turn of [...turns.values()]) failPersonalChatTurn(turn, new Error('Chat session ended.'));
  settledVersions.clear();
}

registerWorkspaceCacheClear(clearPersonalChatTurnBarriers);
