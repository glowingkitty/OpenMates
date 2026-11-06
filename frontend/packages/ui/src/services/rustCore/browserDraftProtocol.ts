/// <reference lib="es2022.object" />
/** Closed platform IO transport only. Rust owns encryption, draft versions,
 * tombstones, pending synchronization and original-resource authorization. */
export const MAX_DRAFT_MARKDOWN_BYTES=1_000_000;
export const MAX_DRAFT_PACKET_BYTES=2*1024*1024;
export const DRAFT_PREDICATES=/* @__PURE__ */ Object.freeze(['chat_id','id','user_id','owner_id','team_id','hashed_team_id','chat_visibility','encrypted_chat_key','key_version','key_fingerprint','messages_v','draft_v','cleared_draft_v','encrypted_draft_md','encrypted_draft_preview','updated_at'] as const);
export const DRAFT_WRITES=/* @__PURE__ */ Object.freeze(['encrypted_draft_md','encrypted_draft_preview','draft_v','updated_at'] as const);
export type DraftProjection=Record<typeof DRAFT_PREDICATES[number],{present:boolean;value:unknown}>;
export interface BrowserDraftScope{lifecycleGeneration:number;workspaceEpoch:number}
export interface BrowserDraftPlan{
 version:1;kind:'capture_draft'|'store_draft'|'readback_draft'|'ack_draft';operationId:string;
 owner:string;chatId:string;scope:BrowserDraftScope;expected:DraftProjection|null;
 queueMaximum:number|null;patch:Record<typeof DRAFT_WRITES[number],string|number>|null;
 change:{change_id:string;chat_id:string;type:'draft';value:string;encrypted_draft_preview:string;version_before_edit:number;queue_order:number;queue_token:string}|null;
}
export interface BrowserDraftResult{source:'browser_rust_draft';chatId:string;version:number;localSaved:true;remoteSynced:boolean;pending:boolean;credentialAcknowledged:false}
export interface BrowserDraftRestore{source:'browser_rust_draft';chatId:string;version:number;present:boolean;markdown:string;preview:string|null;localOnly:boolean;credentialAcknowledged:false}
export interface BrowserDraftEffectHandler{current():void;execute(encoded:string,signal:AbortSignal):Promise<string>;close():Promise<void>}
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&Object.getPrototypeOf(v)===Object.prototype;
const exact=(v:Record<string,unknown>,keys:readonly string[])=>Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const uuid=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(v);
const integer=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0;
const PLAN_KINDS:readonly unknown[]=['capture_draft','store_draft','readback_draft','ack_draft'];
const RESOURCE_OPERATIONS:readonly unknown[]=['sync_draft','cancel_draft','close_draft'];
export function draftProjection(raw:Record<string,unknown>):DraftProjection{return Object.fromEntries(DRAFT_PREDICATES.map(field=>[field,{present:Object.hasOwn(raw,field),value:Object.hasOwn(raw,field)?raw[field]:null}])) as DraftProjection;}
function projection(v:unknown):v is DraftProjection{return record(v)&&exact(v,DRAFT_PREDICATES)&&DRAFT_PREDICATES.every(field=>record(v[field])&&exact(v[field],['present','value'])&&typeof v[field].present==='boolean'&&(v[field].present||v[field].value===null));}
export function parseBrowserDraftPlan(encoded:string):BrowserDraftPlan{
 if(typeof encoded!=='string'||new TextEncoder().encode(encoded).length>MAX_DRAFT_PACKET_BYTES)throw Error('invalid_draft_plan');
 const v:unknown=JSON.parse(encoded);
 if(!record(v)||!exact(v,['version','kind','operationId','owner','chatId','scope','expected','queueMaximum','patch','change'])||v.version!==1||!PLAN_KINDS.includes(v.kind)||!uuid(v.operationId)||!uuid(v.owner)||!uuid(v.chatId)||!record(v.scope)||!exact(v.scope,['lifecycleGeneration','workspaceEpoch'])||!integer(v.scope.lifecycleGeneration)||v.scope.lifecycleGeneration===0||!integer(v.scope.workspaceEpoch))throw Error('invalid_draft_plan');
 if(v.kind==='capture_draft'){if(v.expected!==null||v.queueMaximum!==null||v.patch!==null||v.change!==null)throw Error('invalid_draft_plan');}
 else{
  if(!projection(v.expected)||!integer(v.queueMaximum)||!record(v.patch)||!exact(v.patch,DRAFT_WRITES)||typeof v.patch.encrypted_draft_md!=='string'||typeof v.patch.encrypted_draft_preview!=='string'||!integer(v.patch.draft_v)||!integer(v.patch.updated_at))throw Error('invalid_draft_plan');
  const c=v.change;if(!record(c)||!exact(c,['change_id','chat_id','type','value','encrypted_draft_preview','version_before_edit','queue_order','queue_token'])||!uuid(c.change_id)||!uuid(c.queue_token)||c.chat_id!==v.chatId||c.type!=='draft'||typeof c.value!=='string'||typeof c.encrypted_draft_preview!=='string'||!integer(c.version_before_edit)||!integer(c.queue_order)||c.queue_order===0)throw Error('invalid_draft_plan');
 }
 // Every field of BrowserDraftPlan was validated above; the record type cannot express that.
 return v as unknown as BrowserDraftPlan;
}
export type BrowserDraftRequest={handle:string;generation:number;expectedPrincipal:string}&(
 |{operation:'prepare_local_draft';chatId:string;markdown:Uint8Array;scope:BrowserDraftScope;nowSeconds:number}
 |{operation:'restore_local_draft';chatId:string;scope:BrowserDraftScope}
 |{operation:'sync_draft'|'cancel_draft'|'close_draft';resourceId:string}
);
export type BrowserDraftReply={kind:'local';resourceId:string;result:BrowserDraftResult}|{kind:'synced';result:BrowserDraftResult}|{kind:'restored';result:BrowserDraftRestore}|{kind:'cancelled'|'closed'};
export interface BrowserDraftHostPort{requestDraft(input:BrowserDraftRequest,signal:AbortSignal,effects:BrowserDraftEffectHandler):Promise<BrowserDraftReply>}
export function validBrowserDraftResult(v:unknown):v is BrowserDraftResult{return record(v)&&exact(v,['source','chatId','version','localSaved','remoteSynced','pending','credentialAcknowledged'])&&v.source==='browser_rust_draft'&&uuid(v.chatId)&&integer(v.version)&&v.version>0&&v.localSaved===true&&typeof v.remoteSynced==='boolean'&&v.pending===!v.remoteSynced&&v.credentialAcknowledged===false;}
export function validBrowserDraftRestore(v:unknown):v is BrowserDraftRestore{return record(v)&&exact(v,['source','chatId','version','present','markdown','preview','localOnly','credentialAcknowledged'])&&v.source==='browser_rust_draft'&&uuid(v.chatId)&&integer(v.version)&&typeof v.present==='boolean'&&(v.present?v.version>0:v.markdown===''&&v.preview===null)&&typeof v.markdown==='string'&&new TextEncoder().encode(v.markdown).length<=MAX_DRAFT_MARKDOWN_BYTES&&(v.preview===null||typeof v.preview==='string')&&v.localOnly===true&&v.credentialAcknowledged===false;}
export function validBrowserDraftRequest(v:unknown):v is BrowserDraftRequest{
 if(!record(v)||!uuid(v.handle)||!uuid(v.expectedPrincipal)||!integer(v.generation)||v.generation<1)return false;
 const base=['handle','generation','expectedPrincipal','operation'];
 if(v.operation==='prepare_local_draft'||v.operation==='restore_local_draft'){
  if(!uuid(v.chatId)||!record(v.scope)||!exact(v.scope,['lifecycleGeneration','workspaceEpoch'])||!integer(v.scope.lifecycleGeneration)||v.scope.lifecycleGeneration<1||!integer(v.scope.workspaceEpoch))return false;
  if(v.operation==='restore_local_draft')return exact(v,[...base,'chatId','scope']);
  return exact(v,[...base,'chatId','scope','markdown','nowSeconds'])&&v.markdown instanceof Uint8Array&&v.markdown.byteLength<=MAX_DRAFT_MARKDOWN_BYTES&&integer(v.nowSeconds);
 }
 return RESOURCE_OPERATIONS.includes(v.operation)&&exact(v,[...base,'resourceId'])&&uuid(v.resourceId);
}
