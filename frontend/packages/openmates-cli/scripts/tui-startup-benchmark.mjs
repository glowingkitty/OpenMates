/** Synthetic encrypted-cache benchmark. No account, network, or inference is used. */
import {createCipheriv,createHash,randomBytes,webcrypto} from 'node:crypto';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {performance} from 'node:perf_hooks';
const args=process.argv.slice(2),arg=name=>args[args.indexOf(name)+1];
const modulePath=resolve(args.includes('--module')?arg('--module'):'dist/index.js');
const startImport=performance.now();
const {OpenMatesClient}=await import(pathToFileURL(modulePath).href);
const importMs=performance.now()-startImport;
const dir=mkdtempSync(join(tmpdir(),'openmates-startup-benchmark-'));
const previous=process.env.OPENMATES_STATE_DIR;process.env.OPENMATES_STATE_DIR=dir;
const hash=v=>createHash('sha256').update(v).digest('hex');
const encrypt=(value,key)=>{
 const iv=randomBytes(12),cipher=createCipheriv('aes-256-gcm',key,iv);
 return Buffer.concat([iv,cipher.update(value),cipher.final(),cipher.getAuthTag()]).toString('base64');
};
const master=Buffer.alloc(32,11),key=Buffer.alloc(32,22),hot='11111111-1111-4111-8111-111111111111';
const session={apiUrl:'https://synthetic.invalid',sessionId:'synthetic-session',wsToken:null,cookies:{},
 masterKeyExportedB64:master.toString('base64'),hashedEmail:'synthetic-benchmark',userEmailSalt:'synthetic-salt',
 createdAt:1,authorizerDeviceName:'Synthetic benchmark',autoLogoutMinutes:null};
const messages=Array.from({length:500},(_,i)=>JSON.stringify({id:`message-${i}`,client_message_id:`message-${i}`,chat_id:hot,
 role:i%2?'assistant':'user',created_at:i+1,hashed_user_id:'synthetic-user',
 encrypted_content:encrypt(`Synthetic message ${i}. `+'Encrypted benchmark text. '.repeat(20),key),
 encrypted_sender_name:encrypt(i%2?'Assistant':'You',key),encrypted_category:encrypt('technology',key),
 encrypted_model_name:encrypt('Synthetic model',key),encrypted_pii_mappings:encrypt('[]',key)}));
const chats=Array.from({length:500},(_,i)=>({details:{id:i===0?hot:`synthetic-chat-${i}`,messages_v:i===0?500:0,
 created_at:1,last_edited_overall_timestamp:500-i,encrypted_chat_key:encrypt(key,master),
 encrypted_title:encrypt(`Synthetic chat ${i}`,key),encrypted_chat_summary:encrypt('Synthetic encrypted cache preview.',key),
 encrypted_category:encrypt('technology',key),encrypted_slug:encrypt(`synthetic-chat-${i}`,key)},messages:i===0?messages:[]}));
const embeds=Array.from({length:10000},(_,i)=>({embed_id:`synthetic-embed-${i}`,hashed_message_id:hash(`message-${i%500}`),
 ...(i%7===0?{parent_embed_id:'synthetic-parent'}:{})}));
const cache={syncedAt:Date.now(),totalChatCount:chats.length,loadedChatCount:chats.length,chats,embeds,embedKeys:[]};
const serialized=JSON.stringify(cache);writeFileSync(join(dir,'sync_cache.json'),serialized,{mode:0o600});
const median=x=>[...x].sort((a,b)=>a-b)[Math.floor(x.length/2)];
const samples=[];
try{
 for(let i=0;i<5;i++){
  const client=new OpenMatesClient({session});
  // Any accidental fetch is a hard failure; all work must come from local ciphertext.
  client.http.get=client.http.post=async()=>{throw Error('Synthetic benchmark attempted network');};
  let imports=0;const original=webcrypto.subtle.importKey;
  webcrypto.subtle.importKey=function(...a){imports++;return original.apply(this,a);};
  try{
   let firstHome=null;const homeStart=performance.now();
   const home=await client.listCachedChats(Number.MAX_SAFE_INTEGER,1,{onCachedChats:()=>{firstHome??=performance.now()-homeStart;}});
   const homeTotal=performance.now()-homeStart,homeImports=imports;imports=0;
   let firstChat=null;const chatStart=performance.now();
   const opened=await client.getChatMessages(hot,{preferCache:true,onMessages:()=>{firstChat??=performance.now()-chatStart;}});
   const chatTotal=performance.now()-chatStart;
   if(home.chats.length!==500||opened.messages.length!==500||opened.messages.at(-1).content.indexOf('Synthetic message 499')!==0)throw Error('Incomplete benchmark output');
   samples.push({home_first_ms:firstHome??homeTotal,home_complete_ms:homeTotal,home_key_imports:homeImports,
    chat_first_ms:firstChat??chatTotal,chat_complete_ms:chatTotal,chat_key_imports:imports});
  }finally{webcrypto.subtle.importKey=original;}
 }
 const result={scope:'Synthetic encrypted local cache only; excludes terminal paint, auth, sync, network and inference.',
  node:process.version,platform:process.platform,arch:process.arch,module_import_ms:importMs,cache_bytes:Buffer.byteLength(serialized),
  chats:500,messages:500,embeds:10000,samples,median:Object.fromEntries(Object.keys(samples[0]).map(k=>[k,median(samples.map(v=>v[k]))]))};
 if(args.includes('--output'))writeFileSync(resolve(arg('--output')),JSON.stringify(result,null,2)+'\n');
 console.log(JSON.stringify(result.median,null,2));
}finally{
 if(previous===undefined)delete process.env.OPENMATES_STATE_DIR;else process.env.OPENMATES_STATE_DIR=previous;
 rmSync(dir,{recursive:true,force:true});
}
