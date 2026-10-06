/** The rendered web workspace home hierarchy, adapted to terminal cells. */
import type { ChatListItem, DailyInspiration, OpenMatesClient } from "./client.js";
import type { TuiState, TuiWorkspace } from "./tuiRenderer.js";
import { getWorkspaceInspirations } from "../../workspaceInspirationDefaults.js";
import { CATEGORY_GRADIENTS } from "../../chatCategoryTheme.js";
import { centeredCarouselText, renderCardCarousel } from "./tuiCarousel.js";
import { terminalText, wrapCells, type TuiLine } from "./tuiText.js";
import { runningTuiChatGroups, refreshTuiChatSidebar, updateTuiChatSidebar } from './tuiChatSidebar.js';

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
  const selectedId=preserveSelection ? homeChatItems(state)[state.selectedIndex]?.id : undefined;
  updateTuiChatSidebar(state,()=>{state.recentChats=chats;});
  if(preserveSelection) {
    const items=homeChatItems(state), index=items.findIndex(chat=>chat.id===selectedId);
    state.selectedIndex=index>=0 ? index : Math.max(0,Math.min(state.selectedIndex,items.length-1));
  }
}
export async function loadHomeData(state: TuiState, client: OpenMatesClient, render: () => void): Promise<void> {
  state.homeAbortController?.abort();
  const controller=new AbortController();state.homeAbortController=controller;
  const request = ++state.homeLoadVersion, signedIn=state.signedIn;
  const current=()=>!controller.signal.aborted && request===state.homeLoadVersion && state.signedIn===signedIn;
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
  const work: Promise<void>[]=[];
  if (typeof client.getDailyInspirations === "function") work.push(client.getDailyInspirations().then((list)=>{
    if(current()) {state.inspirations=list; for(const workspace of ["chats","apps","projects","tasks","workflows"] as const) {
      const index=list.filter((i)=>(i.surface??"chats")===workspace).findIndex((i)=>!i.is_opened);
      state.inspirationIndices[workspace]=Math.max(0,index);
    }render();}
  }).catch(()=>{if(current())state.homeError="Daily inspiration is temporarily unavailable.";}));
  if(signedIn && typeof client.whoAmI === "function") work.push(client.whoAmI().then((user)=>{if(current()){state.username=typeof user.username==="string" ? terminalText(user.username):null;render();}}).catch(()=>{}));
  if(signedIn && typeof client.listChats === "function") work.push(client.listChats(Number.MAX_SAFE_INTEGER,1,{forceRefresh:true,signal:controller.signal,onSyncedChats:(page)=>{
    if(current()){updateHomeChats(state,page.chats);state.homeChatsLoading=false;render();}
  }}).then((page)=>{if(current()){
    updateHomeChats(state,page.chats);
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
  const chats=homeChatItems(state), result=homeHeader(state,width,height);
  const activeCount = runningTuiChatGroups(state).length;
  if (activeCount) result.push(centered(`${activeCount} ${activeCount === 1 ? 'chat' : 'chats'} active…  /active`, width), '');
  if(!chats.length){
    result.push(centered(state.homeChatsLoading ? "Loading your recent chats…" : state.homeError || "Start a chat below. Your recent chats will appear here.",width),"");
    return result;
  }
  result.push(centered(state.signedIn ? "Continue where you left off" : "Explore example chats",width),"");
  const selected=Math.max(0,Math.min(chats.length-1,state.selectedIndex));
  result.push(...renderCardCarousel(chats.map((chat)=>({
    title:chat.title||chat.draftPreview||"Untitled chat",description:chat.hasDraft?'Draft':chat.summary||"Continue this conversation",
    footer:chat.category?.replaceAll("_"," ")||"Chat",background:(chat.category && CATEGORY_GRADIENTS[chat.category] || BLUE).start,
  })),width,selected,state.focus==="content"));
  result.push("",centered(`${selected>0?"‹":" "}  Chat ${selected+1} of ${chats.length}  ${selected<chats.length-1?"›":" "}`,width),
    centered("←/→ choose chat  ·  Enter open  ·  Tab write",width),"",
    centered("/search Search chats  ·  Ctrl+N New chat",width));
  return result;
}
