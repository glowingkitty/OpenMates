/** Actual public npm API-key chat reads. No account/profile discovery. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
if(!process.argv.includes('--case')) {
 const child=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/runners/sdk-api-key-chats.py','--language','npm',...process.argv.slice(2)],{cwd:ROOT,stdio:'inherit'});
 process.exitCode=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',(code,signal)=>resolve(signal?1:code??1));});
} else {
 const {OpenMates,OpenMatesApiError,OpenMatesConfigError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
 const raw=readFileSync(0);assert.ok(raw.length<=1024*1024);const c=JSON.parse(raw),url=new URL(c.endpoint);
 assert.equal(url.protocol,'http:');assert.equal(url.hostname,'127.0.0.1');assert.ok(url.port);assert.equal(url.pathname,'/');
 for(const field of ['search','hash','username','password'])assert.equal(url[field],'');
 assert.equal(c.api_key,'sk-api-chatOwnerA.localSetupSuffix');assert.equal(c.device_id,'synthetic-chat-device');
 const client=new OpenMates({apiKey:c.api_key,apiUrl:c.endpoint,deviceId:c.device_id});
 const v=c.vector,a=v.arguments;
 let result;
 try {
  let value;
  if(v.operation==='list')value=await client.chats.list({limit:a.limit,offset:a.offset});
  else if(v.operation==='search')value=await client.chats.search(a.query,{limit:a.limit,offset:a.offset});
  else {assert.equal(v.operation,'load');value=await client.chats.load(a.chat_id);}
  result={ok:true,value};
 } catch(error) {
  if(error instanceof OpenMatesConfigError)result={ok:false,error:'invalid'};
  else {
   assert.ok(error instanceof OpenMatesApiError);const status=error.status;
   result={ok:false,error:({401:'authentication',403:'forbidden',409:'conflict'})[status]??([400,404,410,422].includes(status)?'invalid':status===429||status>=500?'offline':'protocol')};
  }
 }
 console.log(JSON.stringify(result));
}
