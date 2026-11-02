/** Actual public npm API-key embeds methods. No account/profile discovery. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
if(!process.argv.includes('--case')) {
 const child=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/runners/sdk-api-key-embeds.py','--language','npm',...process.argv.slice(2)],{cwd:ROOT,stdio:'inherit'});
 const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',(code,signal)=>resolve(signal?1:code??1));});
 process.exitCode=code;
} else {
 const {OpenMates,OpenMatesApiError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
 const raw=readFileSync(0);assert.ok(raw.length<=1024*1024);const c=JSON.parse(raw),url=new URL(c.endpoint);
 assert.equal(url.protocol,'http:');assert.equal(url.hostname,'127.0.0.1');assert.ok(url.port);assert.equal(url.pathname,'/');assert.equal(url.search,'');assert.equal(url.hash,'');
 assert.equal(c.device_id,'synthetic-embed-device');assert.ok(['sk-api-embedOwnerA.localSetupSuffix','sk-api-embedOwnerB.localSetupSuffix'].includes(c.api_key));
 const client=new OpenMates({apiKey:c.api_key,apiUrl:c.endpoint,deviceId:c.device_id});
 const v=c.vector;
 let result;
 try {
  let value;
  if(v.operation==='show')value=await client.embeds.show(v.embed_id);
  else if(v.operation==='versions')value=await client.embeds.versions(v.embed_id);
  else {assert.equal(v.operation,'version');value=await client.embeds.version(v.embed_id,v.version);}
  result={ok:true,value};
 } catch(error) {
  assert.ok(error instanceof OpenMatesApiError);const status=error.status;
  const code=({401:'authentication',403:'forbidden',409:'conflict'})[status]??([400,404,410,422].includes(status)?'invalid':status===429||status>=500?'offline':'protocol');
  result={ok:false,error:code,http_status:status};
 }
 console.log(JSON.stringify(result));
}
