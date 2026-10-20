// contract-test-file: infrastructure
import {describe,it,expect,vi,afterEach} from 'vitest';
const m=vi.hoisted(()=>({db:{getChat:vi.fn(),getMessage:vi.fn(),saveMessage:vi.fn(),updateChat:vi.fn(),getEncryptedFields:vi.fn(),getPendingEmbedOperations:vi.fn(async()=>[])},getKey:vi.fn(),openOutput:vi.fn(),fetch:vi.fn(),complete:vi.fn(),ws:{on:vi.fn(),off:vi.fn(),sendMessage:vi.fn()}}));
vi.mock('../db',()=>({chatDB:m.db}));
vi.mock('../userDB',()=>({userDB:{getUserProfile:async()=>({user_id:"owner"})}}));
vi.mock('../../config/api',()=>({getApiEndpoint:(x)=>x,storageArchiveFetch:m.fetch}));
vi.mock('../encryption/ChatKeyManager',()=>({computeKeyFingerprint:(key)=>Array.from(key).join(","),chatKeyManager:{getKey:m.getKey,injectKey:()=>{},onKeyReady:()=>()=>{}}}));
vi.mock('../chatKeyWriteGuard',()=>({ensureChatKeySafeForWrite:async()=>true}));
vi.mock('../websocketService',()=>({webSocketService:m.ws}));
vi.mock('../../stores/aiTypingStore',()=>({aiTypingStore:{clearTyping:()=>{}}}));
vi.mock('../../stores/notificationStore',()=>({notificationStore:{chatMessage:()=>{}}}));
vi.mock('../../stores/unreadMessagesStore',()=>({unreadMessagesStore:{incrementUnread:()=>{}}}));
vi.mock('../chatNotificationVisibility',()=>({isChatVisiblyActive:()=>true}));
vi.mock('../embedDiffStore',()=>({reconstructEncryptedVersionRows:()=>{}}));
vi.mock('../recoveryEmbedSource',()=>({catalogContextFromSealedEmbed:async()=>null,historySourceFromSealedEmbed:()=>null,isUnwrittenInitialDiffRead:()=>false}));
vi.mock('../chatRecoveryVersionRefresh',()=>({refreshRecoveryChatVersion:async(x)=>x}));
vi.mock('../chatRecoveryVersionApply',()=>({chatAfterRecoveredReply:(current,base,v)=>({...current,...base,messages_v:v})}));
vi.mock('../recoveryAssistantTimestamp',()=>({clearRecoveryFinalTimestamps:()=>{},waitForRecoveryFinalTimestamp:async()=>100}));
vi.mock('../personalChatTurnBarrier',()=>({clearPersonalChatTurnBarriers:()=>{},completePersonalChatTurn:m.complete,failMatchingPersonalChatTurn:()=>{}}));
vi.mock('../canonicalEmbedWriteCoordinator',()=>({hasAcknowledgedRecoveredEmbed:()=>false,markAcknowledgedRecoveredEmbed:()=>{},withCanonicalEmbedWrite:async(id,fn)=>fn({})}));
vi.mock('../../message_parsing/utils',()=>({computeSHA256:async(s)=>s==="content-cipher"?"a".repeat(64):s==="encrypted"?"b".repeat(64):"hash:"+s}));
vi.mock('../encryption/MessageEncryptor',()=>({encryptWithChatKey:async()=>"encrypted"}));
vi.mock('../encryption/MetadataEncryptor',()=>({encryptChatKeyWithMasterKey:async()=>"wrapped",deriveEmbedKeyFromChatKey:async()=>new Uint8Array([1]),encryptWithEmbedKey:async(value)=>value==='code'?'type-cipher':"encrypted",decryptWithEmbedKey:async(s)=>s==="type-cipher"?"code":"{}",wrapEmbedKeyWithMasterKey:async()=>"master-wrapper",wrapEmbedKeyWithChatKey:async()=>"chat-wrapper",unwrapEmbedKeyWithMasterKey:async(cipher)=>new Uint8Array([cipher==='conflicting-wrapper'?2:1]),unwrapEmbedKeyWithChatKey:async()=>new Uint8Array([1])}));
vi.mock('../../utils/chatCompletionRecovery',()=>({deriveChatCompletionRecoveryKeypair:async()=>({privateKey:"private"}),openRecoveryOutputEnvelope:m.openOutput,openChatCompletionRecoveryEnvelope:async()=>new TextEncoder().encode(JSON.stringify({job_id:"job",chat_id:"chat",turn_id:"turn",assistant_message_id:"assistant",key_version:1,content:"Recovered reply",category:null,model_name:null}))}));
const {handleRecoveryOutputsAvailableImpl,handleRecoveryJobsAvailableImpl,resetRecoveryLifecycleImpl}=await import('../chatSyncServiceHandlersRecovery.ts');

const output={record_id:'record',root_chat_id:'chat',target_chat_id:'chat',turn_id:'turn',subject_id:'embed',output_kind:'embed',output_version:1,chat_key_version:1};
const job={job_id:'job',chat_id:'chat',turn_id:'turn',assistant_message_id:'assistant',chat_key_version:1};
const canonical={embed:{embed_id:'embed',hashed_chat_id:'hash:chat',hashed_message_id:'hash:assistant',hashed_user_id:'hash:owner',encrypted_content:'content-cipher',encrypted_type:'type-cipher',version_number:1},embed_keys:[{hashed_embed_id:'hash:embed',key_type:'master',encrypted_embed_key:'master-wrapper',hashed_user_id:'hash:owner'},{hashed_embed_id:'hash:embed',key_type:'chat',hashed_chat_id:'hash:chat',encrypted_embed_key:'chat-wrapper',hashed_user_id:'hash:owner'}]};
function setup({terminal=false,selectedOutput=output,selectedOutputs=[selectedOutput]}={}){
 resetRecoveryLifecycleImpl();vi.clearAllMocks();m.openOutput.mockImplementation(async()=>new TextEncoder().encode(JSON.stringify({record_id:"record",target_chat_id:"chat",subject_id:"embed",output_kind:"embed",output_version:1,content:{embed_id:"embed",chat_id:"chat",message_id:"assistant",content:"{}",type:"code",version_number:1}})));vi.useFakeTimers();vi.spyOn(document,'hasFocus').mockReturnValue(true);
 Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});
 const listeners=new Map();const sent=[];
 m.ws.on.mockImplementation((type,fn)=>{if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(fn)});
 m.ws.off.mockImplementation((type,fn)=>listeners.get(type)?.delete(fn));
 const emit=(type,payload)=>{for(const fn of [...(listeners.get(type)??[])])fn(payload)};
 m.ws.sendMessage.mockImplementation(async(type,p)=>{
  sent.push({type,...p});const common={...p};
  if(type==='recovery_output_get')emit('recovery_output_ready',{...(selectedOutputs.find(row=>row.record_id===p.record_id)??selectedOutput),...common,sealed_payload:'{}',messages_v:1,encrypted_chat_key:'wrapped'});
  if(type==='store_embed_keys')emit('store_embed_keys_confirmed',{...common,failed_count:0,created_count:p.keys.length,requested_count:p.keys.length});
  if(type==='recovery_output_ack_embed')emit('recovery_output_embed_acknowledged',{...common,state:'ACKNOWLEDGED'});
  if(type==='recovery_job_claim')emit('recovery_job_claimed',{...job,...common,state:terminal?'TERMINAL':'LEASED',lease_token:'lease',lease_generation:1,sealed_payload:'{}'});
  if(type==='recovery_job_persist')emit('recovery_job_persisted',{...common,state:'TERMINAL',committed_messages_v:2});
 });
 const chat={chat_id:'chat',user_id:'owner',messages_v:terminal?2:1,encrypted_chat_key:'wrapped'};
 m.db.getChat.mockResolvedValue(chat);m.db.getMessage.mockResolvedValue(terminal?{message_id: "assistant",chat_id: "chat"}:undefined);m.getKey.mockResolvedValue(new Uint8Array([1]));
 m.db.getEncryptedFields.mockResolvedValue({encrypted_content:'cipher'});
 const service={hasCompletedInitialSync_FOR_HANDLERS_ONLY:true,requestChatContentBatch_FOR_HANDLERS_ONLY:vi.fn().mockResolvedValue(undefined),dispatchEvent:vi.fn()};
 const errors=vi.spyOn(console,'error').mockImplementation(()=>{});
 return{sent,service,errors,emit};
}
afterEach(()=>{resetRecoveryLifecycleImpl();vi.useRealTimers();vi.restoreAllMocks()});
describe('offline diagnostic: typed output readiness and terminal job ordering',()=>{
 // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
 it('acknowledges equivalent historical duplicate wrappers without rewriting encrypted records',async()=>{
  const {sent,service,errors}=setup();
  const stored=structuredClone(canonical);
  stored.embed_keys.push(...canonical.embed_keys.map(row=>({...row,encrypted_embed_key:row.encrypted_embed_key+'-duplicate'})));
  const before=JSON.stringify(stored);
  m.fetch.mockResolvedValue({status:200,ok:true,json:async()=>stored});
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});
  expect(errors).not.toHaveBeenCalled();
  expect(sent.filter(row=>row.type==='store_embed'||row.type==='store_embed_keys')).toHaveLength(0);
  expect(sent.filter(row=>row.type==='recovery_output_ack_embed')).toHaveLength(1);
  expect(JSON.stringify(stored)).toBe(before);
 });
 // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
 it.each(['conflict','foreign-owner','foreign-scope','oversized','cursor-loop'])('preserves encrypted data and withholds acknowledgement for %s wrapper proof',async(mode)=>{
  const {sent,service,errors}=setup();
  const stored=structuredClone(canonical);
  if(mode==='conflict')stored.embed_keys.push({...stored.embed_keys[0],encrypted_embed_key:'conflicting-wrapper'});
  if(mode==='foreign-owner')stored.embed_keys.push({...stored.embed_keys[0],hashed_user_id:'foreign'});
  if(mode==='foreign-scope')stored.embed_keys.push({...stored.embed_keys[0],hashed_project_id:'unrelated'});
  if(mode==='oversized')stored.oversized_embed_key_id='oversized-wrapper';
  if(mode==='cursor-loop'){stored.embed_keys_has_more_after=true;stored.embed_keys_end_cursor='cursor';}
  const before=JSON.stringify(stored);
  m.fetch.mockImplementation(async(url)=>({status:200,ok:true,json:async()=>url.includes('/keys/window')
   ?{embed_keys:stored.embed_keys,has_more_after:true,end_cursor:'cursor'}:stored}));
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});
  expect(errors).toHaveBeenCalled();
  expect(sent.filter(row=>row.type==='store_embed'||row.type==='store_embed_keys'||row.type==='recovery_output_ack_embed')).toHaveLength(0);
  expect(JSON.stringify(stored)).toBe(before);
 });
 // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery
 it('exhausts the scoped wrapper continuation before acknowledging duplicate keys',async()=>{
  const {sent,service,errors}=setup();
  m.fetch.mockImplementation(async(url)=>({status:200,ok:true,json:async()=>url.includes('/keys/window')
   ?{embed_keys:canonical.embed_keys.map(row=>({...row,encrypted_embed_key:row.encrypted_embed_key+'-duplicate'})),has_more_after:false,end_cursor:'end'}
   :{...canonical,embed_keys_has_more_after:true,embed_keys_end_cursor:'first'}}));
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});
  expect(errors).not.toHaveBeenCalled();
  expect(m.fetch.mock.calls.some(([url])=>url.includes('/keys/window?embed_ids=embed&after_key_id=first'))).toBe(true);
  expect(sent.filter(row=>row.type==='store_embed'||row.type==='store_embed_keys')).toHaveLength(0);
  expect(sent.filter(row=>row.type==='recovery_output_ack_embed')).toHaveLength(1);
 });
 // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
 it.each([false,true])('publishes an initial root and its wrappers in one write (failure=%s)',async(failure)=>{
  const {sent,service,emit,errors}=setup();
  let persisted=false;
  m.fetch.mockImplementation(async()=>persisted
   ?{status:200,ok:true,json:async()=>({...canonical,embed:{...canonical.embed,encrypted_content:'encrypted'}})}
   :{status:404,ok:false});
  const originalSend=m.ws.sendMessage.getMockImplementation();
  m.ws.sendMessage.mockImplementation(async(type,payload)=>{
   await originalSend(type,payload);
   if(type==='store_embed'){
    expect(payload.recovery_message_id).toBe('assistant');
    expect(payload.recovery_key_wrappers).toHaveLength(2);
    expect(payload.recovery_record_id).toBe('record');
    if(failure)emit('error',{request_id:payload.request_id,code:'embed_write_denied'});
    else{persisted=true;emit('store_embed_confirmed',{...payload,canonical_source:'head',canonical_digest:'b'.repeat(64)});}
   }
  });
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});
  expect(sent.filter(row=>row.type==='store_embed')).toHaveLength(1);
  expect(sent.filter(row=>row.type==='store_embed_keys')).toHaveLength(0);
  expect(sent.filter(row=>row.type==='recovery_output_ack_embed')).toHaveLength(failure?0:1);
  expect(persisted).toBe(!failure);
  expect(errors.mock.calls.length).toBe(failure?1:0);
 });
 it('advances a sealed v2 root with the verified v1 type ciphertext and wrappers intact',async()=>{
  const v2={...output,output_version:2};
  const {sent,service,emit,errors}=setup({selectedOutput:v2});
  m.openOutput.mockResolvedValue(new TextEncoder().encode(JSON.stringify({
   record_id:'record',target_chat_id:'chat',subject_id:'embed',output_kind:'embed',
   output_version:2,content:{embed_id:'embed',chat_id:'chat',message_id:'assistant',
    content:'{}',type:'code',version_number:2},
  })));
  let version=1;
  m.fetch.mockImplementation(async()=>({status:200,ok:true,json:async()=>({
   ...canonical,embed:{...canonical.embed,version_number:version,
    encrypted_content:version===1?'content-cipher':'encrypted'},
  })}));
  const originalSend=m.ws.sendMessage.getMockImplementation();
  m.ws.sendMessage.mockImplementation(async(type,payload)=>{
   await originalSend(type,payload);
   if(type==='store_embed'){
    expect(payload.version_number).toBe(2);
    expect(payload.encrypted_type).toBe('type-cipher');
    version=2;
    emit('store_embed_confirmed',{...payload,canonical_source:'head',
     canonical_digest:'b'.repeat(64)});
   }
  });
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[v2]});
  expect(errors).not.toHaveBeenCalled();
  expect(sent.filter(row=>row.type==='store_embed')).toHaveLength(1);
  expect(sent.filter(row=>row.type==='store_embed_keys')).toHaveLength(0);
  expect(sent.filter(row=>row.type==='recovery_output_ack_embed')).toHaveLength(1);
 });
 it('rejects a v2 advance when the prior canonical type cannot be authenticated',async()=>{
  const v2={...output,output_version:2};
  const {sent,service,errors}=setup({selectedOutput:v2});
  m.openOutput.mockResolvedValue(new TextEncoder().encode(JSON.stringify({
   record_id:'record',target_chat_id:'chat',subject_id:'embed',output_kind:'embed',
   output_version:2,content:{embed_id:'embed',chat_id:'chat',message_id:'assistant',
    content:'{}',type:'code',version_number:2},
  })));
  m.fetch.mockResolvedValue({status:200,ok:true,json:async()=>({
   ...canonical,embed:{...canonical.embed,encrypted_type:'different-type'},
  })});
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[v2]});
  expect(errors).toHaveBeenCalledWith('[ChatSyncService:Recovery] Output recovery failed:',
   expect.objectContaining({record_id:'record'}),
   expect.objectContaining({message:'Canonical embed type identity mismatch.'}));
  expect(sent.filter(row=>row.type==='store_embed')).toHaveLength(0);
  expect(sent.filter(row=>row.type==='recovery_output_ack_embed')).toHaveLength(0);
 });
 it.each([false,true])('retries once after authoritative completion hydration (terminal receipt=%s)',async(terminal)=>{
  const {sent,service,errors}=setup({terminal});

  m.fetch.mockResolvedValueOnce({status:503,ok:false}).mockImplementation(async()=>({status:200,ok:true,json:async()=>canonical}));
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});
  expect(m.fetch).toHaveBeenCalledTimes(1);
  expect(errors).toHaveBeenCalledWith('[ChatSyncService:Recovery] Output recovery failed:',expect.objectContaining({record_id:'record'}),expect.objectContaining({message:'Canonical embed read failed (503).'}));
  expect(sent.filter(x=>x.type==='recovery_output_get')).toHaveLength(1);
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(0);
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});
  expect(sent.filter(x=>x.type==='recovery_job_persist')).toHaveLength(terminal?0:1);
  expect(m.complete).toHaveBeenCalledWith('chat','turn',2);
  await vi.advanceTimersByTimeAsync(0);
  expect(sent.filter(x=>x.type==='recovery_output_get')).toHaveLength(2);
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(1);
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});
  await vi.advanceTimersByTimeAsync(120000);
  expect(sent.filter(x=>x.type==='recovery_output_get')).toHaveLength(2);
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(1);
  expect(errors).toHaveBeenCalledTimes(1);
 });
 it('distinguishes missing-root skip: no output retrieval or canonical read occurs',async()=>{
  const {sent,service,errors}=setup();m.db.getChat.mockResolvedValue(null);
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});
  expect(sent.filter(x=>x.type==='recovery_output_get')).toHaveLength(0);expect(m.fetch).not.toHaveBeenCalled();expect(errors).not.toHaveBeenCalled();
 });
 it.each([401,403,400,'identity'])('does not retry canonical HTTP/identity failure %s after terminal persistence',async(status)=>{
  const {sent,service}=setup();
  // 404 means missing canonical content, then storing times out only when allowed;
  // use a malformed 200 canonical body instead to test identity failure below.
  if(status==='identity'){m.fetch.mockResolvedValue({status:200,ok:true,json:async()=>({embed:{embed_id:'foreign'}})})}
  else m.fetch.mockResolvedValue({status,ok:false});
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});await vi.advanceTimersByTimeAsync(0);
  expect(sent.filter(x=>x.type==='recovery_output_get')).toHaveLength(1);
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(0);
 });
 it('does not retry again when the single automatic retry also receives 503',async()=>{
  const {sent,service,errors}=setup();m.fetch.mockResolvedValue({status:503,ok:false});
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});await vi.advanceTimersByTimeAsync(0);
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});await vi.advanceTimersByTimeAsync(120000);
  expect(sent.filter(x=>x.type==='recovery_output_get')).toHaveLength(2);expect(errors).toHaveBeenCalledTimes(2);
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(0);
 });
 it.each(['session','owner','key','team'])('fences a pending retry after %s changes',async(change)=>{
  const {sent,service}=setup();m.fetch.mockResolvedValue({status:503,ok:false});
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});
  if(change==='session')resetRecoveryLifecycleImpl();
  if(change==='owner')m.db.getChat.mockResolvedValue({chat_id:'chat',user_id:'different-owner',messages_v:1});
  if(change==='key')m.getKey.mockResolvedValue(new Uint8Array([2]));
  if(change==='team')m.db.getChat.mockResolvedValue({chat_id:'chat',user_id:'owner',team_id:'different-team',messages_v:1});
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});await vi.advanceTimersByTimeAsync(0);
  expect(sent.filter(x=>x.type==='recovery_output_get')).toHaveLength(1);
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(0);
 });
 it('retries when terminal hydration completes before the in-flight canonical read fails',async()=>{
  const {sent,service}=setup();let failRead;
  m.fetch.mockImplementationOnce(()=>new Promise(resolve=>{failRead=resolve})).mockImplementation(async()=>({status:200,ok:true,json:async()=>canonical}));
  const pending=handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});await vi.advanceTimersByTimeAsync(0);
  expect(failRead).toBeTypeOf('function');await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});
  failRead({status:503,ok:false});await pending;await vi.advanceTimersByTimeAsync(0);
  expect(sent.filter(x=>x.type==='recovery_output_get')).toHaveLength(2);
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(1);
 });
 it('does not use another root or turn terminal receipt as retry readiness',async()=>{
  const otherOutput={...output,turn_id:'other-turn'};
  const {sent,service}=setup({selectedOutput:otherOutput});m.fetch.mockResolvedValue({status:503,ok:false});
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[otherOutput]});
  // Valid retrieval fails transiently, but a different turn cannot authorize retry.
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});await vi.advanceTimersByTimeAsync(0);
  expect(sent.filter(x=>x.type==='recovery_output_get')).toHaveLength(1);
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(0);
 });

 it('reconciles canonical storage after a missing store receipt, without acknowledging before verification',async()=>{
  const {sent,service}=setup();m.fetch.mockResolvedValue({status:404,ok:false});
  const pending=handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});
  await vi.advanceTimersByTimeAsync(20000);await pending;
  expect(sent.filter(x=>x.type==='store_embed')).toHaveLength(1);
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(0);
  m.fetch.mockImplementation(async()=>({status:200,ok:true,json:async()=>canonical}));
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});await vi.advanceTimersByTimeAsync(0);
  expect(sent.filter(x=>x.type==='recovery_output_get')).toHaveLength(2);
  expect(sent.filter(x=>x.type==='store_embed')).toHaveLength(1);
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(1);
 });
 it('does not retry cryptographic envelope rejection after terminal hydration',async()=>{
  const {sent,service}=setup();m.openOutput.mockRejectedValue(new Error('decryption failed'));
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[output]});
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});await vi.advanceTimersByTimeAsync(0);
  expect(sent.filter(x=>x.type==='recovery_output_get')).toHaveLength(1);
  expect(m.fetch).not.toHaveBeenCalled();
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(0);
 });

 it('bounds recent retry identities at 128, retains the newest consumed identity, and permits evicted explicit rediscovery',async()=>{
  const {sent,service}=setup();m.fetch.mockResolvedValue({status:503,ok:false});
  m.openOutput.mockImplementation(async()=>new TextEncoder().encode(JSON.stringify({
    record_id:sent.filter(x=>x.type==='recovery_output_get').at(-1).record_id,
    target_chat_id:'chat',subject_id:'embed',output_kind:'embed',output_version:1,
    content:{embed_id:'embed',chat_id:'chat',message_id:'assistant',content:'{}',type:'code',version_number:1},
  })));
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});
  for(let index=0;index<129;index++) {
    await handleRecoveryOutputsAvailableImpl(service,{outputs:[{...output,record_id:`capacity-${index}`}]});
    await vi.advanceTimersByTimeAsync(0);
  }
  const gets=(recordId)=>sent.filter(x=>x.type==='recovery_output_get'&&x.record_id===recordId).length;
  expect(gets('capacity-0')).toBe(2);expect(gets('capacity-128')).toBe(2);
  // The newest identity still suppresses a second automatic attempt.
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[{...output,record_id:'capacity-128'}]});
  await vi.advanceTimersByTimeAsync(0);expect(gets('capacity-128')).toBe(3);
  // The oldest identity was evicted; a later explicit discovery gets one bounded attempt.
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[{...output,record_id:'capacity-0'}]});
  await vi.advanceTimersByTimeAsync(0);expect(gets('capacity-0')).toBe(4);
  await vi.advanceTimersByTimeAsync(120000);expect(gets('capacity-0')).toBe(4);
  expect(sent.filter(x=>x.type==='recovery_output_ack_embed')).toHaveLength(0);
 });

});

describe('confirmed child visibility depends on its acknowledged canonical parent',()=>{
 it.each(['ready','still-missing','unauthorized-parent','wrong-parent','stale-parent','stale-session','owner-change'])('child-before-parent across discovery pages: %s',async(mode)=>{
  const child={...output,record_id:'child-record',subject_id:'child'};
  const parent={...output,record_id:'parent-record',subject_id:mode==='wrong-parent'?'unrelated':'parent'};
  const {sent,service,emit}=setup({selectedOutputs:[child,parent]});
  m.openOutput.mockImplementation(async()=>{
   const record=sent.filter(row=>row.type==='recovery_output_get').at(-1).record_id;
   const row=record===child.record_id?child:parent;
   return new TextEncoder().encode(JSON.stringify({record_id:row.record_id,target_chat_id:'chat',subject_id:row.subject_id,output_kind:'embed',output_version:1,
    content:{embed_id:row.subject_id,chat_id:'chat',message_id:'assistant',content:'{}',type:'code',version_number:1,...(row===child?{parent_embed_id:'parent'}:{})}}));
  });
  const originalSend=m.ws.sendMessage.getMockImplementation();
  m.ws.sendMessage.mockImplementation(async(type,payload)=>{
   await originalSend(type,payload);
   if(type==='store_embed')emit('store_embed_confirmed',{...payload,canonical_source:'head',canonical_digest:'a'.repeat(64)});
  });
  let parentReady=false;
  m.fetch.mockImplementation(async(url)=>{
   const id=String(url).split('/').at(-1);
   if(id==='child'&&(!parentReady||mode==='still-missing'))return {status:404,ok:false};
   if(id!=='child'&&mode==='unauthorized-parent')return {status:403,ok:false};
   return {status:200,ok:true,json:async()=>({...canonical,embed:{...canonical.embed,embed_id:id,...(id==='parent'&&mode==='stale-parent'?{version_number:2}:{})},embed_keys:canonical.embed_keys.map(row=>({...row,hashed_embed_id:'hash:'+id}))})};
  });
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[child]});
  expect(sent.filter(row=>row.type==='store_embed')).toHaveLength(1);
  expect(sent.filter(row=>row.type==='recovery_output_ack_embed')).toHaveLength(0);
  // Terminal hydration alone must not consume the dependency-specific attempt.
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});await vi.advanceTimersByTimeAsync(0);
  expect(sent.filter(row=>row.type==='recovery_output_get'&&row.record_id===child.record_id)).toHaveLength(1);
  if(mode==='stale-session')resetRecoveryLifecycleImpl();
  if(mode==='owner-change')m.db.getChat.mockResolvedValue({chat_id:'chat',user_id:'other-owner',messages_v:2});
  parentReady=true;
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[parent]});await vi.advanceTimersByTimeAsync(0);
  const childGets=()=>sent.filter(row=>row.type==='recovery_output_get'&&row.record_id===child.record_id);
  expect(childGets()).toHaveLength(['ready','still-missing'].includes(mode)?2:1);
  expect(sent.filter(row=>row.type==='recovery_output_ack_embed'&&row.record_id===child.record_id)).toHaveLength(mode==='ready'?1:0);
  // Duplicate parent delivery/readiness cannot start another child attempt.
  await handleRecoveryOutputsAvailableImpl(service,{outputs:[parent]});
  await handleRecoveryJobsAvailableImpl(service,{jobs:[job]});await vi.advanceTimersByTimeAsync(120000);
  expect(childGets()).toHaveLength(['ready','still-missing'].includes(mode)?2:1);
  expect(sent.filter(row=>row.type==='recovery_output_ack_embed'&&row.record_id===child.record_id)).toHaveLength(mode==='ready'?1:0);
 });
});
