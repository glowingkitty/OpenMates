/// <reference lib="es2022.object" />
/** Negative-only metadata lifetime from the EXISTING auth generation owner.
 * No duplicated counter, owner decision, login flow or positive admission.
 * Crypto/profile lifecycle and its generic messages remain unchanged.
 */
import {PROFILE_MUTATION_CHANNEL} from './platformLifecycle';
const listeners=new Set<()=>void>();
export function publishMetadataAuthInvalidation():void {
  for(const listener of [...listeners]){try{listener();}catch{/* Never change auth action semantics. */}}
  if(typeof window==='undefined'||typeof BroadcastChannel==='undefined')return;
  let channel:BroadcastChannel|undefined;
  try{channel=new BroadcastChannel(PROFILE_MUTATION_CHANNEL);channel.postMessage({version:1,type:'metadata-auth-invalidate'});}catch{/* Local cancellation already delivered. */}
  finally{try{channel?.close();}catch{/* Never change auth action semantics. */}}
}
function authNegative(value:unknown):boolean {
  if(!value||typeof value!=='object'||Object.getPrototypeOf(value)!==Object.prototype)return false;
  const own=Object.getOwnPropertyDescriptors(value);
  return Reflect.ownKeys(own).length===2&&Object.hasOwn(own,'version')&&Object.hasOwn(own,'type')
    &&'value'in own.version&&own.version.value===1&&'value'in own.type&&own.type.value==='metadata-auth-invalidate';
}
export function bindMetadataAuthLifetime(input:{page:Pick<Window,'addEventListener'|'removeEventListener'>;signal:AbortSignal},revoke:()=>void):()=>void {
  let closed=false;const channel=new BroadcastChannel(PROFILE_MUTATION_CHANNEL);
  const cancel=()=>{if(!closed)revoke();};
  // Existing generic key/profile invalidations never become an auth decision.
  // A spoofed auth-negative message can only cancel; it cannot admit/rearm.
  const message=(event:MessageEvent<unknown>)=>{if(authNegative(event.data))cancel();};
  const storage=(event:Event)=>{const key=(event as StorageEvent).key;if(key===null||key==='session_id')cancel();};
  listeners.add(cancel);input.page.addEventListener('pagehide',cancel);input.page.addEventListener('storage',storage);
  input.signal.addEventListener('abort',cancel,{once:true});channel.addEventListener('message',message);channel.addEventListener('messageerror',cancel);
  if(input.signal.aborted)cancel();
  return()=>{if(closed)return;closed=true;listeners.delete(cancel);input.page.removeEventListener('pagehide',cancel);input.page.removeEventListener('storage',storage);input.signal.removeEventListener('abort',cancel);channel.removeEventListener('message',message);channel.removeEventListener('messageerror',cancel);channel.close();};
}
