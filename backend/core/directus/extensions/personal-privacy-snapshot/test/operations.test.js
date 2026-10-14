import test from 'node:test';
import assert from 'node:assert/strict';
import { authorized } from '../src/index.js';
import { readPersonalPrivacySnapshot } from '../src/operations.js';

function fakeDatabase({supported=true, token='epoch:7'}={}) {
  const reads=[];
  const trx = table => {
    reads.push(table);
    const query={insert(){return query},onConflict(){return query},ignore(){return Promise.resolve()},
      where(){return query},whereNull(){return query},forShare(){return query},select(){return query},
      first(){return Promise.resolve(table === 'personal_privacy_generations' ? {epoch:token.split(':')[0],generation:token.split(':')[1]} : {id:'owner',encrypted_settings:'opaque'})},
      orderBy(){return Promise.resolve([{id:'personal-memory',encrypted_item_json:'opaque'}])}};
    return query;
  };
  trx.raw=async () => ({rows:[{count:supported ? 4 : 0}]});
  return {reads,transaction:async callback=>callback(trx)};
}
// contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy,auth.session.isolation
test('internal route rejects absent, developer and wrong credentials',()=>{
 assert.equal(authorized({},'internal'),false);
 assert.equal(authorized({'authorization':'Bearer developer'},'internal'),false);
 assert.equal(authorized({'x-internal-service-token':'wrong'},'internal'),false);
 assert.equal(authorized({'x-internal-service-token':'internal'},''),false);
 assert.equal(authorized({'x-internal-service-token':'internal'},'internal'),true);
});
// contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy
test('unchanged reads only enforcement and owner generation, no ciphertext bodies',async()=>{
 const db=fakeDatabase();
 const result=await readPersonalPrivacySnapshot(db,{user_id:'owner',known_generation:'epoch:7'});
 assert.equal(result.unchanged,true); assert.equal(result.privacy_generation,'epoch:7');
 assert.equal(Object.hasOwn(result,'personal_memories'),false);
 assert.deepEqual(db.reads,['personal_privacy_generations','personal_privacy_generations']);
});
// contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy
test('unknown or reset generation loads a full consistent encrypted batch',async()=>{
 for (const known of [undefined,'epoch:6','old-epoch:7']) {
  const db=fakeDatabase();const result=await readPersonalPrivacySnapshot(db,{user_id:'owner',known_generation:known});
  assert.equal(result.unchanged,false);assert.equal(result.personal_memories.encrypted_settings,'opaque');
  assert.deepEqual(db.reads,['personal_privacy_generations','personal_privacy_generations','directus_users','user_app_settings_and_memories']);
 }
});
// contract-test: direct surface=rest_api assertions=ai-model-routing.preprocessing.prepared-privacy
test('missing trigger enforcement never certifies equality',async()=>{
 const db=fakeDatabase({supported:false});assert.deepEqual(await readPersonalPrivacySnapshot(db,{user_id:'owner',known_generation:'epoch:7'}),{supported:false});
 assert.deepEqual(db.reads,[]);
});
