// contract-test-file: tooling
// Actual direct-library benchmark worker; no product endpoints or CLI invocation.
import assert from 'node:assert/strict';
import {register} from 'node:module';
import {createInterface} from 'node:readline';
register(new URL('../../../frontend/packages/openmates-cli/tests/loader.mjs',import.meta.url));
const {OpenMates,OpenMatesApiError,OpenMatesConfigError}=await import('../../../frontend/packages/openmates-cli/src/sdk.ts');
async function invoke(c) {
 const client=new OpenMates({apiKey:c.api_key,apiUrl:c.endpoint,deviceId:c.device_id});
 const v=c.vector;
 let result;
 try {
  let value;
  if(v.operation==='show')value=await client.embeds.show(v.embed_id);
  else if(v.operation==='versions')value=await client.embeds.versions(v.embed_id);
  else if(v.operation==='version')value=await client.embeds.version(v.embed_id,v.version);
  else if(v.operation==='restore_version')value=await client.embeds.restoreVersion(v.embed_id,v.version,{confirmed:v.confirmed??false});
  else if(v.operation==='preview_start')value=await client.embeds.preview.start(v.embed_id,{chatId:v.chat_id,wait:v.wait??false,timeoutMs:v.local_timeout?0:120000,sharedContext:v.options?.shared_context,requestedRuntime:v.options?.requested_runtime,sourceMessageId:v.options?.source_message_id});
  else if(v.operation==='preview_status')value=await client.embeds.preview.status(v.session_id);
  else if(v.operation==='preview_open')value=await client.embeds.preview.open(v.session_id);
  else if(v.operation==='preview_stop')value=await client.embeds.preview.stop(v.session_id);
  else if(v.operation==='share')value=await client.embeds.share(v.embed_id,{expires:v.expires,password:v.password});
  else if(v.operation==='add_to_project')value=await client.embeds.addToProject(v.embed_id,v.project_id,{folder:v.folder});
  else {assert.equal(v.operation,'remove_from_project');const raw=await client.embeds.removeFromProject(v.embed_id,v.project_id);value={deleted:raw.deleted,deleted_count:raw.deletedCount};}
  result={ok:true,value};
 } catch(error) {
  if(error instanceof OpenMatesConfigError) {return {ok:false,error:v.wrong_hash?"key-unavailable":"invalid"};}
  assert.ok(error instanceof OpenMatesApiError);const status=error.status;
  const code=(status===408&&v.local_timeout?'preview-timeout':undefined)??({401:'authentication',403:'forbidden',409:'conflict'})[status]??([400,404,410,422].includes(status)?'invalid':status===429||status>=500?'offline':'protocol');
  result={ok:false,error:code,http_status:status,...(code==='preview-timeout'?{timeout_source:'local',semantic_status:408,http_observed:false}:{})};
 }
 return result;
}
const lines=createInterface({input:process.stdin,crlfDelay:Infinity})[Symbol.asyncIterator]();
const input=JSON.parse((await lines.next()).value),c=input.case,n=input.iterations,url=new URL(c.endpoint);
assert.equal(url.protocol,'http:');assert.equal(url.hostname,'127.0.0.1');assert.ok(url.port);assert.equal(url.pathname,'/');assert.equal(url.search,'');assert.equal(url.hash,'');
assert.equal(c.device_id,'synthetic-embed-device');assert.ok(['sk-api-embedOwnerA.localSetupSuffix','sk-api-embedOwnerB.localSetupSuffix'].includes(c.api_key));
assert.ok(Number.isInteger(n)&&n>=100&&n<=1000000);
console.log(JSON.stringify({ready:true}));assert.equal((await lines.next()).value,'start');
const results=[];
for(let i=0;i<n;i++) {
 const r=await invoke(c),v=c.vector;
 if(v.expected_error) {assert.equal(r.ok,false);assert.equal(r.error,v.expected_error);}
 else if(v.operation!=='share')assert.deepEqual(r,{ok:true,value:v.response});
 if(v.operation==='share'||i===n-1)results.push(r);
}
console.log(JSON.stringify({done:true,iterations:n,results}));
assert.equal((await lines.next()).value,'release');
process.exit(0);
