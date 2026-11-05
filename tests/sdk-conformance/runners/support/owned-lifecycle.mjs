/** Bounded owned operation and independent child teardown; no SDK dependencies. */
export async function deadline(work,ms,onTimeout=()=>{}){
 let timer;const pending=Promise.resolve().then(work);
 try{return await Promise.race([pending,new Promise((_,reject)=>{timer=setTimeout(()=>{try{onTimeout();}catch{}reject(new Error('owned operation deadline'));},ms);})]);}
 finally{clearTimeout(timer);}
}
export async function terminateChild(child,graceMs=300){
 if(child.exitCode!==null||child.signalCode!==null)return;
 const exited=new Promise(resolve=>child.once('exit',resolve));child.kill('SIGTERM');
 try{await deadline(()=>exited,graceMs);}catch{child.kill('SIGKILL');await deadline(()=>exited,2000);}
}
export async function cleanupOwned({child,close,graceMs=300}){
 // Start termination before awaiting a potentially stalled native close.
 const termination=terminateChild(child,graceMs);const closing=deadline(close,2000).catch(error=>error);
 const [terminated,closed]=await Promise.allSettled([termination,closing]);
 if(terminated.status==='rejected')throw terminated.reason;
 if(closed.status==='rejected')throw closed.reason;
 if(closed.value instanceof Error)throw closed.value;
}
export async function runOwned(work,ms,cancel,cleanup){
 let timer,timedOut=false;const pending=Promise.resolve().then(work);
 const expired=new Promise((_,reject)=>{timer=setTimeout(()=>{timedOut=true;try{cancel();}catch{}reject(new Error('owned operation deadline'));},ms);});
 try{
  try{return await Promise.race([pending,expired]);}
  catch(error){if(timedOut){try{await deadline(()=>pending.catch(()=>{}),2000);}catch{throw new Error('owned operation cleanup failed: pending work did not settle');}}throw error;}
 }finally{clearTimeout(timer);await cleanup();}
}

// The vector watchdog owns the entire fixture. The read token owns only A's
// callback operation; intentional read cancellation must leave follow-up B live.
export function createOwnership(){
 const vector=new AbortController(),read=new AbortController();
 const check=()=>{if(vector.signal.aborted)throw new Error('owned operation cancelled');};
 return Object.freeze({vector,read,check,cancelAll(){vector.abort();read.abort();}});
}
