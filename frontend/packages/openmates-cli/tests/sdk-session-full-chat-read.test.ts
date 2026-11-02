/** Actual npm facade; native doubles exercise opaque handoff, not crypto/runtime proof. */
// contract-test-file: tooling
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {SessionClient,SessionClientError} from '../src/sdkSession.ts';
const fixture=JSON.parse(readFileSync(new URL('../../../../packages/openmates-rust/tests/fixtures/full-chat-read-metadata.json',import.meta.url),'utf8'));
function client(native:object):SessionClient {const c=Object.create(SessionClient.prototype) as SessionClient;Object.defineProperty(c,'essentialEpoch',{value:0,writable:true});Object.defineProperty(c,'native',{value:native});return c;}
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
test('openChat preserves optional slug/legacy shared vectors with synchronous final native release',async()=>{
  for(const v of fixture.vectors){const calls:string[]=[];const c=client({openChatPrepare:async(id:string)=>{calls.push(id);return {releaseJson:()=>{calls.push('release');return JSON.stringify(v.expected);},discard:()=>{calls.push('discard');}};}});
    assert.deepEqual(await c.openChat(fixture.chat.id),v.expected);assert.deepEqual(calls,[fixture.chat.id,'release','discard']);}
});
test('changed authority while opaque native result queued refuses output and discards without release',async()=>{
  let discarded=false;const c:SessionClient=client({openChatPrepare:async()=>{Reflect.set(c,'essentialEpoch',1);return {releaseJson:()=>assert.fail('stale read released'),discard:()=>{discarded=true;}};}});
  await assert.rejects(c.openChat(fixture.chat.id),(e:unknown)=>e instanceof SessionClientError&&e.code==='cancelled');assert.equal(discarded,true);
});
test('native final denial is normalized and always discards the original opaque result',async()=>{
  let discarded=false;const c=client({openChatPrepare:async()=>({releaseJson:()=>{throw new Error(JSON.stringify({code:'forbidden',message:'Denied.'}));},discard:()=>{discarded=true;}})});
  await assert.rejects(c.openChat(fixture.chat.id),(e:unknown)=>e instanceof SessionClientError&&e.code==='forbidden');assert.equal(discarded,true);
});
