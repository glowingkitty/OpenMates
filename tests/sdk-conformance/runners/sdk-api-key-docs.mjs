/** Actual npm docs methods; developer-only harness, never CLI/profile execution. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {performance} from 'node:perf_hooks';
import {fileURLToPath} from 'node:url';
// BEGIN CLOSED NPM DOCS DIAGNOSTIC
const DOCS_CHILD_STAGES=Object.freeze(['sdk_import','input_read','input_decode','input_admission','client_constructor','invoke','error_mapping','emit_result','unclassified']);
const DOCS_CHILD_ERRORS=Object.freeze(['assertion','module_not_found','module_export_missing','unsupported_ts_syntax','syntax','type','reference','sdk_config','sdk_api','unclassified']);
function docsError(error){
 try{
  const own=(v,k)=>{const d=Object.getOwnPropertyDescriptor(v,k);return d&&Object.hasOwn(d,'value')?d.value:undefined;};
  if(error===null||!['object','function'].includes(typeof error))return 'unclassified';
  const code=own(error,'code'),prototype=Object.getPrototypeOf(error),name=own(error,'name')??(prototype===null?undefined:own(prototype,'name'));
  if(code==='ERR_ASSERTION'||name==='AssertionError')return 'assertion';
  if(code==='ERR_MODULE_NOT_FOUND'||code==='MODULE_NOT_FOUND')return 'module_not_found';
  if(code==='ERR_PACKAGE_PATH_NOT_EXPORTED')return 'module_export_missing';
  if(code==='ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX')return 'unsupported_ts_syntax';
  if(name==='SyntaxError')return 'syntax';if(name==='TypeError')return 'type';if(name==='ReferenceError')return 'reference';
  if(name==='OpenMatesConfigError')return 'sdk_config';if(name==='OpenMatesApiError')return 'sdk_api';
 }catch{}
 return 'unclassified';
}
function docsLine(stage,error){return `npm docs diagnostic: stage=${DOCS_CHILD_STAGES.includes(stage)?stage:'unclassified'};error=${DOCS_CHILD_ERRORS.includes(error)?error:'unclassified'}\n`;}
// END CLOSED NPM DOCS DIAGNOSTIC
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
if(!process.argv.includes('--case')){
 const child=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/runners/sdk-api-key-docs.py','--language','npm',...process.argv.slice(2)],{cwd:ROOT,stdio:'inherit'});
 process.exitCode=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',(code,signal)=>resolve(signal?1:code??1));});
}else{
 let stage='sdk_import';try{
 const {OpenMates,OpenMatesApiError,OpenMatesConfigError,OpenMatesInvalidInputError}=await import(new URL('../../../frontend/packages/openmates-cli/dist/sdk-entry.js',import.meta.url));
 stage='input_read';const raw=readFileSync(0);assert.ok(raw.length<=1024*1024);stage='input_decode';const c=JSON.parse(raw),u=new URL(c.endpoint),v=c.vector;stage='input_admission';
 assert.equal(u.protocol,'http:');assert.equal(u.hostname,'127.0.0.1');assert.ok(u.port);assert.equal(u.pathname,'/');assert.equal(u.search,'');assert.equal(u.hash,'');assert.equal(u.username,'');assert.equal(u.password,'');
 assert.equal(c.api_key,'sk-api-docsOwnerA.localSetupSuffix');assert.equal(c.device_id,'synthetic-docs-device');assert.ok([1,1024].includes(c.iterations??1));
 stage='client_constructor';const client=new OpenMates({apiKey:v.anonymous?undefined:c.api_key,anonymous:v.anonymous,apiUrl:c.endpoint,deviceId:c.device_id});
 const invoke=()=>v.operation==='list'?client.docs.list():v.operation==='search'?client.docs.search(v.query):v.operation==='show'?client.docs.show(v.slug):v.operation==='download'?client.docs.download(v.slug):assert.fail('docs operation');
 const ticks=()=>{const f=readFileSync('/proc/self/stat','utf8').split(') ')[1].split(/\s+/);return Number(f[11])+Number(f[12]);};
 let result;
 try{stage='invoke';const start=ticks(),wall=performance.now();let value;for(let i=0;i<(c.iterations??1);i++)value=await invoke();const cpu=ticks()-start,elapsed=performance.now()-wall;result={ok:true,value};if(c.iterations>1)result.performance={iterations:c.iterations,cpuTicks:cpu,wallMs:elapsed};}
 catch(e){stage='error_mapping';if(e instanceof OpenMatesConfigError)result={ok:false,error:'authentication'};else if(e instanceof OpenMatesInvalidInputError)result={ok:false,error:'invalid'};else{assert.ok(e instanceof OpenMatesApiError);const n=e.status;result={ok:false,error:({401:'authentication',403:'forbidden',409:'conflict'})[n]??([400,404,410,422].includes(n)?'invalid':n===429||n>=500?'offline':'protocol'),http_status:n};}}
 stage='emit_result';console.log(JSON.stringify(result));
 }catch(error){process.stderr.write(docsLine(stage,docsError(error)));process.exitCode=1;}
}
