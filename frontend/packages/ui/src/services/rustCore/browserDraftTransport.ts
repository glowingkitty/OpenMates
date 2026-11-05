/// <reference lib="es2022.object" />
import {isNativeChatIOEvent} from './browserAdapters';
/** Dedicated local Worker envelope on the SAME original Host/Client. No server
 * protocol or application policy. Opaque Rust resources survive IO drain until
 * take()/local_result rechecks their ORIGINAL owner/key/child/root authority.
 */
import {MAX_DRAFT_PACKET_BYTES,parseBrowserDraftPlan,validBrowserDraftResult,validBrowserDraftRestore,validBrowserDraftRequest} from './browserDraftProtocol';
import type {BrowserDraftRequest,BrowserDraftReply,BrowserDraftEffectHandler,BrowserDraftHostPort} from './browserDraftProtocol';
/** Untrusted Worker/Host envelope. envelope() validates only version/draftId;
 * every other field is checked where it is consumed. */
interface Wire{
 version:1;draftId:number;
 effectId?:unknown;draftEffect?:unknown;draftError?:unknown;draftCancel?:unknown;draftReply?:unknown;draftRequest?:unknown;
 draftPrepared?:{resourceId?:unknown;kind?:unknown}|null;
 draftEffectReply?:{ok?:unknown;packet?:unknown}|null;
 draftDrained?:{resourceId?:unknown}|null;
}
export type BrowserDraftWorkerMessage={version:1;draftId:number}&({effectId:number;draftEffect:string}|{draftPrepared:{resourceId:string;kind:'local'|'publication'}}|{draftReply:BrowserDraftReply}|{draftError:'unavailable'|'invalid_request'|'cancelled'});
const uuid=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(v);
const envelope=(v:unknown):v is Wire=>!!v&&typeof v==='object'&&Object.getPrototypeOf(v)===Object.prototype&&(v as Wire).version===1&&Number.isSafeInteger((v as Wire).draftId)&&(v as Wire).draftId>0;
const wipe=(body:BrowserDraftRequest)=>{if(body.operation==='prepare_local_draft')try{body.markdown.fill(0);}catch{/* Already transferred. */}};
interface HostPending{expectedChat:string;settling:boolean;body:BrowserDraftRequest;effect:BrowserDraftEffectHandler;controller:AbortController;effectId:number;operationId:string|null;inFlight:Promise<void>|null;prepared:string|null;drained:boolean;cancelled:boolean;resolve:(reply:BrowserDraftReply)=>void;reject:(error:Error)=>void;release:()=>void;terminal:Promise<void>;finish:()=>void}
export function createBrowserDraftHostChannel(input:{worker:Pick<Worker,'postMessage'|'addEventListener'|'removeEventListener'>;current():void;fatal():void;expectedPrincipal:string|null}):BrowserDraftHostPort&{ownsEvent(event:Event):boolean;hasPending():boolean;fail():void;close():Promise<void>}{
 let next=1,closed=false,closing:Promise<void>|null=null,workerFailure:Error|null=null,drainFailure:Error|null=null;const pending=new Map<number,HostPending>(),issued=new Map<string,{handle:string;generation:number;owner:string;chatId:string}>();
 const cancel=(id:number,p:HostPending)=>{if(p.cancelled)return;p.cancelled=true;p.controller.abort();try{input.worker.postMessage({version:1,draftId:id,draftCancel:true});}catch{/* Root cleanup still drains actual owned IO. */}};
 const settle=async(id:number,p:HostPending,error:Error|null,reply?:BrowserDraftReply)=>{
  if(pending.get(id)!==p||p.settling)return;p.settling=true;p.release();p.controller.abort();
  let failure=error;try{await p.inFlight;await p.effect.close();}catch{failure=Error('draft_io_drain_failed');drainFailure=failure;}
  try{if(failure)throw failure;if(p.cancelled||closed)throw Error('cancelled');input.current();if(!reply)throw Error('invalid_draft_reply');if(reply.kind==='local')issued.set(reply.resourceId,{handle:p.body.handle,generation:p.body.generation,owner:p.body.expectedPrincipal,chatId:p.expectedChat});else if((reply.kind==='synced'||reply.kind==='closed')&&'resourceId'in p.body)issued.delete(p.body.resourceId);p.resolve(reply);}catch(error){p.reject(error instanceof Error?error:Error('unavailable'));}finally{if(pending.get(id)===p)pending.delete(id);p.finish();}
 };
 const accept=(message:unknown):boolean=>{
  if(!message||typeof message!=='object'||!Object.hasOwn(message,'draftId'))return false;
  if(!envelope(message)){input.fatal();return true;}
  const p=pending.get(message.draftId);if(!p||p.settling)return true;
  try{
   if(Object.hasOwn(message,'draftEffect')){
    if(p.inFlight||p.drained||!Number.isSafeInteger(message.effectId)||message.effectId!==p.effectId+1||typeof message.draftEffect!=='string')throw Error('draft_effect_sequence');
    const plan=parseBrowserDraftPlan(message.draftEffect);if(plan.owner!==p.body.expectedPrincipal||plan.operationId!==p.operationId&&p.operationId!==null)throw Error('draft_effect_owner');
    if('chatId'in p.body&&(plan.chatId!==p.body.chatId||(plan.scope.lifecycleGeneration!==p.body.scope.lifecycleGeneration||plan.scope.workspaceEpoch!==p.body.scope.workspaceEpoch)))throw Error('draft_effect_scope');
    const expected=p.body.operation==='prepare_local_draft'?['capture_draft','store_draft','readback_draft'][p.effectId]:p.body.operation==='restore_local_draft'&&p.effectId<2?'capture_draft':p.body.operation==='sync_draft'&&p.effectId===0?'ack_draft':null;
    if(plan.kind!==expected)throw Error('draft_effect_sequence');p.operationId=plan.operationId;p.effectId=message.effectId;
    const id=message.draftId,encodedEffect=message.draftEffect;const task=(async()=>{let result:{ok:true;packet:string}|{ok:false;error:'unavailable'};
     try{if(p.cancelled)throw Error('cancelled');input.current();p.effect.current();const packet=await p.effect.execute(encodedEffect,p.controller.signal);p.effect.current();input.current();
      if(p.cancelled||new TextEncoder().encode(packet).length>MAX_DRAFT_PACKET_BYTES)throw Error('cancelled');const decoded=JSON.parse(packet);if(decoded.kind!==plan.kind||decoded.operationId!==plan.operationId||decoded.chatId!==plan.chatId||decoded.transactionCommitted!==true)throw Error('draft_packet_identity');result={ok:true,packet};
     }catch{result={ok:false,error:'unavailable'};}
     p.inFlight=null;if(pending.get(id)===p)input.worker.postMessage({version:1,draftId:id,effectId:message.effectId,draftEffectReply:result});
    })();p.inFlight=task;void task.catch(()=>input.fatal());return true;
   }
   if(Object.hasOwn(message,'draftPrepared')){
    const prepared=message.draftPrepared;if(p.prepared||p.inFlight||!uuid(prepared?.resourceId)||!(prepared?.kind==='local'||prepared?.kind==='publication'))throw Error('draft_prepared');
    const count=p.body.operation==='prepare_local_draft'?3:p.body.operation==='restore_local_draft'?2:null;if(count!==null&&p.effectId!==count)throw Error('draft_effect_incomplete');
    if(prepared.kind!==(p.body.operation==='prepare_local_draft'?'local':'publication'))throw Error('draft_prepared_kind');p.prepared=prepared.resourceId;
    void(async()=>{await p.effect.close();if(pending.get(message.draftId)!==p)return;input.current();p.effect.current();if(p.cancelled)throw Error('cancelled');p.drained=true;input.worker.postMessage({version:1,draftId:message.draftId,draftDrained:{resourceId:p.prepared}});})().catch(()=>{drainFailure=Error('draft_io_drain_failed');cancel(message.draftId,p);});return true;
   }
   if(Object.hasOwn(message,'draftError')){void settle(message.draftId,p,Error('unavailable'));return true;}
   if(Object.hasOwn(message,'draftReply')){
    const reply=message.draftReply as BrowserDraftReply;
    if(!reply||typeof reply!=='object')throw Error('draft_reply');
    if(reply.kind==='local'){if(!p.drained||reply.resourceId!==p.prepared||!validBrowserDraftResult(reply.result)||reply.result.chatId!==p.expectedChat||reply.result.remoteSynced)throw Error('draft_reply');}
    else if(reply.kind==='restored'){if(!p.drained||!validBrowserDraftRestore(reply.result)||reply.result.chatId!==p.expectedChat)throw Error('draft_reply');}
    else if(reply.kind==='synced'){if(!p.drained||!validBrowserDraftResult(reply.result)||reply.result.chatId!==p.expectedChat||reply.result.remoteSynced&&p.effectId!==1)throw Error('draft_reply');}
    else if(!['cancelled','closed'].includes(reply.kind))throw Error('draft_reply');
    void settle(message.draftId,p,null,reply);return true;
   }
   throw Error('invalid_draft_message');
  }catch{input.fatal();}return true;
 };
 const messageData=Object.getOwnPropertyDescriptor(MessageEvent.prototype,'data')!.get!;
 const listener=(event:MessageEvent<unknown>)=>{let message:unknown;try{message=messageData.call(event);}catch{return;}if(!message||typeof message!=='object'||!Object.hasOwn(message,'draftId'))return;if(!isNativeChatIOEvent(event,input.worker as unknown as EventTarget)){input.fatal();return;}accept(message);};
 input.worker.addEventListener('message',listener as EventListener);
 return {ownsEvent(event){try{const data=messageData.call(event);return !!data&&typeof data==='object'&&Object.hasOwn(data,'draftId');}catch{return false;}},hasPending:()=>pending.size>0||workerFailure!==null||drainFailure!==null,fail(){workerFailure=Error('draft_worker_failed');for(const[id,p]of [...pending])void settle(id,p,workerFailure);},requestDraft(original,signal,effect){
  let body=original;
  if(closed||signal.aborted){wipe(body);return Promise.reject(Error('cancelled'));}
  try{input.current();if(Object.values(Object.getOwnPropertyDescriptors(body)).some(d=>!('value'in d))||!validBrowserDraftRequest(body)||input.expectedPrincipal!==null&&body.expectedPrincipal!==input.expectedPrincipal)throw Error('invalid_draft_request');body=structuredClone(body);wipe(original);if('resourceId'in body){const prior=issued.get(body.resourceId);if(!prior||prior.handle!==body.handle||prior.generation!==body.generation||prior.owner!==body.expectedPrincipal)throw Error('invalid_draft_resource');}
  }catch(error){wipe(body);wipe(original);return Promise.reject(error);}
  const id=next++;return new Promise((resolve,reject)=>{let finish!:()=>void;const terminal=new Promise<void>(done=>finish=done),controller=new AbortController();
   const abort=()=>cancel(id,p);const timer=setTimeout(abort,30000);const p:HostPending={expectedChat:'chatId'in body?body.chatId:issued.get(body.resourceId)!.chatId,settling:false,body,effect,controller,effectId:0,operationId:null,inFlight:null,prepared:null,drained:false,cancelled:false,resolve,reject,release:()=>{clearTimeout(timer);signal.removeEventListener('abort',abort);},terminal,finish};
   pending.set(id,p);signal.addEventListener('abort',abort,{once:true});
   try{input.worker.postMessage({version:1,draftId:id,draftRequest:body},body.operation==='prepare_local_draft'?[body.markdown.buffer as ArrayBuffer]:[]);}catch{void settle(id,p,Error('unavailable'));}finally{wipe(body);}
  });
 },close(){if(closing)return closing;closed=true;const active=[...pending];for(const[id,p]of active)cancel(id,p);
  // Parent Host must keep this exact Worker alive until request/core + actual
  // transaction terminals drain. Worker termination is not an IO receipt.
  if(!active.length){issued.clear();input.worker.removeEventListener('message',listener as EventListener);closing=workerFailure||drainFailure?Promise.reject(workerFailure??drainFailure):Promise.resolve();return closing;}
  closing=Promise.all(active.map(([,p])=>p.terminal)).then(()=>{if(workerFailure||drainFailure)throw workerFailure??drainFailure;}).finally(()=>{issued.clear();input.worker.removeEventListener('message',listener as EventListener);});return closing;
 }};
}

export interface DraftRustStatus{principal:string;free():void}
export interface DraftRustPublication{take(client:DraftRustClient):string;free():void}
export interface DraftRustControl{cancel():void;free():void}
export interface DraftRustWrite{local_result(client:DraftRustClient):string;control():DraftRustControl;synchronize(client:DraftRustClient,effect:(plan:string)=>Promise<string>):Promise<DraftRustPublication>;free():void}
export interface DraftRustClient{status(handle:string,generation:number):DraftRustStatus;
 prepare_local_draft(handle:string,generation:number,owner:string,chatId:string,markdown:string,scope:string,now:number,effect:(plan:string)=>Promise<string>):Promise<DraftRustWrite>;
 restore_local_draft(handle:string,generation:number,owner:string,chatId:string,scope:string,effect:(plan:string)=>Promise<string>):Promise<DraftRustPublication>}
interface RuntimePending{cancelled:boolean;effectId:number;effect:null|{id:number;resolve:(packet:string)=>void;reject:(error:Error)=>void};drain:null|{id:string;resolve:()=>void;reject:(error:Error)=>void};control:DraftRustControl|null}
export function createBrowserDraftRuntime(input:{endpoint:EventTarget;client():DraftRustClient|null;acquire(client:DraftRustClient):()=>void;post(message:BrowserDraftWorkerMessage):void;current():void}){
 let closed=false;const active=new Map<number,RuntimePending>(),resources=new Map<string,{client:DraftRustClient;write:DraftRustWrite;control:DraftRustControl;handle:string;generation:number;owner:string}>();
 const check=(client:DraftRustClient,body:BrowserDraftRequest,p:RuntimePending)=>{input.current();if(closed||p.cancelled||input.client()!==client)throw Error('cancelled');const status=client.status(body.handle,body.generation);try{if(status.principal!==body.expectedPrincipal)throw Error('session_expired');}finally{status.free();}};
 const serve=async(id:number,body:BrowserDraftRequest)=>{const client=input.client();if(!client)throw Error('unavailable');const p:RuntimePending={cancelled:false,effectId:0,effect:null,drain:null,control:null};active.set(id,p);let release:(()=>void)|null=null,publication:DraftRustPublication|null=null,write:DraftRustWrite|null=null;
  const effects=(plan:string)=>new Promise<string>((resolve,reject)=>{try{check(client,body,p);if(p.effect||p.drain)throw Error('draft_effect_busy');p.effect={id:++p.effectId,resolve,reject};input.post({version:1,draftId:id,effectId:p.effectId,draftEffect:plan});}catch(error){reject(error);}});
  const drained=(resourceId:string,kind:'local'|'publication')=>new Promise<void>((resolve,reject)=>{p.drain={id:resourceId,resolve,reject};input.post({version:1,draftId:id,draftPrepared:{resourceId,kind}});});
  try{
   // Exact negative child teardown has no server/read/publication permission and
   // must not wait on an unrelated sibling's mutable Client borrow.
   if(body.operation==='cancel_draft'||body.operation==='close_draft'){
    input.current();const original=resources.get(body.resourceId);
    if(!original||original.client!==client||input.client()!==client||original.handle!==body.handle||original.generation!==body.generation||original.owner!==body.expectedPrincipal)throw Error('invalid_draft_resource');
    original.control.cancel();if(body.operation==='close_draft'){original.write.free();original.control.free();resources.delete(body.resourceId);}
    input.post({version:1,draftId:id,draftReply:{kind:body.operation==='close_draft'?'closed':'cancelled'}});return;
   }
   release=input.acquire(client);check(client,body,p);
   if(body.operation==='prepare_local_draft'){
    const markdown=new TextDecoder('utf-8',{fatal:true}).decode(body.markdown);wipe(body);write=await client.prepare_local_draft(body.handle,body.generation,body.expectedPrincipal,body.chatId,markdown,JSON.stringify(body.scope),body.nowSeconds,effects);check(client,body,p);
    const resourceId=crypto.randomUUID(),control=write.control();p.control=control;await drained(resourceId,'local');check(client,body,p);
    const result=JSON.parse(write.local_result(client));if(!validBrowserDraftResult(result)||result.chatId!==body.chatId)throw Error('invalid_draft_reply');
    resources.set(resourceId,{client,write,control,handle:body.handle,generation:body.generation,owner:body.expectedPrincipal});write=null;p.control=null;input.post({version:1,draftId:id,draftReply:{kind:'local',resourceId,result}});
   }else if(body.operation==='restore_local_draft'){
    publication=await client.restore_local_draft(body.handle,body.generation,body.expectedPrincipal,body.chatId,JSON.stringify(body.scope),effects);check(client,body,p);await drained(crypto.randomUUID(),'publication');check(client,body,p);
    const result=JSON.parse(publication.take(client));publication=null;if(!validBrowserDraftRestore(result)||result.chatId!==body.chatId)throw Error('invalid_draft_reply');input.post({version:1,draftId:id,draftReply:{kind:'restored',result}});result.markdown='';result.preview=null;
   }else{
    const original=resources.get(body.resourceId);if(!original||original.client!==client||original.handle!==body.handle||original.generation!==body.generation||original.owner!==body.expectedPrincipal)throw Error('invalid_draft_resource');
    resources.delete(body.resourceId);p.control=original.control;publication=await original.write.synchronize(client,effects);check(client,body,p);await drained(crypto.randomUUID(),'publication');check(client,body,p);
    const result=JSON.parse(publication.take(client));publication=null;if(!validBrowserDraftResult(result))throw Error('invalid_draft_reply');input.post({version:1,draftId:id,draftReply:{kind:'synced',result}});
   }
  }catch{if(!closed)input.post({version:1,draftId:id,draftError:'unavailable'});}
  finally{wipe(body);p.effect?.reject(Error('cancelled'));p.drain?.reject(Error('cancelled'));p.control?.cancel();p.control?.free();publication?.free();write?.free();active.delete(id);release?.();if(closed)input.post({version:1,draftId:id,draftError:'cancelled'});}
 };
 const messageData=Object.getOwnPropertyDescriptor(MessageEvent.prototype,'data')!.get!;
 return {accept(event:Event):boolean{
  let message:unknown;try{message=messageData.call(event);}catch{return false;}
  if(!message||typeof message!=='object'||!Object.hasOwn(message,'draftId'))return false;
  if(!isNativeChatIOEvent(event,input.endpoint))return true;
  if(!message||typeof message!=='object'||!Object.hasOwn(message,'draftId'))return false;
  if(!envelope(message))return true;
  const p=active.get(message.draftId);
  if(message.draftCancel===true){if(p){p.cancelled=true;p.control?.cancel();p.effect?.reject(Error('cancelled'));p.effect=null;p.drain?.reject(Error('cancelled'));p.drain=null;}return true;}
  if(message.draftEffectReply&&p?.effect){const e=p.effect;if(message.effectId!==e.id)return true;p.effect=null;const r=message.draftEffectReply;if(r.ok===true&&typeof r.packet==='string')e.resolve(r.packet);else e.reject(Error('unavailable'));return true;}
  if(message.draftDrained&&p?.drain){if(message.draftDrained.resourceId!==p.drain.id)return true;const d=p.drain;p.drain=null;d.resolve();return true;}
  if(message.draftRequest&&!closed&&!active.has(message.draftId)){if(!validBrowserDraftRequest(message.draftRequest)){input.post({version:1,draftId:message.draftId,draftError:'invalid_request'});return true;}void serve(message.draftId,message.draftRequest).catch(()=>input.post({version:1,draftId:message.draftId,draftError:'unavailable'}));return true;}return true;
 },close(){if(closed)return;closed=true;for(const p of active.values()){p.cancelled=true;p.control?.cancel();p.effect?.reject(Error('cancelled'));p.drain?.reject(Error('cancelled'));}for(const r of resources.values()){r.control.cancel();r.write.free();r.control.free();}resources.clear();}};
}
