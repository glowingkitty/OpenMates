/** Distinct original-native draft header compatibility budget. Normal cache
 * IO remains 256KiB. This only accounts bytes; Rust owns provenance and policy. */
export const ORIGINAL_PHYSICAL_DRAFT_ROW_BYTES=2*1024*1024;
export const ORIGINAL_PHYSICAL_DRAFT_PACKET_BYTES=4*1024*1024;
export function boundedOriginalPhysicalDraft(value:unknown):boolean{return bounded(value,false);}
export function boundedOriginalPhysicalDraftHeader(value:unknown):boolean{return bounded(value,true);}
function bounded(value:unknown,headerRoot:boolean):boolean {
 let nodes=0,normalUnits=0;const headers:unknown[]=[];const allowed=new Set<unknown>();
 const header=(v:unknown):boolean=>!!v&&typeof v==='object'&&Object.getPrototypeOf(v)===Object.prototype&&typeof Object.getOwnPropertyDescriptor(v,'chat_id')?.value==='string';
 if(headerRoot){if(!header(value))return false;allowed.add(value);}
 else if(value&&typeof value==='object'&&Object.getPrototypeOf(value)===Object.prototype){
  const fields=Object.getOwnPropertyDescriptors(value);
  for(const key of ['metadata','record','before']){const item=fields[key];if(item&&'value'in item&&header(item.value))allowed.add(item.value);}
 }
 const walk=(v:unknown,depth:number,draft=false):boolean=>{
  if(++nodes>16384||depth>32)return false;
  if(v===null||typeof v==='boolean')return true;
  if(typeof v==='number')return Number.isFinite(v);
  if(typeof v==='string'){if(draft)return new TextEncoder().encode(v).byteLength<=ORIGINAL_PHYSICAL_DRAFT_ROW_BYTES;normalUnits+=v.length;return normalUnits<=256*1024;}
  if(typeof v!=='object')return false;
  const array=Array.isArray(v);if(Object.getPrototypeOf(v)!==(array?Array.prototype:Object.prototype))return false;
  if(array&&Object.keys(v).length!==v.length)return false;
  const descriptors=Object.getOwnPropertyDescriptors(v);
  const isHeader=allowed.has(v);if(isHeader)headers.push(v);
  for(const [key,item]of Object.entries(descriptors)){
   if(array&&key==='length')continue;
   if(!('value'in item)||item.get||item.set)return false;
   normalUnits+=key.length;if(normalUnits>256*1024)return false;
   if(!walk(item.value,depth+1,isHeader&&['encrypted_draft_md','encrypted_draft_preview'].includes(key)))return false;
  }return true;
 };
 try{
  if(!walk(value,0)||!headers.every(header=>new TextEncoder().encode(JSON.stringify(header)).byteLength<=ORIGINAL_PHYSICAL_DRAFT_ROW_BYTES))return false;
  const full=JSON.stringify(value);
  const accounting=JSON.stringify(value,function(key,entry){
   return allowed.has(this)&&['encrypted_draft_md','encrypted_draft_preview'].includes(key)?undefined:entry;
  });
  return new TextEncoder().encode(accounting).byteLength<=256*1024&&new TextEncoder().encode(full).byteLength<=ORIGINAL_PHYSICAL_DRAFT_PACKET_BYTES;
 }catch{return false;}
}
