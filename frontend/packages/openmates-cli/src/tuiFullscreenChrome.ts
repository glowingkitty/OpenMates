import {clearTuiSendState} from './tuiStreamingRender.js';
/** Contextual navigation uses view state, never deletes the underlying object. */
import type {TuiState, TuiFocus, TuiScreen, TuiWorkspace} from './tuiRenderer.js';
import type {TuiLine, TuiSpan} from './tuiText.js';
import {cells, truncateCells} from './tuiText.js';
import {headerCapabilities} from './tuiHeaderActions.js';

export type TuiViewOrigin = {
  screen:TuiScreen; workspace:TuiWorkspace; focus:TuiFocus;
  selectedIndex:number; scrollOffset:number; filter:string; input:string;
  inputCursor?:number|null; sidebarOpen?:boolean;
};
export function captureTuiView(state:TuiState):TuiViewOrigin {
  return {screen:state.screen,workspace:state.workspace,focus:state.focus,
    selectedIndex:state.selectedIndex,scrollOffset:state.scrollOffset,filter:state.filter,
    input:state.input,inputCursor:state.inputCursor,sidebarOpen:state.sidebarOpen};
}
export function restoreTuiView(state:TuiState,origin:TuiViewOrigin):void {
  clearTuiSendState(state);
  Object.assign(state,origin);state.inputCursor=origin.inputCursor??null;
  state.navigationIndex=['chats','apps','projects','workflows','tasks'].indexOf(state.workspace);
  state.status=null;state.followSelection=false;state.headerActionIndex=0;++state.routeVersion;
}
export function isTuiFullscreen(state:TuiState):boolean {
  return ['chat','example','embed','results-view','app-result'].includes(state.screen);
}
export function closeTuiFullscreen(state:TuiState):boolean {
  if(state.screen==='embed'||state.screen==='results-view'){
    const origin=state.screen==='results-view'?state.resultsViewOrigin:state.embedOrigin;
    if(state.screen==='results-view')state.resultsViewOrigin=null;else state.embedOrigin=null;
    state.detailEmbed=null;state.embedChoices=[];
    if(origin)restoreTuiView(state,origin);
    else {state.screen=state.workspace==='projects'?'project':state.workspace==='apps'?'app':'chats';state.focus='content';state.scrollOffset=0;++state.routeVersion;}
    return true;
  }
  if(state.screen==='chat'||state.screen==='example'){
    clearTuiSendState(state);
    if(!state.input.startsWith('/'))state.drafts[state.screen==='example'?`example:${state.activeExample?.chat.id}`:state.activeChatId??'new']=state.input;
    const origin=state.chatOrigin;state.chatOrigin=null;
    state.activeChatId=null;state.activeChat=null;state.activeExample=null;state.messages=[];
    state.headerState='new';state.headerError=null;state.followUpSuggestions=[];state.status=null;
    state.chatEmbeds={};state.embedAliases={};state.chatSelectedEmbedId=null;state.chatEmbedLoads=new Set();
    state.resultsViewModes={};state.activeResultsView=null;state.resultsViewOrigin=null;
    if(origin)restoreTuiView(state,origin);
    else {state.screen='start';state.workspace='chats';state.focus='content';state.navigationIndex=0;state.input=state.drafts.new??'';state.inputCursor=null;state.scrollOffset=0;state.selectedIndex=0;++state.routeVersion;}
    return true;
  }
  if(state.screen==='app-result'){
    state.screen=state.activeAppSkill?'app-skill':'app';state.appSkillTab='embeds';state.appTab='embeds';state.focus='content';state.scrollOffset=0;++state.routeVersion;return true;
  }
  return false;
}
type HeaderControl={id:string;label:string;command:string};
export function fullscreenHeaderControls(state:TuiState,width:number):HeaderControl[] {
  const origin=state.screen==='embed'?state.embedOrigin:state.screen==='results-view'?state.resultsViewOrigin:state.chatOrigin;
  const controls:HeaderControl[]=[{id:'back',label:width<10?'‹':'‹ Back',command:'/back'}];
  if(width>=20&&origin?.workspace==='projects'&&state.activeProject)controls.push({id:'parent',label:state.activeProject.name,command:`/project ${state.activeProject.id}`});
  else if(width>=20)controls.push({id:'parent',label:state.workspace==='apps'?'Apps':'Chats',command:state.workspace==='apps'?'/apps':'/chats'});
  if(width>=36&&['embed','results-view'].includes(state.screen)&&origin&&['chat','example'].includes(origin.screen))controls.push({id:'chat',label:state.activeChat?.title??state.activeExample?.chat?.title??'Chat',command:'/back'});
  const actions=headerCapabilities(state).filter(action=>width>=64||width>=30&&['share','more'].includes(action.id)||width>=15&&action.id==='more');
  controls.push(...actions.map(action=>({id:action.id,label:action.label,command:`/header ${action.id}`})),{id:'close',label:width<10?'×':'× Close',command:'/close'});
  return controls;
}
export function fullscreenHeaderLines(state:TuiState,width:number):TuiLine[] {
  if(!isTuiFullscreen(state))return [];
  width=Math.max(1,width);
  const controls=fullscreenHeaderControls(state,width),actionStart=controls.findIndex(control=>!['back','parent','chat'].includes(control.id));
  const span=(control:HeaderControl):TuiSpan=>({text:control.label,color:state.focus==='header'&&controls[state.headerActionIndex]?.id===control.id?'#32ade6':'#b3c5e9',bold:true,action:{kind:'command',command:control.command}});
  const title=['embed','results-view'].includes(state.screen)?state.detailTitle||'Results':state.screen==='app-result'?String(state.activeAppResult?.content.title??'Saved result'):state.activeChat?.title??state.activeExample?.chat?.title??'Chat';
  const crumbControls=controls.slice(0,actionStart),crumbs:TuiSpan[]=[];
  let remaining=width;
  for(const control of crumbControls){
    if(remaining<5)break;
    const item=span(control);
    item.text=truncateCells(item.text,Math.max(1,Math.min(remaining-4,control.id==='back'?8:Math.floor(width/3))));
    crumbs.push(item,{text:' › ',color:'#808080'});remaining-=cells(item.text)+3;
  }
  crumbs.push({text:truncateCells(title,Math.max(0,Math.min(72,remaining))),color:'#cfcfcf',bold:true});
  const actions:TuiSpan[]=[];
  const actionControls=controls.slice(actionStart),gap=width<40?' ':'   ';
  let room=width;
  for(const [index,control] of actionControls.entries()){
    const separator=index?gap:'';
    const label=truncateCells(control.label,Math.max(1,room-cells(separator)));
    if(!label)break;
    if(separator){actions.push({text:separator});room-=cells(separator);}
    actions.push({...span(control),text:label});room-=cells(label);
    if(room<=0)break;
  }
  if(room>=20)actions.push({text:'   '},{text:'Alt+H header',color:'#808080'});
  const centered=(parts:TuiSpan[]):TuiLine=>{
    const offset=Math.max(0,Math.floor((width-cells(parts.map(item=>item.text).join('')))/2));
    const spans=[{text:' '.repeat(offset)},...parts];
    return {text:spans.map(item=>item.text).join(''),spans};
  };
  return [centered(crumbs),centered(actions),''];
}
