/** Isolated preview proof only. No import from production bootstrap/actions.
 * Two genuine connections exercise the actual crypto-key deletion lifetime.
 * Unknown schema/data refuses before deletion; key bytes never leave WebCrypto.
 */
import { deleteCryptoDatabase, getMasterKey, saveMasterKey } from "../cryptoKeyStorage";
import { browserProfileLifecycle } from "./platformLifecycle";
import { committedRequest } from "./browserAdapters";
import type { PriorProfileReader } from "./priorProfile";

export interface StorageProof {
  knownSchema: boolean; blockedCallerRejected: boolean; captureRefused: boolean;
  keyWriteRefused: boolean; fenceHeld: boolean; terminalReleased: boolean;
  exactKeyShapeRestored: boolean; freshCaptureDecrypted: boolean;
}
interface Snapshot { database: IDBDatabase; key: CryptoKey | null }
function unavailable(): never { throw new Error("unavailable"); }
async function knownSnapshot(): Promise<Snapshot> {
  if (typeof indexedDB.databases !== "function" || !(await indexedDB.databases()).some(row => row.name === "openmates_crypto" && row.version === 1)) unavailable();
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("openmates_crypto", 1); let abandoned = false;
    request.onupgradeneeded = () => { abandoned = true; request.transaction?.abort(); reject(new Error("unavailable")); };
    request.onerror = request.onblocked = () => { abandoned = true; reject(new Error("unavailable")); };
    request.onsuccess = () => { if (abandoned) request.result.close(); else resolve(request.result); };
  });
  try {
    if (database.version !== 1 || database.objectStoreNames.length !== 1 || !database.objectStoreNames.contains("keys")) unavailable();
    const transaction = database.transaction("keys", "readonly"), store = transaction.objectStore("keys");
    if (store.keyPath !== null || store.autoIncrement || store.indexNames.length !== 0) { transaction.abort(); unavailable(); }
    // Metadata is bounded before selecting a value. Never clone unrelated rows.
    const countRequest = store.count();
    const keysRequest = store.getAllKeys(undefined, 2);
    const selected: { request: IDBRequest<unknown> | null } = { request: null };
    keysRequest.onsuccess = () => {
      const count = countRequest.result, keys = keysRequest.result;
      if (!Number.isSafeInteger(count) || count < 0 || count > 1 || !Array.isArray(keys)
        || keys.length !== count || (count === 1 && keys[0] !== "master_key")) { transaction.abort(); return; }
      if (count === 1) selected.request = store.get("master_key");
    };
    const count = await committedRequest(transaction, countRequest, new AbortController().signal);
    const keys = keysRequest.result;
    if (!Array.isArray(keys) || count !== keys.length || count > 1) unavailable();
    if (keys.length === 0) return { database, key: null };
    const key = selected.request?.result;
    if (keys[0] !== "master_key" || !(key instanceof CryptoKey) || key.type !== "secret"
      || key.algorithm.name !== "AES-GCM" || (key.algorithm as AesKeyAlgorithm).length !== 256
      || !key.extractable || key.usages.length !== 2 || !key.usages.includes("encrypt") || !key.usages.includes("decrypt")) unavailable();
    return { database, key };
  } catch (error) { database.close(); throw error; }
}
function idleAfterDeletion(): { settled: Promise<number>; dispose: () => void } {
  let release: () => void = () => undefined;
  const settled = new Promise<number>(resolve => {
    release = browserProfileLifecycle.observe(() => {
      try { resolve(browserProfileLifecycle.current()); } catch { /* Still owned. */ }
    });
  });
  return { settled, dispose: () => release() };
}
async function refuses(operation: () => Promise<unknown>, code: string): Promise<boolean> {
  try { await operation(); return false; } catch (error) { return error instanceof Error && error.message === code; }
}
/** gate is test opt-in, never owner/session authority. Actual sources remain authoritative. */
export async function runBlockedCryptoDeleteProof(reader: PriorProfileReader, gate: boolean): Promise<StorageProof> {
  if (!gate || !["localhost", "127.0.0.1"].includes(location.hostname)) unavailable();
  // Inspect the exact known stored shape before any legacy getter can clean up.
  const snapshot = await knownSnapshot();
  const stay = localStorage.getItem("openmates_was_stay_logged_in");
  const clear = sessionStorage.getItem("clear_master_key_on_unload");
  if ((stay !== null && stay !== "true") || (clear !== null && clear !== "true")
    || (stay === "true" && clear === "true") || (snapshot.key !== null) !== (stay === "true")) {
    snapshot.database.close(); unavailable();
  }
  const sources = await (async () => {
    try {
      const original = await getMasterKey(); if (!original) unavailable();
      return { original, prior: await reader.capture() };
    } catch (error) { snapshot.database.close(); throw error; }
  })();
  const { original, prior } = sources;
  const persisted = prior.persistence === "persisted";
  if (original !== prior.key || (snapshot.key !== null) !== persisted) { snapshot.database.close(); unavailable(); }
  const plaintext = new TextEncoder().encode("isolated key-store capability proof");
  const iv = crypto.getRandomValues(new Uint8Array(12));
  let encrypted: ArrayBuffer;
  try { encrypted = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, original, plaintext); }
  catch { snapshot.database.close(); plaintext.fill(0); iv.fill(0); unavailable(); }
  const decrypts = async (key: CryptoKey) => {
    const bytes = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, encrypted));
    try { return bytes.length === plaintext.length && bytes.every((value, index) => value === plaintext[index]); }
    finally { bytes.fill(0); }
  };
  let peer: IDBDatabase | null = null;
  try {
    if (snapshot.key && !await decrypts(snapshot.key)) unavailable();
    const second = await knownSnapshot(); peer = second.database;
    if ((second.key !== null) !== persisted || (second.key && !await decrypts(second.key))) unavailable();
    // The cooperative peer closes on versionchange; the held snapshot connection
    // intentionally remains open. Both are genuine IndexedDB connections.
    peer.onversionchange = () => peer?.close();
    await reader.assertCurrent(prior);
    const result: StorageProof = { knownSchema: true, blockedCallerRejected: false, captureRefused: false,
      keyWriteRefused: false, fenceHeld: false, terminalReleased: false, exactKeyShapeRestored: false, freshCaptureDecrypted: false };
    // Keep this extra real connection open when deletion requests versionchange.
    snapshot.database.onversionchange = () => undefined;
    const idle = idleAfterDeletion();
    let deletionStarted = false;
    try {
      // No await between the final fence and invocation: an intervening writer
      // must win without being deleted and replaced by this proof's old key.
      if (browserProfileLifecycle.current() !== prior.generation || !Number.isSafeInteger(prior.generation + 4)) unavailable();
      const deletion = deleteCryptoDatabase();
      deletionStarted = true;
      result.blockedCallerRejected = await refuses(() => deletion, "storage_busy");
      result.captureRefused = await refuses(() => reader.capture(), "invalidated_snapshot");
      result.keyWriteRefused = await refuses(() => saveMasterKey(original, persisted), "storage_busy");
      try { browserProfileLifecycle.current(); } catch { result.fenceHeld = true; }
    } finally {
      snapshot.database.close();
      try {
        if (deletionStarted) {
          // No timeout/caller disposal can cancel deletion or release its fence.
          // Restore only while this proof still owns the terminal generation.
          const terminalGeneration = await idle.settled;
          result.terminalReleased = true;
          // Deletion alone advances begin+finish. A newer writer must not be
          // overwritten by restoration of the older captured key. No await
          // separates this check from enqueueing the restoring key writer.
          if (terminalGeneration !== prior.generation + 2 || browserProfileLifecycle.current() !== terminalGeneration) unavailable();
          const restoration = saveMasterKey(snapshot.key ?? original, persisted);
          await restoration;
          await getMasterKey(); // Settle legacy memory-only cleanup before capture.
        }
      } finally { idle.dispose(); }
    }
    const restored = await knownSnapshot();
    try { result.exactKeyShapeRestored = (restored.key !== null) === persisted && (!restored.key || await decrypts(restored.key)); }
    finally { restored.database.close(); }
    const fresh = await reader.capture(); await reader.assertCurrent(fresh);
    result.freshCaptureDecrypted = fresh.profile.principal === prior.profile.principal && fresh.persistence === prior.persistence && await decrypts(fresh.key);
    if (!Object.values(result).every(value => value === true)) unavailable();
    return result;
  } finally { peer?.close(); snapshot.database.close(); plaintext.fill(0); iv.fill(0); }
}
