/** Thin sequencing of the actual opaque Rust monitor-acquisition resources.
 * Keep this owner through errors. No result/exception/Drop is a drain grant.
 */
export interface CacheMonitorResource {readonly id:string;changed():Promise<boolean>;close():void;free():void}
export interface MonitorStartTerminal {acquisition_io_quiescent():boolean;free():void}
export interface MonitorStartControl<C> {cancel():void;ensure_current(client:C):void;retire():Promise<void>;terminal():MonitorStartTerminal|undefined;free():void}
export interface MonitorStartStep<C> {readonly kind:string;apply(client:C):void;retain(client:C):CacheMonitorResource;free():void}
export interface PreparedCacheMonitor<C> {control():MonitorStartControl<C>;next():Promise<MonitorStartStep<C>>;terminal():MonitorStartTerminal|undefined;free():void}
export interface PhasedMonitorClient {prepare_cache_monitor(handle:string,generation:number,owner:string):PreparedCacheMonitor<this>}
export class OwnedCacheMonitorAcquisition<C> {
 private prepared:PreparedCacheMonitor<C>|null=null;
 private control:MonitorStartControl<C>|null=null;
 private step:MonitorStartStep<C>|null=null;
 private monitor:CacheMonitorResource|null=null;
 private invoked=false;private stopped=false;
 constructor(private readonly client:C,private readonly prepare:(handle:string,generation:number,owner:string)=>PreparedCacheMonitor<C>,private readonly phase:<T>(fn:()=>Promise<T>)=>Promise<T>,private readonly current:()=>void){}
 cancel():void {this.stopped=true;this.control?.cancel();this.monitor?.close();}
 async run(binding:{handle:string;generation:number;owner:string}):Promise<CacheMonitorResource>{
  if(this.invoked)throw Error('unavailable');this.invoked=true;
  await this.phase(async()=>{this.current();if(this.stopped)throw Error('cancelled');this.prepared=this.prepare(binding.handle,binding.generation,binding.owner);this.control=this.prepared.control();});
  for(;;){
   // Real auth/header/body/handshake/socket futures are owned and awaited here,
   // outside the Client/auth lane. Never select-drop next() on cancellation.
   this.step=await this.prepared!.next();
   if(this.step.kind==='apply'){
    const original=this.step;
    // Do not pre-check private-ready/current/control here. The matched opaque
    // Apply must account real Cookie headers even after LOCAL cancellation/TTL.
    // The owning lane still checks actual Worker+Client identity; Rust decides.
    try{await this.phase(async()=>original.apply(this.client));}
    catch{this.control!.cancel();}
    finally{original.free();this.step=null;}
    continue;
   }
   if(this.step.kind!=='ready')throw Error('unavailable');
   await this.phase(async()=>{
    this.current();if(this.stopped)throw Error('cancelled');this.control!.ensure_current(this.client);
    this.monitor=this.step!.retain(this.client);this.current();
   });
   // retain consumed only after actual success; an error keeps the same ready
   // resource and its socket/error receiver in this owner, never a successor.
   this.step.free();this.step=null;return this.monitor!;
  }
 }
 /** Native acquisition scope only; actor/socket/global closure stays separate. */
 acquisitionIoQuiescent():boolean {const t=this.control?.terminal();if(!t)return false;try{return t.acquisition_io_quiescent();}finally{t.free();}}
 /** Explicit negative retirement, always outside the Client/auth lane. */
 async retire():Promise<void>{this.cancel();if(this.control)await this.control.retire();}
}
