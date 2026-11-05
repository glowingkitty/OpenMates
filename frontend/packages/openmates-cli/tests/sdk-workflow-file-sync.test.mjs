/** Pure extracted facade/DTO cases. No product module/native library is loaded. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
const here=fileURLToPath(import.meta.url);
const privateIndex=here.indexOf('/logs/rust-migration-proposals/');
const require=createRequire(privateIndex<0?import.meta.url:here.slice(0,privateIndex)+'/frontend/packages/openmates-cli/package.json');
const ts=require('typescript');
const path=fileURLToPath(new URL('../src/sdkSession.ts',import.meta.url));
const source=readFileSync(path,'utf8');
const tree=ts.createSourceFile(path,source,ts.ScriptTarget.Latest,true);
const fn=name=>tree.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name).getText(tree);
const projects=tree.statements.find(n=>ts.isClassDeclaration(n)&&n.name.text==='SessionProjects');
const method=projects.members.find(n=>n.name?.getText(tree)==='syncWorkflowFiles').getText(tree);
const code=`class SessionClientError extends Error {constructor(code,message){super(message);this.code=code;}}
const NATIVE_PREPARATION=Symbol('native preparation');
${fn('preparedNative')}
${fn('workJson')}
${fn('workflowFileSyncJson')}
class NewProjects {constructor(native){this.native=native;this.invoke=async op=>op();}
${method}
}
globalThis.API=NewProjects;`;
const js=ts.transpileModule(code,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText;
const context={};vm.runInNewContext(js,context);const calls=[];const api=new context.API({projectsSyncWorkflowFiles:async(...args)=>{calls.push(args);return '[{"project_id":"actual","status":"pending"}]';}});
// Construct data within its source realm; JSON fixtures cannot smuggle callbacks.
context.api=api;
await vm.runInNewContext(`api.syncWorkflowFiles('original','version',{approvedPaths:['folder/a.workflow.yml'],sourceChat:'chat'},{personal:true})`,context).catch(error=>{throw error;});
assert.deepEqual(JSON.parse(calls[0][0]),{workflow_id:'original',expected_version:'version',approved_paths:['folder/a.workflow.yml'],source_chat:'chat'});
assert.deepEqual(JSON.parse(calls[0][1]),{personal:true});
for(const expression of [`{workflowId:'foreign'}`,`{expectedVersion:'foreign'}`,`{authenticated:true}`,`{serialize:()=>''}`,`Object.defineProperty({},'approvedPaths',{get(){throw Error('caller callback')},enumerable:true})`,`{approvedPaths:Object.assign(['safe/a.workflow.yml'],{[Symbol.iterator]:function*(){throw Error('caller iterator')}})}`,`{approvedPaths:Object.defineProperty(new Array(1),'0',{get(){throw Error('caller getter')},enumerable:true})}`]){
 await assert.rejects(vm.runInNewContext(`api.syncWorkflowFiles('original','version',${expression},{personal:true})`,context),error=>error.code==='invalid_argument');
}
assert.equal(calls.length,1);
await vm.runInNewContext(`api.syncWorkflowFiles('original','version',{}, {personal:true})`,context);
assert.deepEqual(JSON.parse(calls[1][0]),{workflow_id:'original',expected_version:'version'});
console.log('9 pure facade cases passed; no native SDK/runtime IO');
