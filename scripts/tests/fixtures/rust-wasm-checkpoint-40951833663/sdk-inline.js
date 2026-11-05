
const et=Object.getOwnPropertyDescriptor(Event.prototype,'target').get;
const ey=Object.getOwnPropertyDescriptor(Event.prototype,'type').get;
const md=Object.getOwnPropertyDescriptor(MessageEvent.prototype,'data').get;
const mp=Object.getOwnPropertyDescriptor(MessageEvent.prototype,'ports').get;
const post=MessagePort.prototype.postMessage, start=MessagePort.prototype.start, close=MessagePort.prototype.close;
const add=EventTarget.prototype.addEventListener, remove=EventTarget.prototype.removeEventListener;
const defer=globalThis.queueMicrotask.bind(globalThis);
const own=(v,ks)=>v!==null&&typeof v==='object'&&Object.getPrototypeOf(v)===Object.prototype&&Reflect.ownKeys(v).length===ks.length&&ks.every(k=>Object.hasOwn(v,k))&&Object.values(Object.getOwnPropertyDescriptors(v)).every(p=>'value'in p);
export function recoveryCapture(e){
 if(!(globalThis instanceof DedicatedWorkerGlobalScope)||ey.call(e)!=='message'||et.call(e)!==globalThis||e.isTrusted!==true)throw Error('unavailable');
 const d=md.call(e),ps=mp.call(e);
 if(!own(d,['version','operation','artifact','apiUrl','appOrigin','sessionId','expectedPrincipal'])||d.version!==1||d.operation!=='bootstrap_existing_key'||typeof d.artifact!=='string'||!/^[a-f0-9]{64}$/.test(d.artifact)||d.appOrigin!==globalThis.location.origin||![d.apiUrl,d.sessionId,d.expectedPrincipal].every(v=>typeof v==='string')||ps.length>1)throw Error('unavailable');
 return [ps.length===1?ps[0]:null,d.apiUrl,d.sessionId,d.expectedPrincipal];
}
export function recoveryListen(p,f){add.call(p,'message',f);add.call(p,'messageerror',f);start.call(p);}
export function recoveryUnlisten(p,f){remove.call(p,'message',f);remove.call(p,'messageerror',f);}
export function recoveryClose(p){close.call(p);}
export function recoveryDefer(f){defer(f);}
export function recoveryRequest(p,c,s,o,e){post.call(p,{version:1,contextId:c,sequence:s,operationId:o,effect:JSON.parse(e)});}
export function recoveryInventoryRequest(p,c,s,o,e){post.call(p,{version:1,domain:'draft_inventory',contextId:c,sequence:s,operationId:o,effect:JSON.parse(e)});}
export function recoveryCancel(p,c,s,o){post.call(p,{version:1,contextId:c,sequence:s,operationId:o,cancel:true});}
export function recoveryStop(p,c){post.call(p,{version:1,contextId:c,close:true});}
export function recoveryRead(p,e){
 const type=ey.call(e);if(et.call(e)!==p||e.isTrusted!==true)return ['untrusted'];
 if(type==='messageerror')return ['lost'];if(type!=='message')return ['untrusted'];
 const d=md.call(e);if(!d||typeof d!=='object'||d.version!==1)return ['invalid'];
 if(own(d,['version','admitted'])&&own(d.admitted,['contextId'])&&typeof d.admitted.contextId==='string')return ['admitted',d.admitted.contextId];
 if(own(d,['version','contextId','revoked'])&&d.revoked===true&&typeof d.contextId==='string')return ['revoked',d.contextId];
 if(own(d,['version','contextId','closed'])&&d.closed===true&&typeof d.contextId==='string')return ['closed',d.contextId];
 if(own(d,['version','contextId','domain','ready'])&&d.domain==='draft_inventory'&&d.ready===true&&typeof d.contextId==='string')return ['inventory_ready',d.contextId];
 if(own(d,['version','domain','contextId','sequence','operationId','result'])&&d.domain==='draft_inventory'&&typeof d.contextId==='string'&&Number.isSafeInteger(d.sequence)&&d.sequence>=1&&typeof d.operationId==='string'){
  const r=d.result;if(own(r,['ok','packet'])&&r.ok===true&&typeof r.packet==='string'&&r.packet.length<=2097152)return ['inventory_reply',d.contextId,d.sequence,d.operationId,true,r.packet];
  if(own(r,['ok','error'])&&r.ok===false&&['unavailable','cancelled','conflict'].includes(r.error))return ['inventory_reply',d.contextId,d.sequence,d.operationId,false,r.error];return ['invalid'];
 }
 if(!own(d,['version','contextId','sequence','operationId','result'])||typeof d.contextId!=='string'||!Number.isSafeInteger(d.sequence)||d.sequence<1||typeof d.operationId!=='string')return ['invalid'];
 const r=d.result;
 if(own(r,['ok','record'])&&r.ok===true&&(r.record===null||typeof r.record==='string'))return ['reply',d.contextId,d.sequence,d.operationId,true,r.record];
 if(own(r,['ok','error'])&&r.ok===false&&['unavailable','cancelled','conflict'].includes(r.error))return ['reply',d.contextId,d.sequence,d.operationId,false,r.error];
 return ['invalid'];
}
