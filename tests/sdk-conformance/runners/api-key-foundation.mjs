// Actual compiled npm facade/native extension; no doubles or fallback.
import {readFileSync} from "node:fs";
import {loadApiKeyConformanceSdk} from "./sdk-v1-package-loader.mjs";
const {RustApiKeyClient}=await loadApiKeyConformanceSdk();
const [fixture,id,endpoint]=process.argv.slice(2),suite=JSON.parse(readFileSync(fixture,"utf8")).capabilities["sdk.configuration"],v=suite.vectors.find(x=>x.id===id);
const client=new RustApiKeyClient({apiKey:suite.account.api_key,apiUrl:endpoint,appUrl:endpoint,deviceId:suite.account.device_id,privacy:{enhanced:false},allowPrivateOperations:true});
const errorCode=e=>{try{const value=JSON.parse(e.message);if(typeof value.code==="string"&&typeof value.message==="string")return value.code;}catch{}return e.code;};
async function waitPost(){const limit=Date.now()+10000;while(Date.now()<limit){const s=await(await fetch(endpoint+"/__test/status")).json();if(s.skill_posts===1)return;}throw Error("actual POST not observed");}
const release=()=>fetch(endpoint+"/__test/release");
let value,error;
try{
  if(v.mode==="account"||v.mode==="account_auth_refusal")value=await client.accountInfo();
  else if(v.mode==="allocation_cancel"||v.mode==="allocation_close"||v.mode==="stale_successor"){
    // Internal one-shot ABI, actual scheduler and actual NAPI allocation.
    const native=client.native,a=native.request(),output=await a.accountInfoPrepare();
    try{
      if(v.mode==="allocation_close")client.close();else a.cancel();
      if(v.mode==="stale_successor"){
        const b=native.request(),next=await b.accountInfoPrepare();output.discard();a.cancel();
        try{value=JSON.parse(next.releaseJson());}finally{next.discard();b.cancel();}
      }else value=JSON.parse(output.releaseJson());
    }finally{output.discard();a.cancel();}
  }else if(v.mode==="cancel_after_dispatch"||v.mode==="concurrent_account"){
    const controller=new AbortController();
    const a=client.runSkill(suite.request.app,suite.request.skill,suite.request.input,{signal:controller.signal}).then(value=>({value}),failure=>({error:errorCode(failure)}));
    await waitPost();
    if(v.mode==="concurrent_account"){
      // Real B must finish while original A response is still held.
      let watchdog;try{value=await Promise.race([client.accountInfo(),new Promise((_,reject)=>{watchdog=setTimeout(()=>reject(Error("B serialized behind held A")),5000);})]);}finally{clearTimeout(watchdog);}
    }
    controller.abort();await release();const terminal=await a;
    if(terminal.error!=="cancelled")throw Error("A did not cancel");
    if(v.mode==="cancel_after_dispatch")error=terminal.error;
  }else if(["parallel_code_success","parallel_code_failed_status","parallel_code_http_failure"].includes(v.mode)){
    const r=v.request,pending=client.runSkill(r.app,r.skill,r.input).then(value=>({value}),failure=>({error:errorCode(failure)}));
    const limit=Date.now()+10000;
    while(true){const s=await(await fetch(endpoint+"/__test/status")).json();if(s.code_all_arrived&&s.code_b_sent){if(s.a_released)throw Error("A released before B status response");break;}if(Date.now()>=limit)throw Error("code statuses serialized behind A");}
    if(v.mode==="parallel_code_http_failure"){
      let watchdog,terminal;try{terminal=await Promise.race([pending,new Promise((_,reject)=>{watchdog=setTimeout(()=>reject(Error("HTTP failure serialized behind A")),5000);})]);}finally{clearTimeout(watchdog);}
      if(terminal.error!=="forbidden"||"value" in terminal)throw Error("expected safe typed code HTTP failure");
      const ack=await(await fetch(endpoint+"/__test/code-terminal")).json();if(!ack.terminal_while_a_held)throw Error("missing held-A failure witness");error=terminal.error;await release();
    }else{await release();const terminal=await pending;if(terminal.error)throw Error(JSON.stringify({code:terminal.error}));value=terminal.value;}
  }else if(v.mode==="parallel_tasks_success"||v.mode==="parallel_tasks_failure"){
    const pending=client.runSkill(suite.request.app,suite.request.skill,suite.request.input).then(value=>({value}),failure=>({error:errorCode(failure)}));
    const limit=Date.now()+10000;
    while(true){
      const status=await(await fetch(endpoint+"/__test/status")).json();
      if(status.parallel_all_arrived&&status.parallel_b_sent){if(status.a_released)throw Error("A released before B response");break;}
      if(Date.now()>=limit)throw Error("original task polls serialized behind held A");
    }
    if(v.mode==="parallel_tasks_failure"){
      let watchdog,terminal;
      try{terminal=await Promise.race([pending,new Promise((_,reject)=>{watchdog=setTimeout(()=>reject(Error("failure serialized behind held A")),5000);})]);}finally{clearTimeout(watchdog);}
      if(terminal.error!=="invalid_argument"||"value" in terminal)throw Error("expected safe typed original B failure");
      const ack=await(await fetch(endpoint+"/__test/parallel-terminal")).json();if(!ack.terminal_while_a_held)throw Error("missing held-A terminal witness");
      error=terminal.error;await release();
    }else{await release();const terminal=await pending;if(terminal.error)throw Error(JSON.stringify({code:terminal.error}));value=terminal.value;}
  }else{
    const controller=new AbortController();if(v.mode==="pre_cancel")controller.abort();
    const input=v.mode==="routing_override"?{...suite.request.input,model:null}:suite.request.input;
    value=await client.runSkill(suite.request.app,suite.request.skill,input,{signal:controller.signal});
  }
}catch(e){error=errorCode(e);}finally{client.close();}
console.log(JSON.stringify({id,adapter:"actual-rust-api-key-library",...(error?{error}:{value})})); // sensitive-logging: allow - conformance runner result protocol on stdout; synthetic fixture data only
