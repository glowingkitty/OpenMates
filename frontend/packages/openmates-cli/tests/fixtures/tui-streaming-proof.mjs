/** Real product TUI loop and terminal, with a deterministic synthetic SDK stream.
 * No account, network, inference or server-latency claim. */
import {register} from 'node:module';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
if(!process.execArgv.includes('--experimental-strip-types')) {
  const result=spawnSync(process.execPath,['--experimental-strip-types',fileURLToPath(import.meta.url)],{stdio:'inherit',env:process.env});
  process.exit(result.status??1);
}
register(new URL('../loader.mjs',import.meta.url),import.meta.url);
const {runTui}=await import('../../src/tui.ts');
const {TuiTerminal}=await import('../../src/tuiTerminal.ts');
const {noStartupPrompts}=await import('../tuiTestServices.ts');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const metadata=id=>({id,shortId:id,slug:id,title:'Synthetic streaming proof',summary:null,category:'software_development',mateName:null,createdAt:Math.floor(Date.now()/1000),updatedAt:null});
const call=skill=>'```json_embed\n'+JSON.stringify({type:'app_skill_use',embed_id:skill,app_id:'web',skill_id:skill,status:'processing'})+'\n```';
const search=call('search'),action=search+'\n\n'+call('create');
const first=action+'\n\n### Progressive response\n\n**First paragraph** appears while the response continues.';
const second=first+'\n\nSecond paragraph follows in source order.';
const final=second+'\n\nComplete response.';
const client={apiUrl:'https://example.invalid',hasSession:()=>true,getActiveTeamId:()=>null,
  getMasterKeyBytes:()=>new Uint8Array(32),whoAmI:async()=>({username:'Synthetic'}),
  beginInteractiveViewerSession:()=>{},endInteractiveViewerSession:()=>{},
  clearInteractiveChatViewer:()=>{},setInteractiveChatViewer:async()=>{},
  getDailyInspirations:async()=>[{id:'synthetic-inspiration',surface:'chats',title:'Synthetic streaming proof',prompt:'A deterministic response stream for terminal presentation.',category:'software_development'}],
  getDraft:async()=>null,listUserTasks:async()=>[],getChatMetadata:async id=>metadata(id),
  sendMessage:async input=>{
    const event=(kind,content)=>({kind,content,category:'software_development',modelName:'Synthetic model',taskId:'synthetic-task'});
    input.onStream?.(event('typing',''));
    await delay(2000);input.onStream?.({...event('typing',''),thinkingContent:'Synthetic visible reasoning for this response.',thinkingActive:true});
    await delay(1500);input.onStream?.({...event('chunk',search),thinkingActive:false});
    await delay(1800);input.onStream?.(event('chunk',action));
    await delay(1800);input.onStream?.(event('chunk',first));
    await delay(1800);input.onStream?.(event('chunk',second));
    await delay(1800);input.onStream?.(event('done',final));
    return {chatId:input.chatId??input.newChatId,assistant:final,userMessageId:'synthetic-user',
      mateName:'Sophia',category:'software_development',followUpSuggestions:[]};
  },
};
await runTui(client,new TuiTerminal(),noStartupPrompts);
