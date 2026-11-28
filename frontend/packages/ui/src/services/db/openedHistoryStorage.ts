/**
 * Physical IndexedDB routing and same-transaction invalidation for opened
 * history receipts. Legacy databases stay readable and have no fast receipt
 * authority. The renamed store prevents older unversioned writers from
 * mutating the gated store.
 */
export const LEGACY_CHAT_DATABASE_VERSION = 33;
export const COVERED_CHAT_DATABASE_VERSION = 34;
export const LEGACY_MESSAGE_STORE = "messages";
export const COVERED_MESSAGE_STORE = "saved_messages_v34";
export const OPENED_HISTORY_STORE = "opened_history_coverage";

export async function preferredChatDatabaseVersion(factory: IDBFactory, name: string): Promise<number> {
  if (typeof factory.databases !== "function") return LEGACY_CHAT_DATABASE_VERSION;
  try {
    const current = (await factory.databases()).find(database => database.name === name);
    return typeof current?.version === "number"
      ? Math.max(LEGACY_CHAT_DATABASE_VERSION, current.version)
      : COVERED_CHAT_DATABASE_VERSION;
  } catch (error) {
    if (error instanceof DOMException) return LEGACY_CHAT_DATABASE_VERSION;
    throw error;
  }
}

export function messageStoreName(database: Pick<IDBDatabase, "version">): string {
  return database.version === COVERED_CHAT_DATABASE_VERSION ? COVERED_MESSAGE_STORE : LEGACY_MESSAGE_STORE;
}

export function chatTransaction(database: IDBDatabase, stores: string | string[], mode: IDBTransactionMode): IDBTransaction {
  if (database.version !== COVERED_CHAT_DATABASE_VERSION) return database.transaction(stores, mode);
  const names = (typeof stores === "string" ? [stores] : stores)
    .map(name => name === LEGACY_MESSAGE_STORE ? messageStoreName(database) : name);
  if (mode === "readwrite" && names.includes(COVERED_MESSAGE_STORE)) names.push(OPENED_HISTORY_STORE);
  const transaction = database.transaction([...new Set(names)], mode);
  if (database.version === COVERED_CHAT_DATABASE_VERSION && names.includes(COVERED_MESSAGE_STORE)) {
    const nativeStore = transaction.objectStore.bind(transaction);
    // Keep the existing application/Rust logical store token at this boundary.
    // Unversioned legacy clients still use their own untouched native method.
    transaction.objectStore = name => name === LEGACY_MESSAGE_STORE ? savedMessages(transaction) : nativeStore(name);
  }
  return transaction;
}

type Mutation = { chatId: string; revision: string; ciphertext?: string };
const revisions = new WeakMap<IDBTransaction, Map<string, string>>();

export function invalidateOpenedHistory(transaction: IDBTransaction, chatId: unknown): void {
  if (transaction.db?.version !== COVERED_CHAT_DATABASE_VERSION ||
      !transaction.objectStoreNames.contains(OPENED_HISTORY_STORE)) return;
  const store = transaction.objectStore(OPENED_HISTORY_STORE);
  if (typeof chatId !== "string" || !chatId) {
    store.clear();
    revisions.delete(transaction);
    return;
  }
  const changed = revisions.get(transaction) ?? new Map<string, string>();
  revisions.set(transaction, changed);
  if (changed.has(chatId)) return;
  const revision = crypto.randomUUID();
  changed.set(chatId, revision);
  store.put({ chatId, revision } satisfies Mutation);
}

export const LEGACY_COVERAGE_FIELD = "opened_history_receipt_v1";
export const LEGACY_COVERAGE_ROW_LIMIT = 512;

export interface LegacyOpenedHistoryPage {
  rows: Record<string, unknown>[];
  encryptedChatKey: string;
}

export interface OpenedHistoryPageWitness {
  before: string | null;
  after: string;
  encryptedChatKey: string;
}

export function readOpenedHistoryMutation(transaction: IDBTransaction, chatId: string): IDBRequest<Mutation | undefined> {
  return transaction.objectStore(OPENED_HISTORY_STORE).get(chatId);
}

export function openedHistoryRevision(transaction: IDBTransaction, chatId: string): string | undefined {
  return revisions.get(transaction)?.get(chatId);
}

type MessageRow = { chat_id?: string; message_id?: IDBValidKey };
/** Return the native store for reads and wrap only the three mutation entry
 * points. Cursor mutations explicitly invalidate using the row already read.
 * A key-based delete/replace checks the old row so a move stamps both chats. */
export function savedMessages(transaction: IDBTransaction): IDBObjectStore {
  const store = transaction.objectStore(messageStoreName(transaction.db));
  if (!transaction.objectStoreNames.contains(OPENED_HISTORY_STORE)) return store;
  const invalidatePrevious = (key: IDBValidKey) => {
    const previous = store.get(key);
    previous.addEventListener("success", () => {
      if (previous.result) invalidateOpenedHistory(transaction, previous.result.chat_id);
    });
  };
  return new Proxy(store, {
    get(target, property) {
      switch (property) {
        case "add":
          return (row: MessageRow, key?: IDBValidKey) => {
            invalidateOpenedHistory(transaction, row.chat_id);
            return key === undefined ? store.add(row) : store.add(row, key);
          };
        case "put":
          return (row: MessageRow, key?: IDBValidKey) => {
            const physicalKey = key ?? row.message_id;
            if (physicalKey !== undefined) invalidatePrevious(physicalKey);
            invalidateOpenedHistory(transaction, row.chat_id);
            return key === undefined ? store.put(row) : store.put(row, key);
          };
        case "delete":
          return (key: IDBValidKey | IDBKeyRange) => {
            if (key instanceof IDBKeyRange) invalidateOpenedHistory(transaction, null);
            else invalidatePrevious(key);
            return store.delete(key);
          };
        case "clear":
          return () => {
            invalidateOpenedHistory(transaction, null);
            return store.clear();
          };
        default: {
          const value = Reflect.get(target, property, target);
          return typeof value === "function" ? value.bind(target) : value;
        }
      }
    },
  });
}
