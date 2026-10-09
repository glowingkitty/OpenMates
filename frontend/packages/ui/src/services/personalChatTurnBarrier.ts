/** In-memory ordering for personal encrypted turns. Only a canonical terminal
 * persistence acknowledgement may advance the next turn's server version. */
type TurnResult = { version: number } | { error: Error };

export interface PersonalChatTurn {
  readonly chatId: string;
  readonly messageId: string;
  readonly predecessor: Promise<TurnResult> | null;
  readonly done: Promise<TurnResult>;
  turnId: string | null;
  settled: boolean;
  resolve: (result: TurnResult) => void;
}

const tails = new Map<string, PersonalChatTurn>();
const turns = new Map<string, PersonalChatTurn>();

function key(chatId: string, messageId: string): string {
  return `${chatId}:${messageId}`;
}

export function reservePersonalChatTurn(chatId: string, messageId: string): PersonalChatTurn {
  const identity = key(chatId, messageId);
  const existing = turns.get(identity);
  if (existing) return existing;
  let resolve!: (result: TurnResult) => void;
  const done = new Promise<TurnResult>((settle) => { resolve = settle; });
  const turn: PersonalChatTurn = {
    chatId, messageId, predecessor: tails.get(chatId)?.done ?? null,
    done, turnId: null, settled: false, resolve,
  };
  tails.set(chatId, turn);
  turns.set(identity, turn);
  return turn;
}

export async function awaitPersonalChatPredecessor(turn: PersonalChatTurn): Promise<number | null> {
  if (!turn.predecessor) return null;
  const result = await turn.predecessor;
  if ('error' in result) throw new Error('The previous encrypted reply has not been saved. Retry this message after recovery.', { cause: result.error });
  return result.version;
}

export function bindPersonalChatTurn(turn: PersonalChatTurn, turnId: string): void {
  if (turn.settled) throw new Error('Cannot bind a settled encrypted chat turn.');
  if (turn.turnId && turn.turnId !== turnId) throw new Error('Encrypted chat turn identity changed.');
  turn.turnId = turnId;
}

function settle(turn: PersonalChatTurn, result: TurnResult): void {
  if (turn.settled) return;
  turn.settled = true;
  turn.resolve(result);
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
}
