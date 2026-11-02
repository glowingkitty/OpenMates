/** Scheduling for the SAME opaque Rust Personal metadata recovery resource.
 * Rust owns source, scope, key, CAS, reread and checkpoint-retirement policy.
 * This object stays in its original Worker slot on every error/unknown result.
 */
export interface RecoveryFinalizeControl {cancel():void}
export interface RecoveryFinalizeTerminal {native_io_quiescent():boolean;free():void}
export interface RecoveryFinalizeStored<C> {ensure_current(client:C):void;free():void}
export interface RecoveryFinalizeHandle<C> {
 ensure_current(client:C):void;drive():Promise<void>;
 finish(client:C):RecoveryFinalizeStored<C>;
 terminal():RecoveryFinalizeTerminal|undefined;free():void;
}
export interface RecoveryFinalizeSource<C> {
 ensure_current(client:C):void;
 begin_metadata_local_finalize(client:C):RecoveryFinalizeHandle<C>;
}
export class OwnedRecoveryFinalization<C> {
 private finalizer:RecoveryFinalizeHandle<C>|null=null;
 private stored:RecoveryFinalizeStored<C>|null=null;
 private terminal:RecoveryFinalizeTerminal|null=null;
 private invoked=false;private cancelled=false;private running=false;
 private completed=false;private released=false;
 constructor(private readonly client:C,private readonly recovery:RecoveryFinalizeSource<C>,
  private readonly control:RecoveryFinalizeControl,
  private readonly phase:<T>(operation:()=>Promise<T>)=>Promise<T>,
  private readonly current:()=>void){}
 cancel():void {
  this.cancelled=true;
  // A separate genuine original control stays callable while wasm-bindgen
  // drive() holds its mutable finalizer borrow. Never call that borrowed handle.
  this.control.cancel();
 }
 async run():Promise<void>{
  if(this.invoked||this.released)throw Error('unavailable');
  this.invoked=true;this.running=true;
  const check=()=>{this.current();if(this.cancelled)throw Error('cancelled');};
  try{
   await this.phase(async()=>{
    check();this.recovery.ensure_current(this.client);
    this.finalizer=this.recovery.begin_metadata_local_finalize(this.client);
    this.finalizer.ensure_current(this.client);check();
   });
   // Exact actual native transaction/crypto/journal awaits run without a
   // Client/auth phase. Cancellation never races or drops this owned Promise.
   await this.finalizer!.drive();
   await this.phase(async()=>{
    check();this.finalizer!.ensure_current(this.client);
    this.stored=this.finalizer!.finish(this.client);
    this.stored.ensure_current(this.client);check();
    this.terminal=this.finalizer!.terminal()??null;
    if(!this.terminal||!this.terminal.native_io_quiescent())throw Error('unavailable');
    check();this.completed=true;
   });
  }finally{this.running=false;}
 }
 /** Short SAME-Client check before a nonfinal observational progress frame. */
 ensure_current():void {
  if(!this.completed||this.released||this.cancelled)throw Error('unavailable');
  this.current();this.stored!.ensure_current(this.client);this.current();
 }
 /** Native IO retirement only; never whole-hint completion, publish or ACK. */
 nativeIoQuiescent():boolean {
  return !this.running&&this.completed&&this.terminal!==null&&this.terminal.native_io_quiescent();
 }
 /** Invoke only after SAME original recovery.retire() during existing teardown.
  * Unknown/error/cancel paths keep this object and its original resources held.
  */
 releaseAfterRecoveryRetired():void {
  if(this.released||!this.nativeIoQuiescent())throw Error('unavailable');
  this.stored!.free();this.stored=null;
  this.terminal!.free();this.terminal=null;
  this.finalizer!.free();this.finalizer=null;this.released=true;
 }
}
