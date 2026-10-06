/** The rendered web workspace home hierarchy, adapted to terminal cells. */
import {createHash} from "node:crypto";
import type { ChatListItem, DailyInspiration, DecryptedMemoryEntry, OpenMatesClient } from "./client.js";
import type { TuiState, TuiWorkspace } from "./tuiRenderer.js";
import { getWorkspaceInspirations } from "../../workspaceInspirationDefaults.js";
import { CATEGORY_GRADIENTS } from "../../chatCategoryTheme.js";
import { centeredCarouselText, renderCardCarousel } from "./tuiCarousel.js";
import { terminalText, wrapCells, type TuiLine } from "./tuiText.js";
import { runningTuiChatGroups, refreshTuiChatSidebar, updateTuiChatSidebar } from './tuiChatSidebar.js';

import {getSavedEmbedContinueCandidates,getReminderByTargetEmbedId,getReminderByTargetChatId,sortContinuePriorityItems,
  type ActiveReminderForContinue,type ContinuePriority,type SavedEmbedContinueCandidate} from "../../ui/src/services/continueCarouselService.js";

export type HomeContinueItem = SavedEmbedContinueCandidate | {kind:"chat";chat:ChatListItem;priority?:ContinuePriority};
export function homeContinueItems(state:TuiState,now=Date.now()):HomeContinueItem[] {
  const chats=homeChatItems(state);
  if(!state.signedIn || !state.continueData)return chats.map(chat=>({kind:"chat",chat}));
  const entriesByApp=new Map<string,Record<string,{id:string;item_key:string;item_value:Record<string,unknown>;settings_group:string}[]>>();
  for(const memory of state.continueData.memories) {
    const groups=entriesByApp.get(memory.app_id) ?? {};const group=memory.item_type;
    (groups[group] ??= []).push({id:memory.id,item_key:memory.item_key_hash,item_value:memory.data,settings_group:group});
    entriesByApp.set(memory.app_id,groups);
  }
  const reminders=state.continueData.reminders as unknown as ActiveReminderForContinue[];
  const reminderChats=getReminderByTargetChatId(reminders,now);
  const priorityChats=chats.filter(chat=>reminderChats.has(chat.id) && !chat.parentId && !chat.isSubChat && chat.id!==state.activeChatId)
    .map(chat=>({kind:"chat" as const,chat,priority:reminderChats.get(chat.id)!.priority}));
  const embeds=getSavedEmbedContinueCandidates({entriesByApp},getReminderByTargetEmbedId(reminders,now),now)
    .filter(item=>`${item.title} ${item.summary??""} ${item.priority.label}`.toLowerCase().includes(state.filter.toLowerCase()));
  const priority=sortContinuePriorityItems([...priorityChats,...embeds],now).slice(0,10);
  const promoted=new Set(priority.filter(item=>item.kind==="chat").map(item=>item.chat.id));
  return [...priority,...chats.filter(chat=>!promoted.has(chat.id)).map(chat=>({kind:"chat" as const,chat}))];
}
export const homeItemId=(item:HomeContinueItem|undefined):string|undefined=>item?.kind==="embed" ? `embed:${item.embedId}` : item ? `chat:${item.chat.id}` : undefined;

const BLUE = {start: "#4867cd", end: "#5a85eb"};
const prompts: Record<TuiWorkspace, string> = {
  chats: "What do you need help with?", projects: "What do you want to organize next?",
  workflows: "What do you want to automate next?", tasks: "What task is next?", apps: "What app do you want to use?",
};
export const isWorkspaceHome = (s: TuiState): boolean => ["start", "chats", "projects", "tasks", "workflows", "apps"].includes(s.screen);
export function homeChatItems(state: TuiState): ChatListItem[] {
  const chats: ChatListItem[] = state.signedIn ? state.recentChats : state.examples;
  return chats.filter(c => !c.isHiddenCandidate && !c.isHidden && `${c.title} ${c.draftPreview ?? ''} ${c.summary}`.toLowerCase().includes(state.filter.toLowerCase()));
}
export function workspaceInspirations(state: TuiState): DailyInspiration[] {
  const available = state.inspirations.filter((i) => (i.surface ?? "chats") === state.workspace);
  if (available.length || state.workspace === "chats") return available;
  return getWorkspaceInspirations(state.workspace).map((i) => ({...i, id:i.inspiration_id, title:i.title ?? "", assistant_response:i.assistant_response ?? "", follow_up_suggestions:i.follow_up_suggestions ?? []}));
}
export function currentInspiration(state: TuiState): DailyInspiration | undefined {
  const list = workspaceInspirations(state);
  return list[(state.inspirationIndices[state.workspace] ?? 0) % Math.max(1,list.length)];
}
function updateHomeChats(state: TuiState, chats: ChatListItem[]): void {
  const preserveSelection=isWorkspaceHome(state) && state.workspace==="chats";
  const selectedId=preserveSelection ? homeItemId(homeContinueItems(state)[state.selectedIndex]) : undefined;
  updateTuiChatSidebar(state,()=>{state.recentChats=chats;});
  if(preserveSelection) {
    const items=homeContinueItems(state), index=items.findIndex(item=>homeItemId(item)===selectedId);
    state.selectedIndex=index>=0 ? index : Math.max(0,Math.min(state.selectedIndex,items.length-1));
  }
}
export async function loadHomeData(state: TuiState, client: OpenMatesClient, render: () => void): Promise<void> {
  state.homeAbortController?.abort();
  const controller=new AbortController();state.homeAbortController=controller;
  const request = ++state.homeLoadVersion, signedIn=state.signedIn;
    const teamId=typeof client.getActiveTeamId==="function" ? client.getActiveTeamId() : null;
  const masterKey=signedIn && typeof client.getMasterKeyBytes==="function" ? Buffer.from(client.getMasterKeyBytes()) : null;
  const contextKey=`${teamId ?? "personal"}:${masterKey ? createHash("sha256").update(masterKey).digest("hex") : signedIn}`;
  if(state.homeContextKey && state.homeContextKey!==contextKey){state.continueData=null;state.recentChats=[];state.activityChats=[];state.sidebarLinkedChats=[];state.chatSidebarProjects=[];}
  state.homeContextKey=contextKey;
  const current=()=>{
    if(controller.signal.aborted || request!==state.homeLoadVersion || state.signedIn!==signedIn)return false;
    if(typeof client.getActiveTeamId==="function" && client.getActiveTeamId()!==teamId)return false;
    try{return !masterKey || ((typeof client.hasSession!=="function" || client.hasSession()) && masterKey.equals(Buffer.from(client.getMasterKeyBytes())));}catch{return false;}
  };
  state.homeLoading=true;
  state.homeError=null;
  state.homeChatsLoading=signedIn && homeChatItems(state).length===0;
  // Publish locally decrypted history before starting any remote home request.
  if(signedIn && typeof client.listCachedChats === "function") {
    try {
      const cached=await client.listCachedChats(Number.MAX_SAFE_INTEGER,1);
      if(!current())return;
      if(cached)updateHomeChats(state,cached.chats);
    } catch {
      if(!current())return;
      // An unavailable local cache still permits the normal remote refresh.
    }
    state.homeChatsLoading=homeChatItems(state).length===0;
    render();
  }
  const updateContinue = (data:{memories:DecryptedMemoryEntry[];reminders:Array<Record<string,unknown>>}) => {
    const selected=homeItemId(homeContinueItems(state)[state.selectedIndex]);
    state.continueData=data;
    if(state.homeSelectionMoved || state.selectedIndex>0) {
      const index=homeContinueItems(state).findIndex(item=>homeItemId(item)===selected);
      state.selectedIndex=index<0 ? 0 : index;
    } else state.selectedIndex=0;
    render();
  };
  if(signedIn && typeof client.getCachedContinueItems === "function") {
    try {const cached=await client.getCachedContinueItems();if(!current())return;if(cached)updateContinue(cached);} catch {if(!current())return;}
  }
  const work: Promise<void>[]=[];
  let continueRefresh: Promise<void> | undefined;
  const refreshContinue = (): Promise<void> => {
    if (!continueRefresh && signedIn && typeof client.getContinueItems === "function") {
      continueRefresh=client.getContinueItems().then(data=>{
        if(!current())return;
        updateContinue(data);
        if(typeof client.getEmbed !== "function")return;
        const saved=homeContinueItems(state).filter(item=>item.kind==="embed").slice(0,10);
        let next=0;
        // Cache the promoted embeds without delaying the visible home or chat sync.
        void Promise.all(Array.from({length:Math.min(3,saved.length)},async()=>{
          while(current() && next<saved.length) {
            const item=saved[next++];
            try {await client.getEmbed(item.embedId,{preferCache:true});} catch {if(!current())return;}
          }
        }));
      }).catch(()=>{});
    }
    return continueRefresh ?? Promise.resolve();
  };
  // Team reminders are scoped against the newly persisted Team chat metadata.
  if(!teamId)work.push(refreshContinue());
  let warming: Promise<void> | undefined;
  const warmRecent = () => {
    if (!current() || warming || typeof client.cacheRecentChatMessages !== "function") return;
    warming = client.cacheRecentChatMessages({signal:controller.signal}).catch(()=>{}).finally(()=>{warming=undefined;});
  };
  if (typeof client.getDailyInspirations === "function") work.push(client.getDailyInspirations().then((list)=>{
    if(current()) {state.inspirations=list; for(const workspace of ["chats","apps","projects","tasks","workflows"] as const) {
      const index=list.filter((i)=>(i.surface??"chats")===workspace).findIndex((i)=>!i.is_opened);
      state.inspirationIndices[workspace]=Math.max(0,index);
    }render();}
  }).catch(()=>{if(current())state.homeError="Daily inspiration is temporarily unavailable.";}));
  if(signedIn && typeof client.whoAmI === "function") work.push(client.whoAmI().then((user)=>{if(current()){state.username=typeof user.username==="string" ? terminalText(user.username):null;render();}}).catch(()=>{}));
  if(signedIn && typeof client.listChats === "function") work.push(client.listChats(Number.MAX_SAFE_INTEGER,1,{forceRefresh:true,signal:controller.signal,onSyncedChats:(page)=>{
    if(current()){updateHomeChats(state,page.chats);state.homeChatsLoading=false;render();warmRecent();if(teamId)void refreshContinue();}
  }}).then(async(page)=>{if(current()){
    updateHomeChats(state,page.chats);warmRecent();
    if(teamId)await refreshContinue();
    if(!current())return;
    if(page.pendingRecoveryOutputs)state.status="Some saved AI outputs are pending recovery. Use /refresh to retry.";
    render();
  }}).catch(()=>{if(current()){
    state.homeError="Saved chats could not be synced. Use /refresh to retry.";
    if(homeChatItems(state).length)state.status="Showing cached chats. Sync failed; /refresh to retry.";
  }}).finally(()=>{if(current()){state.homeChatsLoading=false;render();}}));
  else state.homeChatsLoading=false;
  if(signedIn) work.push(refreshTuiChatSidebar(state,client,render,true).catch(()=>{if(current())state.homeError="Chat projects could not be loaded. Use /refresh to retry.";}));
  await Promise.all(work);
  if(current()){state.homeLoading=false;render();}
}
/** Reconnect and refresh recent ciphertext without overlapping recovery or user refreshes. */
export function startHomeSync(state:TuiState,client:OpenMatesClient,render:()=>void,closed:()=>boolean):()=>void {
  let refreshing=false;
  const timer=setInterval(()=>{
    if(closed() || state.startup || !state.signedIn || state.homeLoading || refreshing)return;
    refreshing=true;
    void loadHomeData(state,client,render).catch(()=>{}).finally(()=>{refreshing=false;});
  },60_000);
  timer.unref?.();
  return ()=>clearInterval(timer);
}
const centered = centeredCarouselText;
export function homeHeader(state:TuiState,width:number,height:number):TuiLine[] {
  const inspiration=currentInspiration(state), rows=Math.max(4,Math.min(8,Math.floor(height/5))), result:TuiLine[]=[];
  const gradient=inspiration?.category && CATEGORY_GRADIENTS[inspiration.category] || CATEGORY_GRADIENTS.general_knowledge;
  const textWidth=Math.max(1,width-8);
  const phrase=inspiration?.phrase || (state.homeLoading ? "Loading today’s inspiration…" : "Explore a topic with your AI team mates.");
  const parts=wrapCells(phrase,textWidth).slice(0,2);
  const title=inspiration?.feature?.title || inspiration?.title || "Daily inspiration";
  const banner=[centered(`DAILY INSPIRATION  ${state.focus==="inspiration" ? "‹  Enter open  ›" : "‹  Ctrl+O explore  ›"}`,width),"",...parts.map((line)=>centered(line,width)),centered(title,width)];
  while(banner.length<rows)banner.push("");
  banner.forEach((text)=>result.push({text,background:gradient.start}));
  result.push("",{text:centered(state.workspace==="apps" ? prompts.apps : state.username ? `Hey ${state.username}!` : "Hey there!",width),bold:true});
  if(state.workspace!=="chats"||!homeChatItems(state).length)result.push({text:centered(state.workspace==="apps" ? "Use your apps directly and return to saved results." : prompts[state.workspace],width),color:"#cfcfcf"});
  result.push("");
  return result;
}
/** The newest chat and keyboard-selected previews share the web home's center position. */
export function renderHomeChatCards(state:TuiState,width:number,height:number):TuiLine[] {
  const items=homeContinueItems(state), result=homeHeader(state,width,height);
  const activeCount = runningTuiChatGroups(state).length;
  if (activeCount) result.push(centered(`${activeCount} ${activeCount === 1 ? 'chat' : 'chats'} active…  /active`, width), '');
  if(!items.length){
    result.push(centered(state.homeChatsLoading ? "Loading your recent chats…" : state.homeError || "Start a chat below. Your recent chats will appear here.",width),"");
    return result;
  }
  result.push(centered(state.signedIn ? "Continue where you left off" : "Explore example chats",width),"");
  const selected=Math.max(0,Math.min(items.length-1,state.selectedIndex));
  result.push(...renderCardCarousel(items.map(item=>{
    if(item.kind==="embed")return {title:item.title,description:item.summary || "Open saved item",
      footer:`${item.priority.label} · Saved`,background:(item.category && CATEGORY_GRADIENTS[item.category] || BLUE).start};
    const chat=item.chat;return {
      title:chat.title||chat.draftPreview||"Untitled chat",description:chat.hasDraft?'Draft':chat.summary||"Continue this conversation",
      footer:item.priority?.label || chat.category?.replaceAll("_"," ") || "Chat",background:(chat.category && CATEGORY_GRADIENTS[chat.category] || BLUE).start,
    };
  }),width,selected,state.focus==="content"));
  result.push("",centered(`${selected>0?"‹":" "}  ${items.some(item=>item.kind==="embed")?"Item":"Chat"} ${selected+1} of ${items.length}  ${selected<items.length-1?"›":" "}`,width),
    centered("←/→ choose  ·  Enter open  ·  Tab write",width),"",
    centered("/search Search chats  ·  Ctrl+N New chat",width));
  return result;
}
