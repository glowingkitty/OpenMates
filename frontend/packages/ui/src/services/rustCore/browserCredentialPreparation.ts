/** Inactive host orchestration only; no crypto, cookie or sync policy. */
import {withAuthRefreshLock,withAuthRefreshEffectLease,assertAuthRefreshEffectLease} from "./browserAdapters";
import type {AuthRefreshEffectLease} from "./browserAdapters";
import {executeBrowserCredentialIO,validBrowserCredentialIOEffect} from "./browserCredentialStorage";
import type {BrowserCredentialIOEffect,BrowserCredentialIOResult} from "./browserCredentialStorage";
import type {BrowserSealedCredentials,BrowserHostCommit} from "./browserCredentialStorage";
import type {BrowserCoreWorkerHost} from "./workerHost";
import type {PriorProfileReader,PriorProfileSnapshot} from "./priorProfile";
import type {PriorProfileLifecycle} from "./platformLifecycle";
import type {SessionStatus} from "./protocol";
interface Context{owner:string;teamId:string|null;workspaceEpoch:number;apiEndpoint:string;appOrigin:string}
interface HostStore{browserCredentialSnapshot(mode:"read"|"write"|"delete",snapshot:Readonly<BrowserSealedCredentials>,lifecycle:PriorProfileLifecycle,generation:number,signal:AbortSignal,guard:()=>void):Promise<BrowserHostCommit|null>}
export async function prepareBrowserCredentialHost(input:{host:BrowserCoreWorkerHost;reader:PriorProfileReader;prior:PriorProfileSnapshot;lifecycle:PriorProfileLifecycle;status:SessionStatus;locks:LockManager;store:HostStore;signal:AbortSignal;context:()=>Context}):Promise<{commit:BrowserHostCommit;cleanup:()=>Promise<void>}> {
 const {host,reader,prior,lifecycle,status,signal}=input,original={...input.context()};
 const current=()=>{const c=input.context();if(signal.aborted||prior.persistence!=="persisted"||status.persistence!=="persisted"||lifecycle.current()!==prior.generation
  ||status.principal!==prior.profile.principal||c.owner!==status.principal||c.teamId!==null||Object.keys(original).some(k=>c[k as keyof Context]!==original[k as keyof Context]))throw Error("invalidated_snapshot");};
 const assert=async()=>{current();await reader.assertCurrent(prior);current();};
 try{
  await assert();const response=await host.request({operation:"prepare_credentials",handle:status.handle,generation:status.generation},signal);await assert();
  if(!response.ok||!response.snapshot||!response.status||response.status.handle!==status.handle||response.snapshot.owner!==original.owner||response.snapshot.generation!==status.generation||response.snapshot.apiEndpoint!==original.apiEndpoint||response.snapshot.appOrigin!==original.appOrigin)throw Error("invalidated_snapshot");
  const snapshot=Object.freeze({...response.snapshot});
  const access=(mode:"read"|"write"|"delete")=>withAuthRefreshLock(input.locks,signal,async()=>{await assert();current();const result=await input.store.browserCredentialSnapshot(mode,snapshot,lifecycle,prior.generation,signal,current);await assert();return result;});
  const commit=await access("write");if(!commit||commit.credentialAcknowledged!==false||commit.crossDatabaseAssociationProven!==false)throw Error("invalidated_snapshot");
  const read=await access("read");if(!read||JSON.stringify(read.snapshot)!==JSON.stringify(snapshot))throw Error("invalidated_snapshot");
  const checked=await host.request({operation:"validate_credentials",handle:status.handle,generation:status.generation,snapshot},signal);await assert();
  if(!checked.ok||JSON.stringify(checked.snapshot)!==JSON.stringify(snapshot))throw Error("invalidated_snapshot");
  return {commit,cleanup:async()=>{await access("delete");}};
 }catch{host.close();throw Error("invalidated_snapshot");}
}


/** Reverse-effect host adapter for the dedicated Rust-owned CAS RPC. The
 * Worker owns the actual full-operation WebLock; Page IO must not reacquire it.
 * WorkerHost supplies a local lease only for its correlated owned request.
 */
export function createBrowserCredentialEffectHandler(input: {
  issuer: object; reader: PriorProfileReader; prior: PriorProfileSnapshot;
  lifecycle: PriorProfileLifecycle; database: () => Promise<IDBDatabase>; context: () => Context;
}): {
  current: () => void;
  execute: (effect: BrowserCredentialIOEffect, lease: AuthRefreshEffectLease, signal: AbortSignal) => Promise<BrowserCredentialIOResult>;
  close: () => Promise<void>;
} {
  const captured = Object.freeze({ ...input.context() });
  const lifetime = new AbortController(), pending = new Set<Promise<unknown>>();
  let closed = false, closing: Promise<void> | null = null;
  const current = () => {
    const context = input.context();
    if (closed || lifetime.signal.aborted || input.prior.persistence !== "persisted"
      || input.lifecycle.current() !== input.prior.generation
      || captured.owner !== input.prior.profile.principal
      || Object.keys(captured).some(key => captured[key as keyof Context] !== context[key as keyof Context]))
      throw new Error("invalidated_snapshot");
  };
  current();
  const release = input.lifecycle.observe(() => lifetime.abort());
  const execute = (effect: BrowserCredentialIOEffect, lease: AuthRefreshEffectLease, signal: AbortSignal) => {
    let capturedEffect: BrowserCredentialIOEffect;
    try {
      current();
      if (!validBrowserCredentialIOEffect(effect)) throw new Error("invalid_request");
      const scope = effect.kind === "read" ? effect : effect.next;
      if (scope.owner !== captured.owner || scope.apiEndpoint !== captured.apiEndpoint || scope.appOrigin !== captured.appOrigin)
        throw new Error("invalidated_snapshot");
      capturedEffect = effect.kind === "read" ? Object.freeze({ ...effect })
        : Object.freeze({ ...effect, expected: effect.expected === null ? null : Object.freeze({ ...effect.expected }), next: Object.freeze({ ...effect.next }) });
    } catch (error) { return Promise.reject(error); }
    const operationId = capturedEffect.operationId;
    const operation = Promise.resolve().then(() => {
      current();
      return withAuthRefreshEffectLease(lease, input.issuer, operationId, async ownedSignal => {
        const combined = new AbortController();
        const abort = () => combined.abort();
        const signals = [signal, ownedSignal, lifetime.signal];
        for (const item of signals) { item.addEventListener("abort", abort, { once: true }); if (item.aborted) abort(); }
        const guard = () => {
          current();
          if (combined.signal.aborted) throw new Error("cancelled");
          assertAuthRefreshEffectLease(lease, input.issuer, operationId);
        };
        try {
          guard(); await input.reader.assertCurrent(input.prior); guard();
          const database = await input.database(); guard();
          const result = await executeBrowserCredentialIO(database, capturedEffect, input.lifecycle,
            input.prior.generation, combined.signal, guard);
          guard(); await input.reader.assertCurrent(input.prior); guard();
          return result;
        } finally { for (const item of signals) item.removeEventListener("abort", abort); }
      });
    });
    pending.add(operation);
    void operation.then(() => pending.delete(operation), () => pending.delete(operation));
    return operation;
  };
  return { current, execute, close: () => {
    if (!closing) {
      closed = true; lifetime.abort();
      closing = (async () => { while (pending.size) await Promise.allSettled([...pending]); })().finally(release);
    }
    return closing;
  } };
}
