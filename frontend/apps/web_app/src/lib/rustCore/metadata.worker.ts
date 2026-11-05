/// <reference lib="webworker" />
/** Prototype-only separate entry. Never imported by the maintained producer. */
import {artifact,loadBinding} from 'virtual:openmates-rust-core-package';
import {withAuthRefreshLock} from '@openmates/ui/src/services/rustCore/browserAdapters';
interface Bootstrap {store_selected(chat:string):Promise<Stored>;store_subchat(chat:string):Promise<Stored>;free():void}
interface Stored {check_current():Promise<void>;free():void}
interface Binding {capture_native_metadata_bootstrap(event:MessageEvent<unknown>):Promise<Bootstrap>;close_native_metadata_io_only():Promise<void>}
const scope=self as DedicatedWorkerGlobalScope,originalLifetime=new AbortController();
let started=false,bootstrap:Bootstrap|undefined,stored:Stored|undefined,binding:Binding|undefined,task:Promise<unknown>|undefined,failedHeld=false,revoked=false,busy=false,session:string|undefined;
/** Untrusted page frame; every field is validated where it is consumed. */
interface UntrustedFrame{version?:unknown;operation?:unknown;artifact?:unknown;sessionId?:unknown;id?:unknown;chatId?:unknown}
const target=Object.getOwnPropertyDescriptor(Event.prototype,'target')!.get!,type=Object.getOwnPropertyDescriptor(Event.prototype,'type')!.get!,data=Object.getOwnPropertyDescriptor(MessageEvent.prototype,'data')!.get!;
const native=(event:MessageEvent<unknown>)=>{try{return target.call(event)===scope&&type.call(event)==='message'&&event.isTrusted===true;}catch{return false;}};
scope.addEventListener('message',function first(event:MessageEvent<unknown>){
 if(started||!native(event))return;started=true;scope.removeEventListener('message',first);
 const frame=data.call(event) as UntrustedFrame|null|undefined;session=typeof frame?.sessionId==='string'?frame.sessionId:undefined;
 if(!frame||frame.version!==1||frame.operation!=='bootstrap_metadata'||frame.artifact!==artifact){failedHeld=true;scope.postMessage({version:1,ready:false});return;}
 busy=true;task=(async()=>{
  binding=await loadBinding() as Binding;if(revoked)throw Error('cancelled');
  if(typeof binding.capture_native_metadata_bootstrap!=='function'||typeof binding.close_native_metadata_io_only!=='function')throw Error('unavailable');
  // Rust independently validates native event + fixed configured module + native
  // profile observation + authentic first-party Cookie response before Ready.
  bootstrap=await withAuthRefreshLock(scope.navigator.locks,originalLifetime.signal,()=>binding!.capture_native_metadata_bootstrap(event),{current:()=>{if(revoked)throw Error('cancelled');}});scope.postMessage({version:1,ready:true});
 })().catch(()=>{failedHeld=true;scope.postMessage({version:1,ready:false});}).finally(()=>{busy=false;});
});
scope.addEventListener('message',(event:MessageEvent<unknown>)=>{
 if(!native(event))return;const frame=data.call(event) as UntrustedFrame|null|undefined;
 if(frame?.version===1&&frame.operation==='metadata_revoke'&&frame.sessionId===session){revoked=true;originalLifetime.abort();return;}
 if(!frame||frame.version!==1||typeof frame.id!=='number'||!Number.isSafeInteger(frame.id)||frame.id<1)return;
 if(frame.operation==='close_native_metadata_io_only'){
  // Native-only closure never waits for or acknowledges unknown HTTP. A prior
  // negative prevents late startup/capture even before WASM finishes loading.
  revoked=true;originalLifetime.abort();void(async()=>{try{await binding?.close_native_metadata_io_only();scope.postMessage({version:1,id:frame.id,nativeIOOnlyClosed:true,coreHTTPSettlement:'unproven'});}catch{failedHeld=true;scope.postMessage({version:1,id:frame.id,ok:false});}})();return;
 }
 if(failedHeld||revoked||busy)return;
 if((frame.operation==='store_selected_metadata'||frame.operation==='store_subchat_metadata')&&bootstrap){
  if(frame.operation==='store_subchat_metadata'&&Object.keys(frame).sort().join(',')!=='chatId,id,operation,version'){failedHeld=true;scope.postMessage({version:1,id:frame.id,ok:false});return;}
  const original=bootstrap;bootstrap=undefined;busy=true;
  task=(async()=>{try{if(typeof frame.chatId!=='string')throw Error('unavailable');const chatId=frame.chatId;stored=await withAuthRefreshLock(scope.navigator.locks,originalLifetime.signal,()=>frame.operation==='store_subchat_metadata'?original.store_subchat(chatId):original.store_selected(chatId),{current:()=>{if(revoked)throw Error('cancelled');}});scope.postMessage({version:1,id:frame.id,opaqueStored:true});}catch{failedHeld=true;scope.postMessage({version:1,id:frame.id,ok:false});}finally{original.free();busy=false;}})();return;
 }
 if(frame.operation==='check_metadata_current'&&stored){
  busy=true;task=(async()=>{try{await stored!.check_current();scope.postMessage({version:1,id:frame.id,current:true});}catch{failedHeld=true;scope.postMessage({version:1,id:frame.id,ok:false});}finally{busy=false;}})();
 }
});

// Retain the original task resource even on an unknown failure; native-only
// closure deliberately does not reinterpret its result as HTTP settlement.
void task;
