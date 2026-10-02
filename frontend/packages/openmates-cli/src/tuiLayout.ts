/** Pure shared workspace layout, terminal color adaptation and overlays. */
import type { TuiState } from "./tuiRenderer.js";
import { CATEGORY_GRADIENTS } from "../../chatCategoryTheme.js";
import { paletteActions } from "./tuiActions.js";
import { foreground, gradientLine, lineText, padCells, terminalText, truncateCells, wrapCells, type TuiColorMode, type TuiLine } from "./tuiText.js";

export const WORKSPACES = ["chats", "apps", "projects", "workflows", "tasks"] as const;
export const DEFAULT_CHAT_GRADIENT = { start: "#4867cd", end: "#5a85eb" };
export function chatGradient(category: string | null | undefined) {
  return category && CATEGORY_GRADIENTS[category] || DEFAULT_CHAT_GRADIENT;
}

export function sidebarLines(state: TuiState): string[] {
  const selected = (label: string, index: number) => `${state.focus === "sidebar" && state.sidebarIndex === index ? ">" : " "} ${label}`;
  switch (state.workspace) {
    case "chats": return ["Chats", "", selected("+ New chat", 0), "", "Recent chats", "", ...state.recentChats.map((c, i) => selected(c.title || "Untitled chat", i + 1)), "", "/chats browse   /examples"];
    case "projects": return ["Projects", "", ...state.projects.map((p, i) => selected(p.name, i)), "", "/project-create new"];
    case "tasks": return ["Tasks", "", ...state.tasks.map((t, i) => selected(`${t.shortId} ${t.title}`, i)), "", "/task-create new"];
    case "workflows": return ["Workflows", "", ...state.workflows.map((w, i) => selected(w.title, i)), "", "Select a workflow to open"];
    case "apps": return ["Apps", "", ...state.apps.map((a,i)=>selected(a.name,i)), "", "Ctrl+B close sidebar"];
  }
}

export function workspaceHint(state: TuiState): string {
  if (state.form) return "Tab field   ←/→ choice   Ctrl+S save   Esc cancel";
  if (state.paletteOpen) return "↑/↓ choose   Enter action   Esc close";
  if (state.focus === "navigation") return "←/→ workspace   Enter open   Tab focus   Ctrl+B sidebar";
  if (state.focus === "inspiration") return "←/→ inspiration   Enter explore   Tab focus";
  if (state.focus === "sidebar") return "↑/↓ choose   Enter open   Ctrl+B close   Tab focus";
  if (state.workflowEdit) return "Enter save title   Esc cancel edit";
  if (state.screen === "workflow") return "g template   r runs   ↑/↓ select   Enter expand   e title   E config   x run   c cancel";
  if (state.screen === "task") return "e edit   m status   a activity   s start   d done   b block   Esc back";
  if (state.screen === "project") return "1 overview   2 files   3 tasks   Enter open   n new chat   Esc back";
  if (state.screen === "app") return "1–5 tabs   ↑/↓ choose   Enter open   Esc Apps   /search";
  if (state.screen === "app-skill") return "1–3 tabs   Enter use skill   Esc app   Ctrl+P actions";
  if (state.screen === "app-result") return "↑/↓ scroll   Esc saved results   Ctrl+P actions";
  if (state.screen === "apps") return "↑/↓ choose   Enter open   /search   /browse Show all   Tab focus";
  if (state.screen === "projects" || state.screen === "tasks" || state.screen === "workflows" || state.screen === "chats") return "↑/↓ choose   Enter open   /search filter   Tab focus   Ctrl+P actions";
  if (state.screen === "interests") return "↑/↓ move   Space select   Enter continue   Esc back";
  if (state.screen === "examples") return "↑/↓ choose   Enter open   /search filter   Esc back";
  return "Enter send   Alt+Enter newline   Ctrl+B sidebar   Ctrl+P actions   @ attach";
}

function overlayLines(state: TuiState, width: number, height: number): string[] {
  if (state.paletteOpen) {
    const actions = paletteActions(state.paletteQuery);
    const start = Math.max(0, state.paletteIndex - Math.max(1, height - 5));
    return ["Actions", `Search: ${state.paletteQuery}_`, "", ...actions.slice(start).map((a, i) => `${i + start === state.paletteIndex ? ">" : " "} ${a.label}  ${a.command}`)];
  }
  const form = state.form;
  if (!form) return [];
  const rows = [form.title, ""];
  for (const [index, field] of form.fields.entries()) {
    rows.push(`${index === form.fieldIndex ? ">" : " "} ${field.label}${field.options ? " [←/→]" : ""}`);
    rows.push(...wrapCells(`  ${field.value || "(empty)"}${index === form.fieldIndex && !form.busy ? "_" : ""}`, width));
    rows.push("");
  }
  if (form.error) rows.push(`Error: ${form.error}`);
  rows.push(form.busy ? "Saving…" : form.fields.length ? "Ctrl+S saves. Escape cancels." : "Enter confirms. Escape cancels.");
  return rows;
}

export function renderWorkspaceFrame(state: TuiState, rawWidth: number, rawHeight: number, body: TuiLine[], options: {colorMode?: TuiColorMode; ascii?: boolean; headerRows?: number; stickyRows?:number} = {}): string {
  const width = Math.max(1, Math.floor(rawWidth)), height = Math.max(1, Math.floor(rawHeight));
  const mode = options.colorMode ?? "none";
  const ascii = options.ascii ?? false;
  const inner = Math.max(1, width - 4);
  const line = ascii ? "-" : "─", vertical = ascii ? "|" : "│";
  const border = (left: string, right: string) => left + line.repeat(Math.max(0, width - 2)) + right;
  const top = border(ascii ? "+" : "╭", ascii ? "+" : "╮");
  const bottom = border(ascii ? "+" : "╰", ascii ? "+" : "╯");
  const divider = border(ascii ? "+" : "├", ascii ? "+" : "┤");
  const box = (text: string, style?: string) => `${vertical} ${style ?? padCells(text, inner)} ${vertical}`;
  const labels = WORKSPACES.map((w, i) => state.workspace === w ? `[${titleCase(w)}]` : state.focus === "navigation" && i === state.navigationIndex ? `>${titleCase(w)}<` : titleCase(w)).join("  ");
  const title = state.activeChat?.title && state.workspace === "chats" ? ` · ${state.activeChat.title}` : "";
  const nav = width >= 90 ? `OpenMates  ${labels}${title}` : `OpenMates  [${titleCase(state.workspace)}]  ${state.sidebarOpen ? "Sidebar open" : "Ctrl+B sidebar"}${title}`;
  const inputLines = state.input.split("\n");
  const showComposer = state.workspace !== "apps" || state.focus === "composer" || Boolean(state.input);
  const composerRows = showComposer ? Math.min(3, Math.max(1, inputLines.length)) : 0;
  const bodyHeight = Math.max(1, height - 5 - (showComposer ? 1+composerRows : 0));
  const overlay = state.form || state.paletteOpen;
  const sidebar = state.sidebarOpen && !overlay;
  const sidebarWidth = sidebar && width >= 90 ? 27 : 0;
  const contentWidth = Math.max(1, inner - sidebarWidth);
  const sidebarOverlay = sidebar && !sidebarWidth;
  let content = overlay ? overlayLines(state, inner, bodyHeight) : sidebarOverlay ? sidebarLines(state) : body;
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
    const marker = content.findIndex((row) => lineText(row).startsWith("> "));
    start = marker >= bodyHeight ? Math.max(0, marker - bodyHeight + 3) : 0;
  } else if (["start", "tasks", "projects", "project", "chats", "examples", "workflow", "workflows", "apps", "app", "app-skill"].includes(state.screen) && state.focus === "content") {
    const markers=content.map((row,index)=>/(?:^|[│|])\s*[>›] /.test(lineText(row))?index:-1).filter((index)=>index>=0);
    const marker=state.screen==="workflow" ? markers.at(-1)??-1 : markers[0]??-1;
    let selectionEnd=marker;
    if(state.screen==="workflow"&&marker>=0){
      const closing=content.findIndex((row,index)=>index>marker&&lineText(row).includes("╰"));
      selectionEnd=Math.min(marker+10,closing<0?marker:closing);
    }
    if (selectionEnd >= start + viewportHeight) start = Math.min(maxStart, selectionEnd - viewportHeight + 2);
    if (marker >= 0 && marker < start) start = marker;
  }
  const heroRows = options.headerRows ?? 0;
  const category = state.screen === "example" ? state.activeExample?.chat.category : state.activeChat?.category;
  const gradient = chatGradient(category);
  const allSide = sidebarLines(state);
  const sideMarker = allSide.findIndex((row) => row.startsWith("> "));
  const sideStart = Math.max(0, sideMarker - bodyHeight + 3);
  const side = sideStart ? [allSide[0], "", ...allSide.slice(sideStart)] : allSide;
  const rows: string[] = [];
  for (let i = 0; i < bodyHeight; i++) {
    const index = i<stickyCount ? i : start+i;
    const value = i<stickyCount ? fixed[i] : content[start+i-stickyCount] ?? "";
    const style = typeof value === "string" ? undefined : value;
    const raw = terminalText(lineText(value)).replace(/\n/g, " ");
    let rendered = padCells(raw, contentWidth);
    if (style && !overlay && !sidebarOverlay) {
      const inset=Math.max(0,Math.min(Math.floor(contentWidth/2)-1,style.inset??0));
      const span=Math.max(1,contentWidth-2*inset);
      rendered=" ".repeat(inset)+(style.gradient ? gradientLine(raw,span,style.gradient,mode,style.row??0,style.rows??1)
        :foreground(padCells(raw,span),style.color??"#e6e6e6",mode,style.bold))+" ".repeat(inset);
    }
    else if (!overlay && !sidebarOverlay && index < heroRows) rendered = gradientLine(raw, contentWidth, gradient, mode, index, heroRows);
    else if (raw.startsWith("> ") || raw.includes("›")) rendered = foreground(rendered, "#ff553b", mode, true);
    else if (/^(You|Sophia|Tasks|Projects|Workflows|Recent chats|Suggestions|Actions)$/.test(raw)) rendered = foreground(rendered, "#5a85eb", mode, true);
    if (sidebarWidth) rendered = foreground(padCells(side[i] ?? "", sidebarWidth - 2), "#cfcfcf", mode) + `${vertical} ` + rendered;
    rows.push(box("", rendered));
  }
  const placeholder = state.screen === "example" ? "Continue from this example, or ask your own question..."
    : state.workspace === "chats" ? state.screen === "chat" ? "Ask a follow-up, use @file, or type /help" : "Ask anything..."
    : state.workspace === "projects" ? "Name a new project  ·  /search to browse"
    : state.workspace === "workflows" ? "Describe new workflow  ·  /search to browse"
    : state.workspace === "tasks" ? "Add or update tasks  ·  /search to browse" : "Search apps or type / for actions";
  const composer = showComposer ? inputLines.slice(-composerRows).map((text, i) => box(`${i ? "  " : "> "}${text || (!state.input ? placeholder : "")}`)) : [];
  const hint = state.status && state.screen !== "status" ? `${state.status}  ·  ${workspaceHint(state)}` : workspaceHint(state);
  const frame = [top, box("", foreground(padCells(nav, inner), "#cfcfcf", mode, true)), divider, ...rows, ...(showComposer?[divider,...composer]:[]), box("", foreground(padCells(hint, inner), state.focus === "composer" ? "#a0a0a0" : "#ff553b", mode)), bottom];
  // Even tiny terminals are bounded by their actual dimensions.
  return frame.slice(0, height).map((row) => width < 5 ? truncateCells(row, width) : row).join("\n");
}

function titleCase(value: string) { return value.charAt(0).toUpperCase() + value.slice(1); }
