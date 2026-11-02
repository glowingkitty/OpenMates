/** Per-owner platform lifetime, inactive until explicit context retirement.
 * Startup cutover refuses busy/unsaved state instead of cancelling user work.
 * No owner list, wire status, count snapshot or receipt grants Rust policy. */
import {assertRustChatIORootCurrent} from './browserAdapters';
import type {RustChatIORoot} from './browserAdapters';
declare const ownerReceiptBrand:unique symbol;
export interface LegacyProducerReceipt {readonly [ownerReceiptBrand]:true}
const receipts=new WeakMap<object,{owner:LegacyProducerLifetime;root:RustChatIORoot}>();
export class LegacyProducerLifetime {
 private retired=false;
 private readonly active=new Set<Promise<unknown>>();
 private readonly timers=new Set<ReturnType<typeof setTimeout>>();
 private readonly intervals=new Set<ReturnType<typeof setInterval>>();
 private readonly queued=new Set<object>();
 private readonly bindings=new Set<()=>void>();
 private readonly websocketBindings:{socket:{on(type:string,handler:(payload:unknown)=>void|Promise<void>):void;off(type:string,handler:(payload:unknown)=>void|Promise<void>):void};type:string;original:(payload:unknown)=>unknown;wrapped:(payload:unknown)=>void|Promise<void>;off:()=>void}[]=[];
 on<T>(socket:{on(type:string,handler:(payload:T)=>void|Promise<void>):void;off(type:string,handler:(payload:T)=>void|Promise<void>):void},type:string,original:(payload:T)=>unknown):void {
  this.assertAdmission();
  const existing=this.websocketBindings.find(record=>record.socket===socket&&record.type===type&&record.original===original);
  if(existing){socket.on(type,existing.wrapped);return;}
  const wrapped=(payload:T):void|Promise<void>=>{if(this.retired)return;const result=this.run(()=>original(payload));if(result&&typeof(result as {then?:unknown}).then==='function')return Promise.resolve(result).then(()=>undefined);};
  const record={socket,type,original,wrapped,off:()=>{socket.off(type,wrapped);this.bindings.delete(record.off);const index=this.websocketBindings.indexOf(record as never);if(index>=0)this.websocketBindings.splice(index,1);}};
  this.websocketBindings.push(record as never);this.bindings.add(record.off);socket.on(type,wrapped);
 }
 off<T>(socket:{off(type:string,handler:(payload:T)=>void|Promise<void>):void},type:string,original:(payload:T)=>unknown):void {
  const record=this.websocketBindings.find(entry=>entry.socket===socket&&entry.type===type&&entry.original===original);
  if(record)record.off();else socket.off(type,original as (payload:T)=>void|Promise<void>);
 }
 private readonly eventBindings:{target:EventTarget;type:string;original:EventListenerOrEventListenerObject;capture:boolean;off:()=>void}[]=[];
 listen(target:EventTarget,type:string,original:EventListenerOrEventListenerObject,options?:boolean|AddEventListenerOptions):void {
  this.assertAdmission();const capture=typeof options==='boolean'?options:options?.capture??false;
  if(this.eventBindings.some(record=>record.target===target&&record.type===type&&record.original===original&&record.capture===capture))return;
  const wrapped:EventListener=event=>{if(this.retired)return;this.run(()=>typeof original==='function'?original(event):original.handleEvent(event));};
  const record={target,type,original,capture,off:()=>{target.removeEventListener(type,wrapped,options);this.bindings.delete(record.off);const index=this.eventBindings.indexOf(record);if(index>=0)this.eventBindings.splice(index,1);}};
  this.eventBindings.push(record);this.bindings.add(record.off);target.addEventListener(type,wrapped,options);
 }
 unlisten(target:EventTarget,type:string,original:EventListenerOrEventListenerObject,options?:boolean|EventListenerOptions):void {
  const capture=typeof options==='boolean'?options:options?.capture??false;
  const record=this.eventBindings.find(entry=>entry.target===target&&entry.type===type&&entry.original===original&&entry.capture===capture);
  if(record)record.off();else target.removeEventListener(type,original,options);
 }
 subscribe<T>(store:{subscribe(callback:(value:T)=>void):()=>void},original:(value:T)=>unknown):()=>void {
  this.assertAdmission();let release=()=>{};const wrapped=(value:T)=>{if(!this.retired)this.run(()=>original(value));};
  const off=()=>{release();this.bindings.delete(off);};this.bindings.add(off);release=store.subscribe(wrapped);return off;
 }
 constructor(readonly name:string,private readonly pendingState:()=>boolean=()=>false,private readonly cancelEmptyBackgroundCallbacks=false){}
 isRetired():boolean{return this.retired;}
 assertAdmission():void{if(this.retired)throw Error('legacy_producer_retired:'+this.name);}
 preflight():void{
  this.assertAdmission();
  // No unadmitted editor/journal state is discarded; already admitted writes
  // keep running unchanged. Caller can try explicit cutover again when idle.
  if(this.active.size||this.pendingState()||(!this.cancelEmptyBackgroundCallbacks&&(this.timers.size>0||this.intervals.size>0||this.queued.size>0)))throw Error('legacy_producer_pending:'+this.name);
 }
 observe<T>(pending:Promise<T>):Promise<T>{
  this.assertAdmission();this.active.add(pending);
  void pending.then(()=>this.active.delete(pending),()=>this.active.delete(pending));return pending;
 }
 run<T>(operation:()=>T):T{
  this.assertAdmission();
  let finish!:()=>void;
  const terminal=new Promise<void>(resolve=>{finish=resolve;});this.active.add(terminal);
  const settled=()=>{this.active.delete(terminal);finish();};
  try{
   const result=operation();
   if(result&&typeof (result as {then?:unknown}).then==='function')void Promise.resolve(result).then(settled,settled);
   else settled();
   return result;
  }catch(error){settled();throw error;}
 }
 later(callback:()=>unknown,delay?:number):ReturnType<typeof setTimeout>{
  this.assertAdmission();
  const timer:ReturnType<typeof setTimeout>=setTimeout(()=>{this.timers.delete(timer);if(!this.retired)this.run(callback);},delay);
  this.timers.add(timer);return timer;
 }
 cancel(timer:ReturnType<typeof setTimeout>|undefined|null):void{
  if(timer!==undefined&&timer!==null){clearTimeout(timer);this.timers.delete(timer);}
 }
 every(callback:()=>unknown,delay?:number):ReturnType<typeof setInterval>{
  this.assertAdmission();const timer=setInterval(()=>{if(!this.retired)this.run(callback);},delay);this.intervals.add(timer);return timer;
 }
 cancelEvery(timer:ReturnType<typeof setInterval>|undefined|null):void{
  if(timer!==undefined&&timer!==null){clearInterval(timer);this.intervals.delete(timer);}
 }
 queue(callback:()=>unknown):void{
  this.assertAdmission();const ticket={};this.queued.add(ticket);
  queueMicrotask(()=>{if(!this.queued.delete(ticket)||this.retired)return;this.run(callback);});
 }
 /** Synchronously closes admission/cancels only callbacks not yet admitted.
  * The original promises are retained independently of domain registries. */
 async retire(root:RustChatIORoot):Promise<LegacyProducerReceipt>{
  assertRustChatIORootCurrent(root);this.preflight();this.retired=true;
  let failed=false;for(const off of [...this.bindings]){try{off();}catch{failed=true;}}
  this.bindings.clear();
  for(const timer of this.timers)clearTimeout(timer);this.timers.clear();
  for(const timer of this.intervals)clearInterval(timer);this.intervals.clear();this.queued.clear();
  while(this.active.size)await Promise.allSettled([...this.active]);
  assertRustChatIORootCurrent(root);
  if(failed)throw Error('legacy_unsubscribe_failed:'+this.name);
  if(this.pendingState())throw Error('legacy_producer_pending:'+this.name);
  const receipt=Object.freeze({checkpoint:()=>undefined}) as unknown as LegacyProducerReceipt;
  receipts.set(receipt,{owner:this,root});return receipt;
 }
 assertFinalState():void{
  if(!this.retired||this.active.size||this.pendingState())throw Error('legacy_producer_pending:'+this.name);
 }
 assertReceipt(receipt:LegacyProducerReceipt,root:RustChatIORoot):void{
  const original=receipts.get(receipt);
  if(!original||original.owner!==this||original.root!==root||!this.retired||this.active.size)throw Error('legacy_producer_receipt_invalid');
  assertRustChatIORootCurrent(root);
 }
}
