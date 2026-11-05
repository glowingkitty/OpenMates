// contract-test-file: tooling
// Exact maintained facade AST, fake native only. This is not Rust enforcement proof.
const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path'), vm=require('node:vm'), ts=require('typescript');
const root=path.resolve(__dirname,'../..');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/session-cache-settlement-wrappers.json'),'utf8'));
function classes(){
 const values={module:{exports:{}},JSON,Number,Error,Object,FinalizationRegistry};
 let file=path.join(root,'frontend/packages/openmates-cli/src/sdkSession.ts');
 let text=fs.readFileSync(file,'utf8'),tree=ts.createSourceFile(file,text,ts.ScriptTarget.Latest,true);
 let nodes=tree.statements.filter(n=>(ts.isClassDeclaration(n)||ts.isFunctionDeclaration(n))&&['SessionClient','SessionClientError','failure'].includes(n.name?.text));
 assert.equal(nodes.length,3);
 let code=nodes.map(n=>n.getText(tree).replace(/^export /,'')).join('\n');
 file=path.join(root,'frontend/packages/openmates-cli/src/sdkEssential.ts');
 text=fs.readFileSync(file,'utf8');tree=ts.createSourceFile(file,text,ts.ScriptTarget.Latest,true);
 nodes=tree.statements.filter(n=>ts.isClassDeclaration(n)&&n.name?.text==='SessionChatMonitor');assert.equal(nodes.length,1);
 code+='\nconst abandoned=new FinalizationRegistry(()=>{});\n'+nodes[0].getText(tree).replace(/^export /,'')+'\nmodule.exports={SessionClient,SessionClientError,SessionChatMonitor};';
 vm.runInNewContext(ts.transpileModule(code,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,values);
 return values.module.exports;
}
function client(){
 const api=classes(),c=Object.create(api.SessionClient.prototype),calls=[];
 c.essentialEpoch=0;
 c.native={cacheChatStage:async(...args)=>{calls.push(['stage',args]);return JSON.stringify(fixture.stage);},cacheChatCommit:async(...args)=>{calls.push(['commit',args]);return JSON.stringify(fixture.publications[1]);},cacheChatDiscard:(...args)=>calls.push(['discard',args]),chatMonitorStagePreferCache:async(...args)=>{calls.push(['monitor_stage_prefer_cache',args]);return JSON.stringify(fixture.stage);},chatMonitorDiscard:(...args)=>calls.push(['monitor_discard',args]),chatMonitorClose:(...args)=>calls.push(['monitor_close',args])};
 return {c,api,calls};
}
test('stage preserves exact opaque bytes without automatic ACK',async()=>{
 const{c,calls}=client();assert.deepEqual(await c.cacheChatStage('synthetic-chat',{includeSecrets:true}),fixture.stage);
 assert.deepEqual(calls,[['stage',['synthetic-chat',true]]]);await c.cacheChatDiscard('synthetic-stage');assert.deepEqual(calls.at(-1),['discard',['synthetic-stage']]);
});
for(const publication of fixture.publications)test('source and actual receipt forwarding '+publication.source,async()=>{
 const{c,calls}=client();c.native.cacheChatCommit=async(...args)=>{calls.push(['commit',args]);return JSON.stringify(publication);};
 assert.deepEqual(await c.cacheChatCommit('synthetic-stage',fixture.receipt),publication);
 assert.deepEqual(calls,[['commit',['synthetic-stage',JSON.stringify(fixture.receipt)]]]);
});
for(const error of fixture.native_errors)test('native refusal propagated without publication '+error.id,async()=>{
 const{c,calls}=client();c.native.cacheChatCommit=async(...args)=>{calls.push(['commit',args]);throw new Error(JSON.stringify(error));};
 await assert.rejects(c.cacheChatCommit('synthetic-stage',fixture.receipt),e=>e.code===error.code);assert.deepEqual(calls.map(x=>x[0]),['commit']);
});
test('consent refusal makes no native call',async()=>{const{c,calls}=client();await assert.rejects(c.cacheChatStage('synthetic-chat',{includeSecrets:false}),e=>e.code==='invalid_argument');assert.deepEqual(calls,[]);});
for(const monitor of [false,true])test('stale epoch drops exact stage '+monitor,async()=>{
 const{c,api,calls}=client();let release;const gate=new Promise(resolve=>{release=resolve;});
 c.native.cacheChatStage=async()=>{await gate;return JSON.stringify(fixture.stage);};c.native.chatMonitorStagePreferCache=c.native.cacheChatStage;
 const m=monitor?new api.SessionChatMonitor(c.native,c.essentialInvoke.bind(c),()=>c.essentialEpoch===0,'synthetic-monitor',fixture.stage.scope):null;
 const ticket=m?m.stageRefreshPreferCache({includeSecrets:true,selectedChatId:'synthetic-chat'}):c.cacheChatStage('synthetic-chat',{includeSecrets:true});
 c.essentialEpoch++;release();await assert.rejects(ticket,e=>e.code==='cancelled');
 assert.deepEqual(calls,[monitor?['monitor_discard',['synthetic-monitor','synthetic-stage']]:['discard',['synthetic-stage']]]);
 if(m)await m.close();
});
test('monitor policy forwards selected ID without ACK',async()=>{
 const{c,api,calls}=client();const m=new api.SessionChatMonitor(c.native,c.essentialInvoke.bind(c),()=>true,'synthetic-monitor',fixture.stage.scope);
 assert.deepEqual(await m.stageRefreshPreferCache({includeSecrets:true,selectedChatId:'synthetic-chat'}),fixture.stage);
 assert.deepEqual(calls,[['monitor_stage_prefer_cache',['synthetic-monitor',true,'synthetic-chat']]]);await m.close();
});
for(const error of fixture.native_errors.slice(0,2))test('stage refusal is not a cached success '+error.id,async()=>{
 const{c,calls}=client();c.native.cacheChatStage=async(...args)=>{calls.push(['stage',args]);throw new Error(JSON.stringify(error));};
 await assert.rejects(c.cacheChatStage('synthetic-chat',{includeSecrets:true}),e=>e.code===error.code);assert.deepEqual(calls.map(x=>x[0]),['stage']);
});
test('commit output suppressed after authority changes during await',async()=>{
 const{c}=client();let release;const gate=new Promise(resolve=>{release=resolve;});c.native.cacheChatCommit=async()=>{await gate;return JSON.stringify(fixture.publications[1]);};
 const task=c.cacheChatCommit('synthetic-stage',fixture.receipt);c.essentialEpoch++;release();await assert.rejects(task,e=>e.code==='cancelled');
});
