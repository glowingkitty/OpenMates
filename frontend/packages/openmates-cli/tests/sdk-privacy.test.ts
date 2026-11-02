// contract-test: supporting surface=sdks.npm assertions=pii.surface.semantic-parity
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {preparePrivacy,restorePrivacy} from '../src/sdkPrivacy.ts';
import {SessionClientError} from '../src/sdkSession.ts';
const invalid=(run:()=>unknown)=>assert.throws(run,error=>error instanceof SessionClientError && error.code==='invalid_argument' && !error.message.includes('synthetic-secret'));
test('privacy rejects lossy malformed caller values before native dispatch',()=>{
  for(const value of [undefined,NaN,Infinity,1n,()=>0,Symbol('x'),new Date(),{toJSON(){return 'synthetic-secret';}}, {opaque:undefined}, '\ud800',9007199254740992]) invalid(()=>preparePrivacy('plain',{memories:[value]}));
  invalid(()=>preparePrivacy('plain',{unknown:'synthetic-secret'} as never));
  invalid(()=>preparePrivacy('plain',{enhanced:undefined}));
  invalid(()=>preparePrivacy('plain',{memories:new Array(1)}));
  invalid(()=>restorePrivacy('x',new Array(1025).fill(null)));
  invalid(()=>restorePrivacy('x'.repeat(1048577),[]));
  const cycle:unknown[]=[];cycle.push(cycle);invalid(()=>preparePrivacy('plain',{memories:cycle}));
});
// contract-test: supporting surface=sdks.npm assertions=pii.surface.semantic-parity
test('privacy calls native core and preserves mapping metadata and caller inputs',()=>{
  const mappings=[{original:'fictional@example.invalid',placeholder:'[KNOWN_EMAIL]',opaque:{retained:true}}];
  const before=structuredClone(mappings);
  const prepared=preparePrivacy('fictional@example.invalid',{existingMappings:mappings});
  assert.equal(prepared.text,'[KNOWN_EMAIL]');
  assert.deepEqual(prepared.mappings,[{...mappings[0],type:'OTHER'}]);
  assert.equal(restorePrivacy(prepared.text,prepared.mappings),'fictional@example.invalid');
  assert.deepEqual(mappings,before);
  invalid(()=>preparePrivacy('synthetic-secret',{enhanced:true}));
});
