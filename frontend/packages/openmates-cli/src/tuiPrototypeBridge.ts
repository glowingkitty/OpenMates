/** Presentation-only bridge for the opt-in Ratatui experiment. Never carries keys or credentials. */
import type {TuiState} from './tuiRenderer.js';
import {parseTuiMarkdown} from './tuiMarkdown.js';
import {terminalText} from './tuiText.js';
import {aliasForEmbed, messageEmbedReferences} from './tuiEmbeds.js';
import {APP_GRADIENTS, PRIMARY_GRADIENT} from '../../appGradientTheme.js';
import {CATEGORY_GRADIENTS} from '../../chatCategoryTheme.js';

export type PrototypeSpan = {text:string;bold?:boolean;color?:string};
export type PrototypeSnapshot = {v:1;type:'snapshot';epoch:number;scope:string;state:{
  view:string;sidebarOpen:boolean;title:string;category:string;
  categories:Array<{id:string;label:string;color:string}>;
  chats:Array<{id:string;title:string;categoryId:string}>;selectedChatId:string;
  messages:Array<{id:string;role:string;senderName:string;lines:Array<{spans:PrototypeSpan[]}>;
    embeds:Array<{id:string;title:string;app:string;color:string}>}>;
  draft:string;workspaceRows:Array<{id:string;label:string;detail?:string;color?:string}>;
}};
export type PrototypeAction = {v:1;type:'action';epoch:number;scope:string;action:string;id?:string;value?:string;open?:boolean};
const VIEWS=['chats','apps','projects','workflows','tasks'];
export function prototypeScope(state:TuiState):string {
  return JSON.stringify([state.signedIn,state.currentUserHash,state.activeTeamId,state.activeChatId,state.workspace]);
}
export function prototypeSnapshot(state:TuiState,epoch:number,width:number):PrototypeSnapshot {
  const messages=state.messages.slice(-1000).map((message,index)=>({
    id:message.id??`message-${index}`,role:message.role,
    senderName:terminalText(message.remoteUser?message.title??'Member':message.role==='user'?'You':message.title??state.activeChat?.mateName??'Assistant'),
    lines:parseTuiMarkdown(message.content,Math.max(1,width-4),{
      resolveEmbedAlias:id=>aliasForEmbed(state,id),questionBlocks:message.role==='assistant',
    }).flatMap(block=>block.type!=='line'?[]:[{spans:typeof block.line==='string'?[{text:block.line}]:
      block.line.spans?.map(({text,bold,color})=>({text,bold,color}))??[{text:block.line.text,bold:block.line.bold,color:block.line.color}]}]),
    embeds:messageEmbedReferences(message).map(ref=>{
      const embed=state.chatEmbeds[ref.value];const app=embed?.appId??'embed';
      return {id:ref.value,title:terminalText(embed?.textPreview??`${app} · ${embed?.skillId??'Saved result'}`),app,
        color:(APP_GRADIENTS[app]??PRIMARY_GRADIENT).start};
    }),
  }));
  const rows=state.workspace==='tasks'?state.tasks.map(task=>({id:task.taskId,label:task.title??'Task'})):
    state.workspace==='projects'?state.projects.map(project=>({id:project.id,label:project.name})):
    state.workspace==='workflows'?state.workflows.map(workflow=>({id:workflow.id,label:workflow.title??'Workflow'})):[];
  const snapshot:PrototypeSnapshot={v:1,type:'snapshot',epoch,scope:prototypeScope(state),state:{
    view:state.workspace,sidebarOpen:state.sidebarOpen,title:terminalText(state.activeChat?.title??'OpenMates'),category:state.activeChat?.category??'',
    categories:Object.entries(CATEGORY_GRADIENTS).map(([id,gradient])=>({id,label:id.replaceAll('_',' '),color:gradient.start})),
    chats:state.recentChats.slice(0,1000).map(chat=>({id:chat.id,title:terminalText(chat.title??'Untitled chat'),categoryId:chat.category??''})),
    selectedChatId:state.activeChatId??'',messages,draft:state.input,workspaceRows:rows.slice(0,1000),
  }};
  if(Buffer.byteLength(JSON.stringify(snapshot))>4*1024*1024)throw new Error('Prototype presentation exceeds the 4 MiB bound.');
  return snapshot;
}

/** IDs and authority come from the currently owned presentation, never from a Rust action. */
export function currentPrototypeAction(value:unknown,snapshot:PrototypeSnapshot):PrototypeAction|null {
  if(!value||typeof value!=='object'||Array.isArray(value))return null;
  const action=value as PrototypeAction;
  if(action.v!==1||action.type!=='action'||action.epoch!==snapshot.epoch||action.scope!==snapshot.scope)return null;
  if(action.action==='draft_changed'||action.action==='send_message')return typeof action.value==='string'&&Buffer.byteLength(action.value)<=8192?action:null;
  if(action.action==='set_sidebar')return typeof action.open==='boolean'?action:null;
  if(action.action==='back')return action;
  if(typeof action.id!=='string')return null;
  if(action.action==='open_chat')return snapshot.state.chats.some(chat=>chat.id===action.id)?action:null;
  if(action.action==='open_embed')return snapshot.state.messages.some(message=>message.embeds.some(embed=>embed.id===action.id))?action:null;
  if(action.action==='select_category')return snapshot.state.categories.some(category=>category.id===action.id)?action:null;
  if(action.action==='open_workspace')return VIEWS.includes(action.id)?action:null;
  if(action.action==='open_workspace_item')return snapshot.state.workspaceRows.some(row=>row.id===action.id)?action:null;
  return null;
}
