/** Real product TUI loop and terminal, with a deterministic synthetic SDK stream.
 * No account, network, inference or server-latency claim. */
import {register} from 'node:module';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
if(!process.execArgv.includes('--experimental-strip-types')) {
  const result=spawnSync(process.execPath,['--experimental-strip-types',fileURLToPath(import.meta.url)],{stdio:'inherit',env:process.env});
  process.exit(result.status??1);
}
register(new URL('../loader.mjs',import.meta.url),import.meta.url);
const {runTui}=await import('../../src/tui.ts');
const {TuiTerminal}=await import('../../src/tuiTerminal.ts');
const {noStartupPrompts}=await import('../tuiTestServices.ts');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let latestTitle = 'Synthetic streaming proof';
const metadata=id=>({id,shortId:id,slug:id,title:latestTitle,summary:null,category:'software_development',mateName:null,createdAt:Math.floor(Date.now()/1000),updatedAt:null});
const call=skill=>'```json_embed\n'+JSON.stringify({type:'app_skill_use',embed_id:skill,app_id:'web',skill_id:skill,status:'processing'})+'\n```';
const search=call('search'),action=search+'\n\n'+call('create');
const first=action+'\n\n### Progressive response\n\n**First paragraph** appears while the response continues.';
const second=first+'\n\nSecond paragraph follows in source order.';
const final=second+'\n\nComplete response.';
const session={apiUrl:'https://example.invalid',sessionId:'synthetic-stream-session',cookies:{},wsToken:null,
  masterKeyExportedB64:Buffer.alloc(32).toString('base64'),hashedEmail:'synthetic-owner',userEmailSalt:'salt',createdAt:1,autoLogoutMinutes:null,authorizerDeviceName:'Synthetic'};
const {resolveStateDir,saveSession}=await import('../../src/storage.ts');
if(!resolveStateDir().startsWith(join(tmpdir(),'openmates-')))throw Error('Synthetic fixture requires a disposable OpenMates test directory.');
saveSession(session,{replace:true});
const client={apiUrl:'https://example.invalid',hasSession:()=>true,getActiveTeamId:()=>null,
  getSession:()=>session,resolveTeamContext:()=>null,
  getAppsWorkspaceCatalog:async()=>({apps:[{id:'web',name:'Web',skills:[{id:'search',name:'Search'}]}]}),
  listMemories:async()=>[],listProjects:async()=>[],
  getMasterKeyBytes:()=>new Uint8Array(32),whoAmI:async()=>({username:'Synthetic'}),
  beginInteractiveViewerSession:()=>{},endInteractiveViewerSession:()=>{},
  clearInteractiveChatViewer:()=>{},setInteractiveChatViewer:async()=>{},
  getDailyInspirations:async()=>[{id:'synthetic-inspiration',surface:'chats',title:'Synthetic streaming proof',prompt:'A deterministic response stream for terminal presentation.',category:'software_development'}],
  getDraft:async()=>null,listUserTasks:async()=>[],getChatMetadata:async id=>metadata(id),
  sendMessage:async input=>{
    const event=(kind,content)=>({kind,content,category:'software_development',modelName:'Synthetic model',taskId:'synthetic-task'});
    input.onStream?.({...event('typing',''),chatTitle:'Early generated chat title',chatIcon:'book',chatId:input.chatId??input.newChatId,turnId:'synthetic-turn',userMessageId:'synthetic-user'});
    await delay(2000);input.onStream?.({...event('typing',''),thinkingContent:'Synthetic visible reasoning for this response.',thinkingActive:true});
    await delay(1500);input.onStream?.({...event('chunk',search),thinkingActive:false});
    await delay(4000);input.onStream?.(event('chunk',action));
    await delay(1800);input.onStream?.(event('chunk',first));
    await delay(1800);input.onStream?.(event('chunk',second));
    await delay(1800);input.onStream?.({...event('done',final),responseTerminal:true});
    // Required reply persistence is independent of the delayed postprocessor.
    await delay(1200);
    setTimeout(()=>{
      latestTitle='Late title after reply completion';
      input.onMetadata?.({chatId:input.chatId??input.newChatId,turnId:'synthetic-turn',userMessageId:'synthetic-user',
        updatedChatTitle:latestTitle,chatSummary:'A delayed summary',followUpSuggestions:['Explain the next step'],
        newChatSuggestions:[],suggestedFollowupMessage:null,chatTags:[],sourceTitleVersion:1,sourceMetadataVersion:1});
    },1800);
    return {chatId:input.chatId??input.newChatId,assistant:final,userMessageId:'synthetic-user',
      mateName:'Sophia',category:'software_development',followUpSuggestions:[]};
  },
};
await runTui(client,new TuiTerminal(),noStartupPrompts);
