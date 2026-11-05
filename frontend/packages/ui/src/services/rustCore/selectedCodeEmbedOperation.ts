/** One selected canonical code artifact on the SAME original Main recovery.
 * Rust owns admission, source linkage, key/row policy and native CAS/rereads.
 * No output/key/row/proof is reconstructed; all actual resources stay retained
 * on success, refusal and unknown. This never retires Main or acknowledges it.
 */
import type {OwnedMainMetadataStore} from './mainMetadataStoreOperation';
import type {RecoveryFinalizeStored} from './recoveryFinalizationOperation';

interface Current<C> {ensure_current(client:C):void}
interface ReadTerminal {acquisition_io_quiescent():boolean}
interface ReadControl<C> extends Current<C> {cancel():void;terminal():ReadTerminal|undefined}
interface SelectedRead<C> extends Current<C> {cancel():void}
interface ReadStep<C> {readonly kind:string;apply(client:C):void;retain(client:C):SelectedRead<C>}
interface ReadHandle<C> {control():ReadControl<C>;next():Promise<ReadStep<C>>}
interface StoreControl<C> extends Current<C> {cancel():void}
interface StoreTerminal {native_io_quiescent():boolean}
interface StoreHandle<C> extends Current<C> {
 control():StoreControl<C>;drive():Promise<void>;terminal():StoreTerminal|undefined;
 finish(client:C):Current<C>;
}
export interface CodeEmbedSource<C> extends Current<C> {
 prepare_selected_code_embed_read(client:C,metadata:RecoveryFinalizeStored<C>,embedId:string):ReadHandle<C>;
 begin_selected_code_embed_local_store(client:C,metadata:RecoveryFinalizeStored<C>,read:SelectedRead<C>):StoreHandle<C>;
}
export class OwnedSelectedCodeEmbedStore<C> {
 private acquisition:ReadHandle<C>|null=null;
 private readControl:ReadControl<C>|null=null;
 private step:ReadStep<C>|null=null;
 private read:SelectedRead<C>|null=null;
 private acquisitionTerminal:ReadTerminal|null=null;
 private native:StoreHandle<C>|null=null;
 private nativeControl:StoreControl<C>|null=null;
 private nativeTerminal:StoreTerminal|null=null;
 private stored:Current<C>|null=null;
 private invoked=false;private cancelled=false;private completed=false;
 constructor(private readonly client:C,private readonly recovery:CodeEmbedSource<C>,
  private readonly metadata:OwnedMainMetadataStore<C>,private readonly embedId:string,
  private readonly phase:<T>(operation:()=>Promise<T>)=>Promise<T>,private readonly current:()=>void){}
 cancel():void{
  this.cancelled=true;
  try{this.readControl?.cancel();}finally{this.nativeControl?.cancel();}
 }
 private check():void{this.current();if(this.cancelled)throw Error('cancelled');}
 async run():Promise<void>{
  if(this.invoked)throw Error('unavailable');this.invoked=true;
  await this.phase(async()=>{
   this.check();this.recovery.ensure_current(this.client);
   this.metadata.beginReply(this.client,metadata=>{
    this.acquisition=this.recovery.prepare_selected_code_embed_read(this.client,metadata,this.embedId);
    return this.acquisition;
   });
   this.readControl=this.acquisition!.control();this.check();this.readControl.ensure_current(this.client);
  });
  for(;;){
   // Actual passive socket/auth/body/crypto awaits own no Client/auth lease.
   // Do not preempt a returned Apply with positive status/currentness: actual
   // matched auth/header/cookie bookkeeping must reach the original Core first.
   this.step=await this.acquisition!.next();
   if(this.step.kind==='apply'){
    await this.phase(async()=>{this.step!.apply(this.client);});
    continue;
   }
   if(this.step.kind!=='ready')throw Error('unavailable');
   await this.phase(async()=>{
    this.check();this.recovery.ensure_current(this.client);this.readControl!.ensure_current(this.client);
    this.read=this.step!.retain(this.client);this.read.ensure_current(this.client);
    this.acquisitionTerminal=this.readControl!.terminal()??null;
    if(!this.acquisitionTerminal?.acquisition_io_quiescent())throw Error('unavailable');
    this.check();
    this.metadata.beginReply(this.client,metadata=>{
     this.native=this.recovery.begin_selected_code_embed_local_store(this.client,metadata,this.read!);
     return this.native;
    });
    this.nativeControl=this.native!.control();this.nativeControl.ensure_current(this.client);this.check();
   });
   break;
  }
  // Native transaction, crypto and independent rereads run detached as well.
  // Never race/drop this Promise on cancellation or synthesize a terminal.
  await this.native!.drive();
  await this.phase(async()=>{
   this.check();this.native!.ensure_current(this.client);this.nativeControl!.ensure_current(this.client);
   this.stored=this.native!.finish(this.client);this.stored.ensure_current(this.client);
   this.nativeTerminal=this.native!.terminal()??null;
   if(!this.nativeTerminal?.native_io_quiescent())throw Error('unavailable');
   this.check();this.completed=true;
  });
 }
 /** Original proof recheck only. No receipt/row/key/native or Main release. */
 ensure_current():void{
  if(!this.completed)throw Error('unavailable');this.check();
  this.metadata.ensure_current();this.recovery.ensure_current(this.client);
  this.stored!.ensure_current(this.client);this.check();
 }
}
