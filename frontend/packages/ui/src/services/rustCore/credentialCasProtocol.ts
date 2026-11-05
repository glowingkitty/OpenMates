/** Closed platform-effect relay only. Rust owns credential transition policy. */
import {validBrowserCredentialIOEffect,validBrowserSealedCredentials} from './browserCredentialStorage';
import type {BrowserCredentialIOEffect,BrowserCredentialIOResult} from './browserCredentialStorage';
export type {BrowserCredentialIOEffect,BrowserCredentialIOResult};
export interface CredentialCasScope {lifecycleGeneration:number;workspaceEpoch:number}
export interface CredentialCasValidation {operationId:string;scope:CredentialCasScope;snapshotId:string;ciphertextSha256:string;crossDatabaseAssociationProven:false;credentialAcknowledged:false}
export interface CredentialEffectMessage {version:1;id:number;effectId:number;hostEffect:BrowserCredentialIOEffect}
export type CredentialEffectReply={version:1;id:number;effectId:number;hostReply:{ok:true;result:BrowserCredentialIOResult}|{ok:false;error:string}};
const object=(v:unknown):v is Record<string,unknown>=>typeof v==='object'&&v!==null&&Object.getPrototypeOf(v)===Object.prototype;
const keys=(v:Record<string,unknown>,fields:string[])=>Object.keys(v).length===fields.length&&Object.keys(v).every(k=>fields.includes(k));
const integer=(v:unknown)=>Number.isSafeInteger(v)&&(v as number)>0;
const uuid=(v:unknown)=>typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(v);
const bounded=(v:unknown)=>{try{return new TextEncoder().encode(JSON.stringify(v)).byteLength+1024<=16*1024;}catch{return false;}};
export function validCredentialCasScope(v:unknown):v is CredentialCasScope{return object(v)&&keys(v,['lifecycleGeneration','workspaceEpoch'])&&integer(v.lifecycleGeneration)&&Number.isSafeInteger(v.workspaceEpoch)&&(v.workspaceEpoch as number)>=0;}
export function validCredentialCasValidation(v:unknown):v is CredentialCasValidation{return object(v)&&keys(v,['operationId','scope','snapshotId','ciphertextSha256','crossDatabaseAssociationProven','credentialAcknowledged'])&&uuid(v.operationId)&&validCredentialCasScope(v.scope)&&uuid(v.snapshotId)&&typeof v.ciphertextSha256==='string'&&/^[a-f0-9]{64}$/.test(v.ciphertextSha256)&&v.crossDatabaseAssociationProven===false&&v.credentialAcknowledged===false;}
export const credentialIOError=(v:unknown):v is string=>typeof v==='string'&&['credential_conflict','invalid_snapshot','owner_mismatch','invalidated_snapshot','cancelled','storage_failed','invalid_request'].includes(v);
export function validCredentialIOResult(v:unknown):v is BrowserCredentialIOResult{
 if(!object(v)||!['read','cas'].includes(v.kind as string)||!keys(v,['kind','operationId','snapshot','transactionCommitted','ownerRowAtomic','crossDatabaseAssociationProven','credentialAcknowledged',...(v.kind==='cas'?['expected']:[])])||!uuid(v.operationId)||v.transactionCommitted!==true||v.ownerRowAtomic!==true||v.crossDatabaseAssociationProven!==false||v.credentialAcknowledged!==false||!bounded(v))return false;
 return (v.snapshot===null?v.kind==='read':validBrowserSealedCredentials(v.snapshot))&&(v.kind==='read'||v.expected===null||validBrowserSealedCredentials(v.expected));
}
export function validCredentialEffectMessage(v:unknown):v is CredentialEffectMessage{return object(v)&&keys(v,['version','id','effectId','hostEffect'])&&v.version===1&&integer(v.id)&&integer(v.effectId)&&(v.effectId as number)<=3&&validBrowserCredentialIOEffect(v.hostEffect)&&bounded(v);}
export function validCredentialEffectReply(v:unknown):v is CredentialEffectReply{return object(v)&&keys(v,['version','id','effectId','hostReply'])&&v.version===1&&integer(v.id)&&integer(v.effectId)&&(v.effectId as number)<=3&&object(v.hostReply)&&(v.hostReply.ok===true?keys(v.hostReply,['ok','result'])&&validCredentialIOResult(v.hostReply.result):v.hostReply.ok===false&&keys(v.hostReply,['ok','error'])&&credentialIOError(v.hostReply.error))&&bounded(v);}
