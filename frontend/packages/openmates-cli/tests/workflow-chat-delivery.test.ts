/** Workflow owner-device crypto/claim contract. Synthetic data only, no server. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { OpenMatesClient } from '../src/client.ts';
import { decryptBytesWithAesGcm, decryptWithAesGcmCombined, encryptBytesWithAesGcm } from '../src/crypto.ts';
const masterKey = new Uint8Array(32).fill(7);
const deliveryId = '11111111-1111-4111-8111-111111111111';
const chatId = '22222222-2222-4222-8222-222222222222';
const claim = {
  delivery_id: deliveryId, chat_id: chatId, message_id: '33333333-3333-4333-8333-333333333333',
  title: 'Workflow test title', message: 'Private deterministic message', created_at: 1750000000,
  status: 'claimed', client_persisted: false, existing_chat: null,
  claim_token: 'synthetic-fence-token', claim_generation: 2, claim_issued_at: Math.floor(Date.now()/1000), claim_expires_at: Math.floor(Date.now()/1000)+60,
  embeds: [{ embed_id: '44444444-4444-4444-8444-444444444444', content_type: 'web-website', content: { title: 'Example listing', url: 'https://example.invalid/flat' } }],
};
function setup(overrides: Record<string,unknown> = {}, failPersist = false) {
  const client = new OpenMatesClient({ apiUrl: 'https://example.invalid', session: { apiUrl: 'https://example.invalid', masterKeyExportedB64: Buffer.from(masterKey).toString('base64'), cookies: {} } as never });
  const sent: {type:string; payload:Record<string,unknown>}[] = [];
  const waiters = new Map<string,{predicate:(payload:unknown)=>boolean;resolve:(value:unknown)=>void;reject:(error:Error)=>void}>();
  const ws = {
    waitForMessage(type:string,predicate:(payload:unknown)=>boolean) { return new Promise((resolve,reject)=>waiters.set(type,{predicate,resolve,reject})); },
    async sendAsync(type:string,payload:Record<string,unknown>) {
      sent.push({type,payload});
      const responseType = type === 'workflow_chat_delivery_claim' ? 'workflow_chat_delivery_claimed' : type === 'workflow_chat_delivery_persist' ? 'workflow_chat_delivery_persisted' : 'workflow_chat_delivery_acknowledged';
      const waiter = waiters.get(responseType)!;
      if (type === 'workflow_chat_delivery_persist' && failPersist) { waiter.reject(new Error('Persist failed')); return; }
      const response = type === 'workflow_chat_delivery_claim' ? {...claim,...overrides,request_id:payload.request_id} : {delivery_id:deliveryId,request_id:payload.request_id};
      assert.equal(waiter.predicate({...response,request_id:'wrong-request'}),false);
      assert.equal(waiter.predicate({...response,delivery_id:'wrong-delivery'}),false);
      assert.equal(waiter.predicate(response),true);
      waiter.resolve({type:responseType,payload:response});
    },
  };
  const internal = client as unknown as {workflowDeliveriesBySocket:WeakMap<object,Map<string,unknown>>;persistPendingWorkflowChatDeliveries:(params:unknown)=>Promise<number>};
  internal.workflowDeliveriesBySocket.set(ws,new Map([[deliveryId,{delivery_id:deliveryId,status:'delivery_pending'}]]));
  return {sent,run:()=>internal.persistPendingWorkflowChatDeliveries({ws,ownerId:'owner-fixture',chats:[]})};
}
// contract-test: supporting surface=cli assertions=workflows.content.encrypted-retained,workflows.surface.semantic-parity,cli.surface.semantic-parity
test('CLI encrypts selected results and persists before fenced acknowledgement',async()=>{
  const {sent,run}=setup(); assert.equal(await run(),1);
  assert.deepEqual(sent.map(item=>item.type),['workflow_chat_delivery_claim','workflow_chat_delivery_persist','workflow_chat_delivery_ack']);
  const persist=sent[1].payload;
  assert.equal(persist.claim_token,claim.claim_token); assert.equal(persist.claim_generation,2);
  const metadata=JSON.parse(String(persist.encrypted_chat_metadata)); const message=JSON.parse(String(persist.encrypted_message));
  const key=await decryptBytesWithAesGcm(metadata.encrypted_chat_key,masterKey); assert(key);
  assert.equal(await decryptWithAesGcmCombined(message.encrypted_content,key),claim.message);
  assert.equal(message.embeds.length,1);assert.equal(message.embeds[0].embed_id,claim.embeds[0].embed_id);
  assert.deepEqual(message.embeds[0].embed_keys.map((item:{key_type:string})=>item.key_type),['master','chat']);
  assert(!String(persist.encrypted_message).includes('Example listing'));
  assert.deepEqual(Object.keys(message).sort(),['created_at','embeds','encrypted_content','role']);
});
// contract-test: supporting surface=cli assertions=workflows.history.persisted-recovery,workflows.chat-delivery.client-encrypted
test('durable reconnect recovery acknowledges without creating new ciphertext',async()=>{
  const {sent,run}=setup({client_persisted:true,existing_chat:undefined});assert.equal(await run(),1);
  assert.deepEqual(sent.map(item=>item.type),['workflow_chat_delivery_claim','workflow_chat_delivery_ack']);
});
// contract-test: supporting surface=cli assertions=workflows.chat-delivery.key-recovery,workflows.chat-delivery.client-encrypted
test('existing destinations preserve their canonical key even outside the recent cache',async()=>{
  const wrapper=await encryptBytesWithAesGcm(new Uint8Array(32).fill(9),masterKey);
  const {sent,run}=setup({existing_chat:{encrypted_chat_key:wrapper,messages_v:7,title_v:1,created_at:1740000000}});
  await run(); const metadata=JSON.parse(String(sent[1].payload.encrypted_chat_metadata));
  assert.equal(metadata.encrypted_chat_key,wrapper);assert.equal(metadata.messages_v,8);
});
// contract-test: supporting surface=cli assertions=workflows.history.delivery-reservations,workflows.chat-delivery.claim-fenced
test('failed persistence cannot acknowledge or mark results delivered',async()=>{
  const {sent,run}=setup({},true);await assert.rejects(run(),/Persist failed/);
  assert(!sent.some(item=>item.type==='workflow_chat_delivery_ack'));
});
