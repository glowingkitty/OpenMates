/** Actual facade methods with explicit native doubles only. No Rust, native VM,
 * HTTP, credentials, account, CLI or performance acceptance is supplied here.
 * Caller encoders/getters are the actual JavaScript operations under test.
 * Old dispatch must remain zero; an independent fresh B must remain usable.
 * Existing shared SDK plans and real Rust guards remain separate CI duties. */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {SessionClient,SessionClientError,SessionTasks,SessionProjects} from '../src/sdkSession.ts';
function client(native:object):SessionClient {
 const c=Object.create(SessionClient.prototype) as SessionClient;
 Object.defineProperty(c,'native',{value:native});Reflect.set(c,'essentialEpoch',0);return c;
}
const cancelled=(e:unknown)=>e instanceof SessionClientError&&e.code==='cancelled';
function output(raw='{"id":"B"}'){return{releaseJson:()=>raw,discard(){},isTerminal:()=>true};}
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,auth.session.isolation
test('rich options toJSON cancellation refuses old native dispatch; fresh B succeeds',async()=>{
 let calls=0,cancel=0;const c=client({cancel(){cancel++;},async chatDetailsPrepare(){calls++;return output();}});
 await assert.rejects(c.chatDetails('chat',{toJSON(){c.cancel();return{};}} as never),cancelled);
 assert.equal(calls,0);assert.equal(cancel,1);assert.deepEqual(await c.chatDetails('chat'),{id:'B'});assert.equal(calls,1);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,auth.session.isolation
test('Work input and confirmation callbacks cannot admit old work after cancellation',async()=>{
 let calls=0;const native={cancel(){},async tasksCreate(){calls++;return '{"task":"B"}';},async tasksDelete(){calls++;return '{}';}};
 const c=client(native),invoke=<T>(op:()=>Promise<T>)=>Reflect.get(c,'invoke').call(c,op) as Promise<T>,tasks=new SessionTasks(native as never,invoke);
 await assert.rejects(tasks.create({title:'A',get description(){c.cancel();return 'private';}},{personal:true}),cancelled);assert.equal(calls,0);
 await assert.rejects(tasks.delete('A',{get confirmed(){c.cancel();return true as const;}},{personal:true}),cancelled);assert.equal(calls,0);
 assert.deepEqual(await tasks.create({title:'B'},{personal:true}),{task:'B'});assert.equal(calls,1);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,auth.session.isolation
test('nested public import from encoder leaves B import alone and never dispatches A',async()=>{
 const seen:unknown[]=[];const c=client({cancel(){},async importSession(raw:string){seen.push(JSON.parse(raw));}});let b:Promise<void>|undefined;
 await assert.rejects(c.importSession({toJSON(){b=c.importSession({identity:'B'});return{identity:'A'};}}),cancelled);
 await b;assert.deepEqual(seen,[{identity:'B'}]);await c.importSession({identity:'fresh'});assert.equal(seen.length,2);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,auth.session.isolation
test('login option reentrancy is checked before retiring B and before native login',async()=>{
 for(const at of [1,3]){
  let reads=0,logins=0,imports=0,b:Promise<void>|undefined;const c=client({cancel(){},async importSession(){imports++;},async loginPassword(){logins++;return '{}';}});
  const options={get stayLoggedIn(){if(++reads===at)b=c.importSession({identity:'B'});return false;}};
  await assert.rejects(c.loginPassword('synthetic@example.invalid','synthetic',undefined,options),cancelled);await b;
  assert.equal(logins,0);assert.equal(imports,1);await c.loginPassword('synthetic@example.invalid','synthetic');assert.equal(logins,1);
 }
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,auth.session.isolation
test('watch selector getter and cache consent cannot replace original invocation',async()=>{
 let watches=0,stages=0;const native={cancel(){},async projectTaskWatchOpen(){watches++;return '{"id":"B"}';},async cacheChatStage(){stages++;return '{"id":"B"}';}};
 const c=client(native),projects=new SessionProjects(native as never,<T>(op:()=>Promise<T>)=>Reflect.get(c,'invoke').call(c,op) as Promise<T>);
 await assert.rejects(projects.watchTasks('project',{get sourceId(){c.cancel();return 'source';}},{personal:true}),cancelled);assert.equal(watches,0);
 await assert.rejects(c.cacheChatStage('chat',{get includeSecrets(){c.cancel();return true as const;}}),cancelled);assert.equal(stages,0);
 assert.equal((await c.cacheChatStage('chat',{includeSecrets:true})).id,'B');assert.equal(stages,1);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,auth.session.isolation
test('saved and anonymous option callbacks do not revive cancelled inference',async()=>{
 let starts=0;const c=client({cancel(){},async startSend(){starts++;return 'B';},async startAnonymous(){starts++;return 'B';}});
 await assert.rejects(c.stream('private A',{get chatId(){c.cancel();return 'chat';}}).next(),cancelled);assert.equal(starts,0);
 await assert.rejects(c.streamAnonymous('synthetic-id','private A',{get language(){c.cancel();return 'en';}} as never).next(),cancelled);assert.equal(starts,0);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,auth.session.isolation
test('legacy custom invoke(op) facade constructor remains callable-compatible',async()=>{
 const seen:unknown[]=[];const native={async tasksCreate(input:string,filters:string){seen.push(JSON.parse(input),JSON.parse(filters));return '{"task":"B"}';}};
 const tasks=new SessionTasks(native as never,operation=>operation());
 assert.deepEqual(await tasks.create({title:'B',primaryChatId:'chat'},{personal:true}),{task:'B'});assert.deepEqual(seen,[{title:'B',primary_chat_id:'chat'},{personal:true}]);
});
