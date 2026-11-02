/** Pure diagnostic helper/actual main extraction; no SDK import, socket or child.
 * Fixed synthetic failures contain canary private values solely in RAM.
 * Production runner assertions and lifecycle remain untouched and UNRUN.
 * This exercises only diagnostic serialization and its failure result shape.
 * No raw message, stack, content, ID or credential is copied to a report.
 */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),crypto=require('node:crypto');
const dir=__dirname,source=fs.readFileSync(path.join(dir,'runners/session-chat-first-page-continuation.mjs'),'utf8');
const helper=source.slice(source.indexOf('// Closed diagnostic projection only.'),source.indexOf('// End closed diagnostic projection.'));
const canary='PRIVATE_FIXTURE_CONTENT_COOKIE_NEVER_EXPORT';
const scope={Set,JSON};vm.createContext(scope);vm.runInContext(helper+'\nglobalThis.closed=closedDiagnostic;globalThis.phase=value=>{diagnosticPhase=value;};',scope);
let checks=0;const check=(condition)=>{assert.ok(condition);checks++;};
for(const [error,code]of [[Object.assign(new Error(canary),{code:'ERR_ASSERTION'}),'assertion'],[{code:'cancelled',message:canary},'cancelled'],[new Error(JSON.stringify({code:'protocol',message:canary})),'protocol'],[new Error(canary),'unclassified'],[new Error('owned operation deadline'),'timeout'],[new Error('synthetic callback failed'),'callback'],[new Error('synthetic capacity IO error'),'storage_io'],[{code:'__proto__',message:canary},'unclassified']]){
 scope.phase('callback');const result=scope.closed(error,'cold-uuid');check(result.errorCode===code);check(result.sourceCoordinate==='runner.callback');check(!JSON.stringify(result).includes(canary));check(Object.keys(result).join(',')==='vectorId,phase,errorCode,sourceCoordinate');
}
scope.phase(canary);check(scope.closed(new Error(canary),'cold-uuid').phase==='suite');check(scope.closed(new Error(canary),'cold-uuid').sourceCoordinate==='runner.suite');
const fixture=JSON.parse(fs.readFileSync(path.join(dir,'fixtures/session-chat-first-page-continuation.json')));
const raw=Buffer.from(JSON.stringify(fixture)),suite=fixture.capabilities['session.chat-first-page-continuation.v1'];
const main=source.slice(source.indexOf('async function main(){'),source.indexOf('\nmain().catch('));
(async()=>{
 for(const failingAt of [0,5,null]){
  const output=[];let calls=0;
  const context={assert,path,JSON,readFileSync:()=>raw,CAP:'session.chat-first-page-continuation.v1',vectors:suite.vectors.map(({id,mode})=>[id,mode]),hash:value=>crypto.createHash('sha256').update(value).digest('hex'),console:{log:value=>output.push(value)},process:{argv:['node','runner','--capability','session.chat-first-page-continuation.v1','--fixture','synthetic.json'],exitCode:0},vector:async(_suite,entry)=>{if(calls++===failingAt)throw Object.assign(new Error(canary),{code:'ERR_ASSERTION'});return{id:entry.id,status:'passed'};}};
  vm.createContext(context);context.rawFixture=raw.toString();vm.runInContext('globalThis.vectors=JSON.parse(rawFixture).capabilities[CAP].vectors.map(({id,mode})=>[id,mode]);',context);vm.runInContext(helper+'\n'+main+'\nglobalThis.run=main;',context);await context.run();const report=JSON.parse(output[0]);check(output.length===1);check(!output[0].includes(canary));check(report.fixtureSha256===context.hash(raw));
  if(failingAt===null){check(report.status==='passed'&&report.results.length===16&&calls===16);check(context.process.exitCode===0);}
  else{check(report.status==='failed'&&context.process.exitCode===1);check(report.results.length===failingAt+1);check(report.results.at(-1).id===suite.vectors[failingAt].id);check(report.results.at(-1).status==='failed');check(report.results.slice(0,-1).every(row=>row.status==='passed'));check(report.diagnostic.vectorId===suite.vectors[failingAt].id);check(report.diagnostic.errorCode==='assertion');}
 }
 console.log(JSON.stringify({status:'passed',checks,SDKOrProductExecuted:false,childrenExecuted:0}));
})().catch(error=>{process.stderr.write('closed diagnostic synthetic checks failed:'+error.name+':'+String(error.stack).split('\n').find(line=>line.includes('checks.cjs:'))+'\n');process.exitCode=1;});
