/** Inactive thin IndexedDB IO only. Rust owns encrypted payload and policy.
 * This commit proves one owner-row/ciphertext transaction, NOT cross-DB key or
 * cookie coherence. It MUST NOT authorize SDK credential ACK/publication.
 */
import type { PriorProfileLifecycle } from "./platformLifecycle";
export const BROWSER_CREDENTIAL_RECORD = "openmates_rust_browser_credentials_v1";
export interface BrowserSealedCredentials {
  version: 1; owner: string; generation: number; credentialRevision: number;
  apiEndpoint: string; appOrigin: string; snapshotId: string;
  ciphertext: string; ciphertextSha256: string;
}
export interface BrowserHostCommit {
  readonly snapshot: Readonly<BrowserSealedCredentials>;
  readonly lifecycleGeneration: number;
  readonly transactionCommitted: true;
  readonly ownerRowAtomic: true;
  readonly crossDatabaseAssociationProven: false;
  readonly credentialAcknowledged: false;
}
const fields=["version","owner","generation","credentialRevision","apiEndpoint","appOrigin","snapshotId","ciphertext","ciphertextSha256"];
export function validBrowserSealedCredentials(value: unknown): value is BrowserSealedCredentials {
  if(typeof value!=="object"||value===null||Object.getPrototypeOf(value)!==Object.prototype)return false;
  const v=value as Record<string,unknown>;
  if(Object.keys(v).length!==fields.length||!Object.keys(v).every(k=>fields.includes(k)))return false;
  const uuid=(v:unknown)=>typeof v==="string"&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(v);
  const endpoint=(v:unknown)=>{if(typeof v!=="string"||v.length>2048)return false;try{const u=new URL(v);return ["http:","https:"].includes(u.protocol)&&!u.username&&!u.password&&!u.search&&!u.hash&&u.origin===v;}catch{return false;}};
  return v.version===1&&uuid(v.owner)&&uuid(v.snapshotId)&&Number.isSafeInteger(v.generation)&&(v.generation as number)>0
    &&Number.isSafeInteger(v.credentialRevision)&&(v.credentialRevision as number)>0&&endpoint(v.apiEndpoint)&&endpoint(v.appOrigin)
    &&typeof v.ciphertext==="string"&&v.ciphertext.length>=40&&v.ciphertext.length<=12*1024
    &&/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(v.ciphertext)
    &&typeof v.ciphertextSha256==="string"&&/^[a-f0-9]{64}$/.test(v.ciphertextSha256)
    &&new TextEncoder().encode([v.owner,v.apiEndpoint,v.appOrigin,v.snapshotId,v.ciphertext,v.ciphertextSha256].join("")).byteLength+1024<=16*1024;
}
/** Caller holds existing auth refresh lock; guard binds captured profile/key
 * reference, owner, context and lifecycle. Never await inside an IDB transaction.
 */
export function browserCredentialTransaction(db: IDBDatabase, mode: "read"|"write"|"delete",
  expected: Readonly<BrowserSealedCredentials>, lifecycle: PriorProfileLifecycle,
  lifecycleGeneration: number, signal: AbortSignal, guard: ()=>void): Promise<BrowserHostCommit|null> {
  if(!validBrowserSealedCredentials(expected))return Promise.reject(new Error("invalid_request"));
  const captured=Object.freeze({...expected});
  let invalidated=false;
  const current=()=>{if(invalidated)throw Error("invalidated_snapshot");if(signal.aborted)throw Error("cancelled");if(lifecycle.current()!==lifecycleGeneration)throw Error("invalidated_snapshot");guard();};
  try{current();}catch{return Promise.reject(new Error("invalidated_snapshot"));}
  return new Promise((resolve,reject)=>{
    let transaction:IDBTransaction|null=null, found:BrowserSealedCredentials|null=null, failure="storage_failed", settled=false;
    const abort=()=>{invalidated=true;failure=signal.aborted?"cancelled":"invalidated_snapshot";try{transaction?.abort();}catch{/* Terminal callback remains sole settlement. */}};
    const release=lifecycle.observe(abort);
    const cleanup=()=>{release();signal.removeEventListener("abort",abort);db.removeEventListener("versionchange",abort);};
    const fail=()=>{if(settled)return;settled=true;cleanup();reject(new Error(failure));};
    try{
      current();transaction=db.transaction("user_data",mode==="read"?"readonly":"readwrite");
      transaction.onabort=fail;
      transaction.onerror=()=>{/* Transaction abort is terminal; request success is not commit. */};
      transaction.oncomplete=()=>{
        if(settled)return;settled=true;cleanup();
        try{current();resolve(found?Object.freeze({snapshot:Object.freeze({...found}),lifecycleGeneration,transactionCommitted:true as const,ownerRowAtomic:true as const,crossDatabaseAssociationProven:false as const,credentialAcknowledged:false as const}):null);}
        catch{reject(new Error("invalidated_snapshot"));}
      };
      signal.addEventListener("abort",abort,{once:true});db.addEventListener("versionchange",abort);
      const store=transaction.objectStore("user_data"),owner=store.get("id");
      owner.onsuccess=()=>{
        try{
          current();if(owner.result!==captured.owner){failure="owner_mismatch";transaction!.abort();return;}
          const exists=store.getKey(BROWSER_CREDENTIAL_RECORD);
          exists.onsuccess=()=>{try{current();
            if(exists.result===undefined){if(mode==="write"){store.put(captured,BROWSER_CREDENTIAL_RECORD);found=captured;}return;}
            const read=store.get(BROWSER_CREDENTIAL_RECORD);read.onsuccess=()=>{try{current();if(!validBrowserSealedCredentials(read.result))throw Error("invalid_snapshot");
              const row=read.result;if(fields.some(k=>row[k as keyof BrowserSealedCredentials]!==captured[k as keyof BrowserSealedCredentials]))throw Error("invalid_snapshot");if(mode==="delete")store.delete(BROWSER_CREDENTIAL_RECORD);else found=Object.freeze({...row});}catch{failure="invalid_snapshot";transaction!.abort();}};
          }catch{failure="invalid_snapshot";transaction!.abort();}};
        }catch{failure="invalidated_snapshot";try{transaction!.abort();}catch{/* Already terminal. */}}
      };
      current();
    }catch{failure="storage_failed";if(transaction){try{transaction.abort();}catch{fail();}}else fail();}
  });
}
/** Opt-in observer uses the existing lifecycle; no second coordinator. IDB key
 * writes/cookie changes without cooperating notifications remain OPEN.
 */
export function bindBrowserCredentialInvalidation(lifecycle:PriorProfileLifecycle,page:Window,channel:BroadcastChannel):()=>void {
  const invalidate=()=>lifecycle.invalidate();
  const storage=(event:StorageEvent)=>{if(event.key===null||["openmates_email_encrypted_master","openmates_email_salt","openmates_was_stay_logged_in"].includes(event.key))invalidate();};
  const message=(event:MessageEvent<unknown>)=>{const value=event.data;if(typeof value==="object"&&value!==null&&Object.keys(value).length===2&&"version" in value&&value.version===1&&"type" in value&&value.type==="invalidate")invalidate();};
  page.addEventListener("pagehide",invalidate);page.addEventListener("storage",storage);channel.addEventListener("message",message);
  return()=>{page.removeEventListener("pagehide",invalidate);page.removeEventListener("storage",storage);channel.removeEventListener("message",message);};
}


export type BrowserCredentialIOEffect =
  | { readonly kind: "read"; readonly operationId: string; readonly owner: string; readonly apiEndpoint: string; readonly appOrigin: string }
  | { readonly kind: "cas"; readonly operationId: string; readonly expected: Readonly<BrowserSealedCredentials> | null; readonly next: Readonly<BrowserSealedCredentials> };
export type BrowserCredentialIOResult = {
  readonly kind: "read" | "cas"; readonly operationId: string;
  readonly snapshot: Readonly<BrowserSealedCredentials> | null;
  readonly expected?: Readonly<BrowserSealedCredentials> | null;
  readonly transactionCommitted: true; readonly ownerRowAtomic: true;
  readonly crossDatabaseAssociationProven: false; readonly credentialAcknowledged: false;
};
const credentialUUID = (value: unknown): value is string => typeof value === "string"
  && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value);
function sameCredentialRecord(a: Readonly<BrowserSealedCredentials>, b: Readonly<BrowserSealedCredentials>): boolean {
  return fields.every(key => a[key as keyof BrowserSealedCredentials] === b[key as keyof BrowserSealedCredentials]);
}
export function validBrowserCredentialIOEffect(value: unknown): value is BrowserCredentialIOEffect {
  if (typeof value !== "object" || value === null || Object.getPrototypeOf(value) !== Object.prototype) return false;
  const v = value as Record<string, unknown>;
  try { if (new TextEncoder().encode(JSON.stringify(v)).byteLength + 1024 > 16 * 1024) return false; }
  catch { return false; }
  if (!credentialUUID(v.operationId)) return false;
  const exact = (names: string[]) => Object.keys(v).length === names.length && Object.keys(v).every(key => names.includes(key));
  if (v.kind === "read") {
    if (!exact(["kind", "operationId", "owner", "apiEndpoint", "appOrigin"]) || !credentialUUID(v.owner)) return false;
    return [v.apiEndpoint, v.appOrigin].every(value => {
      if (typeof value !== "string" || value.length > 2048) return false;
      try { const u = new URL(value); return ["http:", "https:"].includes(u.protocol) && u.origin === value && !u.username && !u.password; }
      catch { return false; }
    });
  }
  return v.kind === "cas" && exact(["kind", "operationId", "expected", "next"])
    && validBrowserSealedCredentials(v.next) && (v.expected === null || validBrowserSealedCredentials(v.expected)
      && v.expected.owner === v.next.owner
      && v.expected.apiEndpoint === v.next.apiEndpoint && v.expected.appOrigin === v.next.appOrigin);
}

/** Exact owner-row/CAS IO only. Rust supplied and admitted the predecessor and
 * next ciphertext; this function cannot establish key/cookie association/ACK.
 * guard includes the real endpoint-issued local effect lease and operation.
 */
export function executeBrowserCredentialIO(db: IDBDatabase, effect: BrowserCredentialIOEffect,
  lifecycle: PriorProfileLifecycle, lifecycleGeneration: number, signal: AbortSignal,
  guard: () => void): Promise<BrowserCredentialIOResult> {
  if (!validBrowserCredentialIOEffect(effect)) return Promise.reject(new Error("invalid_request"));
  const captured: BrowserCredentialIOEffect = effect.kind === "read" ? Object.freeze({ ...effect })
    : Object.freeze({ ...effect, expected: effect.expected === null ? null : Object.freeze({ ...effect.expected }), next: Object.freeze({ ...effect.next }) });
  const scope = captured.kind === "read" ? captured : captured.next;
  let invalidated = false, refused = false;
  const current = () => {
    if (signal.aborted) throw new Error("cancelled");
    if (invalidated || refused || lifecycle.current() !== lifecycleGeneration) throw new Error("invalidated_snapshot");
    guard();
  };
  try { current(); } catch { return Promise.reject(new Error("invalidated_snapshot")); }
  return new Promise((resolve, reject) => {
    let transaction: IDBTransaction | null = null, failure = "storage_failed", settled = false;
    let snapshot: Readonly<BrowserSealedCredentials> | null = null;
    const abort = () => {
      invalidated = true; failure = signal.aborted ? "cancelled" : "invalidated_snapshot";
      try { transaction?.abort(); } catch { /* Actual oncomplete/onabort remains sole settlement. */ }
    };
    const release = lifecycle.observe(abort);
    const cleanup = () => { release(); signal.removeEventListener("abort", abort); db.removeEventListener("versionchange", abort); };
    const refuse = (code: string) => {
      if (!refused) { failure = code; refused = true; }
      try { transaction?.abort(); } catch { /* Wait actual terminal even if abort is no longer possible. */ }
    };
    const failed = () => { if (settled) return; settled = true; cleanup(); reject(new Error(failure)); };
    try {
      current();
      transaction = db.transaction("user_data", captured.kind === "read" ? "readonly" : "readwrite");
      transaction.onabort = failed;
      transaction.onerror = () => { /* Abort terminal event settles. */ };
      transaction.oncomplete = () => {
        if (settled) return; settled = true; cleanup();
        if (refused) { reject(new Error(failure)); return; }
        try {
          current();
          resolve(Object.freeze({ kind: captured.kind, operationId: captured.operationId, snapshot,
            ...(captured.kind === "cas" ? { expected: captured.expected } : {}),
            transactionCommitted: true as const, ownerRowAtomic: true as const,
            crossDatabaseAssociationProven: false as const, credentialAcknowledged: false as const }));
        } catch { reject(new Error(signal.aborted ? "cancelled" : "invalidated_snapshot")); }
      };
      signal.addEventListener("abort", abort, { once: true }); db.addEventListener("versionchange", abort);
      const store = transaction.objectStore("user_data"), owner = store.get("id");
      const accept = (row: BrowserSealedCredentials | null) => {
        current();
        if (captured.kind === "read") { snapshot = row === null ? null : Object.freeze({ ...row }); return; }
        if ((row === null) !== (captured.expected === null)
          || (row !== null && captured.expected !== null && !sameCredentialRecord(row, captured.expected))) {
          refuse("credential_conflict"); return;
        }
        store.put(captured.next, BROWSER_CREDENTIAL_RECORD);
        snapshot = captured.next;
      };
      owner.onsuccess = () => {
        try {
          current(); if (owner.result !== scope.owner) { refuse("owner_mismatch"); return; }
          const exists = store.getKey(BROWSER_CREDENTIAL_RECORD);
          exists.onsuccess = () => {
            try {
              current(); if (exists.result === undefined) { accept(null); return; }
              const read = store.get(BROWSER_CREDENTIAL_RECORD);
              read.onsuccess = () => {
                try {
                  current();
                  if (!validBrowserSealedCredentials(read.result) || read.result.owner !== scope.owner
                    || read.result.apiEndpoint !== scope.apiEndpoint || read.result.appOrigin !== scope.appOrigin) {
                    refuse("invalid_snapshot"); return;
                  }
                  accept(read.result);
                } catch { refuse("invalidated_snapshot"); }
              };
            } catch { refuse("invalidated_snapshot"); }
          };
        } catch { refuse("invalidated_snapshot"); }
      };
      current();
    } catch {
      refuse("storage_failed");
      if (!transaction) failed();
    }
  });
}
