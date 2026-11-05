// Private draft supporting facade tests; no native source implementation executed.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {SessionProjects} from '../src/sdkSession.ts';
import {OpenMates,OpenMatesProjectSourceAuthoringUnavailableError} from '../src/sdk.ts';
const metadata=JSON.parse('{"root":"/synthetic","binding_root":"/synthetic","teamId":{"updatedAt":1,"config":{"sourceId":"unchanged"}},"__proto__":{"kept":true},"a.b/c":[{"scopeIn":"unchanged"}]}');
const input={sourceId:'source',sourceType:'local_folder',displayName:'Synthetic',metadata,capabilities:[],status:'offline',createdAt:1,updatedAt:2,lastIndexedAt:null};
// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
test('source DTO maps outer fields while complete metadata stays exact',async()=>{
  const seen:unknown[][]=[];
  const native={async projectsCreateSource(...args:unknown[]){seen.push(args);const dto=JSON.parse(args[1] as string);return JSON.stringify(dto);},async projectsUpdateSourceCapabilities(...args:unknown[]){seen.push(args);return JSON.stringify({capabilities:['read'],updated_at:3,metadata});}};
  const projects=new SessionProjects(native as never,async run=>run());
  const result=await projects.createSource('project',input as never,{personal:true});
  assert.deepEqual(result.metadata,metadata);assert.equal(result.source_id,'source');assert.equal(result.display_name,'Synthetic');
  const wire=JSON.parse(seen[0][1] as string);assert.deepEqual(wire.metadata,metadata);assert.deepEqual(wire.capabilities,[]);assert.deepEqual(JSON.parse(seen[0][2] as string),{personal:true});
  await projects.createSource('project',{...input,capabilities:['read','read']} as never,{teamId:'team'});
  assert.deepEqual(JSON.parse(seen[1][1] as string).capabilities,['read','read']);assert.deepEqual(JSON.parse(seen[1][2] as string),{team_id:'team'});
  const changed=await projects.updateSourceCapabilities('project','literal%2F',{capabilities:['read'],updatedAt:3},{personal:true});
  assert.deepEqual(JSON.parse(seen[2][2] as string),{capabilities:['read'],updated_at:3});assert.deepEqual(changed.metadata,metadata);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
test('source malformed/non-JSON/oversized metadata fails statically before native',async()=>{
  let calls=0;const native={async projectsCreateSource(){calls++;throw Error('unexpected');}};const projects=new SessionProjects(native as never,async run=>run());
  const circular:Record<string,unknown>={};circular.self=circular;
  for(const value of [{...input,extra:'private-secret'},{...input,metadata:[]},{...input,metadata:{value:undefined}},{...input,metadata:{value:NaN}},{...input,metadata:circular},{...input,metadata:{value:'x'.repeat(1024*1024+1)}}]){
    await assert.rejects(projects.createSource('project',value as never,{personal:true}),error=>(error as {code?:string}).code==='invalid_argument'&&(error as Error).message==='Invalid typed Project source input.');
  }
  assert.equal(calls,0);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
test('API key source authoring refuses both methods without transport',async()=>{
  const prior=globalThis.fetch;let calls=0;globalThis.fetch=async()=>{calls++;throw Error('unexpected');};
  try{const client=new OpenMates({apiKey:'synthetic-bearer.synthetic-secret',apiUrl:'https://example.invalid',deviceId:'synthetic-device'});for(const run of [()=>client.projects.createSource('project',input as never,{personal:true}),()=>client.projects.updateSourceCapabilities('project','source',{capabilities:['read'],updatedAt:2},{personal:true})])await assert.rejects(run(),error=>error instanceof OpenMatesProjectSourceAuthoringUnavailableError&&error.code==='project_source_authoring_unavailable'&&error.reason==='PROJECT_SOURCE_AUTHORING_REQUIRES_COOKIE_SESSION');assert.equal(calls,0);}finally{globalThis.fetch=prior;}
});

// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
test('bounded compact numeric metadata is not rejected by an inflated estimate',async()=>{
  const native={async projectsCreateSource(_project:string,wire:string){return wire;}};
  const projects=new SessionProjects(native as never,async run=>run());
  const numbers=Array(32000).fill(0);
  const result=await projects.createSource('project',{...input,metadata:{numbers},lastIndexedAt:undefined} as never,{personal:true});
  assert.deepEqual(result.metadata,{numbers});
});
