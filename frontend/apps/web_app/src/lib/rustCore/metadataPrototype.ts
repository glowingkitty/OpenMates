/** Explicit prototype only. No maintained producer import/default activation.
 * Returns no owner/key/chat data; native-only closure never attests HTTP drain.
 */
import workerUrl from './metadata.worker.ts?worker&url';
import {artifact} from 'virtual:openmates-rust-core-package';
import {getApiUrl} from '@openmates/ui/src/config/api';
import {bindMetadataAuthLifetime} from '@openmates/ui/src/services/rustCore/metadataAuthLifetime';
export const metadataPrototypeAssets=Object.freeze({artifact,workerUrl});
export interface BrowserMetadataPrototype {
 readonly admitted:Promise<void>;
 storeSelected(chatId:string):Promise<void>;
 /** Personal child metadata; parent link is authentic source DATA only. */
 storeSubchat(chatId:string):Promise<void>;
 checkCurrent():Promise<void>;
 revoke():void;
 /** Native IndexedDB only; unknown Core HTTP remains unproven/held. */
 closeNativeIOOnly():Promise<void>;
}
const heldWorkers=new Set<Worker>();
const target=Object.getOwnPropertyDescriptor(Event.prototype,'target')!.get!,type=Object.getOwnPropertyDescriptor(Event.prototype,'type')!.get!,data=Object.getOwnPropertyDescriptor(MessageEvent.prototype,'data')!.get!;
function sessionId():string{const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;const h=[...bytes].map(v=>v.toString(16).padStart(2,'0')).join('');return`${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
export function createBrowserMetadataPrototype(input:{signal:AbortSignal}):BrowserMetadataPrototype {
 if(typeof window==='undefined'||input.signal.aborted||typeof artifact!=='string'||!/^[a-f0-9]{64}$/.test(artifact))throw Error('unavailable');
 const worker=new Worker(new URL(workerUrl,import.meta.url),{type:'module',name:'openmates-metadata-prototype'});heldWorkers.add(worker);
 const originalSession=sessionId(),pending=new Map<number,{resolve:()=>void;reject:(e:Error)=>void;nativeOnly:boolean}>();let next=0,revoked=false,used=false,closing:Promise<void>|undefined;
 let resolveAdmitted!:()=>void,rejectAdmitted!:(e:Error)=>void;const admitted=new Promise<void>((resolve,reject)=>{resolveAdmitted=resolve;rejectAdmitted=reject;});void admitted.catch(()=>{});
 const post=(frame:unknown)=>worker.postMessage(frame);
 const revoke=()=>{if(revoked)return;revoked=true;post({version:1,operation:'metadata_revoke',sessionId:originalSession});rejectAdmitted(Error('cancelled'));for(const value of pending.values())if(!value.nativeOnly)value.reject(Error('cancelled'));};
 // Actual existing mutation sources are negative-only. Install before native
 // bootstrap/profile read; no Master capture or crypto Root enrollment occurs.
 const release=bindMetadataAuthLifetime({page:window,signal:input.signal},revoke);
 input.signal.addEventListener('abort',revoke,{once:true});
 worker.addEventListener('message',event=>{
  if(target.call(event)!==worker||type.call(event)!=='message'||event.isTrusted!==true)return;
  const frame=data.call(event);if(!frame||typeof frame!=='object'||frame.version!==1)return;
  if(Object.keys(frame).length===2&&'ready'in frame){if(frame.ready===true&&!revoked)resolveAdmitted();else{revoke();rejectAdmitted(Error('unavailable'));}return;}
  const original=pending.get(frame.id);if(!original)return;
  if(original.nativeOnly){if(frame.nativeIOOnlyClosed===true&&frame.coreHTTPSettlement==='unproven'){pending.delete(frame.id);original.resolve();}else if(frame.ok===false)original.reject(Error('unavailable'));return;}
  if(revoked)return;
  if(frame.opaqueStored===true||frame.current===true){pending.delete(frame.id);original.resolve();}else if(frame.ok===false){original.reject(Error('unavailable'));revoke();}
 });
 worker.addEventListener('messageerror',revoke);worker.addEventListener('error',revoke);
 const request=(operation:string,chatId?:string,nativeOnly=false)=>{
  if(!nativeOnly&&revoked)return Promise.reject(Error('cancelled'));const id=++next;
  return new Promise<void>((resolve,reject)=>{pending.set(id,{resolve,reject,nativeOnly});post({version:1,id,operation,...(chatId===undefined?{}:{chatId})});});
 };
 post({version:1,operation:'bootstrap_metadata',artifact,apiUrl:getApiUrl(),appOrigin:window.location.origin,sessionId:originalSession});
 return Object.freeze({admitted,
  async storeSelected(chatId:string){await admitted;if(used)throw Error('unavailable');used=true;await request('store_selected_metadata',chatId);},
  async storeSubchat(chatId:string){await admitted;if(used)throw Error('unavailable');used=true;await request('store_subchat_metadata',chatId);},
  async checkCurrent(){await admitted;if(!used)throw Error('unavailable');await request('check_metadata_current');},
  revoke,
  closeNativeIOOnly(){if(!closing){revoke();closing=request('close_native_metadata_io_only',undefined,true).finally(()=>{release();input.signal.removeEventListener('abort',revoke);});}return closing;},
 });
}
