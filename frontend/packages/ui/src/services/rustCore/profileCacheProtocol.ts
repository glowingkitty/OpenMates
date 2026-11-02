/// <reference lib="es2022.object" />
/** Negative notification only. This frame never grants profile/key/session,
 * native IO, durability or cache publication authority. */
export interface ProfileCacheInvalidation {version:1;profileCacheInvalidated:{handle:string;generation:number;owner:string};}
function record(value:unknown):value is Record<string,unknown>{return value!==null&&typeof value==='object'&&Object.getPrototypeOf(value)===Object.prototype;}
function closed(value:unknown,keys:string[]):value is Record<string,unknown>{return record(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));}
export function validProfileCacheInvalidation(value:unknown):value is ProfileCacheInvalidation {
 if(!closed(value,['version','profileCacheInvalidated'])||value.version!==1||!closed(value.profileCacheInvalidated,['handle','generation','owner']))return false;
 const v=value.profileCacheInvalidated;
 return typeof v.handle==='string'&&v.handle.length>0&&v.handle.length<=128
  &&typeof v.generation==='number'&&Number.isSafeInteger(v.generation)&&v.generation>0
  &&typeof v.owner==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(v.owner);
}
