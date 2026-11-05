// Explicit opt-in pull loop. Rust owns socket hints, policy, crypto and receipts.
// This adapter only sequences owned Worker calls and yields retained UI values.
import type {BrowserCoreWorkerHost} from './workerHost';
import type {BrowserCacheEffectHandler,BrowserCacheScope,BrowserIncomingCacheUpdate,BrowserRetainedRead,BrowserCacheSourceEvidence} from './browserCacheProtocol';
import type {LocalCursorSelector} from './protocol';
export async function* browserIncomingCacheUpdates(host:BrowserCoreWorkerHost,
 context:{handle:string;generation:number;expectedPrincipal:string;chatId:string;scope:BrowserCacheScope;selector:LocalCursorSelector},
 signal:AbortSignal,effects:()=>BrowserCacheEffectHandler,clock:()=>number,
 onSelected?:(selected:BrowserRetainedRead,evidence:BrowserCacheSourceEvidence)=>void|Promise<void>):AsyncGenerator<BrowserIncomingCacheUpdate> {
 const {chatId,scope,selector,...owner}=context;
 const originalEffects=effects;
 if(signal.aborted)throw Error('unavailable');
 // Caller cancellation retires this original resource, never the shared Host.
 const transport=new AbortController();
 const start=await host.request({...owner,operation:'start_cache_monitor'},transport.signal);
 if(!start.ok||!start.cacheMonitor)throw Error('unavailable');
 const monitorId=start.cacheMonitor.id;
 let stopping:Promise<unknown>|undefined;
 const stopOwn=()=>stopping??=host.request({...owner,operation:'stop_cache_monitor',monitorId},transport.signal).catch(()=>undefined);
 const abort=()=>{void stopOwn();};
 signal.addEventListener('abort',abort,{once:true});
 if(signal.aborted)void stopOwn();
 try {
  while(!signal.aborted){
   const change=await host.request({...owner,operation:'wait_cache_monitor',monitorId},transport.signal);
   if(signal.aborted)throw Error('unavailable');
   if(!change.ok||!change.cacheMonitor)throw Error('unavailable');
   if(change.cacheMonitor.state==='idle')continue;
   if(change.cacheMonitor.state!=='ready')throw Error('unavailable');
   const update=await host.request({...owner,operation:'read_cache_monitor_update',monitorId,chatId,scope,selector,nowSeconds:clock()},transport.signal,30000,undefined,originalEffects(),{
    // Host owns this nonfinal progress terminal and serializes any later actual
    // metadata effects behind it. The generator yields only final updates.
    onSelected:async(selected,evidence)=>{
     if(selected.chat.id!==chatId||selected.cacheReadKind!=='monitor')throw Error('unavailable');
     if(!signal.aborted)await onSelected?.(selected,evidence);
    },
    createContinuationEffects:(current:()=>void)=>{
     const actual=originalEffects();
     return{current:()=>{current();actual.current();current();},
      execute:(plan:string,signal:AbortSignal)=>{current();return actual.execute(plan,signal);},
      // Always drain the original actual handler, even after revocation.
      close:()=>actual.close()};
    },
   });
   if(signal.aborted)throw Error('unavailable');
   if(!update.ok||!update.cacheUpdate||update.cacheMonitorId!==monitorId)throw Error('unavailable');
   // No next read occurs until the consumer has accepted this exact publication.
   if(signal.aborted)throw Error('unavailable');
   yield update.cacheUpdate;
  }
 }finally{
  signal.removeEventListener('abort',abort);
  await stopOwn();
 }
}
