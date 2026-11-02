/** Direct native original startup resources. Counts are observed DATA only. */
import {SessionClientError} from './sdkSession.js';
export type NativeInitialSyncMetadata={receivedMetadataCount():Promise<number>;cancel():void};
export type NativeInitialSyncOperation={run():Promise<NativeInitialSyncMetadata>;cancel():void};
type Invoke=<T>(run:()=>Promise<T>)=>Promise<T>;
export class SessionInitialSyncOperation {
 private started=false;
 private readonly native:NativeInitialSyncOperation;
 private readonly invoke:Invoke;
 private readonly current:()=>boolean;
 constructor(native:NativeInitialSyncOperation,invoke:Invoke,current:()=>boolean){this.native=native;this.invoke=invoke;this.current=current;}
 async run():Promise<SessionInitialSyncMetadata>{
  if(this.started)throw new SessionClientError('conflict','The initial sync operation was already consumed.');
  this.started=true;
  try{
   if(!this.current())throw new SessionClientError('cancelled','The original monitor is no longer current.');
   const value=await this.invoke(()=>this.native.run());
   if(!this.current()){value.cancel();throw new SessionClientError('cancelled','The original monitor is no longer current.');}
   return new SessionInitialSyncMetadata(value,this,this.invoke,this.current);
  }catch(error){this.native.cancel();throw error;}
 }
 cancel():void{this.native.cancel();}
}
/** No rows, import/restore constructor, native commit or hint ACK is exposed. */
export class SessionInitialSyncMetadata {
 private readonly native:NativeInitialSyncMetadata;
 private readonly original:SessionInitialSyncOperation;
 private readonly invoke:Invoke;
 private readonly current:()=>boolean;
 constructor(native:NativeInitialSyncMetadata,original:SessionInitialSyncOperation,invoke:Invoke,current:()=>boolean){this.native=native;this.original=original;this.invoke=invoke;this.current=current;}
 async receivedMetadataCount():Promise<number>{
  if(!this.current())throw new SessionClientError('cancelled','The original monitor is no longer current.');
  const count=await this.invoke(()=>this.native.receivedMetadataCount());
  if(!this.current())throw new SessionClientError('cancelled','The original monitor is no longer current.');
  if(!Number.isSafeInteger(count)||count<0)throw new SessionClientError('protocol','Invalid received metadata count.');
  return count;
 }
 cancel():void{this.native.cancel();this.original.cancel();}
}
