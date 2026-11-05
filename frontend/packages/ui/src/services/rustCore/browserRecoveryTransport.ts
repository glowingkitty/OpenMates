/// <reference lib="es2022.object" />
/** Fixed PAGE endpoint for original native recovery IO. Rust owns every
 * checkpoint/key/owner/CAS policy. No generic Worker reply completes storage. */
import {assertNativeRustChatIORootBinding,readNativeChatIOMessage,isNativeChatIOEvent,assertRustChatIOPortsRoot} from './browserAdapters';
import type {NativeRustChatIOFactory,RustChatIORoot,RustChatIOPorts} from './browserAdapters';
import {createBrowserRecoveryCheckpointStorage} from './browserRecoveryCheckpointStorage';
import type {RecoveryCheckpointEffect} from './browserRecoveryCheckpointStorage';
import {MAX_PENDING_REQUESTS} from './protocol';
import {createBrowserDraftInventoryIO} from './browserDraftInventoryIO';

declare const bootstrapBrand:unique symbol;
export interface BrowserRecoveryBootstrap {
 readonly [bootstrapBrand]:true;
 /** Own immutable negative/root methods, backed by this factory's WeakMap. */
 bindRoot(issuer:NativeRustChatIOFactory,root:RustChatIORoot):void;
 bindInventoryPorts(ports:RustChatIOPorts):void;
 revoke():void;
 closeAndDrain():Promise<void>;
}
const portPost=typeof MessagePort==='undefined'?undefined:MessagePort.prototype.postMessage;
const portStart=typeof MessagePort==='undefined'?undefined:MessagePort.prototype.start;
const portClose=typeof MessagePort==='undefined'?undefined:MessagePort.prototype.close;
const workerPost=typeof Worker==='undefined'?undefined:Worker.prototype.postMessage;
const add=EventTarget.prototype.addEventListener,remove=EventTarget.prototype.removeEventListener;
const eventType=Object.getOwnPropertyDescriptor(Event.prototype,'type')!.get!;
const Channel=typeof MessageChannel==='undefined'?undefined:MessageChannel;
const RECORD_BYTES=32*1024*1024; // Same physical encoded-record ceiling, EACH record.
const uuid=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(v);
function data(v:unknown):v is Record<string,unknown>{return typeof v==='object'&&v!==null&&Object.getPrototypeOf(v)===Object.prototype;}
function closed(v:unknown,keys:string[]):boolean{
 return data(v)&&Reflect.ownKeys(v).length===keys.length
  &&keys.every(key=>Object.hasOwn(v,key))&&Object.values(Object.getOwnPropertyDescriptors(v)).every(field=>'value'in field);
}
function record(v:unknown):v is string{return typeof v==='string'&&new TextEncoder().encode(v).byteLength<=RECORD_BYTES;}
function effect(v:unknown):v is RecoveryCheckpointEffect{
 if(!data(v))return false;
 const keys=v.operation==='read'?['version','operation','operationId','owner']:['version','operation','operationId','owner','expected','next'];
 return closed(v,keys)&&v.version===1&&uuid(v.operationId)&&uuid(v.owner)
  &&(v.operation==='read'||v.operation==='compare_and_put'&&(v.expected===null||record(v.expected))&&record(v.next));
}
type InventoryEffect={version:1;kind:'read_original_draft_inventory_page';operationId:string;page:number;after:string|null;maxRows:20;maxBytes:2097152}|{version:1;kind:'reread_original_draft_inventory_row';operationId:string;page:number;chatId:string};
type ResultData={ok:true;record:string|null}|{ok:false;error:'unavailable'|'cancelled'|'conflict'};
type Operation={sequence:number;operationId:string;effect:RecoveryCheckpointEffect|InventoryEffect;controller:AbortController;terminal:Promise<void>};
type State={worker:Worker;factory:IDBFactory;port:MessagePort;remote:MessagePort|null;transferred:boolean;revoked:boolean;failed:boolean;
 issuer?:NativeRustChatIOFactory;root?:RustChatIORoot;contextId?:string;storage?:ReturnType<typeof createBrowserRecoveryCheckpointStorage>;
 inventory?:ReturnType<typeof createBrowserDraftInventoryIO>;inventoryPorts?:RustChatIOPorts;
 pending:Map<number,Operation>;lastSequence:number;closing?:Promise<void>;closeRequested:boolean;finished:boolean;closeWait:Promise<void>;signalClose:()=>void;receive:EventListener;error:EventListener};
const states=new WeakMap<object,State>(),workers=new WeakSet<Worker>();
function state(token:BrowserRecoveryBootstrap):State{const value=states.get(token);if(!value)throw Error('invalidated_snapshot');return value;}
function current(s:State):void{
 if(s.revoked||s.failed||!s.root||!s.issuer||!s.contextId)throw Error('invalidated_snapshot');
 assertNativeRustChatIORootBinding(s.root,s.issuer,s.worker,s.factory);
 if(s.revoked||s.failed)throw Error('invalidated_snapshot');
}
function post(s:State,data:unknown):void{
 if(!portPost)throw Error('unavailable');
 try{portPost.call(s.port,data);}catch{s.failed=true;s.signalClose();throw Error('unavailable');}
}
function errorCode(value:unknown):'unavailable'|'cancelled'|'conflict'{
 return value instanceof Error&&value.message==='conflict'?'conflict':value instanceof Error&&['cancelled','invalidated_snapshot'].includes(value.message)?'cancelled':'unavailable';
}
function revoke(s:State):void{
 if(s.revoked)return;s.revoked=true;
 for(const original of s.pending.values())original.controller.abort();
 if(s.contextId){try{post(s,{version:1,contextId:s.contextId,revoked:true});}catch{/* No receipt or drain is inferred from port failure. */}}
 // Storage close revokes synchronously; retain its ACTUAL native terminal wait.
 if(s.storage){const actual=s.storage.close();void actual.catch(()=>{s.failed=true;});}
 if(s.inventory){const actual=s.inventory.close();void actual.catch(()=>{s.failed=true;});}
}
async function finish(s:State):Promise<void>{
 if(s.finished)return;
 revoke(s);
 const outcomes=await Promise.allSettled([s.storage?.close()??Promise.resolve(),s.inventory?.close()??Promise.resolve(),...[...s.pending.values()].map(value=>value.terminal)]);
 if(outcomes.some(value=>value.status==='rejected')){s.failed=true;throw Error('unavailable');}
 if(!s.closeRequested)throw Error('recovery_port_unobserved');
 if(s.pending.size)throw Error('recovery_port_unobserved');
 if(s.contextId)post(s,{version:1,contextId:s.contextId,closed:true});
 s.finished=true;remove.call(s.port,'message',s.receive);remove.call(s.port,'messageerror',s.error);
 portClose?.call(s.port);
 if(s.failed)throw Error('unavailable');
}
function inventoryEffect(value:unknown):value is InventoryEffect{
 if(!data(value)||value.version!==1||!uuid(value.operationId)||!Number.isSafeInteger(value.page)||typeof value.page!=='number'||value.page<1)return false;
 if(value.kind==='read_original_draft_inventory_page')return closed(value,['version','kind','operationId','page','after','maxRows','maxBytes'])&&value.maxRows===20&&value.maxBytes===2097152&&(value.after===null||typeof value.after==='string'&&new TextEncoder().encode(value.after).byteLength<=4096);
 return value.kind==='reread_original_draft_inventory_row'&&closed(value,['version','kind','operationId','page','chatId'])&&uuid(value.chatId)&&value.chatId.toLowerCase()===value.chatId;
}
function inventoryCurrent(s:State):void{
 current(s);if(!s.inventoryPorts||!s.inventory||!s.root)throw Error('unavailable');
 assertRustChatIOPortsRoot(s.inventoryPorts,s.root,s.factory);current(s);
}
function receiveInventory(s:State,value:Record<string,unknown>):void{
 if(!closed(value,['version','domain','contextId','sequence','operationId','effect'])||value.version!==1||value.domain!=='draft_inventory'
  ||typeof value.sequence!=='number'||!Number.isSafeInteger(value.sequence)||value.sequence<=s.lastSequence||!uuid(value.operationId)||!inventoryEffect(value.effect)||value.operationId!==value.effect.operationId){revoke(s);return;}
 const sequence=value.sequence,operationId=value.operationId,plan=value.effect;s.lastSequence=sequence;
 if(s.pending.size>=MAX_PENDING_REQUESTS){post(s,{version:1,domain:'draft_inventory',contextId:s.contextId,sequence,operationId,result:{ok:false,error:'unavailable'}});return;}
 const controller=new AbortController();let release!:()=>void;const terminal=new Promise<void>(resolve=>{release=resolve;});
 s.pending.set(sequence,{sequence,operationId,effect:plan,controller,terminal});
 void(async()=>{
  let result:{ok:true;packet:string}|{ok:false;error:'unavailable'|'cancelled'|'conflict'};
  try{
   inventoryCurrent(s);const io=s.inventory!;
   const packet=await io.execute(JSON.stringify(plan),controller.signal);
   inventoryCurrent(s);if(typeof packet!=='string'||new TextEncoder().encode(packet).byteLength>2097152)throw Error('unavailable');
   result={ok:true,packet};
  }catch(error){result={ok:false,error:errorCode(error)};}
  // This adapter never rejects actually-started native IO before its terminal.
  // Inventory ciphertext DATA never uses checkpoint record/brand/receipt.
  try{post(s,{version:1,domain:'draft_inventory',contextId:s.contextId,sequence,operationId,result});}catch{revoke(s);}
  finally{s.pending.delete(sequence);release();}
 })();
}
function receive(s:State,event:Event):void{
 let value:unknown;
 try{value=readNativeChatIOMessage(event as MessageEvent<unknown>,s.port);}catch{return;}
 if(!data(value)||value.contextId!==s.contextId||!s.contextId){revoke(s);return;}
 if(closed(value,['version','contextId','close'])&&value.version===1&&value.close===true){
  if(s.closeRequested){revoke(s);return;}s.closeRequested=true;s.signalClose();
  s.closing??=finish(s);void s.closing.catch(()=>{});return;
 }
 if(closed(value,['version','contextId','sequence','operationId','cancel'])&&value.version===1&&value.cancel===true
   &&typeof value.sequence==='number'&&Number.isSafeInteger(value.sequence)&&uuid(value.operationId)){
  const original=s.pending.get(value.sequence);
  // A cancel can race the already-posted original terminal. Stale/mismatched
  // negative requests never retire a later sibling or the parent controller.
  if(!original||original.operationId!==value.operationId)return;
  original.controller.abort();return; // ACTUAL execute terminal still owns reply.
 }
 if(value.domain==='draft_inventory'){receiveInventory(s,value);return;}
 if(!closed(value,['version','contextId','sequence','operationId','effect'])||value.version!==1
   ||typeof value.sequence!=='number'||!Number.isSafeInteger(value.sequence)||value.sequence<=s.lastSequence
   ||!uuid(value.operationId)||!effect(value.effect)||value.operationId!==value.effect.operationId){revoke(s);return;}
 const sequence=value.sequence,operationId=value.operationId,plan=value.effect;
 s.lastSequence=sequence;
 const controller=new AbortController();
 let release!:()=>void;const terminal=new Promise<void>(resolve=>{release=resolve;});
 const original:Operation={sequence,operationId,effect:plan,controller,terminal};
 if(s.pending.size>=MAX_PENDING_REQUESTS){post(s,{version:1,contextId:s.contextId,sequence,operationId,result:{ok:false,error:'unavailable'}});return;}
 s.pending.set(sequence,original);
 void(async()=>{
  let result:ResultData;
  try{
   current(s);const storage=s.storage;if(!storage)throw Error('unavailable');
   const physical=await storage.execute(plan,controller.signal);
   current(s);
   // The one-use native terminal/full-readback brand NEVER crosses the port.
   const actual=storage.consume(physical,plan);current(s);
   if(actual!==null&&!record(actual))throw Error('unavailable');
   result={ok:true,record:actual};
  }catch(error){result={ok:false,error:errorCode(error)};}
  // execute rejects started IO only AFTER its genuine transaction terminal.
  // Cleanup is deliberately outside current(), including revoked roots.
  try{post(s,{version:1,contextId:s.contextId,sequence,operationId,result});}
  catch{revoke(s);}
  finally{s.pending.delete(sequence);release();}
 })();
}
/** Loader-only: call synchronously after constructing the actual Worker and
 * before publishing Worker/Host. Importing this module performs no IO. */
export function createBrowserRecoveryBootstrap(worker:Worker,factory:IDBFactory):BrowserRecoveryBootstrap{
 if(!Channel||!portPost||!portStart||!portClose||!workerPost||workers.has(worker))throw Error('unavailable');
 const channel=new Channel();
 const receiveOriginal:EventListener=event=>receive(original,event);
 const error:EventListener=event=>{if(!isNativeChatIOEvent(event,original.port)||eventType.call(event)!=='messageerror')return;original.failed=true;original.signalClose();revoke(original);};
 let signalClose!:()=>void;const closeWait=new Promise<void>(resolve=>{signalClose=resolve;});
 const original:State={worker,factory,port:channel.port1,remote:channel.port2,transferred:false,revoked:false,failed:false,
  pending:new Map(),lastSequence:0,closeRequested:false,finished:false,closeWait,signalClose,receive:receiveOriginal,error};
 const token={checkpoint:()=>undefined} as unknown as BrowserRecoveryBootstrap;
 Object.defineProperties(token,{
  bindRoot:{value:(issuer:NativeRustChatIOFactory,root:RustChatIORoot)=>bindBrowserRecoveryRoot(token,issuer,root)},
  bindInventoryPorts:{value:(ports:RustChatIOPorts)=>bindBrowserRecoveryInventoryPorts(token,ports)},
  revoke:{value:()=>revokeBrowserRecoveryTransport(token)},
  closeAndDrain:{value:()=>closeAndDrainBrowserRecoveryTransport(token)},
 });Object.freeze(token);
 states.set(token,original);workers.add(worker);
 add.call(original.port,'message',receiveOriginal);add.call(original.port,'messageerror',error);portStart.call(original.port);
 return token;
}
/** No getter exposes either port. Use ONLY the first already-valid bootstrap. */
export function postBrowserRecoveryBootstrap(token:BrowserRecoveryBootstrap,bootstrap:unknown):void{
 const s=state(token);if(s.transferred||s.revoked||!s.remote||!workerPost)throw Error('invalidated_snapshot');
 const remote=s.remote;s.transferred=true;s.remote=null;
 try{workerPost.call(s.worker,bootstrap,{transfer:[remote]});}catch{revoke(s);portClose?.call(remote);throw Error('unavailable');}
}
/** Host calls only after actual native validated restore/root enrollment. */
export function bindBrowserRecoveryRoot(token:BrowserRecoveryBootstrap,issuer:NativeRustChatIOFactory,root:RustChatIORoot):void{
 const s=state(token);if(!s.transferred||s.revoked||s.root||s.issuer)throw Error('invalidated_snapshot');
 assertNativeRustChatIORootBinding(root,issuer,s.worker,s.factory);
 s.root=root;s.issuer=issuer;s.contextId=crypto.randomUUID();
 s.storage=createBrowserRecoveryCheckpointStorage({factory:s.factory,root,current:()=>current(s)});
 current(s);post(s,{version:1,admitted:{contextId:s.contextId}});
}
export function revokeBrowserRecoveryTransport(token:BrowserRecoveryBootstrap):void{revoke(state(token));}
/** Host owns both sides' negative handshake. A local abort alone cannot prove
 * Worker/native or Page IO quiescence and never yields a storage receipt. */
export function closeAndDrainBrowserRecoveryTransport(token:BrowserRecoveryBootstrap):Promise<void>{
 const s=state(token);revoke(s);
 if(!s.root&&!s.storage&&!s.contextId){
  // Never admitted: no physical request could start. This is not a native
  // driver quiescence receipt; the owning Host still drains its other work.
  s.finished=true;remove.call(s.port,'message',s.receive);remove.call(s.port,'messageerror',s.error);portClose?.call(s.port);return Promise.resolve();
 }
 return s.closing??=(async()=>{await s.closeWait;return await finish(s);})();
}

/** Actual routing-lease creation calls this only with its sealed original ports.
 * Repeated valid same-Root callers cannot replace the first captured resource. */
export function bindBrowserRecoveryInventoryPorts(token:BrowserRecoveryBootstrap,ports:RustChatIOPorts):void{
 const s=state(token);current(s);const root=s.root!;assertRustChatIOPortsRoot(ports,root,s.factory);
 if(s.inventory){inventoryCurrent(s);return;}
 const originalCurrent=()=>{current(s);assertRustChatIOPortsRoot(ports,root,s.factory);current(s);};
 const inventory=createBrowserDraftInventoryIO(ports,originalCurrent);
 s.inventoryPorts=ports;s.inventory=inventory;inventoryCurrent(s);
 post(s,{version:1,contextId:s.contextId,domain:'draft_inventory',ready:true});
}
