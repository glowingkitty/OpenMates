/** Pure shared workspace layout, terminal color adaptation and overlays. */
import type { TuiState } from "./tuiRenderer.js";
import {renderQuestionEditor} from './tuiInteractiveQuestions.js';
import {addPointerTarget, beginPointerFrame, pointerLine, type TuiPointerAction} from './tuiPointer.js';
import { CATEGORY_GRADIENTS } from "../../chatCategoryTheme.js";
import { paletteActions } from "./tuiActions.js";
import { tuiChatSidebarRows, tuiChatBreadcrumb } from './tuiChatSidebar.js';
import { orderedWorkflowNodes, workflowNodeColor } from './tuiWorkflowWorkspace.js';
import { backgroundLine, cells, foreground, lineText, padCells, terminalText, truncateCells, wrapCells, type TuiColorMode, type TuiLine } from "./tuiText.js";

export const WORKSPACES = ["chats", "apps", "projects", "workflows", "tasks"] as const;
export const DEFAULT_CHAT_BACKGROUND = "#4867cd";
// A terminal-sized counterpart to the web app's centered content containers.
export const CONTENT_MAX_COLUMNS = 100;
export const WORKSPACE_MAX_COLUMNS = 180;
export function workspaceGeometry(state: TuiState, rawWidth: number) {
  const width = Math.max(1, Math.floor(rawWidth));
  const gutter = Math.min(2, Math.floor((width - 1) / 2));
  const sidebarWidth = state.sidebarOpen && width >= 90 && !state.form && !state.paletteOpen && !state.questionEditor ? 27 : 0;
  const paneWidth = Math.max(1, width - gutter * 2 - sidebarWidth);
  const contentWidth = Math.min(WORKSPACE_MAX_COLUMNS, paneWidth);
  const inset = Math.floor((paneWidth - contentWidth) / 2);
  const composerWidth = Math.min(CONTENT_MAX_COLUMNS, paneWidth);
  const composerInset = Math.floor((paneWidth - composerWidth) / 2);
  return { width, gutter, sidebarWidth, paneWidth, contentWidth, inset, composerWidth, composerInset };
}

/** Keep the edit caret and its surrounding lines in the same composer viewport. */
function composerViewport(state: TuiState, width: number) {
  const wrapWidth = Math.max(1, width - 6);
  const lines = state.input.split('\n').flatMap(text => wrapCells(text, wrapWidth));
  const before = state.input.slice(0, state.inputCursor ?? state.input.length).split('\n');
  let row = before.slice(0, -1).reduce((count, text) => count + wrapCells(text, wrapWidth).length, 0);
  const current = wrapCells(before.at(-1) ?? '', wrapWidth);
  row += current.length - 1;
  const column = cells(current.at(-1) ?? '');
  const count = Math.min(3, Math.max(1, lines.length));
  const start = Math.max(0, Math.min(lines.length - count, row - count + 1));
  return { lines: lines.slice(start, start + count), row: row - start, column, count };
}

export function tuiComposerCursor(state: TuiState, width: number, height: number): {row: number; column: number} | null {
  if (state.focus !== 'composer' || state.form || state.paletteOpen || state.startup || state.privacyOffer || state.textSelection) return null;
  const geometry = workspaceGeometry(state, width), input = composerViewport(state, geometry.composerWidth);
  const bodyHeight = Math.max(1, height - 2 - input.count - 3);
  const row = 2 + bodyHeight + 1 + input.row;
  const column = geometry.gutter + geometry.sidebarWidth + geometry.composerInset + 4 + input.column;
  return row < height && column < width ? {row, column} : null;
}
export function chatBackground(category: string | null | undefined) {
  return category && CATEGORY_GRADIENTS[category]?.start || DEFAULT_CHAT_BACKGROUND;
}

export function sidebarLines(state: TuiState): string[] {
  const selected = (label: string, index: number) => `${state.focus === "sidebar" && state.sidebarIndex === index ? ">" : " "} ${label}`;
  switch (state.workspace) {
    case "chats": return [tuiChatBreadcrumb(state) ?? 'Chats', '',
      ...tuiChatSidebarRows(state).map((row, index) => row.kind === 'section' ? `  ${row.label}` : selected(`${row.running ? ['◴','◷','◶','◵'][state.activityFrame % 4] + ' ' : ['project', 'folder'].includes(row.kind) ? '▸ ' : ''}${row.label}`, index)),
      '', '/active  /chat-add-to-project'];
    case "projects": return ["Projects", "", ...state.projects.map((p, i) => selected(p.name, i)), "", "/project-create new"];
    case "tasks": return ["Tasks", "", ...state.tasks.map((t, i) => selected(`${t.shortId} ${t.title}`, i)), "", "/task-create new"];
    case "workflows": return ["Workflows", "", ...state.workflows.map((w, i) => selected(w.title, i)), "", "Select a workflow to open"];
    case "apps": return ["Apps", "", ...state.apps.map((a,i)=>selected(a.name,i)), "", "Ctrl+B close sidebar"];
  }
}

/** Stable row identities survive background sorting without trusting labels. */
export function sidebarPointerIds(state:TuiState):Array<string|null> {
  if(state.workspace==='chats')return tuiChatSidebarRows(state).map(row=>row.kind==='section'?null:
    JSON.stringify([row.kind,row.chatId,row.projectId,row.folderId]));
  return (state.workspace==='projects'?state.projects:state.workspace==='tasks'?state.tasks:
    state.workspace==='workflows'?state.workflows:state.apps).map(item=>'taskId' in item?item.taskId:item.id);
}
function pointerSidebarLines(state:TuiState):TuiLine[] {
  const ids=sidebarPointerIds(state);
  return sidebarLines(state).map((line,row)=>{
    const index=row-2,id=ids[index];
    return id?pointerLine(line,{kind:'select',target:'sidebar',index,id,activate:true}):line;
  });
}

export function workspaceHint(state: TuiState): string {
  if(state.questionEditor)return 'Tab / ↑↓ move   Space choose   ←/→ adjust   Ctrl+S send   Esc cancel';
  if (state.form) return "Tab field   ←/→ choice   Ctrl+S save   Esc cancel";
  if (state.paletteOpen) return "↑/↓ choose   Enter action   Esc close";
  if (state.focus === "navigation") return "←/→ workspace   Enter open   Tab focus   Ctrl+B sidebar";
  if (state.focus === "inspiration") return "←/→ inspiration   Enter explore   Tab focus";
  if (state.focus === "sidebar") return "↑/↓ choose   Enter open   Ctrl+B close   Tab focus";
  if (state.screen === "start" || state.screen === "chats") return state.focus === "composer"
    ? "Enter send   Shift+Tab chats   Ctrl+N new   Ctrl+B sidebar"
    : "←/→ chat   Enter open   Tab write   ↑/↓ scroll   Ctrl+B sidebar";
  if (state.screen === "results-view") return "m map   c calendar   l list   /embed open   ↑/↓ scroll   Esc back";
  if (state.screen === "embed") return state.embedChoices.length ? "↑/↓ choose   Enter open   Esc back" : "↑/↓ scroll   PgUp/PgDn page   Esc back";
  if(['chat','example'].includes(state.screen)&&state.focus==='content')return '←/→ embed   Enter open   ↑/↓ scroll   Tab write   Ctrl+G navigation';
  if (state.workflowEdit) return "Enter save title   Esc cancel edit";
  if (state.screen === "workflow") return "g template   r runs   ↑/↓ select   Enter expand   e title   E config   x run   c cancel";
  if (state.screen === "task") return "e edit   m status   a activity   s start   d done   b block   Esc back";
  if (state.screen === "project") return "1 overview   2 files   3 tasks   Enter open   n new chat   Esc back";
  if (state.screen === "app") return "1–5 tabs   ↑/↓ choose   Enter open   Esc Apps   /search";
  if (state.screen === "app-skill") return "1–3 tabs   Enter use skill   Esc app   Ctrl+P actions";
  if (state.screen === "app-result") return "↑/↓ scroll   Esc saved results   Ctrl+P actions";
  if (state.screen === "apps") return state.focus === "composer"
    ? "Type /command   Shift+Tab apps   Ctrl+B sidebar"
    : "←/→ app   Enter open   ↑/↓ scroll   /search   /browse Show all   Ctrl+B sidebar";
  if (state.screen === "projects" || state.screen === "workflows") return "←/→ card   Enter open   ↑/↓ scroll   /search filter   Tab focus";
  if (state.screen === "tasks") return "←/→ columns   ↑/↓ task   Enter open   /search filter   Tab focus";
  if (state.screen === "interests") return "↑/↓ move   Space select   Enter continue   Esc back";
  if (state.screen === "examples") return "↑/↓ choose   Enter open   /search filter   Esc back";
  return "Enter send   Alt+Enter newline   Esc chats   Ctrl+Q question   Ctrl+Y select text   Ctrl+B sidebar";
}

function overlayLines(state: TuiState, width: number, height: number): TuiLine[] {
  if(state.questionEditor)return renderQuestionEditor(state.questionEditor,width);
  if (state.paletteOpen) {
    const actions = paletteActions(state.paletteQuery);
    const start = Math.max(0, state.paletteIndex - Math.max(1, height - 5));
    return ["Actions", `Search: ${state.paletteQuery}_`, "", ...actions.slice(start).map((a, i) => pointerLine(`${i + start === state.paletteIndex ? ">" : " "} ${a.label}  ${a.command}`,
      {kind:'select',target:'palette',index:i+start,id:a.command,activate:true}))];
  }
  const form = state.form;
  if (!form) return [];
  if(form.kind.startsWith('workflow-')&&form.fields.length){
    const panelWidth=Math.min(width,76),inset=Math.max(0,Math.floor((width-panelWidth)/2));
    const node=state.activeWorkflow?orderedWorkflowNodes(state.activeWorkflow.graph).find(node=>node.id===form.contextId):undefined;
    const color=node?workflowNodeColor(node)??'#4867cd':'#DE1E66';
    const title=truncateCells(form.title,panelWidth),center=Math.max(0,Math.floor((panelWidth-cells(title))/2));
    const rows:TuiLine[]=[{text:padCells(' '.repeat(center)+title,panelWidth),background:color,bold:true,inset},'',
      {text:'Step configuration · Tab field · Ctrl+S save',color:'#a0a0a0',inset},''];
    for(const [index,field] of form.fields.entries()){
      const focused=index===form.fieldIndex;
      const suffix=[field.required?'required':'',field.valueType&&field.valueType!=='string'?field.valueType:'',field.options?'←/→ choose':''].filter(Boolean).join(' · ');
      const action:TuiPointerAction={kind:'select',target:'form-field',index,id:field.name};
      rows.push({text:`${focused?'›':' '} ${field.label}${suffix?` · ${suffix}`:''}`,bold:true,color:focused?'#32ade6':'#e6e6e6',inset,action});
      if(panelWidth>=6){
        const edge='─'.repeat(panelWidth-2),border=focused?'#32ade6':'#626878';
        rows.push({text:`╭${edge}╮`,color:border,inset});
        rows.push(...wrapCells(`${field.value||'(empty)'}${focused&&!form.busy?'_':''}`,panelWidth-4).map(text=>({text:`│ ${padCells(text,panelWidth-4)} │`,color:focused?'#ffffff':'#cfcfcf',...(focused?{background:'#2b3548'}:{}),inset,action})));
        rows.push({text:`╰${edge}╯`,color:border,inset},'');
      }else rows.push(...wrapCells(field.value,panelWidth).map(line=>pointerLine(line,action)));
      if(field.options)rows.push({text:'‹ Previous   Next ›',inset,spans:[
        {text:'‹ Previous',action:{...action,activate:true,name:'left'}},{text:'   '},
        {text:'Next ›',action:{...action,activate:true,name:'right'}}]});
    }
    if(form.error)rows.push({text:form.error,color:'#ff6b6b',bold:true,inset});
    rows.push({text:form.busy?'Saving…':'Save · Ctrl+S    Cancel · Esc',color:'#a0a0a0',inset,
      ...(!form.busy?{spans:[{text:'Save · Ctrl+S',action:{kind:'key' as const,name:'s',ctrl:true}},
        {text:'    '},{text:'Cancel · Esc',action:{kind:'key' as const,name:'escape'}}]}:{})});
    return rows;
  }
  const rows:TuiLine[] = [form.title, ""];
  for (const [index, field] of form.fields.entries()) {
    const action:TuiPointerAction={kind:'select',target:'form-field',index,id:field.name};
    rows.push(pointerLine(`${index === form.fieldIndex ? ">" : " "} ${field.label}${field.options ? " [←/→]" : ""}`,action));
    rows.push(...wrapCells(`  ${field.value || "(empty)"}${index === form.fieldIndex && !form.busy ? "_" : ""}`, width).map(line=>pointerLine(line,action)));
    if(field.options)rows.push({text:'‹ Previous   Next ›',spans:[
      {text:'‹ Previous',action:{...action,activate:true,name:'left'}},{text:'   '},
      {text:'Next ›',action:{...action,activate:true,name:'right'}}]});
    rows.push("");
  }
  if (form.error) rows.push(`Error: ${form.error}`);
  rows.push(form.busy?'Saving…':{text:'Save · Ctrl+S    Cancel · Esc',spans:[
    {text:'Save · Ctrl+S',action:{kind:'key',name:'s',ctrl:true}},{text:'    '},
    {text:'Cancel · Esc',action:{kind:'key',name:'escape'}}]});
  return rows;
}

export function renderWorkspaceFrame(state: TuiState, rawWidth: number, rawHeight: number, body: TuiLine[], options: {colorMode?: TuiColorMode; ascii?: boolean; headerRows?: number; stickyRows?:number} = {}): string {
  const { gutter, sidebarWidth, paneWidth, contentWidth, inset, composerWidth, composerInset } = workspaceGeometry(state, rawWidth);
  const height = Math.max(1, Math.floor(rawHeight));
  beginPointerFrame(state,Math.max(1,Math.floor(rawWidth)),height);
  const modal=Boolean(state.form||state.paletteOpen||state.questionEditor);
  const bodyColumn=gutter+sidebarWidth+inset;
  const mode = options.colorMode ?? "none";
  const ascii = options.ascii ?? false;
  const line = ascii ? "-" : "─", vertical = ascii ? "|" : "│";
  const place = (rendered: string, side = " ".repeat(sidebarWidth)) =>
    " ".repeat(gutter) + side + " ".repeat(inset) + rendered + " ".repeat(paneWidth - inset - contentWidth + gutter);
  const navParts:Array<{text:string;color:string;bold:boolean;action?:TuiPointerAction}> = [{text:'OpenMates  ',color:'#cfcfcf',bold:true,action:{kind:'command',command:'/chats'}},...WORKSPACES.map((workspace,index)=>{
    const focused=state.focus==='navigation'&&index===state.navigationIndex;
    const label=state.workspace===workspace?`[${titleCase(workspace)}]`:titleCase(workspace);
    return {text:`${focused?'› ':''}${label}  `,color:focused?'#32ade6':state.workspace===workspace?'#ff553b':'#cfcfcf',bold:true,
      action:{kind:'command' as const,command:`/${workspace}`}};
  })];
  if(cells(navParts.map(part=>part.text).join(''))>contentWidth-6){
    const focused=state.focus==='navigation';
    navParts.splice(0,navParts.length,{text:'OpenMates  ',color:'#cfcfcf',bold:true,action:{kind:'command',command:'/chats'}},
      {text:`[${titleCase(state.workspace)}]  `,color:'#ff553b',bold:true,action:{kind:'command',command:`/${state.workspace}`}},
      ...(focused?[{text:`› ${titleCase(WORKSPACES[state.navigationIndex])}  `,color:'#32ade6',bold:true,action:{kind:'command' as const,command:`/${WORKSPACES[state.navigationIndex]}`}}]:[]));
  }
  const navUsed=cells(navParts.map(part=>part.text).join(''));
  navParts.push({text:contentWidth-navUsed>=18?'Ctrl+G navigation':'^G nav',color:'#808080',bold:false,action:{kind:'key',name:'g',ctrl:true}});
  let navRemaining=contentWidth;
  const renderedNav=navParts.map(part=>{
    const column=bodyColumn+contentWidth-navRemaining;
    const value=truncateCells(part.text,navRemaining);navRemaining-=cells(value);
    if(!modal&&part.action)addPointerTarget(state,column,0,cells(value.trimEnd()),part.action);
    return foreground(value,part.color,mode,part.bold);
  }).join('')+' '.repeat(navRemaining);
  const input = composerViewport(state, composerWidth);
  const showComposer = state.workspace !== "apps" || state.focus === "composer" || Boolean(state.input);
  const composerRows = showComposer ? input.count : 0;
  const bodyHeight = Math.max(1, height - 2 - (showComposer ? composerRows + 3 : 1));
  const overlay = state.form || state.paletteOpen || state.questionEditor;
  const sidebar = state.sidebarOpen && !overlay;
  const sidebarOverlay = sidebar && !sidebarWidth;
  let content = overlay ? overlayLines(state, contentWidth, bodyHeight) : sidebarOverlay ? pointerSidebarLines(state) : body;
  const stickyCount=!overlay&&!sidebarOverlay?Math.min(options.stickyRows??0,Math.max(0,bodyHeight-8)):0;
  const fixed=content.slice(0,stickyCount);content=content.slice(stickyCount);
  const viewportHeight=bodyHeight-stickyCount;
  const maxStart = Math.max(0, content.length - viewportHeight);
  let start = !overlay && !sidebarOverlay && state.screen === "chat"
    ? Math.max(0, maxStart - state.scrollOffset) : Math.min(maxStart, Math.max(0, state.scrollOffset));
  if (sidebarOverlay && state.focus === "sidebar") {
    const marker = content.findIndex((row) => lineText(row).startsWith("> "));
    start = Math.min(maxStart, Math.max(0, marker - bodyHeight + 3));
  }
  if (overlay) {
    // Keep the focused form field visible without changing transcript scroll.
    const marker = content.findIndex((row) => /^[>›] /.test(lineText(row).trimStart()));
    start = marker >= bodyHeight-4 ? Math.max(0, marker - bodyHeight + 6) : 0;
  } else if (state.followSelection && ["start", "tasks", "projects", "project", "chat", "chats", "example", "examples", "workflow", "workflows", "apps", "app", "app-skill"].includes(state.screen) && state.focus === "content") {
    const markers=content.map((row,index)=>/(?:^|[│|])\s*[>›] /.test(lineText(row))?index:-1).filter((index)=>index>=0);
    const marker=state.screen==="workflow" ? markers.at(-1)??-1 : markers[0]??-1;
    let selectionEnd=marker;
    if(["workflow","start","chats","apps","projects","workflows"].includes(state.screen)&&marker>=0){
      const closing=content.findIndex((row,index)=>index>marker&&lineText(row).includes("╰"));
      selectionEnd=Math.min(marker+10,closing<0?marker:closing);
    }
    if (selectionEnd >= start + viewportHeight) start = Math.min(maxStart, selectionEnd - viewportHeight + 1);
    if (marker >= 0 && marker < start) start = marker;
  }
  // Store the actual viewport, so End or repeated scrolling cannot accumulate overshoot.
  if(!overlay&&!sidebarOverlay)state.scrollOffset=state.screen==="chat"?maxStart-start:start;
  state.followSelection=false;
  const heroRows = options.headerRows ?? 0;
  const category = state.screen === "example" ? state.activeExample?.chat.category : state.activeChat?.category;
  const background = chatBackground(category);
  const allSide = sidebarWidth ? pointerSidebarLines(state) : [];
  const sideMarker = allSide.findIndex((row) => lineText(row).startsWith("> "));
  const sideStart = Math.max(0, sideMarker - bodyHeight + 3);
  const side = sideStart ? [allSide[0], "", ...allSide.slice(sideStart)] : allSide;
  const rows: string[] = [];
  for (let i = 0; i < bodyHeight; i++) {
    const index = i<stickyCount ? i : start+i;
    const value = i<stickyCount ? fixed[i] : content[start+i-stickyCount] ?? "";
    const style = typeof value === "string" ? undefined : value;
    const raw = terminalText(lineText(value)).replace(/\n/g, " ");
    let rendered = padCells(raw, contentWidth);
    const targetInset=Math.max(0,Math.min(Math.floor(contentWidth/2)-1,style?.inset??0));
    const leading=cells(raw)-cells(raw.trimStart());
    if(style?.action)addPointerTarget(state,bodyColumn+targetInset+leading,i+2,
      Math.min(cells(raw.trim()),Math.max(0,contentWidth-2*targetInset-leading)),style.action);
    if (style && !sidebarOverlay) {
      const inset=Math.max(0,Math.min(Math.floor(contentWidth/2)-1,style.inset??0));
      const span=Math.max(1,contentWidth-2*inset);
      if(style.spans){
        let remaining=span;rendered="";
        for(const part of style.spans){
          const text=truncateCells(terminalText(part.text).replace(/\n/g," "),remaining),size=cells(text);
          if(part.action)addPointerTarget(state,bodyColumn+inset+span-remaining,i+2,size,part.action);
          rendered+=part.background?backgroundLine(text,size,part.background,mode,part.bold,part.color):foreground(text,part.color??'#e6e6e6',mode,part.bold);
          remaining-=size;if(!remaining)break;
        }
        rendered=" ".repeat(inset)+rendered+" ".repeat(remaining+inset);
      }else rendered=" ".repeat(inset)+(style.background ? backgroundLine(raw,span,style.background,mode,style.bold)
        :foreground(padCells(raw,span),style.color??"#e6e6e6",mode,style.bold))+" ".repeat(inset);
    }
    else if (!overlay && !sidebarOverlay && index < heroRows) rendered = backgroundLine(raw, contentWidth, background, mode);
    else if (raw.startsWith("> ") || raw.includes("›")) rendered = foreground(rendered, "#ff553b", mode, true);
    else if (/^(You|Sophia|Tasks|Projects|Workflows|Recent chats|Suggestions|Actions)$/.test(raw)) rendered = foreground(rendered, "#5a85eb", mode, true);
    const sideValue=side[i],sideText=sideValue?lineText(sideValue):'';
    if(sideValue&&typeof sideValue!=='string'&&sideValue.action)addPointerTarget(state,gutter,i+2,Math.min(cells(sideText),sidebarWidth-2),sideValue.action);
    const sidebarRow = sidebarWidth ? foreground(padCells(sideText, sidebarWidth - 2), "#cfcfcf", mode) + `${vertical} ` : undefined;
    rows.push(place(rendered, sidebarRow));
  }
  const placeholder = state.screen === "example" ? "Continue from this example, or ask your own question..."
    : state.workspace === "chats" ? state.screen === "chat" ? "Ask a follow-up, use @file, or type /help" : "Ask anything..."
    : state.workspace === "projects" ? "Name a new project  ·  /search to browse"
    : state.workspace === "workflows" ? "Describe new workflow  ·  /search to browse"
    : state.workspace === "tasks" ? "Add or update tasks  ·  /search to browse" : "Search apps or type / for actions";
  const hint = state.textSelection ? 'Select text: drag to highlight, use terminal copy. Ctrl+Y / Esc resume.' : state.status && state.screen !== "status" && state.screen !== "embed" ? `${state.status}  ·  ${workspaceHint(state)}` : workspaceHint(state);
  const hintColor = state.focus === "composer" ? "#a0a0a0" : "#ff553b";
  const composer: string[] = [];
  if (showComposer) {
    if(!modal&&!sidebarOverlay)for(let i=0;i<input.count;i++)addPointerTarget(state,gutter+sidebarWidth+composerInset+(composerWidth<6?0:2),
      2+bodyHeight+(composerWidth<6?0:1)+i,Math.max(1,composerWidth-(composerWidth<6?0:4)),{kind:'focus',focus:'composer'});
    const placeInput = (rendered: string) => ' '.repeat(gutter + sidebarWidth + composerInset) + rendered + ' '.repeat(paneWidth - composerInset - composerWidth + gutter);
    const inputRows = input.lines.map((text, i) => `${i ? "  " : "> "}${text || (!state.input ? placeholder : "")}`);
    if (composerWidth < 6) composer.push(...inputRows.map((text) => placeInput(padCells(text, composerWidth))), placeInput(foreground(padCells(hint, composerWidth), hintColor, mode)), placeInput(" ".repeat(composerWidth)), placeInput(" ".repeat(composerWidth)));
    else {
      const edge = (left: string, right: string) => placeInput(foreground(left + line.repeat(composerWidth - 2) + right, "#6b6b6b", mode));
      const inputRow = (text: string, color?: string) => placeInput(foreground(vertical, "#6b6b6b", mode) + " " + foreground(padCells(text, composerWidth - 4), color ?? "#e6e6e6", mode) + " " + foreground(vertical, "#6b6b6b", mode));
      composer.push(edge(ascii ? "+" : "╭", ascii ? "+" : "╮"), ...inputRows.map((text) => inputRow(text)), inputRow(hint, hintColor), edge(ascii ? "+" : "╰", ascii ? "+" : "╯"));
    }
  }
  const frame = [place(renderedNav), place(" ".repeat(contentWidth)), ...rows,
    ...(showComposer ? composer : [place(foreground(padCells(hint, contentWidth), hintColor, mode))])];
  // Even tiny terminals are bounded by their actual dimensions.
  return frame.slice(0, height).join("\n");
}

function titleCase(value: string) { return value.charAt(0).toUpperCase() + value.slice(1); }
