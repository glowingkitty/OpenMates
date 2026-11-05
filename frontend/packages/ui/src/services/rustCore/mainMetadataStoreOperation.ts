/** Thin scheduling for SAME original Rust Main metadata-only storage.
 * Core validates Progress, Master, native store, journal, CAS and reread.
 * Reuse the maintained detached-IO scheduler without exposing its Personal
 * retirement/release method: Main transcript and journal remain pending.
 * The owning Worker retains this object on success and every unknown result.
 */
import {OwnedRecoveryFinalization,type RecoveryFinalizeControl,type RecoveryFinalizeHandle,type RecoveryFinalizeStored} from './recoveryFinalizationOperation';
export interface MainMetadataSource<C> {
 ensure_current(client:C):void;
 begin_main_metadata_local_store(client:C):RecoveryFinalizeHandle<C>;
}
export class OwnedMainMetadataStore<C> {
 private readonly operation:OwnedRecoveryFinalization<C>;
 private stored:RecoveryFinalizeStored<C>|null=null;
 constructor(private readonly client:C,recovery:MainMetadataSource<C>,control:RecoveryFinalizeControl,
  phase:<T>(operation:()=>Promise<T>)=>Promise<T>,current:()=>void){
  this.operation=new OwnedRecoveryFinalization(client,{
   ensure_current:original=>recovery.ensure_current(original),
   begin_metadata_local_finalize:original=>{
    const actual=recovery.begin_main_metadata_local_store(original);
    return {ensure_current:c=>actual.ensure_current(c),drive:()=>actual.drive(),
     finish:c=>{const stored=actual.finish(c);this.stored=stored;return stored;},
     terminal:()=>actual.terminal(),free:()=>actual.free()};
   },
  },control,phase,current);
 }
 run():Promise<void>{return this.operation.run();}
 ensure_current():void{this.operation.ensure_current();}
 cancel():void{this.operation.cancel();}
 /** Pass only the retained opaque proof to SAME original binding. No getter. */
 beginReply<H>(client:C,begin:(metadata:RecoveryFinalizeStored<C>)=>H):H{
  if(client!==this.client||!this.stored)throw Error('unavailable');
  this.ensure_current();const actual=begin(this.stored);this.ensure_current();return actual;
 }
 // Deliberately no free, retirement, publication, ACK or terminal export.
}
