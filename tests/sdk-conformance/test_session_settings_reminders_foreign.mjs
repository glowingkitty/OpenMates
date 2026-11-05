/** Pure actual-adapter extraction with inert native doubles; no SDK/native imports. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
const root=fileURLToPath(new URL('../../',import.meta.url));
const require=createRequire(root+'/frontend/packages/openmates-cli/package.json');
const ts=require('typescript');
const source=readFileSync(root+'/frontend/packages/openmates-cli/src/sdkSession.ts','utf8');
const tree=ts.createSourceFile('adapter.ts',source,ts.ScriptTarget.Latest,true);
const names=new Set(['SessionAccount','SessionClientError','SessionSettingsReadError','failure','preparedNative']);
const variables=new Set(['NATIVE_PREPARATION','addAbortListener','removeAbortListener','abortState','appsAborted']);
const nodes=tree.statements.filter(node=>(node.name&&names.has(node.name.text))||(ts.isVariableStatement(node)&&node.declarationList.declarations.some(d=>variables.has(d.name.getText(tree)))));
assert.equal(nodes.filter(n=>n.name&&names.has(n.name.text)).length,names.size);
const code=ts.transpileModule(nodes.map(node=>node.getText(tree)).join('\n'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const context={exports:{},Error,AbortSignal,EventTarget,Promise,JSON,Object,Symbol};
vm.runInNewContext(code+'\nexports.fixturePreparation = NATIVE_PREPARATION;',context);
const {SessionAccount,SessionSettingsReadError,fixturePreparation}=context.exports;
const invoke=async operation=>{const prepare=Object.getOwnPropertyDescriptor(operation,fixturePreparation)?.value;return typeof prepare==='function'?prepare()():operation();};
function op(value){
 const state={cancelled:false,cancelCount:0,reads:0,discarded:0,released:0};
 const output={releaseJson(){state.released++;if(state.cancelled)throw new Error(JSON.stringify({code:'cancelled',message:'synthetic original cancellation',http_status:null}));return JSON.stringify(value);},discard(){state.discarded++;}};
 return {state,output,cancel(){state.cancelled=true;state.cancelCount++;},async run(){if(state.cancelled)throw new Error(JSON.stringify({code:'cancelled',message:'synthetic original cancellation',http_status:null}));state.reads++;return output;}};
}
let passed=0;
{
 const value=JSON.parse('{"encrypted":"opaque","unknown":{"__proto__":{"inert":true},"nested":[true,1,null]}}'),a=op(value);
 const api=new SessionAccount({accountRemindersOpen:()=>a},invoke);
 assert.deepEqual(await api.reminders(),value);assert.equal(a.state.discarded,1);assert.equal(a.state.cancelled,true);passed++;
}
{
 const a=op(null),controller=new AbortController();controller.abort();
 const api=new SessionAccount({accountRemindersOpen:()=>a},invoke);
 await assert.rejects(()=>api.reminders({signal:controller.signal}),error=>error instanceof SessionSettingsReadError&&error.code==='cancelled'&&error.httpStatus===null);
 assert.equal(a.state.reads,0);passed++;
}
{
 const a=op('private-A'),b=op('healthy-B'),controller=new AbortController();
 a.run=async()=>{controller.abort();return a.output;};
 const operations=[a,b],api=new SessionAccount({accountRemindersOpen:()=>operations.shift()},invoke);
 await assert.rejects(()=>api.reminders({signal:controller.signal}),error=>error instanceof SessionSettingsReadError&&error.code==='cancelled');
 assert.equal(a.state.discarded,1);assert.equal(b.state.cancelled,false);
 assert.equal(await api.reminders(),'healthy-B');passed++;
}
{
 const a=op(null),api=new SessionAccount({accountRemindersOpen:()=>a},invoke);
 a.run=async()=>{throw new Error(JSON.stringify({code:'forbidden',message:'Settings GET failed with HTTP 403',http_status:403}));};
 await assert.rejects(()=>api.reminders(),error=>error instanceof SessionSettingsReadError&&error.httpStatus===403&&error.message==='Settings GET failed with HTTP 403'&&error.code==='forbidden');passed++;
}
{
 const a=op(null),api=new SessionAccount({accountRemindersOpen:()=>a},invoke);
 a.run=async()=>{throw new Error(JSON.stringify({code:'expired',message:'original owner denial',http_status:null}));};
 await assert.rejects(()=>api.reminders(),error=>error instanceof SessionSettingsReadError&&error.httpStatus===null&&error.message==='original owner denial');passed++;
}
{
 const a=op('returned'),controller=new AbortController(),api=new SessionAccount({accountRemindersOpen:()=>a},invoke);
 assert.equal(await api.reminders({signal:controller.signal}),'returned');
 const cancellations=a.state.cancelCount;controller.abort();assert.equal(a.state.cancelCount,cancellations,'listener retired with only original operation');passed++;
}
{
 const value=JSON.parse('{"z":3,"a":2,"é":4}'),a=op(value),api=new SessionAccount({accountRemindersOpen:()=>a},invoke);
 assert.equal(JSON.stringify(await api.reminders()),'{"z":3,"a":2,"é":4}');passed++;
}
{
 const a=op(null),api=new SessionAccount({accountRemindersOpen:()=>a},invoke);
 a.run=async()=>{throw new Error(JSON.stringify({code:'protocol',message:'The service returned an invalid response.',http_status:null}));};
 await assert.rejects(()=>api.reminders(),error=>error instanceof SessionSettingsReadError&&error.code==='protocol'&&error.httpStatus===null&&error.message==='The service returned an invalid response.');
 assert.equal(a.state.released,0,'typed protocol refusal cannot become an empty success');passed++;
}
{
 const a=op(null),api=new SessionAccount({accountRemindersOpen:()=>a},invoke);
 const message='The settings response exceeds the supported JSON limits or representation.';
 a.run=async()=>{throw new Error(JSON.stringify({code:'unavailable',message,http_status:null}));};
 await assert.rejects(()=>api.reminders(),error=>error instanceof SessionSettingsReadError&&error.code==='unavailable'&&error.httpStatus===null&&error.message===message);
 assert.equal(a.state.released,0,'unsupported JSON refusal cannot become an empty success');passed++;
}
console.log(JSON.stringify({kind:'pure actual foreign adapter with inert native doubles',passed,SDKImported:false,network:false,clockSleep:false}));
