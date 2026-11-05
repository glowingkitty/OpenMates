/** Native API lifecycle adapter tests; no product requests. */
// contract-test-file: tooling
import { test } from "node:test";
import assert from "node:assert/strict";
import { SessionClient, SessionClientError, SessionProjects } from "../src/sdkSession.ts";

function savedOutput(raw:string){return{releaseJson:()=>raw,discard:()=>{},isTerminal:()=>['completed','error'].includes(JSON.parse(raw).type)};}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("Project items use named native operations and preserve strict unlink input", async () => {
  const client = Object.create(SessionClient.prototype) as SessionClient;
  Reflect.set(client,"essentialEpoch",0);
  const calls: unknown[] = [];
  Object.defineProperty(client, "native", {value: {
    projectsItems: async (id:string,filters:string) => { calls.push([id,JSON.parse(filters)]);return JSON.stringify({items:[]}); },
    projectsUnlinkItem: async (id:string,input:string,filters:string) => { calls.push([id,JSON.parse(input),JSON.parse(filters)]);return JSON.stringify({deleted:false}); },
  }});
  const projects = new SessionProjects(Reflect.get(client,"native"), operation => Reflect.get(client,"invoke").call(client,operation));
  assert.deepEqual(await projects.items("exact",{personal:true}),{items:[]});
  assert.deepEqual(await projects.unlinkItem("exact",{itemType:"chat",targetId:"target",confirmed:true},{teamId:"team"}),{deleted:false});
  assert.deepEqual(calls,[["exact",{personal:true}],["exact",{item_type:"chat",target_id:"target",confirmed:true},{team_id:"team"}]]);
  await assert.rejects(()=>projects.unlinkItem("exact",{itemType:"chat",targetId:"target",target_id:"other",confirmed:true} as never,{personal:true}),error=>error instanceof SessionClientError && error.code==="invalid_argument");
  assert.equal(calls.length,2);
});

test("stopping anonymous streaming cancels only its exact stream and drains it", async () => {
  const calls: string[] = [];
  const events = [{type:"update",update:{Content:{content:"Synthetic"}}},{type:"error",error:{code:"cancelled",message:"Cancelled"}}];
  const client = Object.create(SessionClient.prototype) as SessionClient;
  Reflect.set(client,"essentialEpoch",0);
  Object.defineProperty(client,"native",{value:{
    startAnonymous:async (id:string,_text:string,options:string)=>{assert.equal(id,"synthetic-anonymous");assert.deepEqual(JSON.parse(options),{});return "exact-stream";},
    nextEvent:async (id:string)=>{assert.equal(id,"exact-stream");calls.push("event");return JSON.stringify(events.shift());},
    cancelStream:(id:string)=>{calls.push("cancel:"+id);},
    cancel:()=>{assert.fail("anonymous consumer must not cancel unrelated work");},
  }});
  for await (const event of client.streamAnonymous("synthetic-anonymous","Synthetic")) { assert.equal(event.type,"update");break; }
  assert.deepEqual(calls,["event","cancel:exact-stream","event"]);
});

test("stopping a stream cancels and drains the admitted native operation", async () => {
  const calls: string[] = [];
  const events = [
    { type: "update", update: { Content: { content: "Synthetic" } } },
    { type: "error", error: { code: "cancelled", message: "Cancelled" } },
  ];
  const client = Object.create(SessionClient.prototype) as SessionClient;
  Reflect.set(client,"essentialEpoch",0);
  Object.defineProperty(client, "native", { value: {
    startSend: async () => "synthetic-stream",
    nextEventPrepare: async (id: string) => { assert.equal(id, "synthetic-stream"); calls.push("event"); return savedOutput(JSON.stringify(events.shift())); },
    cancelStream: (id:string) => { calls.push("cancel:"+id); },
    cancel: () => { assert.fail("saved consumer must not cancel unrelated work"); },
  } });
  for await (const event of client.stream("Synthetic")) { assert.equal(event.type, "update"); break; }
  assert.deepEqual(calls, ["event", "cancel:synthetic-stream", "event"]);
});

test("pre-aborted sends never enter native admission", async () => {
  const client = Object.create(SessionClient.prototype) as SessionClient;
  Reflect.set(client,"essentialEpoch",0);
  const abort = new AbortController(); abort.abort();
  await assert.rejects(() => client.send("Synthetic", { signal: abort.signal }), (error: unknown) => error instanceof SessionClientError && error.code === "cancelled");
});

test("synchronous native failures cannot expose private diagnostic strings", async () => {
  const client = Object.create(SessionClient.prototype) as SessionClient;
  Reflect.set(client,"essentialEpoch",0);
  Object.defineProperty(client, "native", { value: { list: () => { throw new Error("synthetic-private-token must not escape"); } } });
  await assert.rejects(() => client.list("chats"), (error: unknown) => error instanceof SessionClientError && error.code === "native_failure" && !error.message.includes("synthetic-private-token"));
});

// contract-test: supporting surface=sdks.npm assertions=sync.startup.bounded-phases
test("one-page facade forwards exact typed options to the library without cache completion", async () => {
  const client = Object.create(SessionClient.prototype) as SessionClient;
  const calls: unknown[] = [];
  Object.defineProperty(client,"essentialEpoch",{value:0,writable:true});
  const output = {chat:{id:"exact",title:"Synthetic",messages:[]},historyComplete:false,piiRestoration:"page_local"};
  Object.defineProperty(client,"native",{value:{chatMessageWindow:async (id:string,raw:string)=>{calls.push([id,JSON.parse(raw)]);return JSON.stringify(output);}}});
  const options = {direction:"latest",limit:2,respectCompressionBoundary:false,unknown:"Rust must reject"} as never;
  assert.deepEqual(await client.chatMessageWindow("exact",options),output);
  assert.deepEqual(calls,[["exact",options]]);
});
test("window response cannot escape a host cancellation epoch", async () => {
  const client = Object.create(SessionClient.prototype) as SessionClient;
  Object.defineProperty(client,"essentialEpoch",{value:0,writable:true});
  Object.defineProperty(client,"native",{value:{chatMessageWindow:async ()=>{Reflect.set(client,"essentialEpoch",1);return JSON.stringify({private:"must not escape"});}}});
  await assert.rejects(()=>client.chatMessageWindow("exact"),e=>e instanceof SessionClientError&&e.code==="cancelled");
});


test("password login forwards only an explicit server preference and rejects coercion",async()=>{
 const client=Object.create(SessionClient.prototype) as SessionClient,calls:unknown[][]=[];
  Reflect.set(client,"essentialEpoch",0);
 Object.defineProperty(client,"native",{value:{loginPassword:async(...args:unknown[])=>{calls.push(args);return '{"id":"synthetic-owner"}';}}});
 for(const preference of [undefined,false,true]){
  assert.deepEqual(await client.loginPassword("synthetic@example.invalid","synthetic",undefined,...(preference===undefined?[]:[{stayLoggedIn:preference}])),{id:"synthetic-owner"});
 }
 assert.deepEqual(calls,[["synthetic@example.invalid","synthetic",undefined,false],["synthetic@example.invalid","synthetic",undefined,false],["synthetic@example.invalid","synthetic",undefined,true]]);
 for(const options of [null,{stayLoggedIn:"true"},{stayLoggedIn:1},{stayLoggedIn:null},{persisted:true}]) await assert.rejects(()=>client.loginPassword("e","p",undefined,options as never),error=>error instanceof SessionClientError&&error.code==="invalid_argument");
 assert.equal(calls.length,3);
});


// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
test("saved abort while native admission is pending targets the eventual exact stream",async()=>{
 const controller=new AbortController(),calls:string[]=[];let admitted!:(id:string)=>void;
 const startup=new Promise<string>(resolve=>{admitted=resolve;});let cancelled=false;
 const client=Object.create(SessionClient.prototype) as SessionClient;Object.defineProperty(client,"essentialEpoch",{value:0,writable:true});
 Object.defineProperty(client,"native",{value:{startSend:()=>startup,cancelStream:(id:string)=>{calls.push('cancel:'+id);cancelled=true;},cancel:()=>assert.fail('must not use global cancellation'),nextEventPrepare:async(id:string)=>{assert.equal(id,'A');assert.equal(cancelled,true);return savedOutput(JSON.stringify({type:'error',error:{code:'cancelled',message:'Cancelled'}}));}}});
 const pending=client.send('Synthetic',{signal:controller.signal});controller.abort();admitted('A');
 await assert.rejects(pending,e=>e instanceof SessionClientError&&e.code==='cancelled');assert.deepEqual(calls,['cancel:A']);assert.equal(Reflect.get(client,'essentialEpoch'),0);
});
test("late saved abort and stale iterator cleanup refuse A without cancelling successor B",async()=>{
 const controller=new AbortController(),calls:string[]=[];let active='A',bCancelled=false;
 const client=Object.create(SessionClient.prototype) as SessionClient;Object.defineProperty(client,'essentialEpoch',{value:0,writable:true});
 Object.defineProperty(client,'native',{writable:true,value:{startSend:async(text:string)=>text,cancel:()=>assert.fail('stale cleanup must not globally cancel B'),cancelStream:(id:string)=>{calls.push('cancel:'+id);if(id!==active)throw new Error(JSON.stringify({code:'conflict',message:'Stale stream'}));if(id==='B')bCancelled=true;},nextEventPrepare:async(id:string)=>{if(id!==active)throw new Error(JSON.stringify({code:'conflict',message:'Stale stream'}));return savedOutput(JSON.stringify({type:'update',update:{Content:{content:id}}}));}}});
 const a=client.stream('A',{signal:controller.signal});assert.equal((await a.next()).value.type,'update');
 // Model native A's independently drained terminal before B admission. Actual
 // bridge protocol/rearm is a separate genuine-adapter obligation.
 active='B';const next=client.stream('B');assert.equal((await next.next()).value.type,'update');
 controller.abort();await a.return(undefined);assert.equal(bCancelled,false);assert.deepEqual(calls,['cancel:A','cancel:A']);assert.equal(Reflect.get(client,'essentialEpoch'),0);
 // Finish B with a terminal event rather than a synthetic endless drain.
 Reflect.set(client,'native',{nextEventPrepare:async()=>savedOutput(JSON.stringify({type:'completed',chat:{id:'B'}}))});
 assert.equal((await next.next()).value.type,'completed');await next.return(undefined);
});
test("explicit global cancel retains global native call and epoch invalidation",()=>{
 const calls:string[]=[];const client=Object.create(SessionClient.prototype) as SessionClient;Object.defineProperty(client,'essentialEpoch',{value:7,writable:true});Object.defineProperty(client,'native',{value:{cancel:()=>calls.push('global')},writable:true});client.cancel();assert.deepEqual(calls,['global']);assert.equal(Reflect.get(client,'essentialEpoch'),8);
});

test("saved startup and queued events refuse the originally captured authority epoch before parsing",async()=>{
 for(const phase of ['startup','event']){
  const calls:string[]=[];let reads=0;const client=Object.create(SessionClient.prototype) as SessionClient;Object.defineProperty(client,'essentialEpoch',{value:0,writable:true});
  Object.defineProperty(client,'native',{value:{startSend:async()=>{if(phase==='startup')Reflect.set(client,'essentialEpoch',1);return 'A';},cancel:()=>assert.fail('must not globally cancel changed context'),cancelStream:(id:string)=>calls.push('cancel:'+id),nextEventPrepare:async(id:string)=>{assert.equal(id,'A');reads++;if(phase==='event'&&reads===1){Reflect.set(client,'essentialEpoch',1);return savedOutput('synthetic-private-non-json');}return savedOutput(JSON.stringify({type:'error',error:{code:'cancelled',message:'Cancelled'}}));}}});
  await assert.rejects(client.send('Synthetic'),e=>e instanceof SessionClientError&&e.code==='cancelled'&&!e.message.includes('synthetic-private'));assert.deepEqual(calls,['cancel:A']);assert.equal(reads,phase==='startup'?1:2);
 }
});

test("saved native sync release denial is normalized and exact drain never allocates private strings",async()=>{
 const calls:string[]=[];let reads=0;const client=Object.create(SessionClient.prototype) as SessionClient;Object.defineProperty(client,'essentialEpoch',{value:0,writable:true});
 Object.defineProperty(client,'native',{value:{startSend:async()=> 'A',cancel:()=>assert.fail('must not cancel B globally'),cancelStream:(id:string)=>calls.push('cancel:'+id),nextEventPrepare:async()=>{reads++;if(reads===1)return{releaseJson:()=>{calls.push('release');throw new Error(JSON.stringify({code:'forbidden',message:'Denied.'}));},discard:()=>calls.push('discard:first'),isTerminal:()=>false};return{releaseJson:()=>assert.fail('drain must not allocate foreign plaintext'),discard:()=>calls.push('discard:terminal'),isTerminal:()=>true};}}});
 await assert.rejects(client.send('Synthetic'),e=>e instanceof SessionClientError&&e.code==='forbidden');assert.deepEqual(calls,['release','discard:first','cancel:A','discard:terminal']);
});
