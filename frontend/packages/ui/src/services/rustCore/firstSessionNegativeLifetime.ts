/// <reference lib="es2022.object" />
/** Rejection-only lifetime for a private first-session producer. Existing auth,
 * generic profile and crypto lifetimes stay unchanged. No positive readiness,
 * counter, owner policy, receipt, network grant or settlement lives here. */
import {firstSessionLifetimeEnabled} from './firstSessionPlatform';
import {PROFILE_MUTATION_CHANNEL} from './platformLifecycle';
const listeners=new Set<()=>void>();
const FRAME=/* @__PURE__ */ Object.freeze({version:1,type:'first-session-key-owner-invalidate'});
export function publishFirstSessionKeyOwnerNegative():void {
 if(!firstSessionLifetimeEnabled)return;
 for(const notify of [...listeners])try{notify();}catch{/* Preserve the original mutation. */}
 if(typeof window==='undefined'||typeof BroadcastChannel==='undefined')return;
 let channel:BroadcastChannel|undefined;
 try{channel=new BroadcastChannel(PROFILE_MUTATION_CHANNEL);channel.postMessage(FRAME);}catch{/* Local negative already delivered. */}
 finally{try{channel?.close();}catch{/* No mutation-result change. */}}
}
function negative(value:unknown):boolean {
 if(!value||typeof value!=='object'||Object.getPrototypeOf(value)!==Object.prototype)return false;
 const fields=Object.getOwnPropertyDescriptors(value);
 return Reflect.ownKeys(fields).length===2&&Object.hasOwn(fields,'version')&&Object.hasOwn(fields,'type')
  &&'value'in fields.version&&fields.version.value===1&&'value'in fields.type&&fields.type.value===FRAME.type;
}
export function bindFirstSessionKeyOwnerNegative(revoke:()=>void):()=>void {
 if(!firstSessionLifetimeEnabled)throw Error('first_session_provider_disabled');
 const channel=new BroadcastChannel(PROFILE_MUTATION_CHANNEL);
 const receive=(event:MessageEvent<unknown>)=>{if(negative(event.data))revoke();};
 listeners.add(revoke);channel.addEventListener('message',receive);channel.addEventListener('messageerror',revoke);
 return()=>{listeners.delete(revoke);channel.removeEventListener('message',receive);channel.removeEventListener('messageerror',revoke);channel.close();};
}

/** Exact existing owner-write callsite only. Observe its real same-transaction
 * preimage; ordinary builds perform no additional IDB request. */
export function observeFirstSessionOwnerWrite(store:IDBObjectStore,next:string):void {
 if(!firstSessionLifetimeEnabled)return;
 const previous=store.get('id');
 previous.addEventListener('success',()=>{if(previous.result!==next)publishFirstSessionKeyOwnerNegative();});
 previous.addEventListener('error',()=>publishFirstSessionKeyOwnerNegative());
}
