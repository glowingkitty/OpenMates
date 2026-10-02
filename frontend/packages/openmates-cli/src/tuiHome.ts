/** The rendered web workspace home hierarchy, adapted to terminal cells. */
import type { ChatListItem, DailyInspiration, OpenMatesClient } from "./client.js";
import type { TuiState, TuiWorkspace } from "./tuiRenderer.js";
import { getWorkspaceInspirations } from "../../workspaceInspirationDefaults.js";
import { CATEGORY_GRADIENTS } from "../../chatCategoryTheme.js";
import { cells, padCells, terminalText, truncateCells, wrapCells, type TuiSpan, type TuiLine } from "./tuiText.js";

const BLUE = {start: "#4867cd", end: "#5a85eb"};
const prompts: Record<TuiWorkspace, string> = {
  chats: "What do you need help with?", projects: "What do you want to organize next?",
  workflows: "What do you want to automate next?", tasks: "What task is next?", apps: "What app do you want to use?",
};
export const isWorkspaceHome = (s: TuiState): boolean => ["start", "chats", "projects", "tasks", "workflows", "apps"].includes(s.screen);
export function homeChatItems(state: TuiState): ChatListItem[] {
  return (state.signedIn ? state.recentChats : state.examples).filter((c) => `${c.title} ${c.summary}`.toLowerCase().includes(state.filter.toLowerCase()));
}
export function workspaceInspirations(state: TuiState): DailyInspiration[] {
  const available = state.inspirations.filter((i) => (i.surface ?? "chats") === state.workspace);
  if (available.length || state.workspace === "chats") return available;
  return getWorkspaceInspirations(state.workspace).map((i) => ({...i, id:i.inspiration_id, assistant_response:i.assistant_response ?? "", follow_up_suggestions:i.follow_up_suggestions ?? []}));
}
export function currentInspiration(state: TuiState): DailyInspiration | undefined {
  const list = workspaceInspirations(state);
  return list[(state.inspirationIndices[state.workspace] ?? 0) % Math.max(1,list.length)];
}
export async function loadHomeData(state: TuiState, client: OpenMatesClient, render: () => void): Promise<void> {
  const request = ++state.homeLoadVersion, signedIn=state.signedIn;
  const current=()=>request===state.homeLoadVersion && state.signedIn===signedIn;
  state.homeLoading=true;
  const work: Promise<void>[]=[];
  if (typeof client.getDailyInspirations === "function") work.push(client.getDailyInspirations().then((list)=>{
    if(current()) {state.inspirations=list; for(const workspace of ["chats","apps","projects","tasks","workflows"] as const) {
      const index=list.filter((i)=>(i.surface??"chats")===workspace).findIndex((i)=>!i.is_opened);
      state.inspirationIndices[workspace]=Math.max(0,index);
    }render();}
  }).catch(()=>{if(current())state.homeError="Daily inspiration is temporarily unavailable.";}));
  if(signedIn && typeof client.whoAmI === "function") work.push(client.whoAmI().then((user)=>{if(current()){state.username=typeof user.username==="string" ? terminalText(user.username):null;render();}}).catch(()=>{}));
  if(signedIn && typeof client.listChats === "function") work.push(client.listChats(50,1).then((page)=>{if(current()){state.recentChats=page.chats;render();}}).catch(()=>{if(current())state.homeError="Saved chats could not be loaded. Use /refresh to retry.";}));
  await Promise.all(work);
  if(current()){state.homeLoading=false;render();}
}
function centered(text:string,width:number):string {
  const value=truncateCells(text,width);return " ".repeat(Math.max(0,Math.floor((width-cells(value))/2)))+value;
}
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
/** Fixed-width previews share one horizontal viewport, including a peek at the next card. */
export function renderHomeChatCards(state:TuiState,width:number,height:number):TuiLine[] {
  const chats=homeChatItems(state), result=homeHeader(state,width,height);
  if(!chats.length){
    result.push(centered(state.homeLoading ? "Loading your recent chats…" : "Start a chat below. Your recent chats will appear here.",width),"");
    return result;
  }
  result.push(centered(state.signedIn ? "Continue where you left off" : "Explore example chats",width),"");
  const selected=Math.max(0,Math.min(chats.length-1,state.selectedIndex));
  const cardWidth=Math.min(width,36), inner=Math.max(1,cardWidth-4), stride=cardWidth+2;
  const slots=Math.max(1,Math.floor((width+2)/stride));
  const first=Math.max(0,selected-slots+1);
  const cards=chats.slice(first,first+slots+1).map((chat,index)=>{
    const active=first+index===selected && state.focus==="content";
    const title=wrapCells(`${active?"› ":""}${chat.title||"Untitled chat"}`,inner).slice(0,2);
    const summary=wrapCells(chat.summary||"Continue this conversation",inner).slice(0,2);
    while(title.length<2)title.push("");while(summary.length<2)summary.push("");
    const rows=cardWidth<4 ? [truncateCells(chat.title||"Untitled chat",cardWidth)] : [
      `╭${"─".repeat(cardWidth-2)}╮`,
      ...title.map((line)=>`│ ${padCells(line,inner)} │`),
      ...summary.map((line)=>`│ ${padCells(line,inner)} │`),
      `│ ${padCells(chat.category?.replaceAll("_"," ")||"Chat",inner)} │`,
      `╰${"─".repeat(cardWidth-2)}╯`,
    ];
    return {rows,background:(chat.category && CATEGORY_GRADIENTS[chat.category] || BLUE).start,active};
  });
  for(let row=0;row<cards[0].rows.length;row++){
    const spans:TuiSpan[]=[];let remaining=width;
    for(const card of cards){
      if(!remaining)break;
      const text=truncateCells(card.rows[row],remaining);spans.push({text,background:card.background,bold:card.active});remaining-=cells(text);
      if(remaining){const gap=" ".repeat(Math.min(2,remaining));spans.push({text:gap});remaining-=gap.length;}
    }
    result.push({text:spans.map((span)=>span.text).join(""),spans});
  }
  result.push("",centered(`${selected>0?"‹":" "}  Chat ${selected+1} of ${chats.length}  ${selected<chats.length-1?"›":" "}`,width),
    centered("←/→ choose chat  ·  Enter open  ·  Tab write",width),"",
    centered("/search Search chats  ·  Ctrl+N New chat",width));
  return result;
}
