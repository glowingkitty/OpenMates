/// <reference lib="es2022.object" />
/** Inactive closed transport shapes; Rust owns all restore/merge/key policy. */
import {validCheckpointPresentation,boundedJson,validReadMessageId,validSavedReadData} from './savedReadProtocol';
import type {CheckpointPresentation,SavedReadData} from './savedReadProtocol';
export interface BrowserRetainedRead extends SavedReadData {
 source:'browser_retained_message_cache';readOnly:true;cached:true;fresh:false;historyComplete:false;
 coverage:'retained_rows_only';piiRestoration:'page_local';pagesRead:0;
 hasMoreBefore:null;hasMoreAfter:null;startCursor:null;endCursor:null;anchorFound:false;checkpointPresentation:null|CheckpointPresentation;
 cacheReadKind?:'cold'|'monitor'|'local';contentCoverage?:'unknown';
 rowDispositions:Array<{messageId:string;storedPhysicalMessageId?:string;incomingPhysicalMessageId?:string;disposition:'retained'|'merged'|'inserted'|'replaced'|'retained_local';incomingSuppliedWriteFieldsMatch:boolean;canonicalIncomingDurablyAcknowledged:false}>;
 messagesVersionAdvanced:false;windowCoverageChanged:false;canonicalIncomingDurablyAcknowledged:false;
 credentialAcknowledged:false;nativeDurabilityAcknowledged:false;crossDatabaseAssociationProven:false;inventoryComplete:false;recoveryProof:false;
}
const negative=['fresh','historyComplete','anchorFound','messagesVersionAdvanced','windowCoverageChanged',
 'canonicalIncomingDurablyAcknowledged','credentialAcknowledged','nativeDurabilityAcknowledged','crossDatabaseAssociationProven','inventoryComplete','recoveryProof'] as const;
function record(v:unknown):v is Record<string,unknown>{return !!v&&typeof v==='object'&&Object.getPrototypeOf(v)===Object.prototype;}
function exact(v:Record<string,unknown>,fields:readonly string[]):boolean{return Object.keys(v).length===fields.length&&fields.every(k=>Object.hasOwn(v,k));}
export function validBrowserRetainedRead(value:unknown):value is BrowserRetainedRead {
 if(!record(value)||!validSavedReadData(value))return false;
 const extended=Object.hasOwn(value,'cacheReadKind');
 if(!exact(value,['source','readOnly','cached',...negative,'coverage','chat','chatMetadata','messageMetadata',
  'piiMappingsByMessageId','piiRestoration','pagesRead','hasMoreBefore','hasMoreAfter','startCursor','endCursor','checkpointPresentation','rowDispositions',...(extended?['cacheReadKind','contentCoverage']:[])])
  ||value.source!=='browser_retained_message_cache'||value.readOnly!==true||value.cached!==true||value.coverage!=='retained_rows_only'
  ||extended&&(!['cold','monitor','local'].includes(String(value.cacheReadKind))||value.contentCoverage!=='unknown')
  ||value.piiRestoration!=='page_local'||value.pagesRead!==0||!negative.every(k=>value[k]===false)
  ||!['hasMoreBefore','hasMoreAfter','startCursor','endCursor'].every(k=>value[k]===null)
  ||(value.cacheReadKind==='local'?!validCheckpointPresentation(value.checkpointPresentation,value.chat.id,'retained_latest'):value.checkpointPresentation!==null)
  ||!Array.isArray(value.rowDispositions)||value.rowDispositions.length!==value.chat.messages.length)return false;
 const storage=new Set<string>();
 for(const meta of value.messageMetadata){const physical=extended?meta.sourceMessageId:meta.storageId;if(!validReadMessageId(physical)||storage.has(physical))return false;storage.add(physical);}
 const seen=new Set<string>();
 return value.rowDispositions.every(row=>record(row)&&exact(row,['messageId','disposition','incomingSuppliedWriteFieldsMatch','canonicalIncomingDurablyAcknowledged',...(extended?['storedPhysicalMessageId','incomingPhysicalMessageId']:[])])
  &&validReadMessageId(row.messageId)&&storage.has(row.messageId)&&!seen.has(row.messageId)&&!!seen.add(row.messageId)
  &&(extended?(row.storedPhysicalMessageId===row.messageId&&validReadMessageId(row.incomingPhysicalMessageId)
    &&(value.cacheReadKind==='local'?row.disposition==='retained_local'&&row.incomingSuppliedWriteFieldsMatch===false:value.cacheReadKind==='monitor'?['retained','merged','inserted','replaced'].includes(String(row.disposition)):['retained','merged','inserted'].includes(String(row.disposition)))
    &&(row.incomingPhysicalMessageId===row.storedPhysicalMessageId||value.cacheReadKind==='monitor'&&row.disposition==='retained')):(row.disposition==='retained'||row.disposition==='merged'))
  &&typeof row.incomingSuppliedWriteFieldsMatch==='boolean'&&row.canonicalIncomingDurablyAcknowledged===false);
}
export function retainedKindMatches(operation:string,value:BrowserRetainedRead):boolean {
 return operation==='read_cold_retained_saved_chat'?value.cacheReadKind==='cold':operation==='read_monitored_retained_saved_chat'?value.cacheReadKind==='monitor':value.cacheReadKind===undefined;
}

export interface BrowserCachedMetadataRead {
 source:'browser_cached_metadata';cached:true;fresh:false;readOnly:true;selected:true;inventoryComplete:false;
 historyComplete:false;messagesPersisted:false;metadataOnly:true;metadataRestored:boolean;
 credentialAcknowledged:false;nativeDurabilityAcknowledged:false;recoveryProof:false;
 items:Array<{id:string;title:string;description:string;status:string;category:string;fields:Record<string,unknown>}>;
}
function validCachedItemFields(v:unknown):boolean {
 if(!record(v)||!exact(v,['created_at','updated_at','pinned','messages_v','chat_list_title']))return false;
 return ['created_at','updated_at','messages_v'].every(k=>v[k]===null||Number.isSafeInteger(v[k])&&Number(v[k])>=0)
  &&(v.pinned===null||typeof v.pinned==='boolean')&&(v.chat_list_title===null||typeof v.chat_list_title==='string');
}
export function validBrowserCachedMetadataRead(v:unknown):v is BrowserCachedMetadataRead {
 const flags=['fresh','inventoryComplete','historyComplete','messagesPersisted','credentialAcknowledged','nativeDurabilityAcknowledged','recoveryProof'];
 return record(v)&&boundedJson(v)&&exact(v,['source','cached','readOnly','selected','metadataOnly','metadataRestored','items',...flags])
  &&v.source==='browser_cached_metadata'&&v.cached===true&&v.readOnly===true&&v.selected===true&&v.metadataOnly===true
  &&typeof v.metadataRestored==='boolean'&&flags.every(k=>v[k]===false)&&Array.isArray(v.items)&&v.items.length>0&&v.items.length<=20
  &&new Set(v.items.map(row=>record(row)?row.id:null)).size===v.items.length
  &&v.items.every(row=>record(row)&&exact(row,['id','title','description','status','category','fields'])
   &&typeof row.id==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(row.id)
   &&['title','description','status','category'].every(k=>typeof row[k]==='string')&&new TextEncoder().encode(row.title as string).byteLength<=4096
   &&validCachedItemFields(row.fields));
}

export interface BrowserCacheScope {lifecycleGeneration:number;workspaceEpoch:number}
export type BrowserCacheOperation='restore_cached_metadata'|'read_cached_chat_items'|'read_retained_saved_chat'|'read_cold_retained_saved_chat'|'read_monitored_retained_saved_chat'|'read_cache_monitor_update'|'read_owned_selected_message_cache';
export interface BrowserCacheEffect {version:1;id:number;effectId:number;cacheEffect:string;cacheStage?:'owned_selected'|'owned_local';cacheDraftBudget?:'original_physical_draft'}
export interface BrowserCacheReply {version:1;id:number;effectId:number;cacheDraftBudget?:'original_physical_draft';cacheReply:{ok:true;packet:string}|{ok:false;error:'unavailable'|'cancelled'}}
export interface BrowserCacheEffectHandler {current():void;execute(plan:string,signal:AbortSignal,originalPhysicalDraft?:true,ownedLocal?:true):Promise<string>;close():Promise<void>}
export interface BrowserCachePlanState {effects:number;rows:Map<string,{operationId:string;phase:number;readbackKind?:string}>}
function integer(v:unknown):v is number{return Number.isSafeInteger(v)&&Number(v)>=0;}
function uuid(v:unknown):v is string{return typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(v);}
export function validBrowserCacheScope(v:unknown):v is BrowserCacheScope{return record(v)&&boundedJson(v)&&exact(v,['lifecycleGeneration','workspaceEpoch'])&&integer(v.lifecycleGeneration)&&v.lifecycleGeneration>0&&integer(v.workspaceEpoch);}
export function validBrowserCacheEffect(v:unknown):v is BrowserCacheEffect{
 if(!record(v))return false;const keys=['version','id','effectId','cacheEffect'];
 if(Object.hasOwn(v,'cacheStage')){if(v.cacheStage!=='owned_selected'&&v.cacheStage!=='owned_local')return false;keys.push('cacheStage');}
 if(Object.hasOwn(v,'cacheDraftBudget')){if(v.cacheDraftBudget!=='original_physical_draft')return false;keys.push('cacheDraftBudget');}
 return exact(v,keys)&&v.version===1&&integer(v.id)&&v.id>0&&integer(v.effectId)&&v.effectId>0&&typeof v.cacheEffect==='string'&&new TextEncoder().encode(v.cacheEffect).byteLength<=256*1024;
}
export function validBrowserCacheReply(v:unknown):v is BrowserCacheReply{
 if(!record(v))return false;const keys=['version','id','effectId','cacheReply'];let max=256*1024;
 if(Object.hasOwn(v,'cacheDraftBudget')){if(v.cacheDraftBudget!=='original_physical_draft')return false;keys.push('cacheDraftBudget');max=4*1024*1024;}
 return exact(v,keys)&&v.version===1&&integer(v.id)&&v.id>0&&integer(v.effectId)&&v.effectId>0&&record(v.cacheReply)
 &&(v.cacheReply.ok===true?exact(v.cacheReply,['ok','packet'])&&typeof v.cacheReply.packet==='string'&&new TextEncoder().encode(v.cacheReply.packet).byteLength<=max:exact(v.cacheReply,['ok','error'])&&v.cacheReply.ok===false&&['unavailable','cancelled'].includes(String(v.cacheReply.error)));
}
export interface BrowserIncomingCacheUpdate {
 source:'browser_incoming_cache_sync';readOnly:true;metadata:Record<string,unknown>;selected:BrowserRetainedRead|null;
 canonicalIncomingDurablyAcknowledged:false;historyComplete:false;inventoryComplete:false;recoveryProof:false;
 credentialAcknowledged:false;nativeDurabilityAcknowledged:false;
}
export function validBrowserIncomingCacheUpdate(value:unknown):value is BrowserIncomingCacheUpdate {
 const flags=['canonicalIncomingDurablyAcknowledged','historyComplete','inventoryComplete','recoveryProof','credentialAcknowledged','nativeDurabilityAcknowledged'];
 if(!record(value)||!boundedJson(value)||!exact(value,['source','readOnly','metadata','selected',...flags])
  ||value.source!=='browser_incoming_cache_sync'||value.readOnly!==true||!flags.every(k=>value[k]===false))return false;
 const m=value.metadata,negative=['inventoryComplete','historyComplete','messagesVersionAdvanced','canonicalIncomingWindow','selectedWindowPublished','credentialAcknowledged','nativeDurabilityAcknowledged','crossDatabaseAssociationProven','recoveryProof'];
 if(!record(m)||!exact(m,['source','metadataOnly','metadataRowsPersisted','draftRowsNotPersisted','selectedChatInvalidated','items',...negative])
  ||m.source!=='browser_metadata_monitor'||m.metadataOnly!==true||!negative.every(k=>m[k]===false)
  ||!integer(m.metadataRowsPersisted)||m.metadataRowsPersisted>120||!integer(m.draftRowsNotPersisted)||m.draftRowsNotPersisted>120
  ||m.metadataRowsPersisted+m.draftRowsNotPersisted>120||!(m.selectedChatInvalidated===null||uuid(m.selectedChatInvalidated))
  ||!Array.isArray(m.items)||new Set(m.items.map(row=>record(row)?row.id:null)).size!==m.items.length)return false;
 if(!m.items.every(row=>record(row)&&exact(row,['id','title','description','status','category','fields'])&&uuid(row.id)
  &&['title','description','status','category'].every(k=>typeof row[k]==='string')
  &&(validCachedItemFields(row.fields)||(row.status==='draft'||row.status==='locked')&&record(row.fields)&&exact(row.fields,['chat_list_title'])&&row.fields.chat_list_title===null)))return false;
 return value.selected===null||validBrowserRetainedRead(value.selected)&&value.selected.cacheReadKind==='monitor'
  &&m.selectedChatInvalidated===value.selected.chat.id;
}
function incomingPlan(state:BrowserCachePlanState,p:Record<string,unknown>,expected:{ids:string[]}):void {
 const stores=p.stores,messages=Array.isArray(stores),chat=p.chatId as string,key=(messages?'messages:':'metadata:')+chat;
 if(messages){if(stores.length!==2||stores[0]!=='chats'||stores[1]!=='messages'||!expected.ids.includes(chat)||Object.hasOwn(p,'store'))throw Error('unavailable');}
 else if(p.store!=='chats'||Object.hasOwn(p,'stores'))throw Error('unavailable');
 const prior=state.rows.get(key);let phase:number;
 if(!prior){if(p.kind!==(messages?'capture_monitor_candidates':'capture')||state.rows.size>=121)throw Error('unavailable');phase=1;}
 else {if(prior.operationId!==p.operationId)throw Error('unavailable');
  if(messages){if(prior.phase===1&&p.kind==='compare_and_replace_monitor_candidates')phase=2;else if(prior.phase===2&&(p.kind==='readback'||p.kind==='readback_metadata_only'))phase=3;else if(prior.phase===3&&p.kind===prior.readbackKind)phase=4;else throw Error('unavailable');}
  else if(prior.phase===1&&p.kind==='compare_and_patch')phase=2;else if(prior.phase===2&&p.kind==='readback')phase=3;else throw Error('unavailable');
 }
 state.rows.set(key,{operationId:p.operationId as string,phase,...(messages&&phase===3?{readbackKind:String(p.kind)}:prior?.readbackKind?{readbackKind:prior.readbackKind}:{})});state.effects++;
}
/** Platform effect routing only. No row merge, crypto, auth or proof policy. */
export function advanceBrowserCachePlan(state:BrowserCachePlanState,encoded:string,expected:{operation:BrowserCacheOperation;owner:string;ids:string[];scope:BrowserCacheScope}):void {
 if(state.effects>=(expected.operation==='read_cache_monitor_update'?364:60)||new TextEncoder().encode(encoded).byteLength>256*1024)throw Error('unavailable');
 const p:unknown=JSON.parse(encoded);if(!record(p)||!boundedJson(p)||p.version!==1||!uuid(p.operationId)||p.owner!==expected.owner
  ||typeof p.chatId!=='string'||!(expected.operation==='read_cache_monitor_update'?uuid(p.chatId):expected.ids.includes(p.chatId))||!validBrowserCacheScope(p.scope)
  ||p.scope.lifecycleGeneration!==expected.scope.lifecycleGeneration||p.scope.workspaceEpoch!==expected.scope.workspaceEpoch||p.database!=='chats_db')throw Error('unavailable');
 if(expected.operation==='read_cache_monitor_update'){incomingPlan(state,p,expected);return;}
 const retained=expected.operation==='read_retained_saved_chat'||expected.operation==='read_cold_retained_saved_chat'||expected.operation==='read_monitored_retained_saved_chat'||expected.operation==='read_owned_selected_message_cache';
 if(retained?(!Array.isArray(p.stores)||p.stores.length!==2||p.stores[0]!=='chats'||p.stores[1]!=='messages'):(p.store!=='chats'||Object.hasOwn(p,'stores')))throw Error('unavailable');
 const prior=state.rows.get(p.chatId);let phase:number;
 if(!prior){const first=(expected.operation==='read_cold_retained_saved_chat'||expected.operation==='read_owned_selected_message_cache')?'capture_cold_incoming_insert':expected.operation==='read_monitored_retained_saved_chat'?'capture_monitor_candidates':'capture';if(p.kind!==first)throw Error('unavailable');phase=1;}
 else{if(prior.operationId!==p.operationId)throw Error('unavailable');
  if(retained){const commit=(expected.operation==='read_cold_retained_saved_chat'||expected.operation==='read_owned_selected_message_cache')?'compare_and_patch_cold_incoming_insert':expected.operation==='read_monitored_retained_saved_chat'?'compare_and_replace_monitor_candidates':'compare_and_patch';if(prior.phase===1&&p.kind===commit)phase=2;else if(prior.phase===2&&(p.kind==='readback'||expected.operation!=='read_retained_saved_chat'&&p.kind==='readback_metadata_only'))phase=3;else if(prior.phase===3&&p.kind===prior.readbackKind)phase=4;else throw Error('unavailable');}
  else{if(prior.phase!==1||p.kind!=='readback')throw Error('unavailable');phase=2;}}
 state.rows.set(p.chatId,{operationId:p.operationId,phase,...(phase===3?{readbackKind:String(p.kind)}:prior?.readbackKind?{readbackKind:prior.readbackKind}:{})});state.effects++;
}
export function browserCachePlansComplete(state:BrowserCachePlanState,operation:BrowserCacheOperation,ids:string[]):boolean {
 if(operation==='read_cache_monitor_update')return state.rows.size>0&&[...state.rows].every(([key,row])=>row.phase===(key.startsWith('messages:')?4:3))&&[...state.rows.keys()].filter(key=>key.startsWith('messages:')).every(key=>ids.includes(key.slice(9)));
 return operation==='read_cached_chat_items'?state.effects===0:state.rows.size===ids.length&&ids.every(id=>state.rows.get(id)?.phase===(['read_retained_saved_chat','read_cold_retained_saved_chat','read_monitored_retained_saved_chat','read_owned_selected_message_cache'].includes(operation)?4:2));
}

/** Storage-drain correlation only, never auth/health/durability authority. */
export interface BrowserCachePrepared {version:1;id:number;cachePrepared:{publicationId:string}}
export interface BrowserCacheDrained {version:1;id:number;cacheDrained:{publicationId:string}}
export function validBrowserCachePrepared(v:unknown):v is BrowserCachePrepared {
 return record(v)&&boundedJson(v)&&exact(v,['version','id','cachePrepared'])&&v.version===1&&integer(v.id)&&v.id>0
  &&record(v.cachePrepared)&&exact(v.cachePrepared,['publicationId'])&&uuid(v.cachePrepared.publicationId);
}
export function validBrowserCacheDrained(v:unknown):v is BrowserCacheDrained {
 return record(v)&&boundedJson(v)&&exact(v,['version','id','cacheDrained'])&&v.version===1&&integer(v.id)&&v.id>0
  &&record(v.cacheDrained)&&exact(v.cacheDrained,['publicationId'])&&uuid(v.cacheDrained.publicationId);
}

/** Nonfinal retained UI publication. The SAME original Rust resource still
 * owns metadata/hint work; this is neither an incoming-loop completion nor an
 * IO/auth/ownership receipt. Native original correlation is mandatory at Host. */
export interface BrowserCacheSourceEvidence {packetStamp:string;messagesVersion:number|null}
export interface BrowserCacheSelected {
 version:1;id:number;cacheSelected:{publicationId:string;selected:BrowserRetainedRead;pending:'metadata';sourceEvidence:BrowserCacheSourceEvidence};
}
export function validBrowserCacheSourceEvidence(v:unknown):v is BrowserCacheSourceEvidence {
 return record(v)&&exact(v,['packetStamp','messagesVersion'])&&typeof v.packetStamp==='string'
  &&/^[a-f0-9]{64}$/.test(v.packetStamp)&&(v.messagesVersion===null||integer(v.messagesVersion));
}
export function validBrowserCacheSelected(v:unknown):v is BrowserCacheSelected {
 return record(v)&&boundedJson(v)&&exact(v,['version','id','cacheSelected'])&&v.version===1&&integer(v.id)&&v.id>0
  &&record(v.cacheSelected)&&exact(v.cacheSelected,['publicationId','selected','pending','sourceEvidence'])&&uuid(v.cacheSelected.publicationId)
  &&validBrowserCacheSourceEvidence(v.cacheSelected.sourceEvidence)
  &&v.cacheSelected.pending==='metadata'&&validBrowserRetainedRead(v.cacheSelected.selected)
  &&(v.cacheSelected.selected.cacheReadKind==='cold'||v.cacheSelected.selected.cacheReadKind==='monitor');
}

/** Negative transport control for one original owned read. No admission/ACK. */
export interface BrowserOwnedCacheIdentity { operation:'read_cold_retained_saved_chat'|'read_cache_monitor_update';handle:string;generation:number;owner:string;chatId:string;monitorId?:string }
export interface BrowserOwnedCacheStop {version:1;id:number;cacheStop:BrowserOwnedCacheIdentity}
export interface BrowserOwnedCacheTerminal {version:1;id:number;cacheTerminal:BrowserOwnedCacheIdentity;state:'drained'|'unsettled'}
function ownedIdentity(v:unknown):v is BrowserOwnedCacheIdentity {
 return record(v)&&exact(v,['operation','handle','generation','owner','chatId',...(v.operation==='read_cache_monitor_update'?['monitorId']:[])])
  &&['read_cold_retained_saved_chat','read_cache_monitor_update'].includes(String(v.operation))
  &&typeof v.handle==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(v.handle)&&integer(v.generation)&&v.generation>0&&uuid(v.owner)&&uuid(v.chatId)
  &&(v.operation!=='read_cache_monitor_update'||uuid(v.monitorId));
}
export function validBrowserOwnedCacheStop(v:unknown):v is BrowserOwnedCacheStop {
 return record(v)&&exact(v,['version','id','cacheStop'])&&v.version===1&&integer(v.id)&&v.id>0&&ownedIdentity(v.cacheStop);
}
export function validBrowserOwnedCacheTerminal(v:unknown):v is BrowserOwnedCacheTerminal {
 return record(v)&&exact(v,['version','id','cacheTerminal','state'])&&v.version===1&&integer(v.id)&&v.id>0&&ownedIdentity(v.cacheTerminal)&&['drained','unsettled'].includes(String(v.state));
}
export function sameBrowserOwnedCacheIdentity(a:BrowserOwnedCacheIdentity,b:BrowserOwnedCacheIdentity):boolean {
 return a.operation===b.operation&&a.handle===b.handle&&a.generation===b.generation&&a.owner===b.owner&&a.chatId===b.chatId&&a.monitorId===b.monitorId;
}

/** Nonfinal native progress DATA, emitted only after actual Core result adoption.
 * It grants no local-store/child/embed/full-hint completion or next admission. */
export interface BrowserCacheRecoveryProgress {version:1;id:number;cacheRecoveryProgress:'local_persistence_pending'|'local_metadata_stored'|'main_metadata_stored_pending'|'main_reply_stored_pending'}
export function validBrowserCacheRecoveryProgress(value:unknown):value is BrowserCacheRecoveryProgress {
  if(!value||typeof value!=='object'||Object.getPrototypeOf(value)!==Object.prototype)return false;
  const row=value as Record<string,unknown>;
  return Object.keys(row).length===3&&row.version===1&&Number.isSafeInteger(row.id)&&Number(row.id)>0&&['local_persistence_pending','local_metadata_stored','main_metadata_stored_pending','main_reply_stored_pending'].includes(row.cacheRecoveryProgress as string);
}
