// contract-test-file: infrastructure
/** Local encrypted fixtures exercise decryption order, cache-first publication and owner fences. */
import assert from 'node:assert/strict';
import {test,afterEach} from 'node:test';
import {createCipheriv,createHash,randomBytes,webcrypto} from 'node:crypto';
import {mkdtempSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {OpenMatesClient} from '../src/client.js';
import type {OpenMatesSession,SyncCache} from '../src/storage.js';
const master=Buffer.alloc(32,11),key=Buffer.alloc(32,22),chatId='11111111-1111-4111-8111-111111111111';
const originalDir=process.env.OPENMATES_STATE_DIR;
const dirs:string[]=[];
afterEach(()=>{for(const dir of dirs.splice(0))rmSync(dir,{recursive:true,force:true});if(originalDir===undefined)delete process.env.OPENMATES_STATE_DIR;else process.env.OPENMATES_STATE_DIR=originalDir;});
const hash=(s:string)=>createHash('sha256').update(s).digest('hex');
function encrypt(value:string|Buffer,k=key):string {
 const iv=randomBytes(12),cipher=createCipheriv('aes-256-gcm',k,iv);
 return Buffer.concat([iv,cipher.update(value),cipher.final(),cipher.getAuthTag()]).toString('base64');
}
function message(i:number){return {id:`m-${i}`,client_message_id:`m-${i}`,chat_id:chatId,role:i%2?'assistant':'user',created_at:i,
 hashed_user_id:'human-hash',encrypted_content:encrypt(`Message ${i}`),encrypted_sender_name:encrypt(i%2?'Sophia':'Human'),
 encrypted_category:encrypt('technology'),encrypted_model_name:encrypt('Known model'),encrypted_pii_mappings:encrypt('[{"original":"private","placeholder":"token"}]')};}
function setup(count=130,chatCount=1){
 const dir=mkdtempSync(join(tmpdir(),'openmates-client-startup-'));dirs.push(dir);process.env.OPENMATES_STATE_DIR=dir;
 const session={apiUrl:'https://synthetic.invalid',sessionId:'local-fixture',cookies:{},wsToken:null,masterKeyExportedB64:master.toString('base64'),hashedEmail:'fixture-owner',userEmailSalt:'salt',createdAt:1,authorizerDeviceName:'Fixture',autoLogoutMinutes:null} satisfies OpenMatesSession;
 const client=new OpenMatesClient({session});
 const cache:SyncCache={syncedAt:Date.now(),loadedChatCount:chatCount,totalChatCount:chatCount,embeds:[
  {embed_id:'parent-a',hashed_message_id:hash('m-129')},{embed_id:'child',parent_embed_id:'parent-a',hashed_message_id:hash('m-129')},
  {embed_id:'other-chat',hashed_message_id:hash('elsewhere')},{embed_id:'parent-b',hashed_message_id:hash('m-129')}],embedKeys:[],
  chats:Array.from({length:chatCount},(_,i)=>({details:{id:i===0?chatId:`chat-${i}`,messages_v:i===0?count:0,
   encrypted_chat_key:encrypt(key,master),encrypted_title:encrypt(`Chat ${i}`),encrypted_chat_summary:encrypt('Summary'),
   encrypted_category:encrypt('technology'),encrypted_slug:encrypt(`chat-${i}`)},messages:i===0?Array.from({length:count},(_,n)=>JSON.stringify(message(n))):[]}))};
 const path=join(dir,'sync_cache.json');writeFileSync(path,JSON.stringify(cache),{mode:0o600});
 const internals=client as unknown as {session:OpenMatesSession;http:{get:(...args:unknown[])=>Promise<unknown>;post:(...args:unknown[])=>Promise<unknown>}};
 internals.http.get=internals.http.post=async()=>{throw Error('Unexpected network request');};
 return {client,cache,path,internals};
}
// contract-test: supporting surface=cli assertions=terminal-ui.offline.cache-first,chat-navigation.open.local-first-coherent
test('publishes a sorted latest cached window before older history, preserving fields and ciphertext',async()=>{
 const {client,cache,path}=setup();cache.chats[0].messages.reverse();writeFileSync(path,JSON.stringify(cache));
 const before=readFileSync(path,'utf8'),events:string[]=[];
 const result=await client.getChatMessages(chatId,{preferCache:true,onMessages:part=>{
  events.push('recent');assert.equal(part.messages.length,100);assert.equal(part.messages[0].content,'Message 30');
  assert.equal(part.messages.at(-1)?.content,'Message 129');assert.equal(part.messages.at(-1)?.senderName,'Sophia');
 }});
 events.push('complete');assert.deepEqual(events,['recent','complete']);assert.equal(result.messages.length,130);
 assert.equal(result.messages[0].content,'Message 0');assert.deepEqual(result.messages.at(-1)?.embedIds,['parent-a','parent-b']);
 assert.equal(result.messages.at(-1)?.hashedSenderUserId,'human-hash');assert.equal(result.messages.at(-1)?.modelName,'Known model');
 assert.deepEqual(result.messages.at(-1)?.piiMappings,[{original:'private',placeholder:'token'}]);
 assert.equal(readFileSync(path,'utf8'),before,'Browsing cannot write decrypted content to cache');
});
// contract-test: supporting surface=cli assertions=terminal-ui.offline.cache-first,chat-navigation.open.local-first-coherent
test('publishes the first cached preview census and still returns the complete ordered list',async()=>{
 const {client}=setup(0,80);const partial:number[]=[];
 const result=await client.listCachedChats(1000,1,{onCachedChats:page=>{partial.push(page.chats.length);assert.equal(page.total,80);assert.equal(page.hasMore,true);assert.equal(page.chats[31].title,'Chat 31');}});
 assert.deepEqual(partial,[32]);assert.equal(result?.chats.length,80);assert.equal(result?.chats[79].slug,'chat-79');
});
// contract-test: supporting surface=cli assertions=terminal-ui.offline.cache-first
test('account, Team, key change and abort after first cached window prevent older publication',async()=>{
 for(const change of ['account','team','key','abort']){
  const {client,internals}=setup();const controller=new AbortController();let calls=0;
  await assert.rejects(client.getChatMessages(chatId,{preferCache:true,signal:controller.signal,onMessages:()=>{
   calls++;if(change==='account')internals.session={...internals.session,hashedEmail:'different-owner'};
   else if(change==='team')internals.session={...internals.session,activeTeamId:'another-team'};
   else if(change==='key')internals.session={...internals.session,masterKeyExportedB64:Buffer.alloc(32,33).toString('base64')};
   else controller.abort();
  }}));assert.equal(calls,1);
 }
});
// contract-test: supporting surface=cli assertions=terminal-ui.offline.cache-first
test('a cached preview callback cannot finish after switching to another account with the same key',async()=>{
 const {client,internals}=setup(0,80);let calls=0;
 await assert.rejects(client.listCachedChats(1000,1,{onCachedChats:()=>{calls++;internals.session={...internals.session,hashedEmail:'other-owner'};}}),/workspace changed/);
 assert.equal(calls,1);
});
// contract-test: supporting surface=cli assertions=terminal-ui.offline.cache-first
test('Team ciphertext without an authorized local Team key remains unreadable offline',async()=>{
 const {client,internals}=setup();internals.session={...internals.session,activeTeamId:'unavailable-team'};
 assert.equal(await client.listCachedChats(),null);
 await assert.rejects(client.getChatMessages(chatId,{preferCache:true}),/Team key unavailable offline/);
});
// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent
test('network windows decrypt each field once and preserve order without duplicate final work',async()=>{
 const {client,internals}=setup(0);const windows=[Array.from({length:30},(_,n)=>message(n+30)),Array.from({length:30},(_,n)=>message(n))];
 // Make metadata advertise server history while keeping the local window empty.
 const path=join(process.env.OPENMATES_STATE_DIR!,'sync_cache.json');const cache=JSON.parse(readFileSync(path,'utf8'));cache.chats[0].details.messages_v=60;writeFileSync(path,JSON.stringify(cache));
 let requests=0,callbacks=0,imports=0;const original=webcrypto.subtle.importKey;
 internals.http.get=async()=>({ok:true,status:200,data:{messages:windows[requests++],has_more_before:requests===1,start_cursor:{created_at:30,message_id:'m-30'}}});
 webcrypto.subtle.importKey=(...args:Parameters<typeof original>)=>{imports++;return original.apply(webcrypto.subtle,args);};
 try{
  const result=await client.getChatMessages(chatId,{preferCache:true,onMessages:part=>{callbacks++;assert.equal(part.messages[0].content,'Message 30');}});
  assert.equal(result.messages.length,60);assert.equal(result.messages[0].content,'Message 0');assert.equal(result.messages.at(-1)?.content,'Message 59');
  assert.equal(requests,2);assert.equal(callbacks,1);assert.ok(imports<=6,`Expected operation-local key imports, saw ${imports}`);
 }finally{webcrypto.subtle.importKey=original;}
});
