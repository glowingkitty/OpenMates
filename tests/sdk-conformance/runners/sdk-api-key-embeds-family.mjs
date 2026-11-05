/** Actual public npm API-key embeds methods. No account/profile discovery. */
// contract-test-file: tooling
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
if(!process.argv.includes('--case')) {
 const child=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/runners/sdk-api-key-embeds-family.py','--language','npm',...process.argv.slice(2)],{cwd:ROOT,stdio:'inherit'});
 const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',(code,signal)=>resolve(signal?1:code??1));});
 process.exitCode=code;
} else {
 const {OpenMates,OpenMatesApiError,OpenMatesConfigError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
 const raw=readFileSync(0);assert.ok(raw.length<=1024*1024);const c=JSON.parse(raw),url=new URL(c.endpoint);
 assert.equal(url.protocol,'http:');assert.equal(url.hostname,'127.0.0.1');assert.ok(url.port);assert.equal(url.pathname,'/');assert.equal(url.search,'');assert.equal(url.hash,'');
 assert.equal(c.device_id,'synthetic-embed-device');assert.ok(['sk-api-embedOwnerA.localSetupSuffix','sk-api-embedOwnerB.localSetupSuffix'].includes(c.api_key));
 const client=new OpenMates({apiKey:c.api_key,apiUrl:c.endpoint,deviceId:c.device_id});
 const v=c.vector;
 let result;
 try {
  let value;
  if(v.operation==='restore_version')value=await client.embeds.restoreVersion(v.embed_id,v.version,{confirmed:v.confirmed??false});
  else if(v.operation==='preview_start')value=await client.embeds.preview.start(v.embed_id,{chatId:v.chat_id,wait:v.wait??false,timeoutMs:v.local_timeout?0:120000,sharedContext:v.options?.shared_context,requestedRuntime:v.options?.requested_runtime,sourceMessageId:v.options?.source_message_id});
  else if(v.operation==='preview_status')value=await client.embeds.preview.status(v.session_id);
  else if(v.operation==='preview_open')value=await client.embeds.preview.open(v.session_id);
  else if(v.operation==='preview_stop')value=await client.embeds.preview.stop(v.session_id);
  else if(v.operation==='share')value=await client.embeds.share(v.embed_id,{expires:v.expires,password:v.password});
  else if(v.operation==='add_to_project')value=await client.embeds.addToProject(v.embed_id,v.project_id,{folder:v.folder});
  else {assert.equal(v.operation,'remove_from_project');const raw=await client.embeds.removeFromProject(v.embed_id,v.project_id);value={deleted:raw.deleted,deleted_count:raw.deletedCount};}
  result={ok:true,value};
 } catch(error) {
  if(error instanceof OpenMatesConfigError) {console.log(JSON.stringify({ok:false,error:v.wrong_hash?"key-unavailable":"invalid"}));process.exit(0);}
  assert.ok(error instanceof OpenMatesApiError);const status=error.status;
  const code=(status===408&&v.local_timeout?'preview-timeout':undefined)??({401:'authentication',403:'forbidden',409:'conflict'})[status]??([400,404,410,422].includes(status)?'invalid':status===429||status>=500?'offline':'protocol');
  result={ok:false,error:code,http_status:status,...(code==='preview-timeout'?{timeout_source:'local',semantic_status:408,http_observed:false}:{})};
 }
 console.log(JSON.stringify(result));
}
