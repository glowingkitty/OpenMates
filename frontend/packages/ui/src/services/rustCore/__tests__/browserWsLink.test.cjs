// Adapter contract for rustCore/browserWsLink.ts: executes Rust ws_link
// commands verbatim and routes frames by the core's Uint32Array answer.
// The core is scripted here; the policy itself is covered by the Rust
// `ws_link` tests. Envelope parsing shares the Rust vectors.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),ts=require('typescript');
const own=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'openmates-ws-link-'));
fs.writeFileSync(path.join(dir,'browserWsLink.js'),ts.transpileModule(fs.readFileSync(path.join(own,'browserWsLink.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText);
process.on('exit',()=>fs.rmSync(dir,{recursive:true,force:true}));
const {RustWsLink,parseLinkFrame,REFRESH_OUTCOME,FAMILY}=require(path.join(dir,'browserWsLink.js'));
const vectors=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../../../../../../packages/openmates-rust/src/ws_link/envelope_vectors.json'),'utf8')).vectors;
const tick=()=>new Promise(r=>setImmediate(r));

class FakeSocket{constructor(){this.readyState=0;this.sent=[];this.closed=null;this.onopen=this.onmessage=this.onerror=this.onclose=null;}
 send(d){this.sent.push(d);} close(code,reason){this.closed={code,reason};this.readyState=3;}
 open(){this.readyState=1;this.onopen({});} message(text){this.onmessage({data:text,timeStamp:42});} drop(code,reason='',wasClean=false){this.readyState=3;this.onclose({code,reason,wasClean});}}

/** Scripted core: every call is recorded; answers come from `script`. */
function fixture(script={}){
 const calls=[],timers=[],statuses=[],sockets=[],refreshes=[],registered=new Map(),types=[];let openSocket;
 const answer=(name,...args)=>{calls.push([name,...args.slice(1)]);const a=script[name];return JSON.stringify(typeof a==='function'?a(...args.slice(1)):a??[]);};
 const core={
  session:(...a)=>answer('session',...a),connect:(...a)=>answer('connect',...a),retry:(...a)=>answer('retry',...a),force_reconnect:(...a)=>answer('force_reconnect',...a),
  disconnect:(...a)=>answer('disconnect',...a),refreshed:(...a)=>answer('refreshed',...a),opened:(...a)=>answer('opened',...a),errored:(...a)=>answer('errored',...a),
  closed:(...a)=>answer('closed',...a),timer:(...a)=>answer('timer',...a),online:(...a)=>answer('online',...a),network_changed:(...a)=>answer('network_changed',...a),
  resumed:(...a)=>answer('resumed',...a),foreground:(...a)=>answer('foreground',...a),data_activity:(now)=>calls.push(['data_activity']),
  intern:(type)=>{const known=types.indexOf(type);if(known>=0)return known;if(types.length>=(script.internCap??64))return 0xffffffff;types.push(type);return types.length-1;},
  frame_id:(now,socket,id)=>{calls.push(['frame',socket,types[id],undefined]);return (script.frame??(()=>5))(socket,types[id],undefined);},
  frame_id_message:(now,socket,id,error)=>{calls.push(['frame',socket,types[id],error]);return (script.frame??(()=>5))(socket,types[id],error);},
  frame:(now,socket,type,error)=>{calls.push(['frame',socket,type,error,'string']);return (script.frame??(()=>5))(socket,type,error);},
  handlers:(type)=>Uint32Array.from(script.handlers?script.handlers(type,registered.get(type)??[]):registered.get(type)??[]),
  drain:()=>{calls.push(['drain']);return JSON.stringify(script.drain??[]);},
  on:(type,id)=>{calls.push(['on',type,id]);const r=(script.on??(()=>0))(type,id);if(r>=0)registered.set(type,[...(registered.get(type)??[]),id]);return r;},
  off:(type,id)=>{calls.push(['off',type,id]);registered.set(type,(registered.get(type)??[]).filter(x=>x!==id));return true;},
  clear:(type)=>(calls.push(['clear',type]),registered.delete(type)),clear_all:()=>(calls.push(['clear_all']),registered.clear(),0),declare_family:(f)=>calls.push(['declare_family',f]),
  open_socket:()=>openSocket,status:()=>'connected'};
 const platform={now:()=>42,setTimeout:(cb,ms)=>timers.push({cb,ms}),createSocket(){if(script.createSocket)script.createSocket();const s=new FakeSocket();sockets.push(s);return s;},
  refreshSession:(reason)=>{refreshes.push(reason);return script.refreshSession?script.refreshSession(reason):Promise.resolve({outcome:REFRESH_OUTCOME.ready,hasToken:true});},
  isForeground:()=>script.pageForeground??true,setStatus:(status,error)=>statuses.push([status,error])};
 const link=new RustWsLink(core,platform),events=[];
 for(const name of['open','close','error','authError','reAuthRequired','message','message_error','serverRestarting','connection_failed_initial','handlers_cleared'])link.addEventListener(name,(e)=>events.push([name,e.detail]));
 return{link,core,calls,timers,statuses,sockets,refreshes,events,setOpen:(id)=>{openSocket=id;}};
}

test('parseLinkFrame follows the shared envelope vectors',()=>{
 assert.ok(vectors.length>=15);
 for(const v of vectors){const p=parseLinkFrame(v.frame);
  if(v.error){assert.equal(p.type,null,v.frame);assert.equal(p.error,v.error,v.frame);continue;}
  assert.equal(p.type,v.type,v.frame);assert.deepEqual(p.payload,v.payload,v.frame);
  assert.equal(p.errorMessage??null,v.error_message,v.frame);}
});

test('connect executes refresh, open, status and settle commands in order',async()=>{
 const f=fixture({connect:[{op:'status',status:'connecting',error:null},{op:'refresh',refresh:1,reason:'missing_token'}],
  refreshed:[{op:'open',socket:7}],opened:[{op:'status',status:'connected',error:null},{op:'emit',event:'open'},{op:'lifecycle',socket:7,foreground:true,source:'open'},
   {op:'schedule',timer:2,seq:3,delay:25000},{op:'settle',ok:true}]});
 const done=f.link.connect();await tick();
 assert.deepEqual(f.refreshes,['missing_token']);
 assert.deepEqual(f.calls.find(c=>c[0]==='refreshed'),['refreshed',1,REFRESH_OUTCOME.ready,true]);
 assert.equal(f.sockets.length,1);f.setOpen(7);f.sockets[0].open();await done;
 assert.deepEqual(f.statuses,[['connecting',null],['connected',null]]);
 assert.deepEqual(JSON.parse(f.sockets[0].sent[0]),{type:'native_client_lifecycle',payload:{is_foreground:true,client_type:'web',source:'open'}});
 assert.deepEqual(f.timers.map(t=>t.ms),[25000]);assert.ok(f.events.some(e=>e[0]==='open'));
 assert.equal(f.link.isConnected(),true);
});

test('a rejected refresh is reported to the core as a failed refresh',async()=>{
 const f=fixture({connect:[{op:'refresh',refresh:4,reason:'reconnect'}],refreshSession:()=>Promise.reject(new Error('offline'))});
 const warn=console.warn;console.warn=()=>{};try{void f.link.connect().catch(()=>{});await tick();await tick();}finally{console.warn=warn;}
 assert.deepEqual(f.calls.find(c=>c[0]==='refreshed'),['refreshed',4,REFRESH_OUTCOME.failed,false]);
});

test('settle rejects every waiter with the refusal reason',async()=>{
 const f=fixture({connect:[{op:'settle',ok:false,reason:'session_principal_mismatch'}]});
 await assert.rejects(f.link.connect(),(r)=>r==='session_principal_mismatch');
});

test('timers feed the core with kind and sequence; ping and close commands reach the socket',()=>{
 const f=fixture({connect:[{op:'open',socket:1}],opened:[{op:'schedule',timer:2,seq:5,delay:25000}],
  timer:(kind,seq)=>kind===2?[{op:'ping',socket:1},{op:'schedule',timer:3,seq:seq+1,delay:10000}]:[{op:'close',socket:1,code:1000,reason:'Pong timeout - client initiated close'}]});
 void f.link.connect();const s=f.sockets[0];s.open();
 assert.deepEqual(f.timers.map(t=>t.ms),[25000]);f.timers.shift().cb();
 assert.equal(s.sent.at(-1),'{"type":"ping","payload":{}}');
 assert.deepEqual(f.timers.map(t=>t.ms),[10000]);f.timers.shift().cb();
 assert.deepEqual(s.closed,{code:1000,reason:'Pong timeout - client initiated close'});
 assert.equal(s.onclose,null,'a detached socket reports nothing back');
 assert.deepEqual(f.calls.filter(c=>c[0]==='timer').map(c=>c.slice(1)),[[2,5],[3,6]]);
});

test('close events and errors from the socket go to the core with their socket id',()=>{
 const f=fixture({connect:[{op:'open',socket:9}],closed:[{op:'status',status:'reconnecting',error:null},{op:'emit',event:'close',code:1006},{op:'schedule',timer:0,seq:1,delay:1000}]});
 void f.link.connect();const s=f.sockets[0];s.onerror({});s.drop(1006,'',false);
 assert.deepEqual(f.calls.find(c=>c[0]==='errored'),['errored',9]);
 assert.deepEqual(f.calls.find(c=>c[0]==='closed'),['closed',9,1006,'',false]);
 assert.deepEqual(f.events.find(e=>e[0]==='close'),['close',{code:1006}]);
 assert.deepEqual(f.timers.map(t=>t.ms),[1000]);
});

test('re-auth and auth errors become the same CustomEvents as websocketService',()=>{
 const f=fixture({connect:[{op:'emit',event:'reAuthRequired',type:'passkey'},{op:'emit',event:'authError',reason:null},{op:'emit',event:'authError',reason:'Session expired'},{op:'emit',event:'serverRestarting'}]});
 void f.link.connect();
 assert.deepEqual(f.events,[['reAuthRequired',{type:'passkey'}],['authError',null],['authError',{reason:'Session expired'}],['serverRestarting',null]]);
});

test('socket construction failure is an attempt failure, not a stuck attempt',()=>{
 const f=fixture({connect:[{op:'open',socket:3}],createSocket:()=>{throw new Error('bad url');}});
 const error=console.error;console.error=()=>{};try{void f.link.connect().catch(()=>{});}finally{console.error=error;}
 assert.deepEqual(f.calls.filter(c=>c[0]==='errored'||c[0]==='closed'),[['errored',3],['closed',3,1006,'',false]]);
 assert.equal(f.events[0][0],'connection_failed_initial');
});

test('frames dispatch to every routed handler in order and one failure does not stop the rest',async()=>{
 const f=fixture({connect:[{op:'open',socket:1}],frame:()=>0,handlers:(t,ids)=>[...ids].reverse()});
 void f.link.connect();const seen=[];
 const a=(p)=>{seen.push(['a',p]);},b=async(p)=>{seen.push(['b',p]);throw new Error('boom');};
 f.link.on('webhook_chat',a);f.link.on('webhook_chat',b);
 const error=console.error;console.error=()=>{};try{f.sockets[0].message('{"type":"webhook_chat","payload":{"id":1}}');await tick();await tick();}finally{console.error=error;}
 assert.deepEqual(seen,[['b',{id:1}],['a',{id:1}]]);
 assert.deepEqual(f.calls.find(c=>c[0]==='frame'),['frame',1,'webhook_chat',undefined]);
 assert.deepEqual(f.events.find(e=>e[0]==='message'),['message',{type:'webhook_chat',payload:{id:1}}]);
});

test('the serialized lane runs phased-sync handlers one after another',async()=>{
 const f=fixture({connect:[{op:'open',socket:1}],frame:()=>1});
 void f.link.connect();const order=[];let release;const gate=new Promise(r=>release=r);
 f.link.on('phase_1_last_chat_ready',async(p)=>{order.push('start'+p.n);if(p.n===1)await gate;order.push('end'+p.n);});
 f.sockets[0].message('{"type":"phase_1_last_chat_ready","payload":{"n":1}}');f.sockets[0].message('{"type":"phase_1_last_chat_ready","payload":{"n":2}}');
 await tick();assert.deepEqual(order,['start1']);release();await tick();await tick();await tick();
 assert.deepEqual(order,['start1','end1','start2','end2']);
});

test('buffered frames replay to the first late handler, newest kept',async()=>{
 let n=0;const f=fixture({connect:[{op:'open',socket:1}],frame:()=>n++<2?2:3,on:()=>2});
 void f.link.connect();f.link.declareFamily(FAMILY.highlights);
 for(const i of[1,2,3])f.sockets[0].message(JSON.stringify({event:'message_highlight_added',i}));
 const seen=[];f.link.on('message_highlight_added',(p)=>{seen.push(p.i);});await tick();
 assert.deepEqual(seen,[2,3]);assert.deepEqual(f.calls.find(c=>c[0]==='declare_family'),['declare_family',FAMILY.highlights]);
});

test('a zero replay count replays nothing',async()=>{
 const f=fixture({connect:[{op:'open',socket:1}],frame:()=>2,on:()=>0});
 void f.link.connect();f.sockets[0].message('{"type":"webhook_chat","payload":1}');
 const seen=[];f.link.on('webhook_chat',(p)=>{seen.push(p);});await tick();assert.deepEqual(seen,[]);
});

test('frames from a replaced socket are dropped before any event or handler',()=>{
 const f=fixture({connect:[{op:'open',socket:1}],frame:()=>6});
 void f.link.connect();f.link.on('webhook_chat',()=>assert.fail('stale frame dispatched'));
 f.sockets[0].message('{"type":"webhook_chat","payload":1}');assert.equal(f.events.length,0);
});

test('frame-produced link commands are drained and executed',()=>{
 const f=fixture({connect:[{op:'open',socket:1}],frame:()=>0x10|4,drain:[{op:'status',status:'error',error:'Session expired'},{op:'emit',event:'authError',reason:'Session expired'}]});
 void f.link.connect();f.sockets[0].message('{"type":"error","payload":{"message":"Session expired"}}');
 assert.deepEqual(f.calls.find(c=>c[0]==='frame'),['frame',1,'error','Session expired']);
 assert.deepEqual(f.statuses,[['error','Session expired']]);assert.ok(f.events.some(e=>e[0]==='authError'));
});

test('unparseable and untyped frames raise message_error without touching the core',()=>{
 const f=fixture({connect:[{op:'open',socket:1}]});void f.link.connect();
 f.sockets[0].message('not json');f.sockets[0].message('{"x":1}');
 assert.deepEqual(f.events.map(e=>[e[0],e[1].error]),[['message_error','Parsing/handling error'],['message_error','Unknown message structure']]);
 assert.equal(f.calls.some(c=>c[0]==='frame'),false);
});

test('duplicate handler registration is refused like websocketService',()=>{
 const f=fixture({on:(t,id)=>f.calls.filter(c=>c[0]==='on').length>1?-1:0});const h=()=>{};
 const warn=console.warn;const warned=[];console.warn=(m)=>warned.push(m);try{f.link.on('x',h);f.link.on('x',h);}finally{console.warn=warn;}
 assert.equal(warned.length,1);const ids=f.calls.filter(c=>c[0]==='on').map(c=>c[2]);assert.equal(ids[0],ids[1],'one stable id per function');
 f.link.off('x',h);assert.deepEqual(f.calls.at(-1),['off','x',ids[0]]);
 f.link.clearAllHandlers();assert.deepEqual(f.events.at(-1),['handlers_cleared',null]);
});

test('receipt-bound sends refuse a changed connection',async()=>{
 const f=fixture({connect:[{op:'open',socket:1}]});void f.link.connect();f.sockets[0].open();f.setOpen(1);
 const expected=f.link.getConnectionForSend();await f.link.sendMessage('chat_message_added',{a:1},{expectedConnection:expected});
 assert.deepEqual(JSON.parse(f.sockets[0].sent.at(-1)),{type:'chat_message_added',payload:{a:1}});
 await assert.rejects(f.link.sendMessage('chat_message_added',{},{expectedConnection:{}}),(e)=>e.code==='websocket_receipt_connection_changed');
});

test('message types are interned once; overflow falls back to the string path',()=>{
 const f=fixture({connect:[{op:'open',socket:1}],internCap:1,frame:()=>4});void f.link.connect();
 for(const t of['pong','pong','active_chat_set_ack'])f.sockets[0].message(JSON.stringify({type:t}));
 assert.deepEqual(f.calls.filter(c=>c[0]==='frame'),[['frame',1,'pong',undefined],['frame',1,'pong',undefined],['frame',1,'active_chat_set_ack',undefined,'string']]);
});

test('handler mirror follows off and clear',async()=>{
 const f=fixture({connect:[{op:'open',socket:1}],frame:(s,t)=>f.core.handlers(t).length?0:5});void f.link.connect();const seen=[];
 const a=()=>{seen.push('a');},b=()=>{seen.push('b');};f.link.on('webhook_chat',a);f.link.on('webhook_chat',b);f.link.off('webhook_chat',a);
 f.sockets[0].message('{"type":"webhook_chat","payload":1}');await tick();assert.deepEqual(seen,['b']);
 f.link.clearHandlers('webhook_chat');const warn=console.warn;console.warn=()=>{};try{f.sockets[0].message('{"type":"webhook_chat","payload":1}');}finally{console.warn=warn;}
 await tick();assert.deepEqual(seen,['b']);
});

test('foreground recovery discovery is sent only while the page is in the foreground',()=>{
 const f=fixture({connect:[{op:'open',socket:1}],pageForeground:true});void f.link.connect();f.sockets[0].open();f.setOpen(1);
 f.link.requestForegroundRecoveryDiscovery('r1');
 assert.deepEqual(f.calls.find(c=>c[0]==='foreground'),['foreground',true,6]);
 assert.deepEqual(JSON.parse(f.sockets[0].sent.at(-1)),{type:'request_recovery_discovery',payload:{request_id:'r1'}});
 const g=fixture({connect:[{op:'open',socket:1}],pageForeground:false});void g.link.connect();g.sockets[0].open();g.setOpen(1);
 g.link.requestForegroundRecoveryDiscovery();assert.equal(g.sockets[0].sent.length,0);assert.equal(g.calls.some(c=>c[0]==='foreground'),false);
});
