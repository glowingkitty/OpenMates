/** Real TUI and local SDK decryption over synthetic encrypted history. No auth/server timing claim. */
import {register} from 'node:module';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createCipheriv,randomBytes} from 'node:crypto';
import {mkdirSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
if(!process.execArgv.includes('--experimental-strip-types')){
 const result=spawnSync(process.execPath,['--experimental-strip-types',fileURLToPath(import.meta.url)],{stdio:'inherit',env:process.env});
 process.exit(result.status??1);
}
register(new URL('../loader.mjs',import.meta.url),import.meta.url);
const {OpenMatesClient}=await import('../../src/client.ts');
const {runTui}=await import('../../src/tui.ts');
const {TuiTerminal}=await import('../../src/tuiTerminal.ts');
const {noStartupPrompts}=await import('../tuiTestServices.ts');
const {resolveStateDir}=await import('../../src/storage.ts');
const master=Buffer.alloc(32,11),key=Buffer.alloc(32,22),id='11111111-1111-4111-8111-111111111111';
const encrypt=(value,k=key)=>{const iv=randomBytes(12),c=createCipheriv('aes-256-gcm',k,iv);return Buffer.concat([iv,c.update(value),c.final(),c.getAuthTag()]).toString('base64');};
const cache={syncedAt:Date.now(),loadedChatCount:160,totalChatCount:160,embeds:[],embedKeys:[],
 chats:Array.from({length:160},(_,i)=>({details:{id:i===0?id:`cache-chat-${i}`,messages_v:i===0?240:0,created_at:1,last_edited_overall_timestamp:160-i,
 encrypted_chat_key:encrypt(key,master),encrypted_title:encrypt(`Cached conversation ${i}`),encrypted_chat_summary:encrypt('Synthetic encrypted offline history.'),
 encrypted_category:encrypt('software_development')},messages:i===0?Array.from({length:240},(_,n)=>JSON.stringify({id:`cached-message-${n}`,client_message_id:`cached-message-${n}`,
 chat_id:id,role:n%2?'assistant':'user',created_at:n,encrypted_sender_name:encrypt(n%2?'Sophia':'You'),encrypted_category:encrypt('software_development'),
 encrypted_content:encrypt(`Cached message ${n}. This history is decrypted locally.`)})):[]}))};
mkdirSync(resolveStateDir(),{recursive:true,mode:0o700});
writeFileSync(join(resolveStateDir(),'sync_cache.json'),JSON.stringify(cache),{mode:0o600});
const client=new OpenMatesClient({session:{apiUrl:'https://synthetic.invalid',sessionId:'synthetic-cache-session',cookies:{},wsToken:null,
 masterKeyExportedB64:master.toString('base64'),hashedEmail:'synthetic-owner',userEmailSalt:'salt',createdAt:1,autoLogoutMinutes:null,authorizerDeviceName:'Synthetic'}});
// Public/remote ancillary startup services are deterministic. Real encrypted
// listCachedChats/getChatMessages/getCachedDraft and all TUI routing are retained.
client.http.get=client.http.post=async()=>{throw Error('Synthetic offline fixture: network unavailable');};
client.whoAmI=async()=>({username:'Synthetic'});
client.listChats=async()=>{throw Error('Synthetic offline fixture: network unavailable');};
client.getDailyInspirations=async()=>[{id:'synthetic-cache',surface:'chats',title:'Encrypted local cache proof',phrase:'Browse encrypted recent chats while sync is unavailable.',category:'software_development'}];
client.getChatActivity=async()=>({ids:[],chats:[]});
client.observeChatActivity=async()=>()=>{};
client.getCachedContinueItems=async()=>null;
client.getContinueItems=async()=>({memories:[],reminders:[]});
client.listProjects=async()=>[{project_id:'22222222-2222-4222-8222-222222222222',encrypted_project_key:encrypt(key,master),
 encrypted_name:encrypt('Synthetic Project'),encrypted_description:encrypt('Synthetic project mention context')}];
client.getProjectSettings=async()=>({write_mode:'always_ask'});
client.getAppsWorkspaceCatalog=async()=>({apps:[{id:'web',name:'Web',skills:[{id:'search',name:'Search'}],
 focus_modes:[{id:'research',name:'Research'}],settings_and_memories:[{id:'preferences',name:'Preferences'}]}]});
client.listMemories=async()=>[{id:'synthetic-memory',app_id:'web',item_type:'preferences',data:{title:'Synthetic research preference'}}];
client.searchWikipediaTitles=async()=>[{page_id:1,key:'Comet',title:'Comet',description:'Synthetic Wikipedia suggestion',language:'en',disambiguation:false}];
client.listWorkflows=async()=>[];client.listUserTasks=async()=>[];
const {createTuiWorkspaceCache}=await import('../../src/tuiWorkspaceCache.ts');
await createTuiWorkspaceCache(client.getSession(),()=>client.getSession()).set('ai-model-catalog-v1',[
 {id:'openai/gpt-6-astra',name:'GPT-6 Astra',providerId:'openai',providerName:'OpenAI',description:'Synthetic model availability',available:true},
 {id:'qwen/qwen3-235b-a22b-2507',name:'Qwen 3',providerId:'qwen',providerName:'Qwen',description:'Synthetic model availability',available:true}]);
client.setInteractiveChatViewer=async()=>{};
await runTui(client,new TuiTerminal(),noStartupPrompts);
