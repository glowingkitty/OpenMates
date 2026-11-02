/**
 * Read-only existing IndexedDB selection witness for the inactive Rust preview.
 * Never initializes/repairs/upgrades/deletes a DB, unwraps keys, decrypts content,
 * imports a Rust cache, or grants owner authority. Only Rust/server may do that.
 * The adapter reads one legacy encrypted row after its transaction completes.
 * Database absence, version races, blocked opens and cancellation fail closed.
 * Ciphertexts remain page-local evidence and are never proof/diagnostic output.
 */
import { committedRequest } from "./browserAdapters";
export interface ChatCiphertextWitness { id: string; encryptedTitle: string; encryptedKey: string; messagesVersion: number; databaseVersion: number }
export async function readExistingChat(factory: IDBFactory, chatId: string, signal: AbortSignal): Promise<ChatCiphertextWitness> {
  if (!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(chatId) || typeof factory.databases !== "function") throw new Error("unavailable");
  const lifetime = new AbortController();
  const abort = () => lifetime.abort(); signal.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 5000);
  let database: IDBDatabase | null = null;
  try {
    if (signal.aborted) abort();
    const cancelled = new Promise<never>((_, reject) => {
      lifetime.signal.addEventListener("abort", () => reject(new Error(signal.aborted ? "cancelled" : "unavailable")), { once: true });
      if (lifetime.signal.aborted) reject(new Error(signal.aborted ? "cancelled" : "unavailable"));
    });
    const databases = await Promise.race([factory.databases(), cancelled]);
    if (!databases.some(row => row.name === "chats_db" && Number.isSafeInteger(row.version) && Number(row.version) > 0)) throw new Error("unavailable");
    database = await Promise.race([new Promise<IDBDatabase>((resolve, reject) => {
      const request = factory.open("chats_db");
      request.onupgradeneeded = () => { request.transaction?.abort(); reject(new Error("unavailable")); };
      request.onblocked = request.onerror = () => reject(new Error("unavailable"));
      request.onsuccess = () => {
        const db = request.result;
        if (lifetime.signal.aborted) { db.close(); reject(new Error("unavailable")); }
        else resolve(db);
      };
    }), cancelled]);
    const db = database;
    db.onversionchange = () => { db.close(); abort(); };
    if (!db.objectStoreNames.contains("chats")) throw new Error("unavailable");
    const transaction = db.transaction("chats", "readonly");
    const raw = await Promise.race([committedRequest(transaction, transaction.objectStore("chats").get(chatId), lifetime.signal), cancelled]);
    const row = raw as Record<string, unknown> | undefined;
    const envelope = (value: unknown): value is string => typeof value === "string" && value.length >= 40 && value.length <= 16384
      && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value);
    if (!row || row.chat_id !== chatId || !envelope(row.encrypted_title)
      || !envelope(row.encrypted_chat_key)
      || !Number.isSafeInteger(row.messages_v) || Number(row.messages_v) < 1) throw new Error("unavailable");
    return { id: chatId, encryptedTitle: row.encrypted_title, encryptedKey: row.encrypted_chat_key,
      messagesVersion: Number(row.messages_v), databaseVersion: db.version };
  } finally { clearTimeout(timer); signal.removeEventListener("abort", abort); lifetime.abort(); database?.close(); }
}
