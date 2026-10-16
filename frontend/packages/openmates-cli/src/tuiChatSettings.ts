/** Chat-local settings tabs, using the same encrypted task and plan records as CLI commands. */
import type { WorkspaceContext } from './tuiWorkspaceController.js';
import type { TuiState } from './tuiRenderer.js';
import { buildCreateUserTaskInput, buildUpdateUserTaskInput, decryptUserTask, type DecryptedUserTask } from './tasksCli.js';
import { loadTuiTaskList } from './tuiTaskList.js';
import { decryptUserPlans } from './plansCli.js';
import { aliasForEmbed, chatEmbedReferences, exampleEmbedMap } from './tuiEmbeds.js';
import { collectGeneratedFiles } from './generatedFiles.js';
import { cells, truncateCells, wrapCells, type TuiLine, type TuiSpan } from './tuiText.js';
import type { ChatUsageEntry } from '../../ui/src/types/chat.js';

export const CHAT_SETTINGS_TABS=['plan','tasks','files','usage','share'] as const;
export type TuiChatSettingsTab=typeof CHAT_SETTINGS_TABS[number];
export type TuiChatUsageRow={id:string;label:string;provider:string;timestamp:number;credits:number|null};
export type TuiChatSettingsState={kind:'chat-settings';chatId:string;title:string;tab:TuiChatSettingsTab;field:number;ownerCurrent:()=>boolean;request:number;loading:boolean;busy:boolean;items:string[];tasks:DecryptedUserTask[];usageRows:TuiChatUsageRow[];usageTotal:number|null;editingTask:boolean;taskTitle:string;error?:string};
const LABELS:Record<TuiChatSettingsTab,string>={plan:'Plan',tasks:'Tasks',files:'Files',usage:'Usage',share:'Share'};
const row=(text:string,command?:string):TuiLine=>({text,...(command?{action:{kind:'command' as const,command}}:{})});
function tabLines(dialog:TuiChatSettingsState,tabs:TuiChatSettingsTab[],width:number):TuiLine[]{
  const groups:Array<Array<{tab:TuiChatSettingsTab;index:number;text:string}>>=[];
  let group:typeof groups[number]=[],used=0;
  tabs.forEach((tab,index)=>{
    const text=`${dialog.field===index?'›':''}${tab===dialog.tab?`[${LABELS[tab]}]`:LABELS[tab]}`;
    const next=cells(text)+(group.length?3:0);
    if(group.length&&used+next>Math.max(1,width-2)){groups.push(group);group=[];used=0;}
    group.push({tab,index,text});used+=cells(text)+(group.length>1?3:0);
  });
  if(group.length)groups.push(group);
  return groups.map(items=>{
    const length=items.reduce((sum,item,index)=>sum+cells(item.text)+(index?3:0),0),spans:TuiSpan[]=[{text:' '.repeat(Math.max(0,Math.floor((width-length)/2)))}];
    items.forEach((item,index)=>{
      if(index)spans.push({text:'   '});
      spans.push({text:item.text,color:item.tab===dialog.tab?'#32ade6':'#b3c5e9',bold:item.tab===dialog.tab||item.index===dialog.field,action:{kind:'command',command:`/header-action settings-tab ${item.tab}`}});
    });
    return {text:spans.map(span=>span.text).join(''),spans};
  });
}

export function createTuiChatSettings(state:TuiState,ownerCurrent:()=>boolean):TuiChatSettingsState {
  const tabs=visibleChatSettingsTabs(state);
  const tab=state.screen==='example'||state.activeChat?.source==='example'?'share':'plan';
  const chatId=state.activeChatId??state.activeExample?.chat.id??'';
  return {kind:'chat-settings',chatId,title:state.activeChat?.title??state.activeExample?.chat.title??'Chat',tab,field:tabs.indexOf(tab),ownerCurrent,request:0,loading:false,busy:false,items:[],tasks:(state.tasks??[]).filter(task=>task.primaryChatId===chatId),usageRows:[],usageTotal:null,editingTask:false,taskTitle:''};
}

export function visibleChatSettingsTabs(state:TuiState):TuiChatSettingsTab[] {
  if(state.screen!=='example' && state.activeChat?.source!=='example')return [...CHAT_SETTINGS_TABS];
  return [...(chatSettingsFileRefs(state).length?['files' as const]:[]),'share'];
}

export function chatSettingsFileRefs(state:TuiState):string[]{
  const example=state.screen==='example'||state.activeChat?.source==='example';
  return [...new Set([...chatEmbedReferences(state).map(ref=>ref.value),...(example?state.activeExample?.files??[]:[]).map(file=>file.embedId)])];
}

function usageRow(entry:ChatUsageEntry):TuiChatUsageRow {
  const timestamp=typeof entry.created_at==='number'?entry.created_at:Math.floor(Date.parse(entry.created_at)/1000)||0;
  return {id:entry.id,label:entry.app_id&&entry.skill_id?`${entry.app_id} | ${entry.skill_id}`:entry.app_id??entry.type??'Unknown activity',provider:entry.server_provider??entry.model_used??'Unknown provider',timestamp,credits:typeof entry.credits==='number'?entry.credits:null};
}

export async function loadTuiChatSettings(context:WorkspaceContext,dialog:TuiChatSettingsState):Promise<void> {
  if (!['plan','tasks','usage'].includes(dialog.tab) || context.state.screen==='example') return;
  const tab=dialog.tab,request=++dialog.request;
  dialog.loading=true;dialog.items=[];dialog.error=undefined;context.render();
  if(tab==='tasks'){
    const current=()=>dialog.ownerCurrent()&&context.state.chrome===dialog&&dialog.tab===tab&&dialog.request===request&&context.state.activeChatId===dialog.chatId;
    await loadTuiTaskList(context.client,`chat:${dialog.chatId}:tasks`,{chatId:dialog.chatId},(tasks,source,complete)=>{
      if(!current())return;
      const tabs=visibleChatSettingsTabs(context.state),selectedCommand=dialog.field>=tabs.length
        ?chatSettingsActions(dialog,context.state)[dialog.field-tabs.length]?.command:undefined;
      dialog.tasks=tasks;dialog.loading=!complete;
      dialog.error=complete?undefined:source==='cache'?'Showing saved tasks. Syncing…':`Loading more tasks… ${tasks.length} available.`;
      if(selectedCommand){const index=chatSettingsActions(dialog,context.state).findIndex(action=>action.command===selectedCommand);if(index>=0)dialog.field=tabs.length+index;}
      context.render();
    },(_error,hasUsable)=>{
      if(!current())return;
      dialog.loading=false;
      dialog.error=hasUsable?'Showing saved or partially synced tasks. Refresh failed.':'Could not load tasks. Retry when connected.';
      context.render();
    });
    return;
  }
  try {
    const key=tab==='usage'?null:context.client.getMasterKeyBytes();
    const plans=tab==='plan'?await decryptUserPlans(await context.client.listUserPlans({chatId:dialog.chatId}),key!):null;
    const usage=tab==='usage'?await Promise.all([
      context.client.settingsGet(`usage/chat-entries?${new URLSearchParams({chat_id:dialog.chatId,limit:'500'})}`),
      context.client.settingsGet(`usage/chat-total?${new URLSearchParams({chat_id:dialog.chatId})}`),
    ]):null;
    if (!dialog.ownerCurrent() || context.state.chrome!==dialog || dialog.tab!==tab || dialog.request!==request || context.state.activeChatId!==dialog.chatId) return;
    if(plans)dialog.items=plans.map(plan=>`${plan.title} · ${plan.status}${plan.goal?` · ${plan.goal}`:''}`);
    if(usage){
      const [entries,total]=usage as [{entries?:ChatUsageEntry[]},{total_credits?:number}];
      if(!Array.isArray(entries?.entries)||!entries.entries.every(item=>item&&typeof item==='object'))throw Error('Invalid usage rows.');
      dialog.usageRows=entries.entries.map(usageRow);
      dialog.usageTotal=typeof total?.total_credits==='number'?total.total_credits:null;
    }
  } catch {
    if (!dialog.ownerCurrent() || context.state.chrome!==dialog || dialog.tab!==tab || dialog.request!==request) return;
    dialog.error=`Could not load ${LABELS[tab].toLowerCase()}. Retry when connected.`;
  } finally {
    if (dialog.ownerCurrent() && context.state.chrome===dialog && dialog.tab===tab && dialog.request===request) {dialog.loading=false;context.render();}
  }
}

export async function submitTuiChatTask(context:WorkspaceContext,dialog:TuiChatSettingsState,taskId?:string):Promise<void>{
  if(dialog.busy||!dialog.ownerCurrent()||context.state.chrome!==dialog||context.state.activeChatId!==dialog.chatId)return;
  const title=dialog.taskTitle.trim();
  if(!taskId && (!title||title.length>200)){dialog.error='Task title must be 1–200 characters.';context.render();return;}
  const task=taskId?dialog.tasks.find(item=>item.taskId===taskId):undefined;
  if(taskId&&(!task||task.readOnly)){dialog.error='This task cannot be changed here.';context.render();return;}
  dialog.busy=true;dialog.error=undefined;context.render();
  let phase:'prepare'|'save'|'decrypt'='prepare';
  try{
    const key=context.client.getMasterKeyBytes();
    const input=task?await buildUpdateUserTaskInput(task,key,{status:task.status==='done'?'todo':'done'})
      :await buildCreateUserTaskInput(key,{title,chatId:dialog.chatId,assign:'user'});
    if(!dialog.ownerCurrent()||context.state.chrome!==dialog||context.state.activeChatId!==dialog.chatId)return;
    phase='save';
    const record=task?await context.client.updateUserTask(task.taskId,input as Parameters<typeof context.client.updateUserTask>[1])
      :await context.client.createUserTask(input as Parameters<typeof context.client.createUserTask>[0]);
    phase='decrypt';
    const updated=await decryptUserTask(record,key);
    if(!dialog.ownerCurrent()||context.state.chrome!==dialog||context.state.activeChatId!==dialog.chatId)return;
    dialog.tasks=[updated,...dialog.tasks.filter(item=>item.taskId!==updated.taskId)];
    context.state.tasks=[updated,...(context.state.tasks??[]).filter(item=>item.taskId!==updated.taskId)];
    dialog.editingTask=false;dialog.taskTitle='';dialog.field=visibleChatSettingsTabs(context.state).length;
  }catch(error){
    // Expose only fixed operation names and numeric status, never server messages or encrypted payloads.
    const status=error&&typeof error==='object'&&'status' in error?error.status:undefined;
    const detail=typeof status==='number'&&Number.isInteger(status)&&status>=100&&status<=599?`${phase}: HTTP ${status}`:phase;
    if(dialog.ownerCurrent()&&context.state.chrome===dialog)dialog.error=task?`Could not update task (${detail}). Retry.`:`Could not create task (${detail}). Review the title and retry.`;
  }finally{dialog.busy=false;if(dialog.ownerCurrent()&&context.state.chrome===dialog)context.render();}
}

export function chatSettingsActions(dialog:TuiChatSettingsState,state:TuiState):Array<{label:string;command:string}> {
  if (dialog.tab==='share') return [{label:'Share chat',command:'/header-action settings-share'},...(state.screen==='chat'&&state.messages.length?[{label:'Download chat',command:'/header-action settings-download'}]:[]),{label:'Copy web settings link',command:'/header-action settings-web'}];
  if (dialog.tab==='files') {const examples=state.screen==='example'||state.activeChat?.source==='example'?exampleEmbedMap(state):{};return [...chatSettingsFileRefs(state).slice(0,30).flatMap(id=>{
    const alias=aliasForEmbed(state,id),loaded=state.chatEmbeds[id]??examples[id];
    if(state.screen==='example'&&!loaded)return [];
    const data=loaded?.content??{},hasText=['code','text','document','markdown','mermaid','diagram'].includes(loaded?.type??'')
      && (typeof data.code==='string'||typeof data.text==='string'||typeof data.content==='string');
    const downloadable=loaded&&(hasText||collectGeneratedFiles(data).length>0);
    return [{label:`Open ${alias}`,command:`/header-action settings-file ${alias}`},...(downloadable?[{label:`Download ${alias}`,command:`/header-action settings-file-download ${alias}`}]:[])];
  }),{label:'Copy web settings link',command:'/header-action settings-web'}];}
  if(dialog.tab==='tasks')return dialog.loading&&!dialog.tasks.length?[]:dialog.editingTask?[{label:'Save task',command:'/header-action settings-task-save'},{label:'Cancel task',command:'/header-action settings-task-cancel'}]
    :[{label:'Create task',command:'/header-action settings-task-create'},...dialog.tasks.slice(0,20).flatMap(task=>[
      {label:`Open task ${task.title}`,command:`/header-action settings-task-open ${task.taskId}`},
      ...(task.readOnly?[]:[{label:`${task.status==='done'?'Undo done':'Mark done'} · ${task.title}`,command:`/header-action settings-task-toggle ${task.taskId}`}]),
    ]),...(dialog.error?[{label:'Retry',command:'/header-action settings-retry'}]:[])];
  if(dialog.tab==='usage')return [...(dialog.usageRows.length?[{label:'Download usage CSV',command:'/header-action settings-usage-download csv'},{label:'Download usage YAML',command:'/header-action settings-usage-download yml'}]:[]),...(dialog.error?[{label:'Retry',command:'/header-action settings-retry'}]:[])];
  if (dialog.tab==='plan'&&dialog.error) return [{label:'Retry',command:'/header-action settings-retry'}];
  return [];
}

export function renderTuiChatSettings(dialog:TuiChatSettingsState,state:TuiState,width:number):TuiLine[] {
  if (!dialog.ownerCurrent()) return [row('This chat is no longer available.')];
  const max=Math.max(8,width-4),actions=chatSettingsActions(dialog,state),tabs=visibleChatSettingsTabs(state);
  const lines:TuiLine[]=[row(`Chat settings · ${truncateCells(dialog.title,max-16)}`),row(''),...tabLines(dialog,tabs,width)];
  lines.push(row(''));
  if (dialog.tab==='plan') {
    if (dialog.loading) lines.push(row('Loading plan…'));
    else if(dialog.error)lines.push(row(dialog.error));
    else if (!dialog.items.length) lines.push(row('No plans linked to this chat.'));
    else for(const item of dialog.items.slice(0,20))lines.push(...wrapCells(`• ${item}`,max).map(line=>row(line)));
  }else if(dialog.tab==='tasks'){
    if(dialog.loading)lines.push(row(dialog.error??'Loading tasks…'));
    else if(dialog.error&&!dialog.editingTask)lines.push(row(dialog.error));
    else lines.push(row(`${dialog.tasks.filter(task=>task.status==='done').length}/${dialog.tasks.length} tasks done`));
    if(dialog.editingTask)lines.push(row(`Task title: ${truncateCells(dialog.taskTitle,max-14)}_`,'/header-action settings-task-focus'));
    else if(!dialog.loading&&!dialog.tasks.length)lines.push(row('No tasks linked to this chat.'));
  } else if (dialog.tab==='files') {
    const fileActions=actions.filter(item=>!item.command.endsWith('settings-web'));
    if (!fileActions.length&&(state.screen==='example'||state.activeChat?.source==='example')&&state.activeExample?.files.length)for(const file of state.activeExample.files.slice(0,20))lines.push(row(truncateCells(`${file.title} · download in web app`,max)));
    else if(!fileActions.length)lines.push(row('No embedded files in this chat.'));
    else lines.push(row('Open or download an embedded result.'));
    lines.push(row('Bulk ZIP download is available in the web app.'));
  } else if (dialog.tab==='usage') {
    if(dialog.loading)lines.push(row('Loading usage…'));
    else if(dialog.error)lines.push(row(dialog.error));
    else{lines.push(row(`Total credits: ${dialog.usageTotal??'unknown'}`));
      for(const item of dialog.usageRows.slice(0,20))lines.push(row(truncateCells(`• ${item.label} · ${item.provider} · ${item.credits??'unknown'} credits`,max)));
      if(!dialog.usageRows.length)lines.push(row('No usage entries for this chat.'));
    }
  } else {
    lines.push(row('Create an encrypted share link, then choose Copy, URL, or QR.'));
    lines.push(row('Community sharing and Stop sharing are available in the web app.'));
  }
  if(dialog.error&&dialog.editingTask)lines.push(row(dialog.error));
  if(dialog.busy)lines.push(row('Saving task…'));
  actions.forEach((item,index)=>lines.push(row(`${dialog.field===tabs.length+index?'▸':' '} ${item.label}`,dialog.busy?undefined:item.command)));
  lines.push(row('Esc Close','/header-action close'));
  return lines;
}
