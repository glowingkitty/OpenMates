/*
 * Apps workspace model for the interactive terminal.
 * Uses the web Apps catalog and natural-language request contract, with client-side encryption
 * for saved Personal results. No file, provider, or account secret is sent to the
 * Apps result index in plaintext. Submitting a request accepts its chosen execution.
 * Team and guest execution are disabled until their web authorization contracts
 * can be carried through the CLI client.
 */

import { randomBytes, randomUUID } from "node:crypto";
import type { OpenMatesClient } from "./client.js";
import { compileCliPrivacy, prepareCliMessagePrivacy } from "./privacyScan.js";
import { readPrivacyPreferences } from "./privacyModel.js";
import { captureTuiWorkspaceOwner } from "./tuiCachedWorkspaces.js";
import { ProjectFilePrivacy } from "../../ui/src/services/projectFilePrivacy.js";
import { isAppsRequestMappingField, isAppsRequestOpaqueField, isAppsRequestOpaqueValue, mapAppsRequestText } from "../../ui/src/services/appsWorkspaceRequestPrivacy.js";
import { decryptBytesWithAesGcm, decryptWithAesGcmCombined, encryptBytesWithAesGcm, encryptWithAesGcmCombined } from "./crypto.js";
import { renderTuiEmbedPreview } from "./tuiEmbedPreviews.js";
import { listExampleChatsForApp } from "./exampleChats.js";
import type { TuiState } from "./tuiRenderer.js";
import { formValue, type TuiForm } from "./tuiForms.js";
import { cells, lineText, padCells, terminalText, truncateCells, wrapCells, type TuiLine, type TuiSpan } from "./tuiText.js";
import { centeredCarouselText, renderCardCarousel, renderLineCarousel } from "./tuiCarousel.js";
import { pointerLine } from "./tuiPointer.js";
import { APP_GRADIENTS, PRIMARY_GRADIENT } from "../../appGradientTheme.js";
import {
  getSkillPath, prepareSkillInput, resolveSkillSchema, schemaForPath, setSkillPath,
  skillLeafPaths, validateSkillInput, type SkillSchema,
} from "../../ui/src/components/apps/appsSkillFormUtils.js";

const APP_ID = /^[a-z][a-z0-9_]{0,63}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RESULT_PAGE_SIZE = 20;
const HOME_APP_ORDER = ["web", "news", "health", "travel", "weather", "audio"];
const pendingConfirmations = new WeakMap<TuiForm, Promise<TuiAppsSavedResult>>();

export type TuiAppSkill = { id: string; name: string; description: string; providers: string[] };
export type TuiApp = {
  id: string; name: string; description: string; category: string;
  skills: TuiAppSkill[];
  focusModes: Array<{ id: string; name: string; description: string }>;
  settingsMemories: Array<{ id: string; name: string; description: string; body?: string }>;
};
export type TuiAppsTab = "skills" | "focus_modes" | "settings_memories" | "embeds" | "workflows";
export type TuiAppsSkillTab = "overview" | "embeds" | "workflows";
export type TuiAppsSkillDetails = {
  appId: string; skillId: string; name: string; description: string;
  schema: SkillSchema; defaults: Record<string, unknown>; primaryFields: string[];
  pricing: Record<string, unknown> | null; providers: string[];
  executionAvailable: boolean; unavailableReason: string | null;
};
export type TuiAppsResultItem = { embedId: string; appId: string; skillId: string; createdAt: number; status: string };
export type TuiAppsResultsPage = { items: TuiAppsResultItem[]; hasMore: boolean; offset: number };
export type TuiAppsWorkflowPage = { items: Array<{ id: string; title: string }>; hasMore: boolean; offset: number };
export type TuiAppsSavedResult = {
  embedId: string; appId: string; skillId: string; status: string;
  content: Record<string, unknown>; children: Array<{ embedId: string; type: string; content: Record<string, unknown> }>;
  retentionError?: string;
  expiresAt?: number;
};
export type TuiAppsPreparedRun = { appId: string; skillId: string; input: Record<string, unknown>; summary: string; requestText?: string };

export type TuiAppsSavedSearch = { id: string; skillId: string; title: string; query: string; parameters: Record<string, unknown>; savedAt: number };
export type TuiAppsRecommendation = { id: string; skillId: string; createdAt: number; expiresAt: number; result: Record<string, unknown>; input?: Record<string,unknown>; requestText?: string };
export type TuiAppsLibrary = { appId: string; dailySearchesEnabled: boolean; savedSearches: TuiAppsSavedSearch[]; recommendations: TuiAppsRecommendation[] };
export type TuiAppsLibraryEntry = { id: string; title: string; description: string; command: string; section: "Saved" | "Recent" | "Example chats" };
export const emptyTuiAppsLibrary = (appId = ""): TuiAppsLibrary => ({ appId, dailySearchesEnabled: true, savedSearches: [], recommendations: [] });

export function parseTuiAppsLibrary(value: unknown, appId: string, now = Date.now()): TuiAppsLibrary {
  const data = record(value);
  if (data.app_id !== appId) throw new Error("Apps library did not match the selected app.");
  const milliseconds = (value: unknown): number => typeof value === "number" ? value < 1e12 ? value * 1000 : value : Date.parse(string(value));
  return { appId, dailySearchesEnabled: data.daily_searches_enabled !== false,
    savedSearches: rows(data.saved_searches).map(item => ({ id: string(item.id), skillId: string(item.skill_id),
      title: string(item.title, string(item.query, string(item.skill_id))), query: string(item.query), parameters: record(item.parameters), savedAt: milliseconds(item.saved_at) })),
    recommendations: rows(data.recommendations).filter(item => milliseconds(item.expires_at) > now && milliseconds(item.created_at) > now - 86400000 && milliseconds(item.created_at) <= now)
      .map(item => ({ id: string(item.id), skillId: string(item.skill_id), createdAt: milliseconds(item.created_at), expiresAt: milliseconds(item.expires_at), result: record(item.result), input: record(item.input), requestText: string(item.request_text) })),
  };
}

/** Expiry also removes data from an already open recommendation and child fullscreen. */
export function expireTuiAppsRecommendations(state:TuiState,now=Date.now()):boolean {
  const publicFresh=state.appPublicRecommendations.filter(item=>item.expiresAt>now);
  let changed=publicFresh.length!==state.appPublicRecommendations.length;state.appPublicRecommendations=publicFresh;
  const fresh=state.appLibrary.recommendations.filter(item=>item.expiresAt>now);
  if(fresh.length!==state.appLibrary.recommendations.length){state.appLibrary.recommendations=fresh.length?fresh:publicFresh;changed=true;}
  const active=state.activeAppResult;
  if(active?.expiresAt&&active.expiresAt<=now&&active.status!=="expired"){
    for(const child of tuiAppsResultChildren(active))delete state.chatEmbeds[child.embedId];
    state.activeAppResult={...active,status:"expired",content:{},children:[]};changed=true;
    if(state.workspace==="apps"&&state.screen==="embed"&&state.embedOrigin?.screen==="app-result"){
      state.detailEmbed=null;state.detailTitle="Recommendation expired";state.detailLines=["This recommendation expired. Open the app for fresh results."];
    }
  }
  return changed;
}

/** Only real saved links and app-specific published examples become navigation targets. */
export function tuiAppsLibraryEntries(state: TuiState): TuiAppsLibraryEntry[] {
  if (!state.activeApp) return [];
  const saved = state.appLibrary.savedSearches.map(item => ({ id: `saved:${item.id}`, title: item.title, description: item.query,
    command: `/app-saved ${item.id}`, section: "Saved" as const }));
  const recent = state.appResults.items.map(item => ({ id: `result:${item.embedId}`, title: item.skillId.replaceAll("_", " "), description: item.status,
    command: `/app-result ${item.embedId}`, section: "Recent" as const }));
  const recentChats=state.appRecentChats.filter(chat=>!chat.isHidden&&!chat.isHiddenCandidate&&chat.activeFocusId?.startsWith(state.activeApp!.id+"-"))
    .map(chat=>({id:`chat:${chat.id}`,title:chat.title||"Recent chat",description:chat.summary||"",command:`/chat ${chat.id}`,section:"Recent" as const}));
  const examples = listExampleChatsForApp(state.activeApp.id).map(chat => ({ id: `example:${chat.id}`, title: chat.title || "Example chat", description: chat.summary || "",
    command: `/example ${chat.slug || chat.id}`, section: "Example chats" as const }));
  return [...saved, ...recent, ...recentChats, ...examples];
}

export function tuiAppsCarouselGroups(state:TuiState): Array<{title:string;commands:string[]}> {
  const entries=tuiAppsLibraryEntries(state),groups:Array<{title:string;commands:string[]}>=[];
  const recommendations=state.appLibrary.recommendations.filter(item=>item.expiresAt>Date.now());
  if(recommendations.length)groups.push({title:"Recommended",commands:recommendations.map(item=>`/app-recommendation ${item.id}`)});
  for(const title of ["Saved","Recent","Example chats"]){const items=entries.filter(item=>item.section===title);if(items.length)groups.push({title,commands:items.map(item=>item.command)});}
  return groups;
}

export function renderTuiAppsWorkspace(state: TuiState, width: number): TuiLine[] {
  const app = state.activeApp;
  if (!app) return ["Loading app…"];
  const lines: TuiLine[] = [...renderTuiAppIdentity(app, width),
    pointerLine("⚙ Settings", {kind:"command",command:"/app-settings"}), "", "What would you like to find or do?", "Describe your request below. Running searches may use credits.", ""];
  const library = state.appLibrary;
  const recommendations = library.recommendations.filter(item => item.expiresAt > Date.now());
  const entries = tuiAppsLibraryEntries(state);
  const selectedSection=tuiAppsCarouselGroups(state)[state.appCarouselRow]?.title;
  if (recommendations.length) {
    lines.push("Recommended", "");
    const cards = recommendations.map(item => {
      const result = recommendationTuiAppsResult(app.id, item);
      const child = tuiAppsResultChildren(result)[0];
      if(!child)return [];
      const cardWidth=Math.min(62,width),card=renderTuiEmbedPreview(toTuiAppsEmbed(child,app.id,item.skillId),cardWidth,child.embedId);
      // Recommendation batches are not persisted embed graphs; their visible shortcut opens the batch.
      if(cardWidth>=6)card[card.length-2]=`│ ${padCells(`/app-recommendation ${item.id}`,cardWidth-4)} │`;
      return card.map(line=>pointerLine(line,{kind:"command",command:`/app-recommendation ${item.id}`}));
    });
    lines.push(...renderLineCarousel(cards,width,state.appCarouselPositions.Recommended??0,state.focus==="content"&&selectedSection==="Recommended",Math.min(62,width)), "");
  }
  for (const section of ["Saved", "Recent", "Example chats"] as const) {
    const items = entries.filter(item => item.section === section);
    if (!items.length) continue;
    lines.push(section, "", ...renderCardCarousel(items.map(item => ({title:item.title,description:item.description,
      footer:section === "Saved" ? "Saved search" : section === "Recent" ? "Open results" : "Open example chat",
      background:(APP_GRADIENTS[app.id]??PRIMARY_GRADIENT).start,action:{kind:"command",command:item.command}})),
      width,state.appCarouselPositions[section]??0,state.focus==="content"&&selectedSection===section), "");
  }
  if (!entries.length && !recommendations.length) lines.push("Your results and saved searches will appear here.");
  return lines;
}

export function renderTuiAppsSettings(state: TuiState, width: number): TuiLine[] {
  const app = state.activeApp;if (!app) return [];
  return [...renderTuiAppIdentity(app,width),"Settings", "",
    pointerLine(`Daily searches: ${state.appLibrary.dailySearchesEnabled ? "On" : "Off"}`,{kind:"command",command:`/app-daily ${state.appLibrary.dailySearchesEnabled ? "off" : "on"}`}),
    "Only your latest saved search runs daily while you are active.", "Personal searches use your credits.", "", "Skills · pricing and providers", "",
    ...app.skills.flatMap(skill => [pointerLine(`${skill.name}${skill.providers.length ? ` · ${skill.providers.join(", ")}` : ""}`,{kind:"command",command:`/app-skill ${app.id}/${skill.id}`})]),
    "",pointerLine("Back to app",{kind:"command",command:`/app ${app.id}`})];
}

export async function interpretTuiAppsRequest(client: OpenMatesClient, app: TuiApp, text: string, result?: TuiAppsSavedResult | null): Promise<{action:"execute"|"chat"|"workflow";run?:TuiAppsPreparedRun}> {
  if(result?.expiresAt&&result.expiresAt<=Date.now())throw new Error("This recommendation expired. Open the app for fresh results.");
  if (!client.hasSession()) throw new Error("Sign in to use Apps.");
  if (client.getActiveTeamId()) throw new Error("Switch to Personal to use Apps in the terminal.");
  const ownerCurrent = captureTuiWorkspaceOwner(client);
  const preferencesKey = JSON.stringify(await readPrivacyPreferences());
  const assertCurrent = async () => {
    const preferences = await readPrivacyPreferences();
    if (!ownerCurrent() || !client.hasSession() || client.getActiveTeamId()) throw new Error("Apps privacy account context changed.");
    if (JSON.stringify(preferences) !== preferencesKey) throw new Error("Apps privacy settings changed. Submit the request again.");
  };
  const [owner, memories] = await Promise.all([client.whoAmI(), client.listMemories({ personal: true })]);
  await assertCurrent();
  const ownerId = string(owner.id, string(owner.user_id));
  if (!UUID.test(ownerId)) throw new Error("Apps privacy account identity unavailable.");
  const privacy = compileCliPrivacy(memories.filter(memory => memory.app_id === "privacy"
    && ["pii_detection_settings", "personal_data_entry"].includes(memory.item_type)));
  let mappings: Awaited<ReturnType<typeof prepareCliMessagePrivacy>>["mappings"] = [];
  const protect = async (value: string) => {
    const prepared = await prepareCliMessagePrivacy(value, [], mappings, { kind: "message" }, undefined, privacy);
    mappings = prepared.mappings;
    return prepared.message;
  };
  const textForModel = await protect(text);
  const requestId = randomUUID();
  const context = result ? { skill_id: result.skillId, input: record(result.content.input),
    embed_id: UUID.test(result.embedId) ? result.embedId : undefined,
    result: { summary: renderTuiAppsResult(result, 120).join("\n").slice(0, 10000) } } : undefined;
  const contextForModel = context ? { ...context, input: record(await transformTuiAppsPrivacy(context.input, protect)),
    result: record(await transformTuiAppsPrivacy(context.result, protect)) } : undefined;
  await assertCurrent();
  const response = record(await client.interpretAppsWorkspaceRequest({ app_id: app.id, text: textForModel, request_id: requestId, expected_user_id: ownerId,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, locale: Intl.DateTimeFormat().resolvedOptions().locale,
    ...(contextForModel ? { context: contextForModel } : {}) }));
  await assertCurrent();
  if (response.request_id !== requestId || !["execute","chat","workflow"].includes(string(response.action))) throw new Error("Apps returned an invalid request plan.");
  if (response.action !== "execute") return {action:response.action as "chat"|"workflow"};
  const skillId = string(response.skill_id);
  if (!app.skills.some(skill => skill.id === skillId)) throw new Error("Apps chose an unavailable skill.");
  const skill = await loadTuiAppsSkill(client,app.id,skillId);
  if (!skill.executionAvailable) throw new Error(skill.unavailableReason || "This skill is unavailable.");
  await assertCurrent();
  const restore = new ProjectFilePrivacy({ mappings, save: async () => {} });
  const restoredInput = mapAppsRequestText(response.input, value => restore.restoreText(value));
  const input = prepareSkillInput(skill.schema,record(restoredInput),Intl.DateTimeFormat().resolvedOptions().timeZone);
  const issues = validateSkillInput(skill.schema,input);
  if (issues.length) throw new Error("Apps could not prepare a valid request. Add more detail and try again.");
  return {action:"execute",run:{appId:app.id,skillId,input,summary:skill.name,requestText:text}};
}


/** Transform user data only; mappings stay local and capability bytes stay exact. */
async function transformTuiAppsPrivacy(value: unknown, transform: (value: string) => string | Promise<string>): Promise<unknown> {
  if (typeof value === "string") return isAppsRequestOpaqueValue(value) ? value : transform(value);
  if (Array.isArray(value)) { const result = []; for (const child of value) result.push(await transformTuiAppsPrivacy(child, transform)); return result; }
  if (value && typeof value === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value)) {
      if (isAppsRequestMappingField(key)) continue;
      result[key] = isAppsRequestOpaqueField(key) ? child : await transformTuiAppsPrivacy(child, transform);
    }
    return result;
  }
  return value;
}

/** Submission of a natural-language search accepts its selected billable execution. */
export function executeTuiAppsRequest(client: OpenMatesClient, run: TuiAppsPreparedRun): Promise<TuiAppsSavedResult> {
  return executeConfirmedTuiAppsSkill(client,run);
}

export function tuiAppsHandoffText(text: string, result?: TuiAppsSavedResult | null): string {
  if (!result) return text;
  return `${text}\n\nPrevious ${result.appId}/${result.skillId} request and results:\n${JSON.stringify({input:result.content.input,
    result:result.content,children:result.children.map(child=>({type:child.type,content:child.content}))})}`;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function string(value: unknown, fallback = ""): string { return typeof value === "string" ? value : fallback; }
function rows(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.map(record) : []; }
function oneLine(value: string): string { return terminalText(value).replace(/\s+/g, " ").trim(); }
function textLines(value: string, width: number): string[] { return wrapCells(value, Math.max(1, width)); }

function parseApp(value: Record<string, unknown>, idHint = ""): TuiApp | null {
  const id = string(value.id, idHint);
  if (!APP_ID.test(id)) return null;
  return {
    id, name: string(value.name, id), description: string(value.description), category: string(value.category),
    skills: rows(value.skills).flatMap((skill): TuiAppSkill[] => {
      const skillId = string(skill.id);
      if (!APP_ID.test(skillId)) return [];
      return [{ id: skillId, name: string(skill.name, skillId), description: string(skill.description),
        providers: rows(skill.providers).map((provider) => string(provider.name, string(provider.provider))).filter(Boolean) }];
    }),
    focusModes: rows(value.focus_modes).map((entry) => ({ id: string(entry.id), name: string(entry.name), description: string(entry.description) })),
    settingsMemories: [
      ...rows(value.settings_and_memories).map((entry) => ({ id: string(entry.id), name: string(entry.name), description: string(entry.description) })),
      ...rows(value.memories).map((entry) => ({ id: string(entry.id), name: string(entry.title),
        description: `App-provided · Read-only · Loads automatically when relevant. ${string(entry.description)}`, body: string(entry.body) })),
    ],
  };
}

/** Read the same public catalog consumed by the web Apps workspace. */
export async function loadTuiApps(client: Pick<OpenMatesClient, "getAppsWorkspaceCatalog">): Promise<TuiApp[]> {
  const data = record(await client.getAppsWorkspaceCatalog());
  const source = data.apps;
  const apps = Array.isArray(source) ? source.map((value) => parseApp(record(value)))
    : Object.entries(record(source)).map(([id, value]) => parseApp(record(value), id));
  return apps.filter((app): app is TuiApp => app !== null).sort((a, b) => {
    const left = HOME_APP_ORDER.indexOf(a.id), right = HOME_APP_ORDER.indexOf(b.id);
    if (left >= 0 || right >= 0) return (left < 0 ? Infinity : left) - (right < 0 ? Infinity : right);
    return a.name.localeCompare(b.name);
  });
}

export function visibleTuiApps(apps: TuiApp[], query = ""): TuiApp[] {
  const words = query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  return apps.filter((app) => words.every((word) => `${app.name} ${app.description} ${app.category} ${app.skills.map((skill) => skill.name).join(" ")}`.toLocaleLowerCase().includes(word)));
}

/** Keep the featured home, full catalog, filtering and Enter targets in agreement. */
export function homeTuiApps(apps: TuiApp[], query = "", showAll = false): TuiApp[] {
  const visible = visibleTuiApps(apps, query);
  return showAll || query ? visible : visible.slice(0, HOME_APP_ORDER.length);
}

export function renderTuiAppsHome(apps: TuiApp[], options: { width: number; selectedId?: string; selectedIndex?: number; query?: string }): TuiLine[] {
  const width = Math.max(1, options.width);
  const visible = visibleTuiApps(apps, options.query);
  if (!visible.length) return [centeredCarouselText(options.query ? "No matching apps." : "No apps available.", width)];
  const selected = Math.max(0, Math.min(visible.length - 1, options.selectedIndex ?? visible.findIndex((app) => app.id === options.selectedId)));
  return [...renderCardCarousel(visible.map((app) => ({ title: app.name, description: app.description,
    footer: `${app.skills.length} skills${app.category ? ` · ${app.category.replaceAll("_", " ")}` : ""}`,
    background: (APP_GRADIENTS[app.id] ?? PRIMARY_GRADIENT).start,
    action: {kind:"command" as const,command:`/app ${app.id}`},
  })), width, selected, options.selectedId !== undefined), "",
  centeredCarouselText(`${selected > 0 ? "‹" : " "}  App ${selected + 1} of ${visible.length}  ${selected < visible.length - 1 ? "›" : " "}`, width),
  centeredCarouselText("←/→ choose app  ·  Enter open  ·  Tab focus", width)];
}

function cardLines(title: string, description: string, footer: string, width: number): string[] {
  if (width < 4) return [truncateCells(title, width)];
  const cardWidth = Math.min(width, 64);
  const inner = cardWidth - 4;
  return [
    `╭${"─".repeat(cardWidth - 2)}╮`,
    `│ ${padCells(title, inner)} │`,
    `│ ${padCells(oneLine(description), inner)} │`,
    `│ ${padCells(footer, inner)} │`,
    `╰${"─".repeat(cardWidth - 2)}╯`,
  ];
}

function identityCard(rows: string[], width: number, label: string): string[] {
  width = Math.max(1, width);
  if (width < 6) return rows.flatMap((row) => textLines(row, width));
  const inner = width - 4;
  const heading = truncateCells(`─ ${label} `, width - 2);
  return [
    `╭${heading}${"─".repeat(Math.max(0, width - 2 - cells(heading)))}╮`,
    ...rows.flatMap((row) => textLines(row, inner).map((line) => `│ ${padCells(line, inner)} │`)),
    `╰${"─".repeat(width - 2)}╯`,
  ];
}

function outlinedTabs<T extends string>(tabs: readonly T[], labels: Record<T, string>, selected: T, width: number): string[] {
  width = Math.max(1, width);
  if (width < tabs.length * 8 + 1) return ["", truncateCells(tabs.map((tab, index) => `${index + 1} ${tab === selected ? `[${labels[tab]}]` : labels[tab]}`).join(" | "), width), ""];
  const available = width - tabs.length - 1;
  const base = Math.floor(available / tabs.length);
  const widths = tabs.map((_, index) => base + (index < available % tabs.length ? 1 : 0));
  const edges = widths.map((size) => "─".repeat(size));
  const row = tabs.map((tab, index) => {
    const label = `${index + 1} ${tab === selected ? `[${labels[tab]}]` : labels[tab]}`;
    const size = widths[index]!;
    return padCells(label, size);
  });
  return ["", `╭${edges.join("┬")}╮`, `│${row.join("│")}│`, `╰${edges.join("┴")}╯`, ""];
}

function outlinedPointerTabs<T extends string>(tabs:readonly T[],labels:Record<T,string>,selected:T,width:number):TuiLine[] {
  const rendered=outlinedTabs(tabs,labels,selected,width);
  const action=(index:number)=>({kind:"key" as const,name:"",chunk:String(index+1),focus:"content" as const});
  if(width<tabs.length*8+1){
    const spans:TuiSpan[]=[];let remaining=Math.max(1,width);
    tabs.forEach((tab,index)=>{
      if(index&&remaining){const separator=truncateCells(" | ",remaining);spans.push({text:separator});remaining-=cells(separator);}
      const label=truncateCells(`${index+1} ${tab===selected?`[${labels[tab]}]`:labels[tab]}`,remaining);
      if(label)spans.push({text:label,action:action(index)});
      remaining-=cells(label);
    });
    return ["",{text:rendered[1],spans},""];
  }
  const available=width-tabs.length-1,base=Math.floor(available/tabs.length);
  const sizes=tabs.map((_,index)=>base+(index<available%tabs.length?1:0));
  return rendered.map((line,row)=>{
    if(row===0||row===rendered.length-1)return line;
    const spans:TuiSpan[]=[{text:line.slice(0,1)}];let offset=1;
    sizes.forEach((size,index)=>{
      spans.push({text:line.slice(offset,offset+size),action:action(index)});offset+=size;
      spans.push({text:line.slice(offset,offset+1)});offset++;
    });
    return {text:line,spans};
  });
}

function pointerPageLine(offset:number,hasMore:boolean):TuiLine {
  const prefix=`Page ${Math.floor(offset / RESULT_PAGE_SIZE) + 1} · `;
  const spans:TuiSpan[]=[{text:prefix},{text:"previous",...(offset>0?{action:{kind:"key" as const,name:"",chunk:"[",focus:"content" as const}}:{})},
    {text:"/"},{text:"next",...(hasMore?{action:{kind:"key" as const,name:"",chunk:"]",focus:"content" as const}}:{})},{text:" available"}];
  return {text:spans.map((span)=>span.text).join(""),spans};
}

export function renderTuiAppIdentity(app: TuiApp, width: number): string[] {
  return identityCard([`APP  /  ${app.id.toUpperCase()}`, app.name, app.description,
    `${app.skills.length} skills · ${app.focusModes.length} focus modes`], width, "APP WORKSPACE");
}

export function renderTuiAppTabs(tab:TuiAppsTab,width:number,options:{pointer:true}):TuiLine[];
export function renderTuiAppTabs(tab:TuiAppsTab,width:number):string[];
export function renderTuiAppTabs(tab: TuiAppsTab, width: number, options?:{pointer:true}): TuiLine[] {
  const tabs: TuiAppsTab[] = ["skills", "focus_modes", "settings_memories", "embeds", "workflows"];
  const labels: Record<TuiAppsTab, string> = { skills: "Skills", focus_modes: "Focus modes", settings_memories: "Memories", embeds: "Embeds", workflows: "Workflows" };
  return options?.pointer?outlinedPointerTabs(tabs,labels,tab,width):outlinedTabs(tabs, labels, tab, width);
}

export function renderTuiApp(app:TuiApp,options:{width:number;tab:TuiAppsTab;selectedId?:string;pointer:true}):TuiLine[];
export function renderTuiApp(app:TuiApp,options:{width:number;tab:TuiAppsTab;selectedId?:string}):string[];
export function renderTuiApp(app: TuiApp, options: { width: number; tab: TuiAppsTab; selectedId?: string;pointer?:true }): TuiLine[] {
  const width = Math.max(1, options.width);
  const lines:TuiLine[] = [...renderTuiAppIdentity(app, width), ...(options.pointer?renderTuiAppTabs(options.tab,width,{pointer:true}):renderTuiAppTabs(options.tab, width))];
  if (options.tab === "skills") {
    lines.push("Which app skill do you want to use?", "");
    if (!app.skills.length) lines.push("No skills available.");
    for (const skill of app.skills) {
      const card=cardLines(`${skill.id === options.selectedId ? "›" : " "} ${skill.name}`, skill.description,
        skill.providers.length ? `via ${skill.providers.join(", ")}` : `${app.id}/${skill.id}`, width);
      lines.push(...(options.pointer?card.map((line)=>pointerLine(line,{kind:"command",command:`/app-skill ${app.id}/${skill.id}`})):card), "");
    }
  } else if (options.tab === "focus_modes" || options.tab === "settings_memories") {
    const items = options.tab === "focus_modes" ? app.focusModes : app.settingsMemories;
    if (!items.length) lines.push("Nothing in this section.");
    for (const item of items) {
      lines.push(truncateCells(`${item.id === options.selectedId ? ">" : " "} ${item.name}`, width));
      if (item.description) lines.push(...textLines(`  ${oneLine(item.description)}`, width));
      if ('body' in item && typeof item.body === "string" && item.body && item.id === options.selectedId) lines.push(...textLines(item.body, width));
    }
    lines.push("", "Manage private Memories in the web app.");
  } else if (options.tab === "embeds") lines.push("Saved results load from the encrypted Apps history. Use Enter to inspect a result.");
  else lines.push("Saved workflows for this app load from Workflows. Open a workflow there to inspect it.");
  return lines;
}

export async function loadTuiAppsSkill(client: Pick<OpenMatesClient, "getAppsWorkspaceSkillDetails">, appId: string, skillId: string): Promise<TuiAppsSkillDetails> {
  const source = record(await client.getAppsWorkspaceSkillDetails(appId, skillId));
  if (source.app_id !== appId || source.skill_id !== skillId) throw new Error("App skill details did not match the selected skill.");
  const schema = record(source.input_schema) as SkillSchema;
  return {
    appId, skillId, name: string(source.name, skillId), description: string(source.description), schema,
    defaults: record(source.defaults), primaryFields: Array.isArray(source.primary_fields) ? source.primary_fields.filter((value): value is string => typeof value === "string") : [],
    pricing: source.pricing ? record(source.pricing) : null,
    providers: rows(source.providers).map((provider) => string(provider.name)).filter(Boolean),
    executionAvailable: source.execution_available === true, unavailableReason: typeof source.unavailable_reason === "string" ? source.unavailable_reason : null,
  };
}

export function renderTuiAppsSkill(skill:TuiAppsSkillDetails,options:{width:number;tab:TuiAppsSkillTab;pointer:true}):TuiLine[];
export function renderTuiAppsSkill(skill:TuiAppsSkillDetails,options:{width:number;tab:TuiAppsSkillTab}):string[];
export function renderTuiAppsSkill(skill: TuiAppsSkillDetails, options: { width: number; tab: TuiAppsSkillTab;pointer?:true }): TuiLine[] {
  const width = Math.max(1, options.width);
  const lines:TuiLine[] = [...renderTuiAppsSkillIdentity(skill, width), ...(options.pointer?renderTuiAppsSkillTabs(options.tab,width,{pointer:true}):renderTuiAppsSkillTabs(options.tab, width))];
  if (options.tab === "overview") {
    lines.push("Describe what you want in the composer below.", "Your mates can also use this skill in chats.", "",
      skill.executionAvailable ? "Enter starts a request. Running may spend credits." : `Unavailable: ${skill.unavailableReason ?? "This skill cannot run here."}`);
    const fixed = skill.pricing?.fixed;
    if (typeof fixed === "number") lines.push(`${fixed} credits per request`);
  } else if (options.tab === "embeds") lines.push("Saved results are listed in the app's Embeds tab.");
  else lines.push("Open related workflows from the app's Workflows tab.");
  return lines;
}

export function renderTuiAppsSkillIdentity(skill: TuiAppsSkillDetails, width: number): string[] {
  return identityCard([`SKILL  /  ${skill.appId.toUpperCase()}`, skill.name, skill.description,
    ...(skill.providers.length ? [`via ${skill.providers.join(", ")}`] : []),
    skill.executionAvailable ? "Describe your request · running may use credits" : "Skill unavailable"], width, "APP SKILL");
}

export function renderTuiAppsSkillTabs(tab:TuiAppsSkillTab,width:number,options:{pointer:true}):TuiLine[];
export function renderTuiAppsSkillTabs(tab:TuiAppsSkillTab,width:number):string[];
export function renderTuiAppsSkillTabs(tab: TuiAppsSkillTab, width: number, options?:{pointer:true}): TuiLine[] {
  const tabs: TuiAppsSkillTab[] = ["overview", "embeds", "workflows"];
  const labels: Record<TuiAppsSkillTab, string> = { overview: "Overview", embeds: "Embeds", workflows: "Workflows" };
  return options?.pointer?outlinedPointerTabs(tabs,labels,tab,width):outlinedTabs(tabs, labels, tab, width);
}

function isRequired(schema: SkillSchema, path: string): boolean {
  const parts = path.replaceAll("[]", "").split(".");
  let current = schema;
  for (const part of parts) {
    const resolved = resolveSkillSchema(current, schema);
    if (!resolved.required?.includes(part)) return false;
    current = resolved.properties?.[part] as SkillSchema ?? {};
    if (current.type === "array") current = current.items as SkillSchema ?? {};
  }
  return true;
}

function displayValue(value: unknown): string { return value === undefined || value === null ? "" : typeof value === "string" ? value : JSON.stringify(value); }

export function buildTuiAppsSkillForm(skill: TuiAppsSkillDetails): TuiForm {
  const paths = skillLeafPaths(skill.schema);
  return {
    kind: "app-skill-input", title: `Use ${skill.name}`, contextId: `${skill.appId}/${skill.skillId}`, fieldIndex: 0,
    fields: paths.map((path) => ({ name: path, label: `${path}${isRequired(skill.schema, path) ? " *" : ""}`, value: displayValue(getSkillPath(skill.defaults, path)),
      multiline: /(?:query|prompt|message|body|text|code)$/i.test(path) })),
  };
}

function parseField(raw: string, schema: SkillSchema | null): unknown {
  const field = schema ?? {};
  const type = field.type;
  if (!raw.trim()) return undefined;
  if (type === "number" || type === "integer") {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || type === "integer" && !Number.isInteger(parsed)) throw new Error("Enter a valid number.");
    return parsed;
  }
  if (type === "boolean") {
    if (raw !== "true" && raw !== "false") throw new Error("Use true or false.");
    return raw === "true";
  }
  if (type === "object" || type === "array") return JSON.parse(raw);
  return raw;
}

export function prepareTuiAppsSkillRun(skill: TuiAppsSkillDetails, form: TuiForm, timezone = Intl.DateTimeFormat().resolvedOptions().timeZone): TuiAppsPreparedRun {
  if (form.kind !== "app-skill-input" || form.contextId !== `${skill.appId}/${skill.skillId}`) throw new Error("App skill form context changed.");
  if (!skill.executionAvailable) throw new Error(skill.unavailableReason ?? "This skill is unavailable.");
  let input = structuredClone(skill.defaults);
  for (const field of form.fields) {
    const previous = getSkillPath(input, field.name);
    if (!field.value.trim() && previous === undefined) continue;
    let value: unknown;
    try { value = parseField(field.value, schemaForPath(skill.schema, field.name)); }
    catch (error) { throw new Error(`${field.label}: ${error instanceof Error ? error.message : "Invalid value"}`); }
    input = setSkillPath(input, field.name, value);
  }
  input = prepareSkillInput(skill.schema, input, timezone);
  const issues = validateSkillInput(skill.schema, input);
  if (issues.length) throw new Error(`Check ${issues.map((issue) => `${issue.path}: ${issue.code}`).join(", ")}`);
  const cost = typeof skill.pricing?.fixed === "number" ? `${skill.pricing.fixed} credits per request` : "Credits may be charged";
  return { appId: skill.appId, skillId: skill.skillId, input, summary: `${skill.name} · ${cost}` };
}

export function buildTuiAppsRunConfirmation(run: TuiAppsPreparedRun): TuiForm {
  return { kind: "app-skill-confirm", title: `Run ${run.appId}/${run.skillId}? ${run.summary}`, contextId: `${run.appId}/${run.skillId}`, fieldIndex: 0,
    fields: [{ name: "confirm", label: "Type RUN to execute and accept any credit charge", value: "" }] };
}

function responseResults(response: unknown): unknown[] {
  const source = record(response).data ?? response;
  if (Array.isArray(source)) return source.flatMap((item) => {
    const nested = responseResults(item);
    return nested.length ? nested : [item];
  });
  const data = record(source);
  const results = data.results;
  if (!Array.isArray(results)) return typeof data.embed_id === "string" && UUID.test(data.embed_id) ? [data] : [];
  return results.flatMap((item) => Array.isArray(record(item).results) ? record(item).results as unknown[] : [item]);
}

function linkedResultIds(response: unknown, results: unknown[]): string[] {
  const data = record(record(response).data ?? response);
  const resultIds = new Set(results.map((item) => string(record(item).embed_id)).filter((id) => UUID.test(id)));
  const candidates = data.child_embed_ids ?? data.embed_ids;
  return Array.isArray(candidates)
    ? [...new Set(candidates.filter((id): id is string => typeof id === "string" && UUID.test(id) && !resultIds.has(id)))] : [];
}

function resultContent(appId: string, skillId: string, input: Record<string, unknown>, response: unknown, status: string, embedIds: string[] = []): Record<string, unknown> {
  const data = record(record(response).data ?? response);
  const results = responseResults(response);
  return { ...data, app_id: appId, skill_id: skillId, input, results, status, result_count: results.length, embed_ids: embedIds };
}

async function saveEncryptedResult(client: OpenMatesClient, ownerId: string, rootId: string, key: Uint8Array, encryptedKey: string, run: TuiAppsPreparedRun, response: unknown, status: string): Promise<void> {
  const results = status === "finished" ? responseResults(response) : [];
  if (results.length > 500) throw new Error("Apps result exceeds the supported graph size.");
  const linkedIds = linkedResultIds(response, results);
  const children = await Promise.all(results.flatMap((result): Array<Promise<Record<string, unknown>>> => {
    const value = record(result);
    const type = string(value.type, string(value.embed_type));
    if (!type && typeof value.embed_id !== "string") return [];
    const id = typeof value.embed_id === "string" && UUID.test(value.embed_id) ? value.embed_id : randomUUID();
    return [(async () => ({
      embed_id: id, encrypted_type: await encryptWithAesGcmCombined(type || "app_skill_use", key),
      encrypted_content: await encryptWithAesGcmCombined(JSON.stringify({ app_id: run.appId, skill_id: run.skillId, ...value, result }), key),
      status: "finished", parent_embed_id: rootId,
    }))()];
  }));
  const childIds = children.map((child) => string(child.embed_id));
  const allIds = [...childIds, ...linkedIds];
  const content = {...resultContent(run.appId, run.skillId, run.input, response, status, allIds), ...(run.requestText?{request_text:run.requestText}:{})};
  await client.saveAppsWorkspaceResult({
    app_id: run.appId, skill_id: run.skillId, root_embed_id: rootId, expected_user_id: ownerId,
    encrypted_embed_key: encryptedKey, linked_embed_ids: linkedIds,
    embeds: [{ embed_id: rootId, encrypted_type: await encryptWithAesGcmCombined("app_skill_use", key),
      encrypted_content: await encryptWithAesGcmCombined(JSON.stringify(content), key), status, embed_ids: allIds }, ...children],
  });
}

/** Only this confirmed path dispatches a potentially billable skill. */
export function executeTuiAppsSkill(client: OpenMatesClient, run: TuiAppsPreparedRun, confirmation: TuiForm): Promise<TuiAppsSavedResult> {
  if (confirmation.kind !== "app-skill-confirm" || confirmation.contextId !== `${run.appId}/${run.skillId}` || formValue(confirmation, "confirm") !== "RUN") {
    return Promise.reject(new Error("Type RUN to confirm skill execution and possible credit charge."));
  }
  const pending = pendingConfirmations.get(confirmation);
  if (pending) return pending;
  const operation = executeConfirmedTuiAppsSkill(client, run);
  pendingConfirmations.set(confirmation, operation);
  void operation.then(() => pendingConfirmations.delete(confirmation), () => pendingConfirmations.delete(confirmation));
  return operation;
}

async function executeConfirmedTuiAppsSkill(client: OpenMatesClient, run: TuiAppsPreparedRun): Promise<TuiAppsSavedResult> {
  if (!client.hasSession()) throw new Error("Sign in to run Apps skills in the terminal.");
  if (client.getActiveTeamId()) throw new Error("Switch to Personal to run Apps skills in the terminal.");
  const owner = record(await client.whoAmI());
  const ownerId = string(owner.id, string(owner.user_id));
  if (!ownerId) throw new Error("Account identity unavailable; skill was not run.");
  const rootId = randomUUID();
  const key = randomBytes(32);
  const encryptedKey = await encryptBytesWithAesGcm(key, client.getMasterKeyBytes());
  await saveEncryptedResult(client, ownerId, rootId, key, encryptedKey, run, { status: "processing" }, "processing");
  const beforeDispatch = record(await client.whoAmI());
  if (string(beforeDispatch.id, string(beforeDispatch.user_id)) !== ownerId || client.getActiveTeamId()) {
    throw new Error(`Account context changed; skill was not run. The pending result is ${rootId}.`);
  }
  let response: unknown;
  try {
    response = await client.runSkill({ app: run.appId, skill: run.skillId, inputData: run.input });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    // A timed-out async task may still complete; leave its accepted root in processing.
    if (!/Task \S+ did not complete within/.test(message)) {
      const current = record(await client.whoAmI());
      if (string(current.id, string(current.user_id)) === ownerId && !client.getActiveTeamId()) {
        await saveEncryptedResult(client, ownerId, rootId, key, encryptedKey, run, { error: message }, "error");
      }
    }
    throw new Error(`${message} Saved Apps result: ${rootId}`);
  }
  const current = record(await client.whoAmI());
  if (string(current.id, string(current.user_id)) !== ownerId || client.getActiveTeamId()) throw new Error(`Account context changed; accepted result ${rootId} can be reopened from Apps history.`);
  try {
    await saveEncryptedResult(client, ownerId, rootId, key, encryptedKey, run, response, "finished");
  } catch {
    const afterFailure = record(await client.whoAmI());
    if (string(afterFailure.id, string(afterFailure.user_id)) !== ownerId || client.getActiveTeamId()) {
      throw new Error(`Account context changed; accepted result ${rootId} can be reopened from Apps history.`);
    }
    return { embedId: rootId, appId: run.appId, skillId: run.skillId, status: "unsaved",
      content: resultContent(run.appId, run.skillId, run.input, response, "unsaved"), children: [],
      retentionError: "The skill completed, but its result could not be saved. Copy the response before leaving this screen." };
  }
  return loadTuiAppsResult(client, rootId);
}

export async function loadTuiAppsResults(client: Pick<OpenMatesClient, "listAppsWorkspaceResults" | "getActiveTeamId">, appId: string, offset = 0): Promise<TuiAppsResultsPage> {
  if (!APP_ID.test(appId)) throw new Error("Invalid app ID.");
  if (client.getActiveTeamId()) throw new Error("Switch to Personal to browse Apps results in the terminal.");
  const page = record(await client.listAppsWorkspaceResults(appId, offset, RESULT_PAGE_SIZE));
  return { items: rows(page.items).map((item) => ({ embedId: string(item.embed_id), appId: string(item.app_id), skillId: string(item.skill_id),
    createdAt: typeof item.created_at === "number" ? item.created_at : 0, status: string(item.status) })), hasMore: page.has_more === true, offset: typeof page.offset === "number" ? page.offset : offset };
}

export async function loadTuiAppsWorkflows(client: Pick<OpenMatesClient, "listAppsWorkspaceWorkflows" | "getActiveTeamId">, appId: string, offset = 0): Promise<TuiAppsWorkflowPage> {
  if (!APP_ID.test(appId)) throw new Error("Invalid app ID.");
  if (client.getActiveTeamId()) throw new Error("Switch to Personal to browse Apps workflows in the terminal.");
  const page = record(await client.listAppsWorkspaceWorkflows(appId, offset, RESULT_PAGE_SIZE));
  return { items: rows(page.workflows).map((item) => ({ id: string(item.id), title: string(item.title, string(item.id)) })).filter((item) => item.id),
    hasMore: page.has_more === true, offset: typeof page.offset === "number" ? page.offset : offset };
}

export function renderTuiAppsWorkflows(page:TuiAppsWorkflowPage,options:{width:number;selectedId?:string;pointer:true}):TuiLine[];
export function renderTuiAppsWorkflows(page:TuiAppsWorkflowPage,options:{width:number;selectedId?:string}):string[];
export function renderTuiAppsWorkflows(page: TuiAppsWorkflowPage, options: { width: number; selectedId?: string;pointer?:true }): TuiLine[] {
  const width = Math.max(1, options.width);
  const lines:TuiLine[] = ["Related workflows", ""];
  if (!page.items.length) lines.push("No workflows for this app.");
  for (const workflow of page.items) {
    const line=truncateCells(`${workflow.id === options.selectedId ? ">" : " "} ${workflow.title} · ${workflow.id.slice(0, 8)}`, width);
    lines.push(options.pointer?pointerLine(line,{kind:"command",command:`/workflow ${workflow.id}`}):line);
  }
  if (page.offset > 0 || page.hasMore) lines.push("", options.pointer?pointerPageLine(page.offset,page.hasMore):`Page ${Math.floor(page.offset / RESULT_PAGE_SIZE) + 1} · previous/next available`);
  return lines;
}

async function decryptedRow(row: Record<string, unknown>, key: Uint8Array): Promise<{ embedId: string; type: string; content: Record<string, unknown> }> {
  const type = await decryptWithAesGcmCombined(string(row.encrypted_type), key);
  const content = await decryptWithAesGcmCombined(string(row.encrypted_content), key);
  if (type === null || content === null) throw new Error("Apps result could not be decrypted.");
  return { embedId: string(row.embed_id), type, content: record(JSON.parse(content)) };
}

export async function loadTuiAppsResult(client: Pick<OpenMatesClient, "getAppsWorkspaceResult" | "getMasterKeyBytes" | "getActiveTeamId">, embedId: string): Promise<TuiAppsSavedResult> {
  if (client.getActiveTeamId()) throw new Error("Switch to Personal to inspect Apps results in the terminal.");
  const detail = record(await client.getAppsWorkspaceResult(embedId));
  const root = record(detail.root), wrapper = record(detail.key);
  if (!wrapper.encrypted_embed_key || wrapper.key_type !== "master") throw new Error("This result needs its original chat or Team key. Open it in the web app.");
  const key = await decryptBytesWithAesGcm(string(wrapper.encrypted_embed_key), client.getMasterKeyBytes());
  if (!key) throw new Error("Apps result key could not be decrypted.");
  const decrypted = await decryptedRow(root, key);
  if (decrypted.embedId !== embedId) throw new Error("Apps result ID mismatch.");
  const children = await Promise.all(rows(detail.children).map((row) => decryptedRow(row, key)));
  return { embedId, appId: string(root.app_id), skillId: string(root.skill_id), status: string(root.status), content: decrypted.content, children };
}

export function renderTuiAppsResults(page:TuiAppsResultsPage,options:{width:number;selectedId?:string;pointer:true}):TuiLine[];
export function renderTuiAppsResults(page:TuiAppsResultsPage,options:{width:number;selectedId?:string}):string[];
export function renderTuiAppsResults(page: TuiAppsResultsPage, options: { width: number; selectedId?: string;pointer?:true }): TuiLine[] {
  const width = Math.max(1, options.width);
  const lines:TuiLine[] = ["Saved results", ""];
  if (!page.items.length) lines.push("No saved results for this app.");
  for (const item of page.items) {
    const line=truncateCells(`${item.embedId === options.selectedId ? ">" : " "} ${item.skillId} · ${item.status} · ${item.embedId.slice(0, 8)}`, width);
    lines.push(options.pointer?pointerLine(line,{kind:"command",command:`/app-result ${item.embedId}`}):line);
  }
  if (page.offset > 0 || page.hasMore) lines.push("", options.pointer?pointerPageLine(page.offset,page.hasMore):`Page ${Math.floor(page.offset / RESULT_PAGE_SIZE) + 1} · previous/next available`);
  return lines;
}

const CHILD_TYPES: Record<string,string> = {web:"web-website",news:"news-article",shopping:"shopping-product",travel:"travel-stay",events:"events-event",health:"health-appointment",videos:"videos-video",fitness:"fitness-class"};
export function tuiAppsResultChildren(result: TuiAppsSavedResult): TuiAppsSavedResult["children"] {
  if (result.children.length) return result.children.map(child=>({...child,content:{...record(child.content.result),...child.content}}));
  const extracted=responseResults(result.content);
  const hasStandaloneContent=["title","name","summary","description","text","content","transcript","forecast","weather","code","url","error"].some(key=>Boolean(result.content[key]));
  const values=extracted.length?extracted:hasStandaloneContent?[result.content]:[];
  return values.map((value,index)=>{
    const content = record(value);
    return {embedId:string(content.embed_id,`${result.embedId}:${index+1}`),type:string(content.type,string(content.embed_type,result.appId==="travel"&&/connection|flight/.test(result.skillId)?"travel-connection":CHILD_TYPES[result.appId]||"app_result")),content};
  });
}
export function recommendationTuiAppsResult(appId:string,item:TuiAppsRecommendation):TuiAppsSavedResult {
  return {embedId:item.id,appId,skillId:item.skillId,status:"finished",expiresAt:item.expiresAt,content:{...item.result,input:item.input??record(item.result.input),request_text:item.requestText,results:responseResults(item.result)},children:[]};
}
export function toTuiAppsEmbed(child:TuiAppsSavedResult["children"][number],appId:string,skillId:string) {
  return {id:child.embedId,embedId:child.embedId,type:child.type,content:child.content,textPreview:null,appId,skillId,createdAt:null};
}
export function renderTuiAppsResultControls(result:TuiAppsSavedResult,width:number,filter=""):TuiLine[] {
  return [truncateCells(`${result.appId} / ${result.skillId} · ${tuiAppsResultChildren(result).length} results · ${result.status}`,width),
    pointerLine(`Filter results${filter?`: ${filter}`:""} · /search`,{kind:"command",command:"/search"}),
    pointerLine("Save search",{kind:"command",command:"/app-save"}), ""];
}
export function renderTuiAppsResult(result: TuiAppsSavedResult, width: number, filter=""): string[] {
  return renderTuiAppsResultCards(result,width,filter).map(lineText);
}
/** Vertical rows of genuine child previews; the pinned controls/composer live outside this grid. */
export function renderTuiAppsResultCards(result:TuiAppsSavedResult,width:number,filter="",dailyNotice=false):TuiLine[] {
  width=Math.max(1,width);
  if(result.status==="expired"||result.expiresAt&&result.expiresAt<=Date.now())return ["This recommendation expired. Open the app for fresh results."];
  const lines:TuiLine[]=[...renderTuiAppsResultControls(result,width,filter)];
  if(dailyNotice)lines.splice(3,0,truncateCells("Daily searches are on · personal searches use your credits",width),
    {text:"OK    Turn off",spans:[{text:"OK",action:{kind:"command",command:"/app-daily-ok"}},{text:"    "},{text:"Turn off",action:{kind:"command",command:"/app-daily off"}}]});
  if(result.retentionError)lines.push(result.retentionError,"");
  const children=tuiAppsResultChildren(result).filter(child=>!filter||JSON.stringify(child.content).toLowerCase().includes(filter.toLowerCase()));
  const columns=width>=100?2:1,gap=2,cardWidth=Math.min(62,Math.floor((width-(columns-1)*gap)/columns));
  for(let index=0;index<children.length;index+=columns){
    const cards=children.slice(index,index+columns).map(child=>renderTuiEmbedPreview(toTuiAppsEmbed(child,result.appId,result.skillId),cardWidth,child.embedId));
    const height=Math.max(...cards.map(card=>card.length));
    for(let row=0;row<height;row++){
      const spans:TuiSpan[]=[];
      for(const [column,card] of cards.entries()){
        if(column)spans.push({text:" ".repeat(gap)});
        const line=card[row]??"",text=lineText(line),source=typeof line==="string"?[{text:line}]:line.spans??[{...line,text:line.text}];
        spans.push(...source,{text:" ".repeat(Math.max(0,cardWidth-cells(text)))});
      }
      lines.push({text:spans.map(span=>span.text).join(""),spans});
    }
    lines.push("");
  }
  if(!children.length)lines.push(filter?"No matching results.":result.status==="processing"?"Waiting for the skill result.":"No result content was returned.");
  if(result.retentionError)lines.push("Request",...readableFields(record(result.content.input),width),"Response",...readableFields(result.content,width));
  return lines;
}

function readableFields(value: Record<string, unknown>, width: number): string[] {
  const lines: string[] = [];
  function visit(label: string, item: unknown, indent: string): void {
    if (Array.isArray(item)) {
      lines.push(`${indent}${label} (${item.length})`);
      item.forEach((entry, index) => visit(`${index + 1}.`, entry, `${indent}  `));
    } else if (item && typeof item === "object") {
      lines.push(`${indent}${label}`);
      for (const [key, entry] of Object.entries(item)) visit(readableLabel(key), entry, `${indent}  `);
    } else {
      const text = item === null ? "None" : typeof item === "boolean" ? item ? "Yes" : "No" : String(item);
      const [first = "", ...rest] = text.split("\n");
      lines.push(`${indent}${label} ${first}`);
      lines.push(...rest.map((line) => `${indent}  ${line}`));
    }
  }
  for (const [key, item] of Object.entries(value)) visit(`${readableLabel(key)}:`, item, "");
  return lines.flatMap((line) => textLines(line, width));
}

function readableLabel(key: string): string {
  const label = key.replace(/[_-]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2");
  return label ? label[0]!.toUpperCase() + label.slice(1) : "Value";
}
