/** PRIVATE draft. Direct native session APIs; no CLI, credentials discovery or automatic persistence. */
import {SessionClientError} from './sdkSession.js';
import {SessionInitialSyncOperation,type NativeInitialSyncOperation} from './sdkStartupSync.js';
export {SessionInitialSyncOperation,SessionInitialSyncMetadata} from './sdkStartupSync.js';
export type SessionStorageScope={api_url:string;account_id:string;team_id:string|null};
export type SessionChatAccessDenial={kind:'access_denial';reason:'expired'|'scope_revoked'|'chat_unavailable';chat_id?:string};
export type SessionChatInvalidation={kind:'invalidation';recovery_chat_ids:string[]}|SessionChatAccessDenial;
export type SessionChatRefresh={id:string;scope:SessionStorageScope;checkpoint_json:string;ciphertext_sha256:string;credential_revision:number;credentials_json:string};
export type SessionChatDurableReceipt={ciphertext_sha256:string;credential_revision:number};
/** All writers sharing this scope MUST use the same atomic, durable CAS generation.
 * JSON strings are opaque exact UTF8 bytes. Never parse/rewrite/camel-case them.
 * compareAndSwap must fsync before returning actual stored digest/revision.
 */
export type SessionDurableStore={
  generation(scope:SessionStorageScope):Promise<string|null>;
  compareAndSwap(input:{scope:SessionStorageScope;expectedVersion:string|null;nextVersion:string;checkpointJson:string;credentialsJson:string;ciphertextSha256:string;credentialRevision:number}):Promise<({stored:true}&SessionChatDurableReceipt)|{stored:false}>;
};
export type SessionRecoveryAdmission=
 |{kind:'deferred'}|{kind:'canonical';receipt:Record<string,unknown>}
 |{kind:'ready';id:string;checkpoint_json:string;checkpoint_sha256:string};
export type NativeEssential={
 initialSyncOpen(id:string):NativeInitialSyncOperation;
 chatMonitorValidate(id:string):Promise<void>;
 chatMonitorAccessDenial(id:string):string;
 chatMonitorOpen():Promise<string>;chatMonitorNext(id:string):Promise<string>;
 chatMonitorStagePreferCache(id:string,includeSecrets:boolean,selected?:string):Promise<string>;
 chatMonitorStage(id:string,includeSecrets:boolean,selected?:string):Promise<string>;
 chatMonitorCommit(id:string,stage:string,receipt:string):Promise<string>;
 chatMonitorDiscard(id:string,stage:string):void;chatMonitorClose(id:string):void;
 completionRecoveryDiscard(id:string):void;
 completionRecoveryEnable(enabled:boolean):Promise<void>;completionRecoveryJobs():Promise<string>;
 completionRecoveryJobsForChat(chatId:string):Promise<string>;
 completionRecoveryStage(id:string):Promise<string>;completionRecoveryResume(checkpoint:string):Promise<string>;
 completionRecoveryCommit(id:string,receipt:string):Promise<string>;
};
type Invoke=<T>(run:()=>Promise<T>)=>Promise<T>;
const abandoned=new FinalizationRegistry<{native:NativeEssential;id:string}>(entry=>{try{entry.native.chatMonitorClose(entry.id);}catch{/* Explicit lifecycle owns correctness. */}});
export class SessionChatMonitor implements AsyncIterableIterator<SessionChatInvalidation>{
 private native:NativeEssential;private invoke:Invoke;private current:()=>boolean;private id:string;private closed=false;
 readonly scope:SessionStorageScope;
 constructor(native:NativeEssential,invoke:Invoke,current:()=>boolean,id:string,scope:SessionStorageScope){this.native=native;this.invoke=invoke;this.current=current;this.id=id;this.scope=Object.freeze({...scope});abandoned.register(this,{native,id},this);}
 private valid():void{if(this.closed||!this.current())throw new SessionClientError('cancelled','The session monitor is no longer current.');}
 [Symbol.asyncIterator]():AsyncIterableIterator<SessionChatInvalidation>{return this;}
 async next():Promise<IteratorResult<SessionChatInvalidation>>{
  if(this.closed)return{done:true,value:undefined};
  try{this.valid();const raw=await this.invoke(()=>this.native.chatMonitorNext(this.id));this.valid();const value=JSON.parse(raw);
   if(value.kind==='access_denial')return{done:false,value};
   if(value.kind!=='invalidation'||!Array.isArray(value.recovery_chat_ids)||value.recovery_chat_ids.some((id:unknown)=>typeof id!=='string'))throw new SessionClientError('protocol','Invalid keyless invalidation.');
   return{done:false,value};
  }catch(error){await this.close();throw error;}
 }
 accessDenial():SessionChatAccessDenial|null{if(!this.current())throw new SessionClientError("cancelled","Session authority changed.");try{return JSON.parse(this.native.chatMonitorAccessDenial(this.id));}catch{throw new SessionClientError("native_failure","The native session operation failed.");}}
 /** Explicit original initial startup; this returns no store/ACK authority. */
 async beginInitialSync():Promise<SessionInitialSyncOperation>{
  this.valid();
  let admitted:NativeInitialSyncOperation|undefined;
  try{
   const result=await this.invoke(async()=>{this.valid();const native=this.native.initialSyncOpen(this.id);admitted=native;this.valid();return new SessionInitialSyncOperation(native,this.invoke,()=>!this.closed&&this.current());});
   this.valid();return result;
  }catch(error){admitted?.cancel();throw error;}
 }
 /** Explicit foreground reauthorization; caller persists rotated credentials even on failure. */
 async validate():Promise<void>{this.valid();await this.invoke(()=>this.native.chatMonitorValidate(this.id));this.valid();}
 async stageRefresh(options:{includeSecrets:true;selectedChatId?:string}):Promise<SessionChatRefresh>{
  this.valid();if(options?.includeSecrets!==true)throw new SessionClientError('invalid_argument','Explicit credential storage consent is required.');
  const raw=await this.invoke(()=>this.native.chatMonitorStage(this.id,true,options.selectedChatId));this.valid();const value=JSON.parse(raw);
  if(typeof value.id!=='string'||typeof value.checkpoint_json!=='string'||typeof value.credentials_json!=='string'||typeof value.ciphertext_sha256!=='string'||!Number.isSafeInteger(value.credential_revision))throw new SessionClientError('protocol','Invalid durable refresh stage.');
  return value;
 }
 /** Opt-in selection policy; use the existing durable commit/discard lifecycle. */
 async stageRefreshPreferCache(options:{includeSecrets:true;selectedChatId?:string}):Promise<SessionChatRefresh>{
  this.valid();if(options?.includeSecrets!==true)throw new SessionClientError('invalid_argument','Explicit credential storage consent is required.');
  let admitted:string|undefined;
  try{
   const raw=await this.invoke(()=>this.native.chatMonitorStagePreferCache(this.id,true,options.selectedChatId).then(raw=>{admitted=raw;return raw;}));this.valid();const value=JSON.parse(raw);
   if(typeof value.id!=='string'||typeof value.checkpoint_json!=='string'||typeof value.credentials_json!=='string'||typeof value.ciphertext_sha256!=='string'||!Number.isSafeInteger(value.credential_revision))throw new SessionClientError('protocol','Invalid durable refresh stage.');
   return value;
  }catch(error){if(admitted!==undefined){try{this.native.chatMonitorDiscard(this.id,JSON.parse(admitted).id);}catch{/* Best-effort discard; the original error is rethrown. */}}throw error;}
 }
 async commitRefresh(stageId:string,receipt:SessionChatDurableReceipt):Promise<Record<string,unknown>>{
  this.valid();const raw=await this.invoke(()=>this.native.chatMonitorCommit(this.id,stageId,JSON.stringify(receipt)));this.valid();return JSON.parse(raw);
 }
 async discardRefresh(stageId:string):Promise<void>{this.valid();await this.invoke(async()=>{this.native.chatMonitorDiscard(this.id,stageId);});}
 async refreshAndPublish(store:SessionDurableStore,options:{includeSecrets:true;selectedChatId?:string}):Promise<Record<string,unknown>>{
  this.valid();const expected=await store.generation(this.scope);this.valid();
  const stage=await this.stageRefresh(options);let committed=false;
  try{
   const receipt=await store.compareAndSwap({scope:this.scope,expectedVersion:expected,nextVersion:stage.id,checkpointJson:stage.checkpoint_json,credentialsJson:stage.credentials_json,ciphertextSha256:stage.ciphertext_sha256,credentialRevision:stage.credential_revision});
   this.valid();if(receipt.stored!==true)throw new SessionClientError('conflict','A newer durable session snapshot won the storage transaction.');
   const output=await this.commitRefresh(stage.id,{ciphertext_sha256:receipt.ciphertext_sha256,credential_revision:receipt.credential_revision});committed=true;return output;
  }finally{if(!committed){try{await this.discardRefresh(stage.id);}catch{/* Cancellation or commit may already have consumed it. */}}}
 }
 async close():Promise<void>{if(this.closed)return;this.closed=true;abandoned.unregister(this);await this.invoke(async()=>{this.native.chatMonitorClose(this.id);});}
 async return():Promise<IteratorResult<SessionChatInvalidation>>{await this.close();return{done:true,value:undefined};}
 async throw(error?:unknown):Promise<IteratorResult<SessionChatInvalidation>>{await this.close();throw error;}
}
export class SessionCompletionRecovery{
 private native:NativeEssential;private invoke:Invoke;
 constructor(native:NativeEssential,invoke:Invoke){this.native=native;this.invoke=invoke;}
 /** Cookie foreground opt-in; disabled by default. This never changes SDK identity. */
 async discard(stageId:string):Promise<void>{await this.invoke(async()=>{this.native.completionRecoveryDiscard(stageId);});}
 async enable(enabled:boolean):Promise<void>{await this.invoke(()=>this.native.completionRecoveryEnable(enabled));}
 async jobs():Promise<Array<{id:string;job:Record<string,unknown>}>>{return JSON.parse(await this.invoke(()=>this.native.completionRecoveryJobs()));}
 /** Selected offered work only; no account inventory, absence or list TTL proof. */
 async jobsForChat(chatId:string):Promise<Array<{id:string;job:Record<string,unknown>}>>{return JSON.parse(await this.invoke(()=>this.native.completionRecoveryJobsForChat(chatId)));}
 async stage(jobHandle:string):Promise<SessionRecoveryAdmission>{return JSON.parse(await this.invoke(()=>this.native.completionRecoveryStage(jobHandle)));}
 /** Checkpoint is exact opaque Rust UTF8. Core reauthenticates; JSON is never authority. */
 async resume(checkpointJson:string):Promise<SessionRecoveryAdmission>{return JSON.parse(await this.invoke(()=>this.native.completionRecoveryResume(checkpointJson)));}
 /** Call only after the exact checkpoint bytes are durably stored. */
 async commit(stageId:string,receipt:{checkpoint_sha256:string}):Promise<Record<string,unknown>>{return JSON.parse(await this.invoke(()=>this.native.completionRecoveryCommit(stageId,JSON.stringify(receipt))));}
}
