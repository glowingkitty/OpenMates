/// <reference lib="es2022.object" />
import { boundedJson, validReadMessageId } from './savedReadProtocol';
/** Request-local physical-read observations only. Neither labels nor readiness
 * confer admission, key availability, durability or permission to fall back. */
export interface OwnedLocalReadState {readonly count:number;readonly metadataMissing:boolean;readonly pending:boolean;}
type Row=Record<string,unknown>;
interface Ledger {plans:Row[];replies:Row[];pending:boolean;failed:boolean;owner:string|null;chatId:string|null;metadataBytes:number;}
const ledgers=new WeakMap<OwnedLocalReadState,Ledger>(),CAP=262144;
const integer=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0;
const positive=(v:unknown):v is number=>integer(v)&&v>0;
const uuid=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(v);
const row=(v:unknown):v is Row=>v!==null&&typeof v==='object'&&Object.getPrototypeOf(v)===Object.prototype;
const exact=(v:unknown,keys:string[]):v is Row=>row(v)&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const bytes=(s:string)=>new TextEncoder().encode(s).byteLength;
function refuse():never{throw Error('unavailable');}
function ledger(state:OwnedLocalReadState):Ledger {const s=ledgers.get(state);if(!s)refuse();return s;}
function equal(a:unknown,b:unknown):boolean {
  if(a===b)return true;
  if(Array.isArray(a)||Array.isArray(b))return Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((v,i)=>equal(v,b[i]));
  return row(a)&&row(b)&&Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>Object.hasOwn(b,k)&&equal(a[k],b[k]));
}
function parse(encoded:string,limit:number):Row {
  if(typeof encoded!=='string'||bytes(encoded)>limit)refuse();
  const value:unknown=JSON.parse(encoded);if(!row(value)||!boundedJson(value))refuse();return value;
}
function optional(v:Row,keys:string[],check:(value:unknown)=>boolean):boolean{return keys.every(k=>v[k]===undefined||v[k]===null||check(v[k]));}
function metadata(v:unknown,owner:string,chat:string):boolean {
  if(!row(v)||v.id!==chat||v.chat_id!==chat||!optional(v,['user_id'],x=>x===owner)
    ||!optional(v,['team_id','hashed_team_id'],x=>x==='')||!optional(v,['chat_visibility'],x=>x===''||x==='personal'))return false;
  return optional(v,['encrypted_chat_key','encrypted_title','encrypted_chat_summary','encrypted_category','encrypted_icon','encrypted_follow_up_request_suggestions','encrypted_share_cta_text','encrypted_chat_tags','encrypted_suggested_followup_message','encrypted_active_focus_id','encrypted_focus_phase_state','encrypted_auto_speak_response'],x=>typeof x==='string')
    &&optional(v,['title_v','metadata_v','messages_v','created_at','updated_at','last_edited_overall_timestamp','key_version'],integer);
}
function checkpoints(v:unknown,chat:string):boolean {
  if(!Array.isArray(v)||v.length>128)return false;const seen=new Set();
  return v.every(x=>row(x)&&x.chat_id===chat&&validReadMessageId(x.id)&&!seen.has(x.id)&&!!seen.add(x.id)
    &&integer(x.created_at)&&integer(x.compressed_up_to_timestamp)&&integer(x.compressed_message_count)
    &&optional(x,['compressed_up_to_message_id'],validReadMessageId)&&optional(x,['encrypted_summary'],v=>typeof v==='string')
    &&optional(x,['covered_message_ids'],v=>Array.isArray(v)&&v.length<=1024&&v.every(validReadMessageId)));
}
function position(v:Row):{createdAt:number;messageId:string}|null {
  const id=typeof v.message_id==='string'&&v.message_id?v.message_id:v.id;
  return validReadMessageId(id)&&integer(v.created_at)?{createdAt:v.created_at,messageId:id}:null;
}
function cmp(a:{createdAt:number;messageId:string},b:{createdAt:number;messageId:string}):number {
  return a.createdAt===b.createdAt?(a.messageId===b.messageId?0:a.messageId<b.messageId?-1:1):a.createdAt<b.createdAt?-1:1;
}
function messages(v:Row,p:Row):boolean {
  if(!Array.isArray(v.messages)||v.messages.length>Number(p.maxPayloadRows)||typeof v.rangeExhausted!=='boolean')return false;
  const next=v.nextKey;
  if(next!==null&&(!exact(next,['createdAt','messageId'])||!integer(next.createdAt)||!validReadMessageId(next.messageId)))return false;
  if(v.rangeExhausted!==(next===null)||next!==null&&v.messages.length!==p.maxPayloadRows)return false;
  const physical=new Set(),logical=new Set();let previous:ReturnType<typeof position>=null;
  for(const value of v.messages){
    if(!row(value)||value.chat_id!==undefined&&value.chat_id!==p.chatId)return false;
    const pos=position(value),id=[value.client_message_id,value.message_id,value.id].find(x=>typeof x==='string'&&x!=='');
    if(!pos||!validReadMessageId(id)||physical.has(pos.messageId)||logical.has(id)||previous&&cmp(previous,pos)<=0
      ||row(p.lower)&&pos.createdAt<=Number(p.lower.createdAt)||typeof value.role!=='string'||!value.role||bytes(value.role)>32
      ||!optional(value,['id','message_id','client_message_id'],validReadMessageId)
      ||!optional(value,['encrypted_content','encrypted_sender_name','encrypted_category','encrypted_model_name','encrypted_thinking_content','encrypted_thinking_signature','encrypted_pii_mappings'],x=>typeof x==='string'))return false;
    if(value.large_payload!==undefined&&value.large_payload!==null){const r=value.large_payload;
      if(!row(r)||!positive(r.size_bytes)||r.size_bytes>2*1024*1024||typeof r.checksum!=='string'||!/^[0-9a-f]{64}$/.test(r.checksum)||typeof r.object_key!=='string'||!r.object_key)return false;}
    physical.add(pos.messageId);logical.add(id);previous=pos;
  }
  if(next!==null){const n=next as {createdAt:number;messageId:string};if(!previous||cmp(n,previous)>=0||row(p.lower)&&n.createdAt<=Number(p.lower.createdAt))return false;}
  return true;
}
export function createOwnedLocalReadState():OwnedLocalReadState {
  const s:Ledger={plans:[],replies:[],pending:false,failed:false,owner:null,chatId:null,metadataBytes:0};
  const state=Object.freeze({get count(){return s.replies.length;},get metadataMissing(){return s.replies.length>0&&s.replies[0].chat_metadata===null;},get pending(){return s.pending;}});
  ledgers.set(state,s);return state;
}
export function beginOwnedLocalRead(state:OwnedLocalReadState,encoded:string,expected:{owner:string;chatId:string}):void {
  const s=ledger(state),overlap=s.pending;s.pending=true;
  try {
    if(s.failed||overlap||s.plans.length>=4||s.plans.length!==s.replies.length||state.metadataMissing)refuse();
    const p=parse(encoded,CAP),index=s.plans.length;
    if(JSON.stringify(p)!==encoded)refuse();
    if(!exact(p,['version','kind','operationId','owner','chatId','maxPacketBytes','maxCheckpointRows','maxPayloadRows','lower','upper','direction'])
      ||p.version!==1||!uuid(p.operationId)||!uuid(p.owner)||!uuid(p.chatId)||p.owner!==expected.owner||p.chatId!==expected.chatId
      ||s.owner!==null&&(s.owner!==p.owner||s.chatId!==p.chatId)||p.upper!==null)refuse();
    if(index%2===0){if(p.kind!=='owned_metadata'||p.maxPacketBytes!==CAP||p.maxCheckpointRows!==128||p.maxPayloadRows!==0||p.lower!==null||p.direction!=='next')refuse();}
    else if(p.kind!=='messages'||!integer(p.maxPacketBytes)||p.maxPacketBytes<1024||p.maxPacketBytes>CAP-2048
      ||p.maxCheckpointRows!==0||!positive(p.maxPayloadRows)||p.maxPayloadRows>20||p.direction!=='prev'
      ||p.lower!==null&&(!exact(p.lower,['createdAt','messageId','open'])||!integer(p.lower.createdAt)||p.lower.messageId!==null||p.lower.open!==true))refuse();
    if(index>0&&p.operationId!==s.plans[0].operationId||index>=2&&!equal(p,s.plans[index-2]))refuse();
    s.owner=p.owner as string;s.chatId=p.chatId as string;s.plans.push(p);
  }catch{s.failed=true;refuse();}
}
export function completeOwnedLocalRead(state:OwnedLocalReadState,packet:string):void {
  const s=ledger(state);
  try {
    if(s.failed||!s.pending||s.plans.length!==s.replies.length+1)refuse();
    const index=s.replies.length,p=s.plans[index],v=parse(packet,Number(p.maxPacketBytes));
    if(v.version!==1||v.kind!==p.kind||v.operationId!==p.operationId||!positive(v.databaseVersion)
      ||index>0&&v.databaseVersion!==s.replies[0].databaseVersion)refuse();
    if(index%2===0){
      if(!exact(v,['version','kind','operationId','databaseVersion','chat_metadata','messages','wrappers','boundary','compression_checkpoints'])
        ||!Array.isArray(v.messages)||v.messages.length!==0||!Array.isArray(v.wrappers)||v.wrappers.length!==0||v.boundary!==null
        ||!checkpoints(v.compression_checkpoints,s.chatId!)
        ||(v.chat_metadata===null?(!Array.isArray(v.compression_checkpoints)||v.compression_checkpoints.length!==0):!metadata(v.chat_metadata,s.owner!,s.chatId!)))refuse();
    }else if(s.metadataBytes+bytes(packet)>CAP-2048||!exact(v,['version','kind','operationId','databaseVersion','messages','nextKey','rangeExhausted'])||!messages(v,p))refuse();
    if(index>=2&&!equal(v,s.replies[index-2]))refuse();
    // Preserve the actual native wire size; Rust and JS float spellings differ.
    if(index%2===0)s.metadataBytes=bytes(packet);
    s.replies.push(v);s.pending=false;
  }catch{s.failed=true;s.pending=true;refuse();}
}
export function ownedLocalReadReady(state:OwnedLocalReadState):boolean {const s=ledger(state);return !s.failed&&!s.pending&&s.replies.length===4&&!state.metadataMissing;}
export function ownedLocalReadFallbackReady(state:OwnedLocalReadState):boolean {const s=ledger(state);return !s.failed&&!s.pending&&(s.replies.length===1&&state.metadataMissing||s.replies.length===4&&!state.metadataMissing);}
