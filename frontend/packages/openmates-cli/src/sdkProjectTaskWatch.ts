/** Direct typed Project Task watch facade over the shared Rust session client.
 * Snapshot receipt commit is explicit and must follow the caller's durable
 * publication. Readiness never grants permission to execute a Task.
 */
import {SessionClientError} from './sdkSession.js';
export type SessionProjectTaskWatchScope={api_url:string;account_id:string;workspace:'personal'|{team:string};project_id:string;source_id:string};
export type SessionProjectTaskWatchReceipt={batch_id:string;cursor:string};
export type SessionProjectTaskWatchCheckpoint={scope:SessionProjectTaskWatchScope;cursor:string;tasks:Record<string,unknown>[]};
export type SessionProjectTaskWatchInput={sourceId:string;checkpoint?:SessionProjectTaskWatchCheckpoint};
export type SessionProjectTaskWatchEvent=
  | {kind:'snapshot';scope:SessionProjectTaskWatchScope;cursor:string|null;tasks:Array<{task_id:string;task:Record<string,unknown>}>;receipt:SessionProjectTaskWatchReceipt;checkpoint:SessionProjectTaskWatchCheckpoint}
  | {kind:'state';state:'starting'|'reconnecting'|'connected'|'revoked'|'expired'|'closed'|'failed';cursor:string|null};
export type NativeProjectTaskWatch={
  projectTaskWatchNext(id:string):Promise<string>;
  projectTaskWatchCommit(id:string,receipt:string):Promise<void>;
  projectTaskWatchClose(id:string):void;
};
// Correctness uses explicit return()/close(); this is only GC cleanup.
const abandoned=new FinalizationRegistry<{native:NativeProjectTaskWatch;id:string}>(entry=>{try{entry.native.projectTaskWatchClose(entry.id);}catch{/* Explicit close owns correctness; finalization is best-effort cleanup. */}});
export class SessionProjectTaskWatch implements AsyncIterableIterator<SessionProjectTaskWatchEvent>{
  private closed=false;
  private readonly native:NativeProjectTaskWatch;
  private readonly invoke:<T>(run:()=>Promise<T>)=>Promise<T>;
  private readonly id:string;
  constructor(native:NativeProjectTaskWatch,invoke:<T>(run:()=>Promise<T>)=>Promise<T>,id:string){
    this.native=native;
    this.invoke=invoke;
    this.id=id;
    abandoned.register(this,{native,id},this);
  }
  [Symbol.asyncIterator]():AsyncIterableIterator<SessionProjectTaskWatchEvent>{return this;}
  async next():Promise<IteratorResult<SessionProjectTaskWatchEvent>>{
    if(this.closed)return{done:true,value:undefined};
    try{
      const event:SessionProjectTaskWatchEvent=JSON.parse(await this.invoke(()=>this.native.projectTaskWatchNext(this.id)));
      if(event.kind!=='snapshot'&&event.kind!=='state')throw new SessionClientError('protocol','Invalid Project Task watch event.');
      if(event.kind==='state'&&['revoked','expired','closed','failed'].includes(event.state))await this.close();
      return{done:false,value:event};
    }catch(error){await this.close();throw error;}
  }
  /** Call only after durably publishing this exact snapshot/checkpoint. */
  async commit(receipt:SessionProjectTaskWatchReceipt):Promise<void>{
    if(this.closed)throw new SessionClientError('cancelled','The Project Task watch is closed.');
    if(!receipt||typeof receipt!=='object'||Reflect.ownKeys(receipt).some(k=>k!=='batch_id'&&k!=='cursor')||typeof receipt.batch_id!=='string'||typeof receipt.cursor!=='string')throw new SessionClientError('invalid_argument','Supply the exact local publication receipt.');
    await this.invoke(()=>this.native.projectTaskWatchCommit(this.id,JSON.stringify(receipt)));
  }
  async close():Promise<void>{
    if(this.closed)return;
    this.closed=true;
    abandoned.unregister(this);
    // Synchronous, independent priority close; no full data/commit queue wait.
    await this.invoke(async()=>{this.native.projectTaskWatchClose(this.id);});
  }
  async return():Promise<IteratorResult<SessionProjectTaskWatchEvent>>{await this.close();return{done:true,value:undefined};}
  async throw(error?:unknown):Promise<IteratorResult<SessionProjectTaskWatchEvent>>{await this.close();throw error;}
}
