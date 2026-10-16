/** Fullscreen terminal actions. Dialogs remain outside route state, preserving drafts and scroll. */
import { constants } from 'node:fs';
import { open, stat } from 'node:fs/promises';
import { basename, resolve } from 'node:path';
import YAML from 'yaml';
import type { DecryptedEmbed } from './client.js';
import type { WorkspaceContext } from './tuiWorkspaceController.js';
import type { TuiState } from './tuiRenderer.js';
import type { TerminalKey } from './tuiTerminal.js';
import { cells, eraseGrapheme, terminalText, truncateCells, wrapCells, type TuiLine } from './tuiText.js';
import { requestTerminalClipboard } from './tuiClipboard.js';
import { deriveWebOrigin, type ShareDuration } from './shareEncryption.js';
import { collectGeneratedFiles, fetchGeneratedFile } from './generatedFiles.js';
import { captureTuiWorkspaceOwner } from './tuiCachedWorkspaces.js';
import { createTuiShareQr, validTuiShareUrl, type TuiShareQr } from './tuiQrCode.js';
import { chatSettingsActions, chatSettingsFileRefs, createTuiChatSettings, loadTuiChatSettings, renderTuiChatSettings, submitTuiChatTask, visibleChatSettingsTabs, type TuiChatSettingsState } from './tuiChatSettings.js';
import { exampleEmbedMap, aliasForEmbed } from './tuiEmbeds.js';
import { settingsWebDestination } from './tuiSettings.js';

export type TuiHeaderAction = 'settings' | 'share' | 'copy' | 'download' | 'more';
export type TuiChromeState =
  | { kind: 'more'; actions: Array<{id:TuiHeaderAction;label:string}>; index:number }
  | TuiChatSettingsState
  | { kind: 'share'; target: 'chat'|'embed'|'public'; id:string; publicUrl?:string; url?:string; duration:ShareDuration; password:string; includeSensitiveData:boolean; field:number; busy:boolean; error?:string; ownerCurrent:()=>boolean }
  | { kind: 'qr'; qr:TuiShareQr; source:Extract<TuiChromeState,{kind:'share'}>; ownerCurrent:()=>boolean }
  | { kind: 'copy'; text:string; title:string; scrollOffset:number; ownerCurrent?:()=>boolean }
  | { kind: 'download'; format:'md'|'yml'|'original'; path:string; content:Buffer|string|null; fileUrl?:string; field:number; busy:boolean; overwrite?:{ino:number;size:number;mtimeMs:number}; error?:string; ownerCurrent:()=>boolean };

const DURATIONS: ShareDuration[] = [0,60,3600,86400,604800,1209600,2592000];
const DURATION_LABELS = ['Never','1 minute','1 hour','24 hours','7 days','14 days','30 days'];
const action = (command:string) => ({kind:'command' as const,command});
const row = (text:string, command?:string):TuiLine => ({text, ...(command?{action:action(command)}:{})});
function wrapWords(text:string,width:number):string[]{
  const lines:string[]=[];let line='';
  for(const word of text.split(/\s+/)){
    if(line&&cells(`${line} ${word}`)>width){lines.push(line);line='';}
    if(cells(word)>width){if(line){lines.push(line);line='';}lines.push(...wrapCells(word,width));}
    else line=line?`${line} ${word}`:word;
  }
  if(line)lines.push(line);
  return lines;
}
function currentEmbed(state:TuiState):DecryptedEmbed|null { return state.screen==='embed' ? state.detailEmbed : null; }
function embedText(embed:DecryptedEmbed):string|null {
  const data=embed.content ?? {};
  if (embed.type==='code') return typeof data.code==='string'?data.code:typeof data.content==='string'?data.content:null;
  if (['text','document','markdown','mermaid','diagram'].includes(embed.type??''))
    return typeof data.text==='string'?data.text:typeof data.content==='string'?data.content:null;
  return null;
}
function originalFile(embed:DecryptedEmbed):{url:string;filename:string}|null {
  const file=collectGeneratedFiles(embed.content).find(item=>{
    try{return new URL(item.url).protocol==='https:';}
    catch{return /^\/v1\/embeds\/[a-zA-Z0-9-]+\/file\?format=(?:original|master|full)$/.test(item.url);}
  });
  return file?{url:file.url,filename:file.filename}:null;
}
function isShareableEmbed(embed:DecryptedEmbed):boolean {
  const type=(embed.type??'').toLowerCase();
  if (!embed.embedId || /audio|recording|pdf|specification|wiki/.test(type)) return false;
  if (/image/.test(type) && !(embed.content?.files && typeof embed.content.files==='object' && 'original' in embed.content.files)) return false;
  return true;
}
function publicExample(state:TuiState):{id:string;slug:string}|null {
  if(state.screen==='example' && state.activeExample?.chat.slug) return {id:state.activeExample.chat.id,slug:state.activeExample.chat.slug};
  if(state.screen==='chat' && state.activeChat?.source==='example' && state.activeChat.slug) return {id:state.activeChat.id,slug:state.activeChat.slug};
  return null;
}
function isPublicContent(state:TuiState):boolean {return !!publicExample(state)||state.screen==='embed'&&state.embedOrigin?.screen==='example';}
export function headerCapabilities(state:TuiState):Array<{id:TuiHeaderAction;label:string}> {
  const embed=currentEmbed(state);
  if(embed){
    const result:Array<{id:TuiHeaderAction;label:string}>=[];
    if(isShareableEmbed(embed) && state.signedIn) result.push({id:'share',label:'Share'});
    if(embedText(embed)!==null) result.push({id:'copy',label:'Copy'});
    if(embedText(embed)!==null||originalFile(embed)) result.push({id:'download',label:'Download'});
    if(result.length) result.push({id:'more',label:'More'});
    return result;
  }
  if((state.screen==='chat' && !state.activeChatId) || !['chat','example'].includes(state.screen)) return [];
  const result:Array<{id:TuiHeaderAction;label:string}>=[];
  if(publicExample(state) || state.signedIn && state.activeChatId) result.push({id:'settings',label:'Chat settings'},{id:'share',label:'Share'});
  if(state.screen==='chat' && state.activeChatId && state.messages.length) result.push({id:'copy',label:'Copy'},{id:'download',label:'Download'});
  if(result.length) result.push({id:'more',label:'More'});
  return result;
}
function chatMarkdown(state:TuiState):string {
  const title=state.activeChat?.title??state.activeExample?.chat.title??'Chat';
  const messages=state.screen==='example'?state.activeExample?.messages??[]:state.messages;
  return `# ${title}\n\n${messages.map(m=>`## ${m.role==='user'?'You':('senderName' in m ? m.senderName : m.title)??m.category??'Assistant'}\n\n${m.content}`).join('\n\n')}`;
}
function chatYaml(state:TuiState):string {
  const messages=state.screen==='example'?state.activeExample?.messages??[]:state.messages;
  return YAML.stringify({chat:{title:state.activeChat?.title??state.activeExample?.chat.title??'Chat'},messages:messages.map(m=>({role:m.role,content:m.content}))});
}
async function fullChatExport(context:WorkspaceContext,format:'md'|'yml'):Promise<string|null>{
  const id=context.state.activeChatId;
  if(context.state.screen!=='chat'||!id||typeof context.client.getChatMessages!=='function')return null;
  const {chat,messages,historyIncomplete}=await context.client.getChatMessages(id);
  if(historyIncomplete)throw new Error('Chat history is incomplete. Reconnect and retry before downloading.');
  if(context.state.activeChatId!==id)return null;
  const stamp=(value:number|null|undefined)=>new Date(value && value<1e12?value*1000:value??Date.now()).toISOString();
  if(format==='yml')return YAML.stringify({chat:{title:chat.title??null,exported_at:new Date().toISOString(),message_count:messages.length,summary:chat.summary??null},messages:messages.map(message=>({role:message.role,sender:message.senderName??(message.role==='user'?'You':message.category??'Assistant'),model:message.modelName??null,timestamp:stamp(message.createdAt),content:message.content}))});
  let markdown=chat.title?`# ${chat.title}\n\n`:'';
  markdown+=`*Created: ${stamp(chat.updatedAt)}*\n\n---\n\n`;
  for(const message of messages){
    const sender=message.role==='user'?'You':message.senderName??'Assistant';
    const cleaned=message.content.replace(/```(?:json_embed|json)\n[\s\S]*?\n```/g,'').trim();
    markdown+=`## ${sender} - ${stamp(message.createdAt)}\n\n${cleaned?`${cleaned}\n\n`:''}`;
  }
  return markdown;
}
// eslint-disable-next-line no-control-regex -- Reject unsafe terminal control bytes in filenames.
function safeFilename(value:string):string {return basename(value.replace(/[<>:"/\\|?*\x00-\x1f]/g,'').trim()).slice(0,80)||'download';}
function downloadContent(state:TuiState,format:'md'|'yml'|'original',embedOverride?:DecryptedEmbed):string|Buffer {
  const embed=embedOverride??currentEmbed(state);
  if(embed){const text=embedText(embed);if(text===null)throw new Error('Download unavailable for this embed.');return text;}
  return format==='yml'?chatYaml(state):chatMarkdown(state);
}
function defaultDownload(state:TuiState,embedOverride?:DecryptedEmbed):{format:'md'|'yml'|'original';path:string;content:string|Buffer|null;fileUrl?:string} {
  const embed=embedOverride??currentEmbed(state);
  if(embed){
    const file=originalFile(embed);
    if(file)return {format:'original',path:resolve(process.cwd(),safeFilename(file.filename)),content:null,fileUrl:file.url};
    const data=embed.content??{};
    const ext=embed.type==='code' && typeof data.language==='string'?({python:'py',javascript:'js',typescript:'ts',json:'json',html:'html',css:'css'} as Record<string,string>)[data.language]??'txt':'txt';
    const filename=safeFilename(typeof data.filename==='string'?data.filename:`embed-${embed.embedId.slice(0,8)}.${ext}`);
    return {format:'original',path:resolve(process.cwd(),filename),content:downloadContent(state,'original',embed)};
  }
  const title=safeFilename(state.activeChat?.title??'chat').replace(/\.[^.]+$/,'');
  return {format:'md',path:resolve(process.cwd(),`${title}.md`),content:downloadContent(state,'md')};
}
function chromeState(state:TuiState):TuiState&{chrome:TuiChromeState|null} {return state as TuiState&{chrome:TuiChromeState|null};}
export function openHeaderAction(context:WorkspaceContext,id:string):void {
  const {state,client,render}=context;
  const allowed=headerCapabilities(state);
  if(!allowed.some(item=>item.id===id))return;
  const chrome=chromeState(state);
  const ownerCurrent=isPublicContent(state)?()=>true:captureTuiWorkspaceOwner(client);
  if(id==='more') {chrome.chrome={kind:'more',actions:allowed.filter(item=>item.id!=='more'),index:0};render();return;}
  if(!ownerCurrent())return;
  if(id==='settings'){
    const dialog=createTuiChatSettings(state,ownerCurrent);
    chrome.chrome=dialog;
    void loadTuiChatSettings(context,dialog);
  }else if(id==='share'){
    const example=publicExample(state),embed=currentEmbed(state);
    chrome.chrome=example?{kind:'share',target:'public',id:example.id,publicUrl:`${deriveWebOrigin(client.apiUrl)}/example/${encodeURIComponent(example.slug)}`,duration:0,password:'',includeSensitiveData:false,field:0,busy:false,ownerCurrent}
      : {kind:'share',target:embed?'embed':'chat',id:embed?.embedId??state.activeChatId!,duration:0,password:'',includeSensitiveData:false,field:0,busy:false,ownerCurrent};
  }else if(id==='copy'){
    const content=currentEmbed(state)?embedText(currentEmbed(state)!)!:chatMarkdown(state);
    requestTerminalClipboard(content);
    chrome.chrome={kind:'copy',text:content,title:'Copy text',scrollOffset:0,ownerCurrent};
  }else{
    const download=defaultDownload(state);
    chrome.chrome={kind:'download',...download,field:0,busy:false,ownerCurrent};
  }
  render();
}
function setError(dialog:Extract<TuiChromeState,{kind:'share'|'download'}>,message:string):void {dialog.error=message;dialog.busy=false;}
function ownerLive(context:WorkspaceContext,dialog:Extract<TuiChromeState,{kind:'share'|'download'}>):boolean{
  if(chromeState(context.state).chrome!==dialog)return false;
  if(dialog.ownerCurrent())return true;
  if(dialog.kind==='share'){dialog.url=undefined;dialog.password='';}
  else dialog.content=null;
  chromeState(context.state).chrome=null;
  context.render();
  return false;
}
async function generateShare(context:WorkspaceContext,dialog:Extract<TuiChromeState,{kind:'share'}>):Promise<void> {
  if(dialog.busy||dialog.target==='public')return;
  if(!ownerLive(context,dialog))return;
  if(dialog.password.length>10){setError(dialog,'Password must be at most 10 characters.');context.render();return;}
  dialog.busy=true;dialog.error=undefined;context.render();
  try{
    const url=dialog.target==='chat'?await context.client.createChatShareLink(dialog.id,dialog.duration,dialog.password||undefined,{includeSensitiveData:dialog.includeSensitiveData})
      :await context.client.createEmbedShareLink(dialog.id,dialog.duration,dialog.password||undefined);
    if(!ownerLive(context,dialog))return;
    if(!validTuiShareUrl(url,deriveWebOrigin(context.client.apiUrl),dialog.target))throw new Error('Invalid share link.');
    dialog.url=url;
  }catch{
    // Client errors may contain keys, URLs, or user-entered passwords; never echo them into status/history.
    if(ownerLive(context,dialog))setError(dialog,'Could not generate link. Check your connection and permissions, then retry.');
  }finally{dialog.busy=false;context.render();}
}
async function saveDownload(context:WorkspaceContext,dialog:Extract<TuiChromeState,{kind:'download'}>,confirmed=false):Promise<void>{
  if(dialog.busy)return;
  if(!ownerLive(context,dialog))return;
  dialog.busy=true;dialog.error=undefined;context.render();
  if(!dialog.path.trim()){setError(dialog,'Choose a destination file.');context.render();return;}
  const destination=resolve(dialog.path);
  const origin={screen:context.state.screen,chatId:context.state.activeChatId,embedId:context.state.detailEmbed?.embedId};
  let handle:Awaited<ReturnType<typeof open>>|undefined;
  try{
    if(!dialog.fileUrl && dialog.format!=='original'){
      const complete=await fullChatExport(context,dialog.format);
      if(complete!==null)dialog.content=complete;
    }
    if(dialog.fileUrl && dialog.content===null){
      let bytes:Buffer;
      if(dialog.fileUrl.startsWith('/'))bytes=Buffer.from((await context.client.getRaw(dialog.fileUrl)).data);
      else{
        const response=await fetchGeneratedFile(dialog.fileUrl);
        if(!response.ok)throw new Error('Download unavailable.');
        const announced=Number(response.headers.get('content-length')??0);
        if(announced>100_000_000)throw new Error('Download too large.');
        bytes=Buffer.from(await response.arrayBuffer());
      }
      if(bytes.length===0||bytes.length>100_000_000)throw new Error('Download unavailable.');
      dialog.content=bytes;
    }
    if(!ownerLive(context,dialog)||context.state.screen!==origin.screen||context.state.activeChatId!==origin.chatId||context.state.detailEmbed?.embedId!==origin.embedId)return;
    if(!confirmed){
      try{handle=await open(destination,constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL,0o600);}
      catch(error){
        if((error as NodeJS.ErrnoException).code!=='EEXIST')throw error;
        const existing=await stat(destination);
        if(!ownerLive(context,dialog))return;
        dialog.overwrite={ino:existing.ino,size:existing.size,mtimeMs:existing.mtimeMs};return;
      }
    }else{
      if(!dialog.overwrite)throw new Error('No overwrite confirmation.');
      handle=await open(destination,constants.O_RDWR|constants.O_NOFOLLOW);
      if(!ownerLive(context,dialog))return;
      const existing=await handle.stat();
      if(!existing.isFile()||existing.ino!==dialog.overwrite.ino||existing.size!==dialog.overwrite.size||existing.mtimeMs!==dialog.overwrite.mtimeMs)throw new Error('Destination changed. Review it before retrying.');
      await handle.truncate(0);
    }
    if(!ownerLive(context,dialog))return;
    await handle!.writeFile(dialog.content!);
    if(ownerLive(context,dialog)){chromeState(context.state).chrome=null;context.state.status=`Saved on this CLI machine: ${destination}`;}
  }catch(error){
    if(ownerLive(context,dialog))setError(dialog,error instanceof Error && ['Destination changed. Review it before retrying.','Chat history is incomplete. Reconnect and retry before downloading.'].includes(error.message)?error.message:'Could not save file. Check the destination and retry.');
  }finally{await handle?.close();dialog.busy=false;context.render();}
}
export async function handleHeaderCommand(context:WorkspaceContext,command:string):Promise<boolean>{
  const dialog=chromeState(context.state).chrome;
  if(!dialog)return false;
  const [name,value]=command.trim().split(/\s+/,2);
  if(name==='close'){if(!('busy'in dialog)||!dialog.busy){chromeState(context.state).chrome=null;context.render();}return true;}
  if(name==='focus' && 'field' in dialog){if('busy' in dialog && dialog.busy)return true;const index=Number(value);if(Number.isInteger(index)&&index>=0&&index<=6){dialog.field=index;context.render();}return true;}
  if(dialog.kind==='more'){
    if(name==='select' && ['settings','share','copy','download'].includes(value)){chromeState(context.state).chrome=null;openHeaderAction(context,value as TuiHeaderAction);return true;}
    return false;
  }
  if(dialog.kind==='chat-settings'){
    if(!dialog.ownerCurrent()){chromeState(context.state).chrome=null;context.render();return true;}
    if(dialog.busy)return true;
    const tabs=visibleChatSettingsTabs(context.state);
    if(name==='settings-tab' && tabs.includes(value as typeof tabs[number])){
      dialog.tab=value as typeof tabs[number];dialog.field=tabs.indexOf(dialog.tab);dialog.error=undefined;dialog.editingTask=false;
      void loadTuiChatSettings(context,dialog);context.render();return true;
    }
    if(name==='settings-retry'){void loadTuiChatSettings(context,dialog);return true;}
    if(name==='settings-web' && ['share','files'].includes(dialog.tab)){
      const example=publicExample(context.state),origin=deriveWebOrigin(context.client.apiUrl);
      const url=example?`${origin}/example/${encodeURIComponent(example.slug)}`:settingsWebDestination(origin,`chats/${encodeURIComponent(dialog.chatId)}/${dialog.tab}`);
      requestTerminalClipboard(url);
      chromeState(context.state).chrome={kind:'copy',text:url,title:'Open chat settings in browser',scrollOffset:0,ownerCurrent:dialog.ownerCurrent};context.render();return true;
    }
    if(name==='settings-share' && dialog.tab==='share'){openHeaderAction(context,'share');return true;}
    if(name==='settings-download' && dialog.tab==='share' && context.state.screen==='chat'){openHeaderAction(context,'download');return true;}
    if((name==='settings-file'||name==='settings-file-download') && dialog.tab==='files'){
      const item=chatSettingsActions(dialog,context.state).find(action=>action.command===`/header-action ${command}`);
      if(item){
        if(name==='settings-file'){
          chromeState(context.state).chrome=null;await context.command(`/embed ${value}`);
        }else{
          const id=chatSettingsFileRefs(context.state).find(id=>aliasForEmbed(context.state,id)===value);
          const example=publicExample(context.state)?exampleEmbedMap(context.state):{};
          const embed=id&&(context.state.chatEmbeds[id]??example[id]);
          if(embed){const download=defaultDownload(context.state,embed);chromeState(context.state).chrome={kind:'download',...download,field:0,busy:false,ownerCurrent:dialog.ownerCurrent};}
        }
        context.render();
      }return true;
    }
    if(name==='settings-task-create' && dialog.tab==='tasks'){dialog.editingTask=true;dialog.taskTitle='';dialog.error=undefined;dialog.field=tabs.length;context.render();return true;}
    if(name==='settings-task-cancel' && dialog.tab==='tasks'){dialog.editingTask=false;dialog.taskTitle='';dialog.field=tabs.indexOf('tasks');context.render();return true;}
    if(name==='settings-task-focus' && dialog.tab==='tasks'){dialog.field=tabs.length;context.render();return true;}
    if(name==='settings-task-save' && dialog.tab==='tasks' && dialog.editingTask){await submitTuiChatTask(context,dialog);return true;}
    if(name==='settings-task-toggle' && dialog.tab==='tasks' && dialog.tasks.some(task=>task.taskId===value)){await submitTuiChatTask(context,dialog,value);return true;}
    if(name==='settings-task-open' && dialog.tab==='tasks'){
      const task=dialog.tasks.find(task=>task.taskId===value);
      if(task){context.state.tasks=[task,...context.state.tasks.filter(item=>item.taskId!==task.taskId)];chromeState(context.state).chrome=null;await context.command(`/task-open ${task.taskId}`);}return true;
    }
    if(name==='settings-usage-download' && dialog.tab==='usage' && dialog.usageRows.length && ['csv','yml'].includes(value)){
      const csv=(rows:typeof dialog.usageRows)=>[['id','label','provider','timestamp','credits'].join(','),...rows.map(item=>[item.id,item.label,item.provider,String(item.timestamp),item.credits??''].map(cell=>`"${String(cell).replace(/"/g,'""')}"`).join(','))].join('\n');
      const content=value==='csv'?csv(dialog.usageRows):YAML.stringify(dialog.usageRows);
      chromeState(context.state).chrome={kind:'download',format:'original',path:resolve(process.cwd(),safeFilename(`${dialog.title}-usage.${value}`)),content,field:0,busy:false,ownerCurrent:dialog.ownerCurrent};context.render();return true;
    }
    return true;
  }
  if(dialog.kind==='qr'){
    if(!dialog.ownerCurrent()){chromeState(context.state).chrome=null;context.render();return true;}
    if(name==='qr-back'){chromeState(context.state).chrome=dialog.source;context.render();return true;}
    if(name==='copy-link'){requestTerminalClipboard(dialog.qr.url);context.render();return true;}
    return true;
  }
  if(dialog.kind==='copy'){
    if(dialog.ownerCurrent && !dialog.ownerCurrent()){chromeState(context.state).chrome=null;context.render();return true;}
    if(name==='copy'){requestTerminalClipboard(dialog.text);context.render();return true;}return false;
  }
  if(dialog.kind==='share'){
    if(dialog.target!=='public' && !ownerLive(context,dialog))return true;
    if(dialog.busy)return true;
    if(name==='duration'){dialog.duration=DURATIONS[(DURATIONS.indexOf(dialog.duration)+1)%DURATIONS.length];dialog.error=undefined;dialog.url=undefined;}
    else if(name==='sensitive' && dialog.target==='chat'){dialog.includeSensitiveData=!dialog.includeSensitiveData;dialog.url=undefined;}
    else if(name==='generate')await generateShare(context,dialog);
    else if(name==='copy-link' && (dialog.url||dialog.publicUrl) && (dialog.target==='public'||ownerLive(context,dialog))){requestTerminalClipboard(dialog.url??dialog.publicUrl!);chromeState(context.state).chrome={kind:'copy',text:dialog.url??dialog.publicUrl!,title:'Share URL',scrollOffset:0,ownerCurrent:dialog.target==='public'?undefined:dialog.ownerCurrent};}
    else if(name==='show-url' && (dialog.url||dialog.publicUrl) && (dialog.target==='public'||ownerLive(context,dialog)))chromeState(context.state).chrome={kind:'copy',text:dialog.url??dialog.publicUrl!,title:'Share URL',scrollOffset:0,ownerCurrent:dialog.target==='public'?undefined:dialog.ownerCurrent};
    else if(name==='show-qr' && (dialog.url||dialog.publicUrl) && (dialog.target==='public'||ownerLive(context,dialog))){
      const qr=createTuiShareQr(dialog.url??dialog.publicUrl!,deriveWebOrigin(context.client.apiUrl),dialog.target);
      if(qr)chromeState(context.state).chrome={kind:'qr',qr,source:dialog,ownerCurrent:dialog.ownerCurrent};
      else dialog.error='Could not create a QR code for this link.';
    }
    else return false;
    context.render();return true;
  }
  if(dialog.kind==='download'){
    if(!ownerLive(context,dialog))return true;
    if(dialog.busy)return true;
    if(name==='format' && dialog.format!=='original'){
      dialog.format=dialog.format==='md'?'yml':'md';dialog.content=downloadContent(context.state,dialog.format);dialog.path=dialog.path.replace(/\.(?:md|yml)$/i,`.${dialog.format}`);dialog.overwrite=undefined;
    }else if(name==='save'){dialog.overwrite=undefined;await saveDownload(context,dialog);}
    else if(name==='overwrite')await saveDownload(context,dialog,true);
    else return false;
    context.render();return true;
  }
  return false;
}
export async function handleHeaderKey(context:WorkspaceContext,chunk:string,key:TerminalKey):Promise<boolean>{
  const dialog=chromeState(context.state).chrome;
  if(!dialog)return false;
  if(dialog.kind==='chat-settings'&&dialog.editingTask&&key.name==='escape'){await handleHeaderCommand(context,'settings-task-cancel');return true;}
  if(key.name==='escape'){await handleHeaderCommand(context,dialog.kind==='qr'?'qr-back':'close');return true;}
  if(dialog.kind==='more'){
    if(key.name==='up'||key.name==='left')dialog.index=Math.max(0,dialog.index-1);
    else if(key.name==='down'||key.name==='right'||key.name==='tab')dialog.index=Math.min(dialog.actions.length-1,dialog.index+1);
    else if(key.name==='return')await handleHeaderCommand(context,`select ${dialog.actions[dialog.index]?.id}`);
    context.render();return true;
  }
  if(dialog.kind==='copy'){
    if(dialog.ownerCurrent && !dialog.ownerCurrent()){chromeState(context.state).chrome=null;context.render();return true;}
    if(key.name==='return')await handleHeaderCommand(context,'copy');
    const total=renderHeaderDialog(dialog,context.terminal?.width??80).length;
    const page=Math.max(1,(context.terminal?.height??24)-8);
    const max=Math.max(0,total-1);
    if(key.name==='up'||key.name==='scrollup')dialog.scrollOffset=Math.max(0,dialog.scrollOffset-1);
    else if(key.name==='down'||key.name==='scrolldown')dialog.scrollOffset=Math.min(max,dialog.scrollOffset+1);
    else if(key.name==='pageup')dialog.scrollOffset=Math.max(0,dialog.scrollOffset-page);
    else if(key.name==='pagedown')dialog.scrollOffset=Math.min(max,dialog.scrollOffset+page);
    else if(key.name==='home')dialog.scrollOffset=0;
    else if(key.name==='end')dialog.scrollOffset=max;
    context.render();return true;
  }
  if(dialog.kind==='qr'){
    if(key.name==='return')await handleHeaderCommand(context,'copy-link');
    context.render();return true;
  }
  if(dialog.kind==='chat-settings'){
    if(!dialog.ownerCurrent()){chromeState(context.state).chrome=null;context.render();return true;}
    if(dialog.busy)return true;
    const tabs=visibleChatSettingsTabs(context.state),max=tabs.length+chatSettingsActions(dialog,context.state).length;
    if(dialog.editingTask && key.ctrl && key.name==='u'){dialog.taskTitle='';context.render();return true;}
    if(dialog.editingTask && key.name==='backspace'){dialog.taskTitle=eraseGrapheme(dialog.taskTitle);context.render();return true;}
    if(dialog.editingTask && chunk && !key.ctrl && !key.meta && !['return','tab'].includes(key.name??'')){
      dialog.taskTitle+=terminalText(chunk).replace(/[\r\n]/g,'').slice(0,200-dialog.taskTitle.length);context.render();return true;
    }
    if(key.name==='up'||key.name==='left'||key.shift&&key.name==='tab')dialog.field=Math.max(0,dialog.field-1);
    else if(key.name==='down'||key.name==='right'||key.name==='tab')dialog.field=Math.min(max-1,dialog.field+1);
    else if(key.name==='return'){
      if(dialog.editingTask)await handleHeaderCommand(context,'settings-task-save');
      else if(dialog.field<tabs.length)await handleHeaderCommand(context,`settings-tab ${tabs[dialog.field]}`);
      else await handleHeaderCommand(context,chatSettingsActions(dialog,context.state)[dialog.field-tabs.length]?.command.replace('/header-action ','')??'');
    }
    context.render();return true;
  }
  if(dialog.busy)return true;
  const max=dialog.kind==='share'?dialog.target==='public'?3:dialog.target==='chat'?(dialog.url?7:4):(dialog.url?6:3):dialog.format==='original'?2:3;
  if(key.name==='tab'||key.name==='down'){dialog.field=(dialog.field+1)%max;context.render();return true;}
  if(key.name==='up'){dialog.field=(dialog.field+max-1)%max;context.render();return true;}
  if(dialog.kind==='share'){
    if(dialog.target==='public'){
      if(key.name==='return')await handleHeaderCommand(context,['copy-link','show-url','show-qr'][dialog.field]);
    }else if(dialog.field===0 && (key.name==='left'||key.name==='right'||key.name==='return'))await handleHeaderCommand(context,'duration');
    else if(dialog.field===1){if(key.name==='backspace')dialog.password=eraseGrapheme(dialog.password);else if(chunk && !key.ctrl && !key.meta)dialog.password+=terminalText(chunk).replace(/[\r\n]/g,'').slice(0,10-dialog.password.length);dialog.url=undefined;}
    else if(dialog.target==='chat' && dialog.field===2 && key.name==='return')await handleHeaderCommand(context,'sensitive');
    else if(key.name==='return')await handleHeaderCommand(context,dialog.field===(dialog.target==='chat'?3:2)?'generate':dialog.field===(dialog.target==='chat'?4:3)?'copy-link':dialog.field===(dialog.target==='chat'?5:4)?'show-url':'show-qr');
  }else{
    if(dialog.format!=='original' && dialog.field===0 && key.name==='return')await handleHeaderCommand(context,'format');
    else if((dialog.format==='original'?dialog.field===0:dialog.field===1)){
      if(key.name==='backspace')dialog.path=eraseGrapheme(dialog.path);
      else if(chunk && !key.ctrl && !key.meta)dialog.path+=terminalText(chunk).replace(/[\r\n]/g,'');
      dialog.overwrite=undefined;
    }else if(key.name==='return')await handleHeaderCommand(context,dialog.overwrite?'overwrite':'save');
  }
  context.render();return true;
}
export function renderHeaderDialog(dialog:TuiChromeState|null,width:number,height=24,state?:TuiState):TuiLine[]{
  if(!dialog)return [];
  const max=Math.max(20,width-4);
  if(dialog.kind==='more')return [row('More actions'),...dialog.actions.map((item,index)=>row(`${index===dialog.index?'▸':' '} ${item.label}`,`/header-action select ${item.id}`)),row('Esc Close','/header-action close')];
  if(dialog.kind==='chat-settings')return state?renderTuiChatSettings(dialog,state,width):[row('Chat settings')];
  if(dialog.kind==='qr'){
    if(!dialog.ownerCurrent())return [row('This content is no longer available.')];
    const available=Math.max(1,width-2),neededRows=dialog.qr.height+4;
    return [row('Share QR code'),row(''),...(dialog.qr.width<=available&&neededRows<=height
      ?dialog.qr.lines.map(line=>{const padding=' '.repeat(Math.floor((width-dialog.qr.width)/2));return {text:padding+line,spans:[{text:padding},{text:line,color:'#ffffff',background:'#000000'}]};})
      :wrapWords(`QR needs ${dialog.qr.width+2} columns and ${neededRows} rows. Resize terminal or copy the link.`,Math.max(1,width-2)).map(line=>row(line))),row('Back to share','/header-action qr-back'),row('Copy Link','/header-action copy-link')];
  }
  if(dialog.kind==='copy')return dialog.ownerCurrent && !dialog.ownerCurrent()?[row('This content is no longer available.')]:[row(dialog.title),...wrapCells(dialog.text,max).map(line=>row(line)),row('Select text above if clipboard delivery was not confirmed.'),row('Copy again','/header-action copy'),row('Close','/header-action close')];
  if(dialog.kind==='share'){
    if(dialog.target!=='public' && !dialog.ownerCurrent())return [row('This content is no longer available.')];
    const url=dialog.url??dialog.publicUrl;
    return [row(dialog.target==='public'?'Public link':'Share settings'),...(dialog.target==='public'?[]:[
      row(`${dialog.field===0?'▸ ':'  '}Expiration: ${DURATION_LABELS[DURATIONS.indexOf(dialog.duration)]}`,'/header-action duration'),
      row(`${dialog.field===1?'▸ ':'  '}Password: ${'*'.repeat(dialog.password.length)} (max 10 characters)`,'/header-action focus 1'),
      ...(dialog.target==='chat'?[row(`${dialog.field===2?'▸ ':'  '}Include sensitive data: ${dialog.includeSensitiveData?'Yes':'No'}`,'/header-action sensitive')]:[]),
      row(`${dialog.field===(dialog.target==='chat'?3:2)?'▸ ':'  '}${dialog.busy?'Generating…':'Generate Link'}`,dialog.busy?undefined:'/header-action generate')]),
      ...(url?[row(`${dialog.field===(dialog.target==='chat'?4:dialog.target==='embed'?3:0)?'▸ ':'  '}Copy Link`,'/header-action copy-link'),row(`${dialog.field===(dialog.target==='chat'?5:dialog.target==='embed'?4:1)?'▸ ':'  '}Show URL`,'/header-action show-url'),row(`${dialog.field===(dialog.target==='chat'?6:dialog.target==='embed'?5:2)?'▸ ':'  '}Show QR code`,'/header-action show-qr')]:[]),
      ...(dialog.error?[row(dialog.error)]:[]),row('Close','/header-action close')];
  }
  if(!dialog.ownerCurrent())return [row('This content is no longer available.')];
  return [row('Download to this CLI machine'),...(dialog.format==='original'?[]:[row(`${dialog.field===0?'▸ ':'  '}Format: ${dialog.format==='md'?'Markdown':'YAML'}`,'/header-action format')]),row(`${dialog.field===(dialog.format==='original'?0:1)?'▸ ':'  '}Destination: ${truncateCells(dialog.path,max-15)}`,`/header-action focus ${dialog.format==='original'?0:1}`),row(`${dialog.field===(dialog.format==='original'?1:2)?'▸ ':'  '}${dialog.overwrite?'Overwrite existing file?':'Save'}`,dialog.busy?undefined:`/header-action ${dialog.overwrite?'overwrite':'save'}`),...(dialog.error?[row(dialog.error)]:[]),row('Close','/header-action close')];
}
