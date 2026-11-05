/** Actual public npm API-key history methods. No account/profile discovery. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
if(!process.argv.includes('--case')) {
 const child=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/runners/sdk-api-key-history.py','--language','npm',...process.argv.slice(2)],{cwd:ROOT,stdio:'inherit'});
 const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',(code,signal)=>resolve(signal?1:code??1));});
 process.exitCode=code;
} else {
 const {OpenMates,OpenMatesApiError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
 const raw=readFileSync(0);assert.ok(raw.length<=1024*1024);const c=JSON.parse(raw),url=new URL(c.endpoint);
 assert.equal(url.protocol,'http:');assert.equal(url.hostname,'127.0.0.1');assert.ok(url.port);assert.equal(url.pathname,'/');assert.equal(url.search,'');assert.equal(url.hash,'');
 assert.equal(c.device_id,'synthetic-history-device');assert.ok(['sk-api-historyOwnerA.localSetupSuffix','sk-api-historyOwnerB.localSetupSuffix'].includes(c.api_key));
 const client=new OpenMates({apiKey:c.api_key,apiUrl:c.endpoint,deviceId:c.device_id});
 const v=c.vector;
 let result;
 try {
  let value;
  if(v.operation==='list')value=await client.history.list({objectType:v.filters.object_type,objectId:v.filters.object_id,limit:v.filters.limit});
  else if(v.operation==='show')value=await client.history.show(v.change_set_id);
  else {assert.equal(v.operation,'undo');value=await client.history.undo(v.change_set_id);}
  result={ok:true,value};
 } catch(error) {
  assert.ok(error instanceof OpenMatesApiError);const status=error.status;
  const code=({401:'authentication',403:'forbidden',409:'conflict'})[status]??([400,404,410,422].includes(status)?'invalid':status===429||status>=500?'offline':'protocol');
  result={ok:false,error:code,http_status:status};
 }
 console.log(JSON.stringify(result));
}
