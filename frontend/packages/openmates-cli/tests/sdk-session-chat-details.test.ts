/** Actual maintained facade with synthetic native objects; no native/runtime IO. */
// contract-test-file: tooling
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {SessionClient,SessionClientError,type SessionChatDetailsOptions} from '../src/sdkSession.ts';
const fixture=JSON.parse(readFileSync(new URL('../../../../packages/openmates-session-bindings/tests/fixtures/chat-details-read.json',import.meta.url),'utf8'));
function client(native:object):SessionClient{const c=Object.create(SessionClient.prototype) as SessionClient;Object.defineProperty(c,'essentialEpoch',{value:0,writable:true});Object.defineProperty(c,'native',{value:native});return c;}
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
test('rich source vectors preserve complete fields, followups, nulls and omission',async()=>{
 for(const vector of fixture.vectors){const calls:unknown[]=[];
  const c=client({chatDetailsPrepare:async(id:string,raw:string)=>{calls.push([id,JSON.parse(raw)]);return{releaseJson:()=>{calls.push('finish');return JSON.stringify(vector.expected);},discard:()=>{calls.push('discard');}};}});
  const options:SessionChatDetailsOptions=vector.flags.includes('--all')?{history:{kind:'full'}}:{};
  const result=await c.chatDetails(vector.expected.chat.id,options);
  assert.deepEqual(result,vector.expected);assert.deepEqual(calls,[[vector.expected.chat.id,options],'finish','discard']);
  assert.equal(Object.hasOwn(result,'has_more_before'),!vector.flags.includes('--all'));
 }
});
test('options and arbitrary raw PII JSON pass unchanged through the facade',async()=>{
 for(const mapping of [null,false,42,'literal',String.fromCharCode(0xd83d),[],{},{placeholder:'[OM_PII_X]',original:'Synthetic Alice'},[null,false,42,'literal',[],{placeholder:'[OM_PII_X]',original:'Synthetic Alice'}]]){
  const expected=structuredClone(fixture.vectors[0].expected);expected.messages[0].piiMappings=mapping;
  const options:SessionChatDetailsOptions={history:{kind:'latest',limit:7},content_mode:'stored'};
  const c=client({chatDetailsPrepare:async(_id:string,raw:string)=>{assert.deepEqual(JSON.parse(raw),options);return{releaseJson:()=>JSON.stringify(expected),discard:()=>{}};}});
  const result=await c.chatDetails(expected.chat.id,options);assert.deepEqual(result,expected);assert.ok(Object.hasOwn(result.messages[0],'piiMappings'));
 }
});
test('queued epoch refusal disposes without releasing the original object',async()=>{
 let discarded=false;const c:SessionClient=client({chatDetailsPrepare:async()=>{Reflect.set(c,'essentialEpoch',1);return{releaseJson:()=>assert.fail('stale rich read released'),discard:()=>{discarded=true;}};}});
 await assert.rejects(c.chatDetails(fixture.vectors[0].expected.chat.id),(e:unknown)=>e instanceof SessionClientError&&e.code==='cancelled');assert.equal(discarded,true);
});
test('sync native authority denial is normalized and always discarded',async()=>{
 let discarded=false;const c=client({chatDetailsPrepare:async()=>({releaseJson:()=>{throw new Error(JSON.stringify({code:'forbidden',message:'Denied.'}));},discard:()=>{discarded=true;}})});
 await assert.rejects(c.chatDetails(fixture.vectors[0].expected.chat.id),(e:unknown)=>e instanceof SessionClientError&&e.code==='forbidden');assert.equal(discarded,true);
});
test('raw JSON escaped draft preview preserves exact trailing UTF-16 high surrogate',async()=>{
 const expected=structuredClone(fixture.vectors[0].expected);expected.chat.draftPreview='a'.repeat(199)+String.fromCharCode(0xd83d);
 const wire=JSON.stringify(expected);assert.ok(wire.includes('\\ud83d'));
 const c=client({chatDetailsPrepare:async()=>({releaseJson:()=>wire,discard:()=>{}})});
 const result=await c.chatDetails(expected.chat.id);assert.deepEqual(result,expected);
 assert.equal(result.chat.draftPreview!.length,200);assert.equal(result.chat.draftPreview!.charCodeAt(199),0xd83d);
});

test('optional active focus omission and nonempty whitespace are preserved without selection logic',async()=>{
 for(const value of [undefined,'synthetic-focus',' ']){
  const expected=structuredClone(fixture.vectors[0].expected);delete expected.chat.activeFocusId;
  if(value!==undefined)expected.chat.activeFocusId=value;
  const c=client({chatDetailsPrepare:async()=>({releaseJson:()=>JSON.stringify(expected),discard:()=>{}})});
  const result=await c.chatDetails(expected.chat.id);assert.deepEqual(result,expected);
  assert.equal(Object.hasOwn(result.chat,'activeFocusId'),value!==undefined);
 }
});

// Shared Rust owns JS-number rounding and duplicate-key normalization. These
// synthetic native tokens prove only the unchanged facade parsing boundary.
test('shared SDK numeric tokens retain infinities, negative zero and decoded keys',async()=>{
 const cases:[string,unknown][]=[['1e400',Infinity],['-1e400',-Infinity],['-0.0',-0],['9007199254740992.0',9007199254740992],['1.0000000000000001e18',1.0000000000000001e18],['{"a":1,"\\u0061":2}',{a:2}],['{"\\ud83d":"\\udfff"}',{[String.fromCharCode(0xd83d)]:String.fromCharCode(0xdfff)}]];
 for(const [token,expectedMapping] of cases){
  const expected=structuredClone(fixture.vectors[0].expected);expected.messages[0].piiMappings='SDK_NUMERIC_TOKEN';
  const wire=JSON.stringify(expected).replace('"SDK_NUMERIC_TOKEN"',token);
  const c=client({chatDetailsPrepare:async()=>({releaseJson:()=>wire,discard:()=>{}})});
  const result=await c.chatDetails(expected.chat.id);assert.deepEqual(result.messages[0].piiMappings,expectedMapping);
  if(token==='-0.0')assert.ok(Object.is(result.messages[0].piiMappings,-0));
 }
});
