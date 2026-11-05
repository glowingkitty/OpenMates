export {AUTH_REFRESH_LOCK} from '@openmates/ui/src/services/rustCore/browserAdapters';
/** Private feature+isolated-CI-only fixture. No admission or private output. */
import {saveMasterKeyToIndexedDB,clearMasterKeyFromIndexedDB} from '@openmates/ui/src/services/cryptoKeyStorage';
import {bumpLoginSessionGeneration,getLoginSessionGeneration,logout} from '@openmates/ui/src/stores/authLoginLogoutActions';
export async function actualMasterOnlyTransition():Promise<boolean>{
 const before=getLoginSessionGeneration();
 const key=await crypto.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);
 await saveMasterKeyToIndexedDB(key);await clearMasterKeyFromIndexedDB();
 return before===getLoginSessionGeneration();
}
export function actualAuthGenerationInvalidation():void{bumpLoginSessionGeneration();}
export async function actualLogout():Promise<void>{await logout();}
