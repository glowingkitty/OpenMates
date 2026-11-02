/// <reference lib="es2022.object" />
import type {RustChatIORoutingLease} from './browserAdapters';
/** Thin existing-IDB IO router. The guard is captured from the ORIGINAL actual
 * profile/key/request/lifecycle, never reconstructed from Rust plan owner labels.
 * No key export, enrollment, schema migration, merge policy or automatic writer.
 */
import {executeBrowserLocalReadPlan} from './browserLocalCursorIO';
import {executeBrowserMetadataCachePlan} from './browserMetadataCacheIO';
import {executeBrowserAssistantReplacementPlan} from './browserAssistantReplacementIO';
import {executeBrowserMessageCachePlan} from './browserMessageCacheIO';
import type {BrowserCacheEffectHandler} from './browserCacheProtocol';
export function createBrowserCacheEffectHandler(factory:IDBFactory,guard:()=>void,routingLease?:RustChatIORoutingLease,checkLocalProfile?:()=>Promise<void>):BrowserCacheEffectHandler {
 const lifetime=new AbortController(),active=new Set<Promise<unknown>>();let closed=false;
 return {
  current:guard,
  execute(encoded,signal,originalPhysicalDraft,ownedLocal){
   if(closed||signal.aborted)return Promise.reject(Error('cancelled'));
   const controller=new AbortController();const abort=()=>controller.abort();
   signal.addEventListener('abort',abort,{once:true});lifetime.signal.addEventListener('abort',abort,{once:true});
   if(signal.aborted||lifetime.signal.aborted)abort();
   const terminal:Promise<string>=Promise.resolve().then(async()=>{
    if(closed||controller.signal.aborted)throw Error('cancelled');guard();
    // Exact plan framing/store policy is checked by the existing IO executors.
    const plan:unknown=JSON.parse(encoded);
    const messages=!!plan&&typeof plan==='object'&&Object.hasOwn(plan,'stores');
    const monitor=messages&&['capture_monitor_candidates','compare_and_replace_monitor_candidates'].includes(String((plan as {kind?:unknown}).kind));
    if(monitor&&originalPhysicalDraft)throw Error('unavailable');
    if(ownedLocal){
      if(originalPhysicalDraft||messages||!checkLocalProfile||!routingLease)throw Error('unavailable');
      await checkLocalProfile();guard();
      const local=await executeBrowserLocalReadPlan(factory,encoded,controller.signal,guard,IDBKeyRange,routingLease);
      await checkLocalProfile();guard();if(controller.signal.aborted)throw Error('cancelled');return local;
    }
    const result=monitor?await executeBrowserAssistantReplacementPlan(factory,encoded,controller.signal,guard,routingLease):await (messages?executeBrowserMessageCachePlan:executeBrowserMetadataCachePlan)(factory,encoded,controller.signal,guard,routingLease,originalPhysicalDraft);
    if(controller.signal.aborted)throw Error('cancelled');guard();return result;
   }).finally(()=>{active.delete(terminal);signal.removeEventListener('abort',abort);lifetime.signal.removeEventListener('abort',abort);});
   active.add(terminal);return terminal;
  },
  async close(){closed=true;lifetime.abort();await Promise.allSettled([...active]);}
 };
}
