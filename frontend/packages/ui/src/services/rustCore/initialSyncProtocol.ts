/** Negative-only same original initial operation control. No completion ACK. */
export interface BrowserInitialSyncStop{version:1;id:number;initialSyncStop:{handle:string;generation:number;owner:string}}
export function validInitialSyncStop(value:unknown):value is BrowserInitialSyncStop{
 if(!value||typeof value!=='object'||Object.getPrototypeOf(value)!==Object.prototype)return false;
 const v=value as Record<string,unknown>,s=v.initialSyncStop;
 if(Object.keys(v).length!==3||v.version!==1||!Number.isSafeInteger(v.id)||Number(v.id)<1||!s||typeof s!=='object'||Object.getPrototypeOf(s)!==Object.prototype)return false;
 const a=s as Record<string,unknown>;return Object.keys(a).length===3&&typeof a.handle==='string'&&a.handle.length>0&&a.handle.length<=128&&Number.isSafeInteger(a.generation)&&Number(a.generation)>=1&&typeof a.owner==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(a.owner);
}
