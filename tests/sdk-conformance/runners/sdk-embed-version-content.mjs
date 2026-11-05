/** Actual API-key SDK with local Rust NAPI reconstruction; synthetic test only. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const ROOT=fileURLToPath(new URL('../../../',import.meta.url));
if(!process.argv.includes('--case')){
 const child=spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON??'python3',['tests/sdk-conformance/runners/sdk-embed-version-content.py','--language','npm',...process.argv.slice(2)],{cwd:ROOT,stdio:'inherit'});
 process.exitCode=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',(code,signal)=>resolve(signal?1:code??1));});
}else{
 const {OpenMates,OpenMatesApiError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
 const {SessionClientError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
 const raw=readFileSync(0);assert.ok(raw.length<=1024*1024);const c=JSON.parse(raw),u=new URL(c.endpoint),s=c.suite,v=c.vector;
 assert.equal(u.protocol,'http:');assert.equal(u.hostname,'127.0.0.1');assert.ok(u.port);assert.equal(u.pathname,'/');for(const field of ['search','hash','username','password'])assert.equal(u[field],'');assert.equal(s.api_key,'sk-api-embedOwnerA.localSetupSuffix');assert.equal(s.device_id,'synthetic-embed-device');
 const client=new OpenMates({apiKey:s.api_key,apiUrl:c.endpoint,deviceId:s.device_id});let out;
 try{out={ok:true,value:await client.embeds.versionContent(v.embed_id,v.version)};}
 catch(e){if(e instanceof SessionClientError)out={ok:false,error:e.code};else{assert.ok(e instanceof OpenMatesApiError);out={ok:false,error:({401:'authentication',403:'forbidden',409:'conflict'})[e.status]??([400,404,410,422].includes(e.status)?'invalid_argument':e.status===429||e.status>=500?'offline':'protocol')};}}
 console.log(JSON.stringify(out));
}
