/** Tab-local pending platform IO accounting only. This gate cannot grant Rust
 * admission or prove that any other legacy producer has stopped. Existing work
 * is allowed to finish; stopping never cancels inference or discards user data.
 * Failure/timeout/cancellation leaves admission closed, with no implicit resume.
 */
export interface LegacyChatDrainInput {
  signal:AbortSignal;
  timeoutMs:number;
  /** ORIGINAL application/account/key/context guard, retained by its owner. */
  current():void;
  verifyOriginal():Promise<void>;
  additionalTerminals?:readonly Promise<unknown>[];
}
export class LegacyChatWorkDrain {
  private stopped=false;
  private readonly active=new Set<Promise<boolean>>();
  isStopped():boolean{return this.stopped;}
  admit():{finish(ok:boolean):void} {
    if(this.stopped)throw Error('legacy_chat_work_stopped');
    let settle!:(ok:boolean)=>void,finished=false;
    const terminal=new Promise<boolean>(resolve=>{settle=resolve;});
    this.active.add(terminal);
    return {finish:(ok:boolean)=>{if(finished)return;finished=true;this.active.delete(terminal);settle(ok);}};
  }
  async stopAndDrain(input:LegacyChatDrainInput):Promise<void> {
    if(this.stopped)throw Error('legacy_chat_work_stopped');
    if(!Number.isSafeInteger(input.timeoutMs)||input.timeoutMs<1||input.timeoutMs>30000)throw Error('invalid_drain_timeout');
    input.current();if(input.signal.aborted)throw Error('cancelled');
    // Synchronous close before the first await, independent of caller dedup maps.
    this.stopped=true;
    const terminals=[...this.active],additional=[...(input.additionalTerminals??[])];
    let timedOut=false,revoked=false,timer:ReturnType<typeof setTimeout>|undefined;
    const check=()=>{if(timedOut||revoked||input.signal.aborted)throw Error('cancelled');input.current();};
    let abort=()=>{};
    const deadline=new Promise<never>((_,reject)=>{
      abort=()=>{revoked=true;reject(Error('cancelled'));};
      input.signal.addEventListener('abort',abort,{once:true});
      if(input.signal.aborted)abort();
      timer=setTimeout(()=>{timedOut=true;reject(Error('legacy_chat_drain_timeout'));},input.timeoutMs);
    });
    const drain=(async()=>{
      check();
      const [outcomes,others]=await Promise.all([Promise.all(terminals),Promise.allSettled(additional)]);
      check();if(outcomes.some(ok=>!ok)||others.some(result=>result.status==='rejected'))throw Error('legacy_chat_drain_failed');
      await input.verifyOriginal();check();
    })();
    try{await Promise.race([drain,deadline]);check();}
    finally{if(timer!==undefined)clearTimeout(timer);input.signal.removeEventListener('abort',abort);}
  }
}
