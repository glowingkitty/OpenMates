// PRIVATE UNRUN DRAFT; must execute against integrated public SDK imports.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {OpenMates,OpenMatesProjectTaskWatchUnavailableError} from '../src/sdk.ts';
// contract-test: supporting surface=sdks.npm assertions=sdk.surface.semantic-parity
test('API-key Project watch refuses with canonical reason before transport',async()=>{
  let calls=0;
  const original=globalThis.fetch;
  globalThis.fetch=async()=>{calls++;throw Error('unexpected transport');};
  try{
    const client=new OpenMates({apiKey:'synthetic-bearer.synthetic-secret',apiUrl:'https://example.invalid',deviceId:'synthetic-device'});
    await assert.rejects(client.projects.watchTasks('project',{sourceId:'source'},{personal:true}),error=>error instanceof OpenMatesProjectTaskWatchUnavailableError && error.code==='project_task_watch_unavailable' && error.reason==='PROJECT_TASK_WATCH_REQUIRES_COOKIE_SESSION');
    assert.equal(calls,0);
  }finally{globalThis.fetch=original;}
});
