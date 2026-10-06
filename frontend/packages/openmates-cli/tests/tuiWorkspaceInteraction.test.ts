// contract-test-file: infrastructure
/** Synthetic TUI interaction coverage. No real terminal, account, or network. */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import type { DecryptedUserTask } from "../src/tasksCli.js";
import { loadHomeData } from "../src/tuiHome.js";
import { runTui } from "../src/tui.js";
import { createInitialTuiState } from "../src/tuiRenderer.js";
import { handleWorkspaceKey, handleWorkspaceCommand, openSavedChat, type WorkspaceContext } from "../src/tuiWorkspaceController.js";

test("public example embed cards open from their bundled content without an account fetch", async () => {
  const state = createInitialTuiState();
  state.activeExample = {embeds:[{embed_id:"example-embed",type:"app_skill_use",content:"app_id: web\nskill_id: search\nquery: Cargo planes\nstatus: finished",parent_embed_id:null,embed_ids:null}]} as typeof state.activeExample;
  let fetched = false;
  const context = {state,client:{getEmbed:async()=>{fetched=true;throw new Error("public embed must use bundled content");}},render:()=>{},terminal:{},command:async()=>{},send:async()=>{}} as unknown as WorkspaceContext;
  await handleWorkspaceCommand(context,"/embed example-embed");
  assert.equal(fetched,false);
  assert.equal(state.detailTitle,"web/search");
  assert.match(state.detailLines.join("\n"),/Cargo planes/);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("guest replies update category header and mate without a saved-account lookup", async () => {
  const terminal = new FakeTerminal();
  const {client} = fakeClient({hasSession:()=>false, sendAnonymousMessage:async()=>({chatId:"guest-chat",assistant:"Guest answer",category:"software_development",mateName:"Ada",followUpSuggestions:["Next?"]})});
  const run=runTui(client as never,terminal as never);
  await tick(); terminal.type("A guest question"); terminal.enterKey(); await tick();
  assert.match(terminal.latest(),/Software Development/); assert.match(terminal.latest(),/Guest answer/); assert.match(terminal.latest(),/Ada/);
  terminal.press("\u0003",{ctrl:true,name:"c"}); await run;
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("session loss clears decrypted chat state before the next frame", async () => {
  const terminal=new FakeTerminal();let signedIn=true;
  const {client}=fakeClient({hasSession:()=>signedIn,getChatMessages:async()=>({chat:chat("saved","Private title"),messages:[{role:"user",content:"Private content",senderName:"You",embedIds:[]}]})});
  const run=runTui(client as never,terminal as never);
  await tick();terminal.type("/chat saved");terminal.enterKey();await tick();assert.match(terminal.latest(),/Private title/);
  signedIn=false;terminal.press("\u0002",{ctrl:true,name:"b"});await tick();
  assert.doesNotMatch(terminal.latest(),/Private title|Private content/);
  assert.match(terminal.latest(),/Session ended/);
  terminal.press("\u0003",{ctrl:true,name:"c"});await run;
});

class FakeTerminal {
  width = 110;
  height = 30;
  colorMode = "none" as const;
  ascii = true;
  frames: string[] = [];
  handler: ((chunk: string, key: Record<string, unknown>) => void) | null = null;
  enter() {}
  leave() {}
  onResize() {}
  render(frame: string) { this.frames.push(frame); }
  onKey(handler: (chunk: string, key: Record<string, unknown>) => void) { this.handler = handler; }
  async suspend<T>(run: () => Promise<T>): Promise<T> { return run(); }
  press(chunk: string, key: Record<string, unknown> = {}) { this.handler?.(chunk, key); }
  type(value: string) { for (const char of value) this.press(char, {name: char}); }
  enterKey() { this.press("\r", {name: "return"}); }
  latest() { return this.frames.at(-1) ?? ""; }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {resolve = done;});
  return {promise, resolve};
}
const tick = () => new Promise<void>((done) => setTimeout(done, 30));
const chat = (id: string, title = "Saved chat") => ({id, shortId: id, slug: id, title, summary: "Summary", category: "software_development", mateName: null, createdAt: Math.floor(Date.now()/1000), updatedAt: null});

function fakeClient(overrides: Record<string, unknown> = {}) {
  const calls: Array<Record<string, unknown>> = [];
  const client = {
    hasSession: () => true,
    beginInteractiveViewerSession: () => {},
    endInteractiveViewerSession: () => {},
    clearInteractiveChatViewer: () => {},
    setInteractiveChatViewer: async (_id: string) => {},
    sendMessage: async (params: Record<string, unknown>) => {
      calls.push(params);
      return {chatId: String(params.chatId ?? params.newChatId), assistant: "Response", followUpSuggestions: []};
    },
    getChatMetadata: async (id: string) => chat(id, "Named chat"),
    getChatMessages: async (id: string) => ({chat: chat(id), messages: [{role:"user", content:"Saved message", senderName:"User", embedIds:[]}]}),
    getDraft: async () => null,
    listUserTasks: async () => [],
    getMasterKeyBytes: () => new Uint8Array(32),
    ...overrides,
  };
  return {client, calls};
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("chat viewer presence starts with the TUI and clears on workspace navigation and exit", async () => {
  const terminal = new FakeTerminal();
  const events: string[] = [];
  const {client, calls} = fakeClient({
    beginInteractiveViewerSession: () => events.push("begin"),
    endInteractiveViewerSession: () => events.push("end"),
    clearInteractiveChatViewer: () => events.push("clear"),
    setInteractiveChatViewer: async (id: string) => { events.push(`view:${id}`); },
  });
  const run = runTui(client as never, terminal as never);
  await tick();
  assert.equal(events[0], "begin");
  terminal.type("A question"); terminal.enterKey(); await tick();
  const id = String(calls[0].newChatId);
  assert.equal(calls[0].interactiveHuman, true);
  assert.ok(events.includes(`view:${id}`));
  const navigationStart = events.length;
  terminal.type("/tasks"); terminal.enterKey(); await tick();
  assert.ok(events.slice(navigationStart).includes("clear"));
  terminal.press("\u0003", {ctrl:true,name:"c"}); await run;
  assert.equal(events.at(-1), "end");
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("a reply finishing after workspace navigation does not restore the old chat viewer", async () => {
  const terminal = new FakeTerminal();
  const reply = deferred<{chatId:string;assistant:string;followUpSuggestions:string[]}>();
  const viewers: string[] = [];
  const {client} = fakeClient({
    sendMessage: () => reply.promise,
    setInteractiveChatViewer: async (id: string) => { viewers.push(id); },
  });
  const run = runTui(client as never, terminal as never);
  await tick(); terminal.type("A question"); terminal.enterKey(); await tick();
  terminal.type("/tasks"); terminal.enterKey(); await tick();
  reply.resolve({chatId:"old-chat",assistant:"Late reply",followUpSuggestions:[]});
  await tick();
  assert.deepEqual(viewers, []);
  terminal.press("\u0003", {ctrl:true,name:"c"}); await run;
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("completed first send releases the header before metadata; second send reuses chat ID", async () => {
  const terminal = new FakeTerminal();
  const metadata = deferred<ReturnType<typeof chat>>();
  const {client, calls} = fakeClient({getChatMetadata: () => metadata.promise});
  const run = runTui(client as never, terminal as never);
  await tick();
  terminal.type("First question"); terminal.enterKey();
  await tick();
  assert.match(terminal.latest(), /Response/);
  assert.doesNotMatch(terminal.latest(), /Creating new chat|is typing/);
  assert.equal(calls.length, 1);
  const id = String(calls[0].newChatId);
  assert.ok(id);
  metadata.resolve(chat(id, "Named chat"));
  await tick();
  assert.match(terminal.latest(), /Named chat/);
  terminal.type("Follow up"); terminal.enterKey();
  await tick();
  assert.equal(calls.length, 2);
  assert.equal(calls[1].chatId, id);
  assert.equal(calls[1].newChatId, undefined);
  terminal.press("\u0003", {ctrl:true,name:"c"});
  await run;
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("draft survives Ctrl+P Tasks and Ctrl+N returns to the new chat draft", async () => {
  const terminal = new FakeTerminal();
  const {client, calls} = fakeClient();
  const run = runTui(client as never, terminal as never);
  await tick();
  terminal.type("unsent draft");
  terminal.press("\u0010", {ctrl:true,name:"p"});
  await tick();
  terminal.type("Tasks"); terminal.enterKey();
  await tick();
  assert.match(terminal.latest(), /Tasks/);
  terminal.press("\u000e", {ctrl:true,name:"n"});
  await tick();
  assert.match(terminal.latest(), /unsent draft/);
  assert.equal(calls.length, 0);
  terminal.press("\u0003", {ctrl:true,name:"c"});
  await run;
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("Unicode cursor edits one grapheme and multiline paste does not send", async () => {
  const terminal = new FakeTerminal();
  const {client, calls} = fakeClient();
  const run = runTui(client as never, terminal as never);
  await tick();
  terminal.type("A🧪B");
  terminal.press("", {name:"left"});
  terminal.press("", {name:"backspace"});
  terminal.press("漢\n字", {name:"paste"});
  await tick();
  assert.equal(calls.length, 0);
  assert.match(terminal.latest(), /A漢/);
  assert.match(terminal.latest(), /字B/);
  terminal.enterKey();
  await tick();
  assert.equal(calls[0].message, "A漢\n字B");
  terminal.press("\u0003", {ctrl:true,name:"c"});
  await run;
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("/chat reopens saved content and late fetch cannot replace Ctrl+N new chat", async () => {
  const terminal = new FakeTerminal();
  const late = deferred<{chat: ReturnType<typeof chat>; messages: Array<{role:string;content:string;senderName:string;embedIds:string[]}>}>();
  const {client} = fakeClient({getChatMessages: (id: string) => id === "slow" ? late.promise : Promise.resolve({chat:chat(id),messages:[{role:"user",content:"Saved message",senderName:"User",embedIds:[]}]})});
  const run = runTui(client as never, terminal as never);
  await tick();
  terminal.type("/chat old"); terminal.enterKey();
  await tick();
  assert.match(terminal.latest(), /Saved message/);
  terminal.press("\u000e", {ctrl:true,name:"n"});
  await tick();
  terminal.type("/chat slow"); terminal.enterKey();
  await tick();
  terminal.press("\u000e", {ctrl:true,name:"n"});
  late.resolve({chat:chat("slow", "Late stale chat"),messages:[{role:"user",content:"Late stale message",senderName:"User",embedIds:[]}]});
  await tick();
  assert.doesNotMatch(terminal.latest(), /Late stale chat|Late stale message/);
  assert.match(terminal.latest(), /Ask anything/);
  terminal.press("\u0003", {ctrl:true,name:"c"});
  await run;
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chat-navigation.draft-only.addressable
test("a short chat ID keeps early history, final history and its saved draft", async () => {
  const state=createInitialTuiState(),id=randomUUID(),shortId=id.slice(0,8);
  const final=deferred<{chat:ReturnType<typeof chat>;messages:Array<{role:string;content:string;senderName:string;embedIds:string[]}>}>();
  const draft=deferred<{markdown:string}>();
  const {client}=fakeClient({
    getChatMessages:async(query:string,options:{onMessages:(result:unknown)=>void})=>{
      assert.equal(query,shortId);
      options.onMessages({chat:chat(id,"Early title"),messages:[{role:"user",content:"Early history",senderName:"User",embedIds:[]}]});
      return final.promise;
    },
    getCachedDraft:async(query:string)=>{assert.equal(query,id);return draft.promise;},
  });
  const context={state,client,render:()=>{},terminal:{},command:async()=>{},send:async()=>{}} as unknown as WorkspaceContext;
  const opening=openSavedChat(context,shortId);
  assert.equal(state.activeChatId,id);assert.equal(state.messages[0]?.content,"Early history");
  final.resolve({chat:chat(id,"Final title"),messages:[{role:"user",content:"Final history",senderName:"User",embedIds:[]}]});
  await opening;
  assert.equal(state.activeChat?.title,"Final title");assert.equal(state.messages[0]?.content,"Final history");
  assert.equal(state.status,null);
  draft.resolve({markdown:"Saved short-ID draft"});await tick();
  assert.equal(state.input,"Saved short-ID draft");
});

// contract-test: supporting surface=cli assertions=chat-navigation.draft-only.addressable,cli.surface.semantic-parity
test("/chat opens an uncached draft-only UUID with its saved composer text", async () => {
  const terminal = new FakeTerminal(), id = randomUUID(), markdown = "TUI saved recovery draft";
  let draftFetched = false, historyReads = 0;
  const {client,calls} = fakeClient({
    getChatMessages: async (query:string,options:{preferCache?:boolean}) => {
      assert.equal(query,id);historyReads++;
      if (!options.preferCache || !draftFetched) throw new Error("Chat metadata failed with HTTP 404");
      return {chat:{...chat(id),title:null,summary:null,category:null,hasDraft:true},messages:[]};
    },
    getDraft: async (query:string,forceRefresh:boolean) => {
      assert.equal(query,id);assert.equal(forceRefresh,true);draftFetched=true;
      return {chatId:id,markdown};
    },
  });
  const run=runTui(client as never,terminal as never);
  try {
    await tick();terminal.type(`/chat ${id}`);terminal.enterKey();await tick();
    assert.equal(historyReads,2);assert.match(terminal.latest(),/TUI saved recovery draft/);
    assert.doesNotMatch(terminal.latest(),/Could not load chat|Loading chat/);
    terminal.enterKey();await tick();
    assert.equal(calls[0].chatId,id);assert.equal(calls[0].message,markdown);
  } finally {terminal.press("\u0003",{ctrl:true,name:"c"});await run;}
});

// contract-test: supporting surface=cli assertions=chat-navigation.draft-only.addressable,cli.output.actionable-readable
test("/chat keeps a missing UUID as an error when no owned draft exists", async () => {
  const terminal=new FakeTerminal(),id=randomUUID();let draftReads=0;
  const {client}=fakeClient({
    getChatMessages:async()=>{throw new Error("Chat metadata failed with HTTP 404");},
    getDraft:async()=>{draftReads++;return null;},
  });
  const run=runTui(client as never,terminal as never);
  try {
    await tick();terminal.type(`/chat ${id}`);terminal.enterKey();await tick();
    assert.equal(draftReads,1);assert.match(terminal.latest(),/Could not load chat/);
    assert.match(terminal.latest(),/Chat metadata failed with HTTP 404/);
  } finally {terminal.press("\u0003",{ctrl:true,name:"c"});await run;}
});

// contract-test: supporting surface=cli assertions=chat-navigation.draft-only.addressable,cli.output.actionable-readable
test("a messages HTTP 404 cannot be relabeled as a draft-only chat", async () => {
  const state=createInitialTuiState(),id=randomUUID();let draftReads=0;
  const {client}=fakeClient({
    getChatMessages:async()=>{throw new Error("Chat messages failed with HTTP 404");},
    getDraft:async()=>{draftReads++;return {chatId:id,markdown:"Unrelated draft"};},
  });
  const context={state,client,render:()=>{},terminal:{},command:async()=>{},send:async()=>{}} as unknown as WorkspaceContext;
  await openSavedChat(context,id);
  assert.equal(draftReads,0);assert.equal(state.headerState,"error");
  assert.match(state.status!,/Chat messages failed with HTTP 404/);
});

// contract-test: supporting surface=cli assertions=chat-navigation.draft-only.addressable,cli.surface.semantic-parity
test("late draft recovery cannot publish after its owning account changes", async () => {
  const state=createInitialTuiState(),id=randomUUID(),pending=deferred<{chatId:string;markdown:string}>();
  let account="first",historyReads=0;
  const {client}=fakeClient({
    apiUrl:"https://other.example",
    getSession:()=>({apiUrl:"https://owner.example",hashedEmail:account,activeTeamId:null,createdAt:1,masterKeyExportedB64:"key"}),
    getChatMessages:async()=>{historyReads++;throw new Error("Chat metadata failed with HTTP 404");},
    getDraft:async()=>pending.promise,
  });
  const context={state,client,render:()=>{},terminal:{},command:async()=>{},send:async()=>{}} as unknown as WorkspaceContext;
  const opening=openSavedChat(context,id);
  await tick();account="second";pending.resolve({chatId:id,markdown:"Previous account draft"});await opening;
  assert.equal(historyReads,1);assert.equal(state.input,"");assert.equal(state.activeChat,null);
});

function task(id: string, position: number): DecryptedUserTask {
  return {taskId:id,shortId:`TASK-${id}`,slug:id,title:`Task ${id}`,description:"",labels:[],tags:[],latestInstruction:"",status:"todo",assigneeType:"user",assigneeIdentity:null,assigneeHash:null,primaryChatId:null,externalChat:null,linkedProjectIds:[],planId:null,dueAt:null,priority:0,priorityLevel:"none",position,queueState:"none",blockedReasonCode:null,blockedReason:"",aiExecutionState:null,version:1,encrypted:{} as DecryptedUserTask["encrypted"]};
}

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.surface.semantic-parity
test("Tasks select A, Escape, then select B opens edit and delete forms bound to B", async () => {
  const state = createInitialTuiState();
  state.workspace="tasks";state.screen="tasks";state.focus="content";state.tasks=[task("a",1),task("b",2)];
  const context: WorkspaceContext = {state,client:{getUserTask:async()=>null,getMasterKeyBytes:()=>new Uint8Array(32)} as never,terminal:{} as never,render:()=>{},command:async()=>{},send:async()=>{}};
  await handleWorkspaceKey(context,"",{name:"return"});
  assert.equal(state.activeTask?.taskId,"a");
  await handleWorkspaceKey(context,"",{name:"escape"});
  await handleWorkspaceKey(context,"",{name:"down"});
  await handleWorkspaceKey(context,"",{name:"return"});
  assert.equal(state.activeTask?.taskId,"b");
  await handleWorkspaceKey(context,"e",{name:"e"});
  assert.equal(state.form?.contextId,"b");
  await handleWorkspaceKey(context,"",{name:"escape"});
  await handleWorkspaceKey(context,"x",{name:"x"});
  assert.equal(state.form?.contextId,"b");
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("signed-out attachment failure keeps draft and never sends", async () => {
  const terminal = new FakeTerminal();
  let sends = 0;
  const {client} = fakeClient({hasSession:()=>false,sendAnonymousMessage:async()=>{sends++;return {assistant:"unexpected"};}});
  const run = runTui(client as never, terminal as never);
  await tick();
  terminal.type("Review @./missing.txt"); terminal.enterKey();
  await tick();
  assert.equal(sends,0);
  assert.match(terminal.latest(), /Review @\.\/missing\.txt/);
  assert.match(terminal.latest(), /signed-in account/);
  terminal.press("\u0003", {ctrl:true,name:"c"});
  await run;
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("ordinary detail views scroll down and immediately reverse at their bounds",async()=>{
  const terminal=new FakeTerminal();terminal.height=18;
  const {client}=fakeClient();const run=runTui(client as never,terminal as never);
  await tick();terminal.type("/help");terminal.enterKey();await tick();
  const top=terminal.latest().split("\n")[3];
  terminal.press("",{name:"down"});await tick();assert.notEqual(terminal.latest().split("\n")[3],top);
  terminal.press("",{name:"up"});await tick();assert.equal(terminal.latest().split("\n")[3],top);
  terminal.press("",{name:"end"});await tick();const end=terminal.latest();
  terminal.press("",{name:"up"});await tick();assert.notEqual(terminal.latest(),end);
  terminal.press("\u0003",{ctrl:true,name:"c"});await run;
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,projects.lifecycle.encrypted-crud
test('a slug-only project search opens the visible card and refresh preserves its Files folder and Tasks tab', async () => {
  const {createHash}=await import('node:crypto');const {encryptWithAesGcmCombined}=await import('../src/crypto.js');
  const {renderTuiFrame}=await import('../src/tuiRenderer.js');
  const key=new Uint8Array(32).fill(9),seal=(value:string)=>encryptWithAesGcmCombined(value,key);
  const record={project_id:'project',encrypted_name:await seal('Launch'),encrypted_slug:await seal('secret-slug'),encrypted_description:await seal('Description')};
  const client={getActiveTeamId:()=>null,getMasterKeyBytes:()=>key,getProject:async()=>({project:record}),decryptProjectKey:async()=>key,
    listProjectItems:async()=>({folders:[{folder_id:'docs',encrypted_name:await seal('Docs')},{folder_id:'nested',hashed_parent_folder_id:createHash('sha256').update('docs').digest('hex'),encrypted_name:await seal('Nested')}],items:[]}),
    listProjectSources:async()=>[],listUserTasks:async()=>[]};
  const state=createInitialTuiState();state.signedIn=true;state.workspace='projects';state.screen='projects';state.focus='content';state.filter='secret-slug';
  state.projects=[{id:'project',slug:'secret-slug',name:'Launch',description:'Description',items:[],files:[],folders:[],sources:[]}] as never;
  const ctx={state,client,terminal:{width:120},render:()=>{},send:async()=>{},command:async(command:string)=>{await handleWorkspaceCommand(ctx as unknown as WorkspaceContext,command);}} as unknown as WorkspaceContext;
  state.focus='composer';await handleWorkspaceCommand(ctx,'/search secret-slug');
  assert.equal(state.focus,'content');
  assert.match(renderTuiFrame(state,120,30),/› Launch/);
  assert.match(renderTuiFrame(state,120,30),/Project 1 of 1/);
  await handleWorkspaceKey(ctx,'\r',{name:'return'});assert.equal(state.activeProject?.id,'project');
  state.projectTab='files';state.projectFolderId='docs';state.filter='Nested';state.scrollOffset=2;
  await handleWorkspaceCommand(ctx,'/refresh');assert.equal(state.projectTab,'files');assert.equal(state.projectFolderId,'docs');assert.equal(state.filter,'Nested');assert.equal(state.scrollOffset,2);
  assert.deepEqual(state.projectFiles.map(f=>f.name),['Nested']);
  state.projectTab='tasks';await handleWorkspaceCommand(ctx,'/refresh');assert.equal(state.projectTab,'tasks');
});

// contract-test: supporting surface=cli assertions=cli.output.actionable-readable
// An HTTP failure and a later background sync failure must remain distinguishable.
test("opening a failed chat exits loading and background sync preserves its retry error", async () => {
  const state=createInitialTuiState();state.signedIn=true;state.recentChats=[chat('saved')];
  const {client}=fakeClient({getChatMessages:async()=>{throw new Error('Chat messages failed with HTTP 503');},listChats:async()=>{throw new Error('Sync unavailable');}});
  const context={state,client,render:()=>{},terminal:{},command:async()=>{},send:async()=>{}} as unknown as WorkspaceContext;
  await openSavedChat(context,'saved');
  assert.equal(state.headerState,'error');assert.equal(state.headerError,'Could not load chat');
  assert.match(state.status!,/HTTP 503.*\/refresh/);
  const message=state.status;await loadHomeData(state,client as never,()=>{});
  assert.equal(state.status,message);
});

test("a failed chat request finishing after Escape leaves the landing page intact", async () => {
  const state=createInitialTuiState();const pending=deferred<never>();
  const client={getChatMessages:async()=>pending.promise};
  const context={state,client,render:()=>{},terminal:{},command:async()=>{},send:async()=>{}} as unknown as WorkspaceContext;
  const opening=openSavedChat(context,'saved');
  await handleWorkspaceKey(context,'\x1b',{name:'escape'});
  // Resolve through a rejected promise without an unhandled rejection.
  pending.resolve(Promise.reject(new Error('HTTP 503')) as never);await opening;
  assert.equal(state.screen,'start');assert.equal(state.headerState,'new');assert.equal(state.status,null);
});
