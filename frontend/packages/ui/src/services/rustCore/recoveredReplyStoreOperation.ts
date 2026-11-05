/** Thin selected-reply scheduling after SAME actual Main metadata storage.
 * Rust owns original Progress/Master/native store/journal and all row limits.
 * This operation retains its original drive/control/result on every unknown.
 * Its success is ONE message only, never full transcript/artifact durability.
 * No resource release, journal retirement, publication, version bump or ACK.
 */
import {OwnedRecoveryFinalization,type RecoveryFinalizeControl,type RecoveryFinalizeHandle,type RecoveryFinalizeStored} from './recoveryFinalizationOperation';
import type {OwnedMainMetadataStore} from './mainMetadataStoreOperation';
export interface ReplyControl<C> extends RecoveryFinalizeControl {ensure_current(client:C):void;free():void}
export interface ReplyHandle<C> extends RecoveryFinalizeHandle<C> {control():ReplyControl<C>}
export interface ReplySource<C> {ensure_current(client:C):void;begin_recovered_reply_local_store(client:C,metadata:RecoveryFinalizeStored<C>):ReplyHandle<C>}
export class OwnedRecoveredReplyStore<C> {
 private readonly operation:OwnedRecoveryFinalization<C>;
 private control:ReplyControl<C>|null=null;
 private handle:ReplyHandle<C>|null=null;
 constructor(client:C,recovery:ReplySource<C>,metadata:OwnedMainMetadataStore<C>,originalControl:RecoveryFinalizeControl,
  phase:<T>(operation:()=>Promise<T>)=>Promise<T>,current:()=>void){
  this.operation=new OwnedRecoveryFinalization(client,{
   ensure_current:original=>{metadata.ensure_current();recovery.ensure_current(original);this.control?.ensure_current(original);},
   begin_metadata_local_finalize:original=>{
    const actual=metadata.beginReply(original,stored=>{const actual=recovery.begin_recovered_reply_local_store(original,stored);this.handle=actual;return this.handle;});
    this.control=actual.control();this.control.ensure_current(original);return actual;
   },
  },{cancel:()=>{this.control?.cancel();originalControl.cancel();}},phase,current);
 }
 run():Promise<void>{return this.operation.run();}
 ensure_current():void{this.operation.ensure_current();}
 cancel():void{this.operation.cancel();}
}
