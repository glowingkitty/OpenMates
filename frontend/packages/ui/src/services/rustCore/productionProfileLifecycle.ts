import { browserProfileLifecycle, isProfileMutation } from "./platformLifecycle";
import type { PriorProfileLifecycle } from "./platformLifecycle";

/** Hold the existing snapshot fence over the entire asynchronous mutation,
 * including rejected IO and cleanup. This adapter cannot repair/rollback data.
 */
export async function withProfileMutation<T>(operation: () => Promise<T>): Promise<T> {
  const finish = browserProfileLifecycle.beginMutation();
  try { return await operation(); } finally { finish(); }
}
export function profileMutation<T>(operation: () => T): T {
  const finish = browserProfileLifecycle.beginMutation();
  try { return operation(); } finally { finish(); }
}

/** Explicit page-owned lifetime only. Install BEFORE prior-profile capture and
 * keep installed through admission and all reads. Closing cannot re-admit or
 * automatically retry. Existing UI runs unchanged when no binding is installed.
 * Cross-tab messages are revocation signals, never an atomic admission snapshot.
 */
export function bindProductionProfileLifetime(input: {
  host: { close(): void };
  page: Pick<Window, "addEventListener" | "removeEventListener">;
  channel: Pick<BroadcastChannel, "addEventListener" | "removeEventListener" | "close">;
  lifecycle: PriorProfileLifecycle;
},lifecycleTeardown?: (origin?:object)=>void): () => void {
  let closed = false;
  const finish = (origin?:object) => {
    if (closed) return;
    closed = true;
    release();
    input.page.removeEventListener("pagehide", close);
    input.page.removeEventListener("storage", storage);
    input.channel.removeEventListener("message", message);
    input.channel.removeEventListener("messageerror", close);
    try { input.channel.close(); } finally { if(lifecycleTeardown)lifecycleTeardown(origin);else input.host.close(); }
  };
  const close=()=>finish();
  const fromLifecycle=(origin?:object)=>finish(origin);
  const storage = (event: Event) => {
    const key = (event as StorageEvent).key;
    if (key === null || ["openmates_email_encrypted_master", "openmates_email_salt", "openmates_was_stay_logged_in", "openmates_user_db_initialized", "openmates_needs_cleanup"].includes(key)) {
      input.lifecycle.invalidateFromPeer();
    }
  };
  const message = (event: Event) => {
    if (isProfileMutation((event as MessageEvent<unknown>).data)) input.lifecycle.invalidateFromPeer();
  };
  const release = input.lifecycle.observe(fromLifecycle);
  input.page.addEventListener("pagehide", close);
  input.page.addEventListener("storage", storage);
  input.channel.addEventListener("message", message);
  input.channel.addEventListener("messageerror", close);
  // A capture cannot begin while an already active local mutation owns the fence.
  try { input.lifecycle.current(); } catch (error) { close(); throw error; }
  return close;
}

/** Keep a separate fence when a caller rejects before IndexedDB reaches a
 * terminal event (request error/blocked is not a completed mutation). Existing
 * request handlers, caller errors and durability acknowledgements stay intact.
 */
export function beginProfileMutation(): () => void {
  return browserProfileLifecycle.beginMutation();
}
export function fenceProfileTransaction(transaction: IDBTransaction): void {
  const finish = beginProfileMutation();
  const terminal = () => {
    transaction.removeEventListener("complete", terminal);
    transaction.removeEventListener("abort", terminal);
    finish();
  };
  transaction.addEventListener("complete", terminal);
  transaction.addEventListener("abort", terminal);
}
