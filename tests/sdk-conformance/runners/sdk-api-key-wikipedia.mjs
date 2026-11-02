/** Actual npm wikipedia methods; developer-only harness, never CLI/profile execution. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {performance} from 'node:perf_hooks';
import {fileURLToPath} from 'node:url';
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
if(!process.argv.includes('--case')){
 const child=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/runners/sdk-api-key-wikipedia.py','--language','npm',...process.argv.slice(2)],{cwd:ROOT,stdio:'inherit'});
 process.exitCode=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',(code,signal)=>resolve(signal?1:code??1));});
}else{
 const {OpenMates,OpenMatesApiError,OpenMatesConfigError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
 const raw=readFileSync(0);assert.ok(raw.length<=1024*1024);const c=JSON.parse(raw),u=new URL(c.endpoint),v=c.vector;
 assert.equal(u.protocol,'http:');assert.equal(u.hostname,'127.0.0.1');assert.ok(u.port);assert.equal(u.pathname,'/');assert.equal(u.search,'');assert.equal(u.hash,'');assert.equal(u.username,'');assert.equal(u.password,'');
 assert.equal(c.api_key,'sk-api-wikipediaOwnerA.localSetupSuffix');assert.equal(c.device_id,'synthetic-wikipedia-device');assert.ok([1,1024].includes(c.iterations??1));
 const client=new OpenMates({apiKey:v.anonymous?undefined:c.api_key,anonymous:v.anonymous,apiUrl:c.endpoint,deviceId:c.device_id});
 const options={language:v.language??undefined};
 const invoke=()=>v.operation==='search'?client.wikipedia.search(v.query,{...options,limit:v.limit??undefined}):v.operation==='summary'?client.wikipedia.summary(v.title,options):v.operation==='learning'?client.wikipedia.learning(v.title,options):v.operation==='article'?client.wikipedia.article(v.title,options):assert.fail('wikipedia operation');
 const ticks=()=>{const f=readFileSync('/proc/self/stat','utf8').split(') ')[1].split(/\s+/);return Number(f[11])+Number(f[12]);};
 let result;
 try{const start=ticks(),wall=performance.now();let value;for(let i=0;i<(c.iterations??1);i++)value=await invoke();const cpu=ticks()-start,elapsed=performance.now()-wall;result={ok:true,value};if(c.iterations>1)result.performance={iterations:c.iterations,cpuTicks:cpu,wallMs:elapsed};}
 catch(e){if(e instanceof OpenMatesConfigError)result={ok:false,error:'authentication'};else{assert.ok(e instanceof OpenMatesApiError);const n=e.status;result={ok:false,error:({401:'authentication',403:'forbidden',409:'conflict'})[n]??([400,404,410,422].includes(n)?'invalid':n===429||n>=500?'offline':'protocol'),http_status:n};}}
 console.log(JSON.stringify(result));
}
