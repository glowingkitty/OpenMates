// contract-test-file: infrastructure
import assert from "node:assert/strict";
import { test } from "node:test";
import { createInitialTuiState, renderTuiFrame } from "../src/tuiRenderer.js";
import { loadHomeData, workspaceInspirations, homeContinueItems, startHomeSync } from "../src/tuiHome.js";
import { handleWorkspaceCommand, handleWorkspaceKey, openSavedChat, type WorkspaceContext } from "../src/tuiWorkspaceController.js";
import { cells, lineText, sliceCells, stripAnsi } from "../src/tuiText.js";
import { renderCardCarousel } from "../src/tuiCarousel.js";
import { tuiChatSidebarRows } from "../src/tuiChatSidebar.js";
import type { ChatListItem } from "../src/client.js";
import type { TuiApp } from "../src/tuiAppsWorkspace.js";

function context(state=createInitialTuiState(),client:Record<string,unknown>={}) {
  const commands:string[]=[];
  const ctx={state,client,terminal:{width:120},render:()=>{},send:async()=>{},command:async(command:string)=>{commands.push(command);await handleWorkspaceCommand(ctx as WorkspaceContext,command);}} as unknown as WorkspaceContext;
  return {ctx,commands};
}
const inspiration={id:"daily",phrase:"Make room for the next idea",title:"A daily planning tip",category:"productivity",content_type:"feature",video:null,generated_at:1,assistant_response:"Plan one small action.",follow_up_suggestions:[]};
const chat=(i:number)=>({id:`chat-${i}`,shortId:`C${i}`,title:`Conversation ${i}`,summary:`Summary ${i}`,category:"technology",mateName:null,updatedAt:null});
const app=(id:string,name:string):TuiApp=>({id,name,description:`${name} description`,category:"general_knowledge",skills:[],focusModes:[],settingsMemories:[]});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chat-navigation.open.local-first-coherent
test("opening a cached chat renders messages before slow draft lookup and preserves new input", async () => {
  const state=createInitialTuiState();state.signedIn=true;
  let draft!:(value:{markdown:string})=>void;
  const {ctx}=context(state,{
    getChatMessages:async(_id:string,options:{preferCache:boolean})=>{
      assert.equal(options.preferCache,true);
      return {chat:chat(1),messages:[{id:'message',role:'user',content:'A cached message',embedIds:[]}]};
    },
    getDraft:()=>new Promise(done=>{draft=done;})
  });
  const frames:string[]=[];ctx.render=()=>frames.push(stripAnsi(renderTuiFrame(state,120,40)));
  await openSavedChat(ctx,'chat-1');
  assert.equal(state.activeChatId,'chat-1');assert.equal(state.status,null);
  assert.match(frames.at(-1)!,/A cached message/);
  assert.doesNotMatch(frames.at(-1)!,/Loading chat/);
  state.input='New text';draft({markdown:'Saved draft'});
  await new Promise<void>(done=>setImmediate(done));
  assert.equal(state.input,'New text');
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chat-navigation.open.local-first-coherent
test("startup renders cached chats before background sync and preserves the selected chat when sync finishes", async () => {
  const state=createInitialTuiState();state.signedIn=true;
  let sync!:(page:unknown)=>void, inspiration!:(list:unknown[])=>void;
  const frames:string[]=[],events:string[]=[];
  const client={
    listCachedChats:async()=>{events.push('cache');return {chats:[chat(1),chat(2)]};},
    listChats:(_limit:number,_page:number,options:{forceRefresh:boolean})=>{
      events.push('sync');assert.equal(options.forceRefresh,true);return new Promise(done=>{sync=done;});
    },
    getDailyInspirations:()=>new Promise(done=>{inspiration=done;})
  };
  const loading=loadHomeData(state,client as never,()=>frames.push(stripAnsi(renderTuiFrame(state,120,40))));
  await new Promise<void>(done=>setImmediate(done));
  assert.deepEqual(events,['cache','sync']);
  assert.equal(state.homeLoading,true);assert.equal(state.homeChatsLoading,false);
  assert.match(frames[0],/Continue where you left off/);assert.match(frames[0],/Conversation 1/);
  assert.doesNotMatch(frames[0],/Loading your recent chats/);
  const {ctx}=context(state,client);
  await handleWorkspaceKey(ctx,"",{ctrl:true,name:"b"});
  assert.equal(state.sidebarOpen,true);assert.equal(state.focus,'sidebar');
  await handleWorkspaceKey(ctx,"",{name:"down"});
  assert.equal(tuiChatSidebarRows(state)[state.sidebarIndex].chatId,'chat-1');
  await handleWorkspaceKey(ctx,"",{ctrl:true,name:"b"});
  await handleWorkspaceCommand(ctx,'/chats');
  assert.deepEqual(events,['cache','sync'],'Cached navigation must reuse the startup sync');
  state.selectedIndex=1;
  sync({chats:[chat(0),chat(1),chat(2)]});
  await new Promise<void>(done=>setImmediate(done));
  assert.equal(state.recentChats.length,3);assert.equal(state.selectedIndex,2);
  assert.equal(state.homeChatsLoading,false);
  inspiration([]);await loading;
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chat-navigation.open.local-first-coherent
test("cold startup shows verified synced previews while saved output recovery is still pending", async () => {
  const state=createInitialTuiState();state.signedIn=true;
  let finish!:(page:unknown)=>void;
  let publish!:(page:{chats:ReturnType<typeof chat>[]})=>void;
  const loading=loadHomeData(state,{
    listCachedChats:async()=>null,
    listChats:(_limit:number,_page:number,options:{onSyncedChats:typeof publish})=>{
      publish=options.onSyncedChats;return new Promise(done=>{finish=done;});
    }
  } as never,()=>{});
  await new Promise<void>(done=>setImmediate(done));
  assert.equal(state.homeChatsLoading,true);
  publish({chats:[chat(1)]});
  assert.equal(state.homeLoading,true);assert.equal(state.homeChatsLoading,false);
  const frame=stripAnsi(renderTuiFrame(state,120,40));
  assert.match(frame,/Conversation 1/);assert.doesNotMatch(frame,/Loading your recent chats/);
  const version=state.homeLoadVersion;
  Object.assign(state,createInitialTuiState(),{homeLoadVersion:version+1});
  publish({chats:[chat(2)]});assert.deepEqual(state.recentChats,[]);
  finish({chats:[chat(3)]});await loading;assert.deepEqual(state.recentChats,[]);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chat-navigation.open.local-first-coherent
test("failed sync keeps cached chats usable and a cold failure stops loading without waiting for inspiration", async () => {
  for(const cached of [[],[chat(1)]]) {
    const state=createInitialTuiState();state.signedIn=true;
    let inspiration!:(list:unknown[])=>void;
    const loading=loadHomeData(state,{
      listCachedChats:async()=>({chats:cached}),
      listChats:async()=>{throw new Error('offline');},
      getDailyInspirations:()=>new Promise(done=>{inspiration=done;})
    } as never,()=>{});
    await new Promise<void>(done=>setImmediate(done));
    assert.equal(state.homeLoading,true);assert.equal(state.homeChatsLoading,false);
    assert.deepEqual(state.recentChats,cached);
    const frame=stripAnsi(renderTuiFrame(state,120,40));
    assert.doesNotMatch(frame,/Loading your recent chats/);
    assert.match(frame,cached.length?/Conversation 1/:/Saved chats could not be synced/);
    inspiration([]);await loading;
  }
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chat-navigation.open.local-first-coherent
test("late cached home data cannot restore private chats after account reset", async () => {
  let cached!:(page:unknown)=>void,syncs=0;
  const state=createInitialTuiState();state.signedIn=true;
  const loading=loadHomeData(state,{
    listCachedChats:()=>new Promise(done=>{cached=done;}),
    listChats:async()=>{syncs++;return {chats:[]};}
  } as never,()=>{});
  Object.assign(state,createInitialTuiState(),{homeLoadVersion:state.homeLoadVersion+1});
  cached({chats:[chat(1)]});await loading;
  assert.deepEqual(state.recentChats,[]);assert.equal(syncs,0);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("authenticated default home loads inspiration username and horizontal keyboard-selected chats",async()=>{
  const state=createInitialTuiState();state.signedIn=true;
  await loadHomeData(state,{getDailyInspirations:async()=>[inspiration],whoAmI:async()=>({username:"Alex"}),listChats:async()=>({chats:[chat(1),chat(2),chat(3),chat(4)]})} as never,()=>{});
  const frame=stripAnsi(renderTuiFrame(state,120,40,{colorMode:"truecolor"}));
  assert.ok(frame.indexOf("DAILY INSPIRATION")<frame.indexOf("Hey Alex!"));
  assert.ok(frame.indexOf("Hey Alex!")<frame.indexOf("Continue where you left off"));
  const first=frame.split("\n").findIndex((line)=>line.includes("Conversation 1")),second=frame.split("\n").findIndex((line)=>line.includes("Conversation 2"));
  assert.ok(first>=0&&second===first);
  assert.match(frame,/› Conversation 1/);assert.match(frame,/Enter open/);
  assert.equal(state.sidebarOpen,false);
  const {ctx}=context(state,{getChatMessages:async(id:string)=>({chat:chat(Number(id.slice(5))),messages:[]})});
  for(let i=0;i<3;i++)await handleWorkspaceKey(ctx,"",{name:"right"});
  assert.equal(state.selectedIndex,3);
  assert.match(renderTuiFrame(state,120,24),/› Conversation 4/);
  await handleWorkspaceKey(ctx,"\r",{name:"return"});assert.equal(state.activeChatId,"chat-4");
});

test("late home data cannot repopulate decrypted state after account reset",async()=>{
  let resolve!:(value:{username:string})=>void;
  const pending=new Promise<{username:string}>((done)=>{resolve=done;});
  const state=createInitialTuiState();state.signedIn=true;
  const loading=loadHomeData(state,{whoAmI:()=>pending} as never,()=>{});
  Object.assign(state,createInitialTuiState(),{homeLoadVersion:state.homeLoadVersion+1});
  resolve({username:"Private name"});await loading;
  assert.equal(state.username,null);assert.equal(state.signedIn,false);
});

test("every workspace has shared colored inspiration and Apps shows web headings without a composer",()=>{
  for(const workspace of ["chats","projects","workflows","tasks","apps"] as const){
    const state=createInitialTuiState();state.workspace=workspace;state.screen=workspace;state.focus="content";
    state.inspirations=[inspiration];state.apps=[app("web","Web")];
    if(workspace!=="chats")assert.ok(workspaceInspirations(state).length);
    const frame=renderTuiFrame(state,120,32,{colorMode:"truecolor"});
    assert.match(stripAnsi(frame),/DAILY INSPIRATION/);assert.ok(frame.includes("\x1b[48;2;"));
    if(workspace==="apps"){assert.match(stripAnsi(frame),/What app do you want to use/);assert.doesNotMatch(stripAnsi(frame),/Hey there!|> Search apps/);}
    else assert.match(stripAnsi(frame),/Hey there!/);
  }
});

test("filtered app highlight and Enter target agree, and returning to Overview cannot open stale history",async()=>{
  const state=createInitialTuiState();state.workspace="apps";state.screen="apps";state.focus="content";state.apps=[app("web","Web"),app("weather","Weather")];state.filter="Weather";
  assert.match(renderTuiFrame(state,100,30),/› Weather/);
  const {ctx}=context(state);await handleWorkspaceKey(ctx,"\r",{name:"return"});assert.equal(state.activeApp?.id,"weather");
  state.screen="app-skill";state.appTab="embeds";state.appSkillTab="embeds";state.activeAppSkill={appId:"weather",skillId:"forecast",name:"Forecast",description:"",schema:{type:"object",properties:{}},defaults:{},primaryFields:[],providers:[],pricing:null,executionAvailable:true,unavailableReason:null};
  await handleWorkspaceKey(ctx,"1",{name:"1"});await handleWorkspaceKey(ctx,"\r",{name:"return"});assert.equal(state.form?.kind,"app-skill-input");
});

test("overlapping result requests keep the latest selected Apps page",async()=>{
  const resolvers:Array<(data:unknown)=>void>=[];
  const state=createInitialTuiState();state.signedIn=true;state.workspace="apps";state.screen="app";state.activeApp=app("web","Web");
  const {ctx}=context(state,{hasSession:()=>true,getActiveTeamId:()=>null,listAppsWorkspaceResults:()=>new Promise((resolve)=>resolvers.push(resolve))});
  const first=handleWorkspaceCommand(ctx,"/app-results 0"),second=handleWorkspaceCommand(ctx,"/app-results 20");
  resolvers[1]({items:[],has_more:false});await second;resolvers[0]({items:[],has_more:false});await first;
  assert.equal(state.appResults.offset,20);
});

test("switching away while Apps history loads keeps the newer tab and result scrolling works",async()=>{
  let resolve!:(value:unknown)=>void;
  const state=createInitialTuiState();state.workspace="apps";state.screen="app";state.focus="content";state.activeApp=app("web","Web");
  const {ctx}=context(state,{getActiveTeamId:()=>null,listAppsWorkspaceResults:()=>new Promise((done)=>{resolve=done;})});
  const loading=handleWorkspaceKey(ctx,"4",{name:"4"});await handleWorkspaceKey(ctx,"1",{name:"1"});resolve({items:[],has_more:false});await loading;
  assert.equal(state.appTab,"skills");
  state.screen="app-result";await handleWorkspaceKey(ctx,"",{name:"down"});assert.equal(state.scrollOffset,1);await handleWorkspaceKey(ctx,"",{name:"up"});assert.equal(state.scrollOffset,0);
});

test("Apps inspiration routes parse the actual web skill and catalog paths",async()=>{
  const state=createInitialTuiState();state.workspace="apps";state.screen="apps";
  const commands:string[]=[];const ctx={state,client:{},terminal:{},render:()=>{},send:async()=>{},command:async(command:string)=>{commands.push(command);}} as unknown as WorkspaceContext;
  for(const [path,target] of [["apps/events/skill/search","/app-skill events/search"],["apps/web/search","/app-skill web/search"],["apps/all/focus_modes","/apps"]]){
    state.inspirations=[{...inspiration,surface:"apps",feature:{feature_id:"feature",title:"Title",description:"",settings_path:path}}];
    await handleWorkspaceCommand(ctx,"/inspiration");assert.equal(commands.at(-1),target);
  }
});

test("a late Project Tasks fetch cannot replace the next Project's task state",async()=>{
  let resolve!:(value:[])=>void;
  const state=createInitialTuiState();state.workspace="projects";state.screen="project";state.focus="content";state.activeProject={id:"a"} as never;
  const sentinel={taskId:"task-b"};
  const {ctx}=context(state,{listUserTasks:()=>new Promise((done)=>{resolve=done;}),getMasterKeyBytes:()=>new Uint8Array(32)});
  const loading=handleWorkspaceKey(ctx,"3",{name:"3"});state.routeVersion++;state.activeProject={id:"b"} as never;state.tasks=[sentinel] as never;resolve([]);await loading;
  assert.equal(state.tasks[0].taskId,"task-b");
});

test("home input opens Project Task and Workflow creation forms instead of filtering",async()=>{
  for(const [workspace,kind,field] of [["projects","project-create","name"],["tasks","task-create","title"],["workflows","workflow-create","description"]] as const){
    const state=createInitialTuiState();state.workspace=workspace;state.screen=workspace;state.focus="composer";state.input="A concrete outcome";
    const {ctx}=context(state);await handleWorkspaceKey(ctx,"\r",{name:"return"});
    assert.equal(state.form?.kind,kind);assert.equal(state.form?.fields.find((f)=>f.name===field)?.value,"A concrete outcome");assert.equal(state.filter,"");
  }
});

test("inspiration focus can cycle and prepare a chat without calling inference",async()=>{
  const state=createInitialTuiState();state.inspirations=[inspiration,{...inspiration,id:"second",phrase:"A different prompt"}];
  const {ctx}=context(state);await handleWorkspaceKey(ctx,"\u000f",{ctrl:true,name:"o"});assert.equal(state.focus,"inspiration");
  await handleWorkspaceKey(ctx,"",{name:"right"});await handleWorkspaceKey(ctx,"\r",{name:"return"});
  assert.equal(state.input,"A different prompt");assert.equal(state.activeChatId,null);assert.deepEqual(state.messages,[]);
});

test("workspace homes retain exact cell geometry with colors Unicode and a sidebar",()=>{
  for(const workspace of ["chats","apps","projects","workflows","tasks"] as const)for(const width of [1,4,24,73,120])for(const sidebar of [false,true]){
    const state=createInitialTuiState();state.workspace=workspace;state.screen=workspace;state.sidebarOpen=sidebar;state.signedIn=true;state.username="漢字 🧪";state.recentChats=[{...chat(1),title:"確認 🧪"}];state.apps=[app("web","漢字 🧪")];
    const rows=renderTuiFrame(state,width,28,{colorMode:"truecolor"}).split("\n");
    assert.equal(rows.length,28);assert.ok(rows.every((row)=>cells(row)===width),`${workspace} width=${width} sidebar=${sidebar}: ${rows.map(cells)}`);
  }
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("carousel bounds, filtering, draft cursor and viewport resizing preserve the chosen chat",async()=>{
  const state=createInitialTuiState();state.signedIn=true;state.recentChats=Array.from({length:8},(_,i)=>({...chat(i),title:`確認 🧪 Conversation ${i}`}));
  const {ctx}=context(state);
  for(let i=0;i<20;i++)await handleWorkspaceKey(ctx,"",{name:"right"});assert.equal(state.selectedIndex,7);
  for(const width of [24,73,120]){
    const frame=renderTuiFrame(state,width,32,{colorMode:"truecolor"});
    assert.ok(frame.split("\n").every((row)=>cells(row)===width));
    assert.match(stripAnsi(frame),width===24?/Conver[\s\S]*sation 7/:/Conversation 7/);assert.match(stripAnsi(frame),/Chat 8 of 8/);
  }
  await handleWorkspaceKey(ctx,"",{name:"tab"});assert.equal(state.focus,"composer");
  await handleWorkspaceKey(ctx,"draft",{name:"paste"});
  await handleWorkspaceKey(ctx,"",{name:"left"});assert.equal(state.inputCursor,4);assert.equal(state.selectedIndex,7);
  await handleWorkspaceKey(ctx,"",{name:"tab",shift:true});assert.equal(state.focus,"content");
  for(let i=0;i<20;i++)await handleWorkspaceKey(ctx,"",{name:"left"});assert.equal(state.selectedIndex,0);assert.equal(state.input,"draft");
  await handleWorkspaceCommand(ctx,"/search Conversation 5");
  assert.match(renderTuiFrame(state,120,32),/› 確認 🧪 Conversation 5/);assert.equal(state.selectedIndex,0);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("home arrow scrolling and mouse wheel never change the selected chat or draft",async()=>{
  const state=createInitialTuiState();state.signedIn=true;state.recentChats=[chat(1),chat(2)];state.input="Kept draft";
  const {ctx}=context(state);ctx.terminal.height=18;
  for(let i=0;i<30;i++){await handleWorkspaceKey(ctx,"",{name:"down"});renderTuiFrame(state,80,18);}
  const bottom=state.scrollOffset;assert.ok(bottom>0);
  await handleWorkspaceKey(ctx,"",{name:"up"});renderTuiFrame(state,80,18);assert.equal(state.scrollOffset,bottom-1);
  await handleWorkspaceKey(ctx,"",{name:"scrollup"});renderTuiFrame(state,80,18);assert.equal(state.scrollOffset,Math.max(0,bottom-4));
  assert.equal(state.selectedIndex,0);assert.equal(state.input,"Kept draft");
  await handleWorkspaceKey(ctx,"",{name:"home"});renderTuiFrame(state,80,18);assert.equal(state.scrollOffset,0);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("centered carousel preserves the selected card across bounds Unicode and resizing",()=>{
  const cards=Array.from({length:8},(_,i)=>({title:`確認 🧪 ${i}`,description:"A wrapped description",footer:"Chat",background:"#4867cd"}));
  for(const width of [1,4,24,73,120,160])for(const selected of [0,3,7]){
    const rows=renderCardCarousel(cards,width,selected,true);
    assert.ok(rows.every((row)=>cells(lineText(row))===width));
    const spans=typeof rows[0]==="string"?[]:rows[0].spans!;
    const active=spans.findIndex((span)=>span.bold);
    assert.ok(active>=0);
    assert.equal(spans.slice(0,active).reduce((n,span)=>n+cells(span.text),0),Math.floor((width-Math.min(width,36))/2));
    assert.equal(cells(spans[active].text),Math.min(width,36));
  }
  assert.equal(sliceCells("a漢🧪z",2,4)," 🧪z");
  assert.equal(sliceCells("a漢🧪z",1,3),"漢 ");
  assert.equal(sliceCells("\x1b[31mA\x1b[0m",0,3),"A  ");
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,apps.discovery.public-catalog
test("Apps uses centered horizontal selection Enter filtering and Show all with bounded scrolling",async()=>{
  const state=createInitialTuiState();state.workspace="apps";state.screen="apps";state.focus="content";
  state.apps=Array.from({length:8},(_,i)=>app(`app${i}`,`App ${i}`));
  const {ctx}=context(state);ctx.terminal.height=18;
  for(let i=0;i<12;i++)await handleWorkspaceKey(ctx,"",{name:"right"});
  assert.equal(state.selectedIndex,5);
  assert.match(stripAnsi(renderTuiFrame(state,120,32)),/› App 5[\s\S]*App 6 of 6/);
  await handleWorkspaceCommand(ctx,"/browse");
  for(let i=0;i<12;i++)await handleWorkspaceKey(ctx,"",{name:"right"});
  assert.equal(state.selectedIndex,7);
  for(const width of [24,73,120]){
    const frame=stripAnsi(renderTuiFrame(state,width,32));
    assert.match(frame,/App 8 of 8/);assert.ok(frame.split("\n").every((row)=>cells(row)===width));
  }
  state.input="Kept draft";
  for(let i=0;i<30;i++){await handleWorkspaceKey(ctx,"",{name:"down"});renderTuiFrame(state,80,18);}
  const bottom=state.scrollOffset;assert.ok(bottom>0);
  await handleWorkspaceKey(ctx,"",{name:"up"});renderTuiFrame(state,80,18);assert.equal(state.scrollOffset,bottom-1);
  assert.equal(state.selectedIndex,7);assert.equal(state.input,"Kept draft");
  await handleWorkspaceKey(ctx,"",{name:"home"});renderTuiFrame(state,80,18);assert.equal(state.scrollOffset,0);
  state.input="";await handleWorkspaceKey(ctx,"\r",{name:"return"});assert.equal(state.activeApp?.id,"app7");
  state.screen="apps";state.focus="content";state.activeApp=null;
  state.apps=Array.from({length:8},(_,i)=>app(`app${i}`,`App ${i}`));
  await handleWorkspaceCommand(ctx,"/search App 2");
  assert.match(stripAnsi(renderTuiFrame(state,120,32)),/› App 2[\s\S]*App 1 of 1/);
  await handleWorkspaceKey(ctx,"\r",{name:"return"});assert.equal(state.activeApp?.id,"app2");
});

// contract-test: supporting surface=cli assertions=chat-navigation.projects.nested-readable,chat-navigation.order.sidebar-header-match
test('startup loads encrypted project folders and the complete cached chat history with the sidebar closed', async () => {
  const {encryptWithAesGcmCombined}=await import('../src/crypto.js');
  const key=new Uint8Array(32).fill(7),state=createInitialTuiState();state.signedIn=true;
  const record={project_id:'project',encrypted_name:await encryptWithAesGcmCombined('Launch',key)};
  let limit=0, sourceReads=0;
  await loadHomeData(state,{
    getActiveTeamId:()=>null,getMasterKeyBytes:()=>key,
    listChats:async(n:number)=>{limit=n;return {chats:Array.from({length:65},(_,i)=>chat(i))};},
    listProjects:async()=>[record],getProject:async()=>({project:record}),decryptProjectKey:async()=>key,
    listProjectItems:async()=>({folders:[{folder_id:'docs',encrypted_name:await encryptWithAesGcmCombined('Docs',key)}],items:[]}),
    listProjectSources:async()=>{sourceReads++;return [];},getSidebarChats:async()=>[],
  } as never,()=>{});
  assert.ok(limit>=65);assert.equal(state.recentChats.length,65);assert.equal(state.sidebarOpen,false);
  assert.equal(state.chatSidebarProjects[0].name,'Launch');assert.equal(state.chatSidebarProjects[0].folders[0].name,'Docs');assert.equal(sourceReads,0);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chat-navigation.projects.nested-readable
test('sidebar wheel page and edge navigation skip headings and preserve main scroll on wide and narrow terminals', async () => {
  const {tuiChatSidebarRows}=await import('../src/tuiChatSidebar.js');
  for(const width of [72,120]){
    const state=createInitialTuiState();state.signedIn=true;state.sidebarOpen=true;state.focus='sidebar';state.scrollOffset=4;state.screen='chat';state.messages=Array.from({length:40},(_,i)=>({role:'assistant' as const,content:`Message ${i}`}));
    state.recentChats=Array.from({length:65},(_,i)=>({...chat(i),updatedAt:Math.floor(Date.now()/1000)-i}));
    const {ctx}=context(state);ctx.terminal.width=width;
    await handleWorkspaceKey(ctx,'',{name:'scrolldown'});
    assert.equal(tuiChatSidebarRows(state)[state.sidebarIndex].chatId,'chat-2');assert.equal(state.scrollOffset,4);
    await handleWorkspaceKey(ctx,'',{name:'end'});
    assert.equal(tuiChatSidebarRows(state)[state.sidebarIndex].chatId,'chat-64');
    assert.match(renderTuiFrame(state,width,24),/> Conversation 64/);assert.equal(state.scrollOffset,4);
    await handleWorkspaceKey(ctx,'',{name:'pageup'});assert.notEqual(tuiChatSidebarRows(state)[state.sidebarIndex].chatId,'chat-64');
    await handleWorkspaceKey(ctx,'',{name:'home'});assert.equal(tuiChatSidebarRows(state)[state.sidebarIndex].kind,'new');
    await handleWorkspaceKey(ctx,'',{name:'down'});assert.equal(tuiChatSidebarRows(state)[state.sidebarIndex].chatId,'chat-0');
  }
});

// contract-test: supporting surface=cli assertions=continue-carousel.saved-item.start-time-gated,continue-carousel.chat.reminder-gated,cli.surface.semantic-parity
test("remembered items and due chats precede recents while dated embeds obey the web time gate",()=>{
  const state=createInitialTuiState(),now=Date.now();state.signedIn=true;state.recentChats=[chat(1),chat(2)];
  const memory=(id:string,hours:number)=>({id,app_id:'events',item_type:'saved_events',item_key_hash:'key',item_version:1,created_at:1,updated_at:1,
    data:{embed_id:id,title:id,date_start:new Date(now+hours*3600000).toISOString()}});
  state.continueData={memories:[memory('Soon event',23),memory('Too early event',46)],reminders:[
    {reminder_id:'early',trigger_at:(now+2*3600000)/1000,target_type:'embed',target_embed_id:'Too early event',status:'pending'},
    {reminder_id:'chat',trigger_at:(now-60000)/1000,target_type:'chat',target_chat_id:'chat-2',status:'pending'},
  ]};
  const items=homeContinueItems(state,now);
  assert.deepEqual(items.map(item=>item.kind==='embed'?item.embedId:item.chat.id),['chat-2','Soon event','chat-1']);
  assert.match(items[0].priority!.label,/Reminder/);assert.match(items[1].priority!.label,/Event/);
  assert.equal(homeContinueItems(state,now+48*3600000).some(item=>item.kind==='embed' && item.embedId==='Soon event'),false);
});

// contract-test: supporting surface=cli assertions=continue-carousel.saved-item.start-time-gated,cli.surface.semantic-parity
test("saved item keyboard opening renders fullscreen and Escape returns to its home selection",async()=>{
  const state=createInitialTuiState();state.signedIn=true;state.focus='content';state.recentChats=[chat(1)];
  state.continueData={memories:[{id:'memory',app_id:'events',item_type:'saved_events',item_key_hash:'key',item_version:1,created_at:1,updated_at:1,
    data:{embed_id:'event',title:'Remembered event',date_start:new Date(Date.now()+3600000).toISOString()}}],reminders:[]};
  let opened=false;
  const {ctx}=context(state,{getEmbed:async(id:string,options:{preferCache:boolean})=>{
    opened=true;assert.equal(id,'event');assert.equal(options.preferCache,true);
    return {id,embedId:id,type:'events-event',appId:'events',skillId:'event',textPreview:'Remembered event',createdAt:null,
      content:{title:'Remembered event',description:'A complete event description',date_start:'2026-10-06T12:00:00Z',venue:{name:'Community Hall',city:'Berlin'},organizer:{name:'Open community'},url:'https://example.org/event'}};
  }});
  const frame=stripAnsi(renderTuiFrame(state,120,40));assert.match(frame,/Remembered event/);assert.match(frame,/Saved/);
  await handleWorkspaceKey(ctx,'',{name:'return'});assert.equal(opened,true);assert.equal(state.screen,'embed');
  assert.match(state.detailLines.join('\n'),/Location[\s\S]*Community Hall/);assert.match(state.detailLines.join('\n'),/Organizer[\s\S]*Open community/);
  assert.match(stripAnsi(renderTuiFrame(state,120,40)),/Esc back/);
  await handleWorkspaceKey(ctx,'',{name:'escape'});assert.equal(state.screen,'start');assert.equal(state.selectedIndex,0);assert.equal(state.focus,'content');
  await handleWorkspaceKey(ctx,'',{name:'right'});assert.equal(state.selectedIndex,1);
});

// contract-test: supporting surface=cli assertions=chat-navigation.open.local-first-coherent,chats.persistence.client-encrypted
test("history polling retries after failure avoids overlap and stops on exit",async(t)=>{
  t.mock.timers.enable({apis:['setInterval']});
  const state=createInitialTuiState();state.signedIn=true;
  let attempts=0,done!:(result:{chats:unknown[]})=>void;
  const client={listCachedChats:async()=>null,listChats:()=>{attempts++;if(attempts===1)return Promise.reject(Error('Offline'));return new Promise(resolve=>{done=resolve;});}};
  const stop=startHomeSync(state,client as never,()=>{},()=>false);
  t.mock.timers.tick(60000);await new Promise<void>(resolve=>setImmediate(resolve));assert.equal(attempts,1);assert.equal(state.homeLoading,false);
  t.mock.timers.tick(60000);await new Promise<void>(resolve=>setImmediate(resolve));assert.equal(attempts,2);
  t.mock.timers.tick(120000);await new Promise<void>(resolve=>setImmediate(resolve));assert.equal(attempts,2);
  done({chats:[]});await new Promise<void>(resolve=>setImmediate(resolve));stop();
  t.mock.timers.tick(120000);assert.equal(attempts,2);
});

// contract-test: supporting surface=cli assertions=continue-carousel.chat.reminder-gated,chat-navigation.open.local-first-coherent
test("cold Team reminders wait for persisted Team chat metadata",async()=>{
  const state=createInitialTuiState();state.signedIn=true;
  let persisted=false,reads=0;
  await loadHomeData(state,{
    getActiveTeamId:()=>"team",listCachedChats:async()=>null,
    getContinueItems:async()=>{assert.equal(persisted,true);reads++;return {memories:[],reminders:[{reminder_id:"due",trigger_at:Date.now()/1000,target_type:"chat",target_chat_id:"chat-1",status:"pending"}]};},
    listChats:async(_limit:unknown,_page:unknown,options:{onSyncedChats:(value:{chats:ChatListItem[]})=>void})=>{
      persisted=true;options.onSyncedChats({chats:[chat(2),chat(1)]});return {chats:[chat(2),chat(1)]};
    },
  } as never,()=>{});
  assert.equal(reads,1);const first=homeContinueItems(state)[0];assert.equal(first.kind,"chat");
  assert.equal(first.kind==="chat" && first.chat.id,"chat-1");
});

// contract-test: supporting surface=cli assertions=continue-carousel.saved-item.start-time-gated,chats.persistence.client-encrypted
test("saved item ciphertext warms in the background with bounded concurrency",async()=>{
  const state=createInitialTuiState();state.signedIn=true;let reads=0;
  const pending:Array<()=>void>=[];
  await loadHomeData(state,{
    getContinueItems:async()=>({memories:Array.from({length:15},(_,i)=>({id:String(i),app_id:"events",item_type:"saved_events",data:{embed_id:String(i),title:"Saved event",date_start:new Date(Date.now()+3600000).toISOString()}})),reminders:[]}),
    getEmbed:async(_id:string,options:{preferCache:boolean})=>{assert.equal(options.preferCache,true);reads++;await new Promise<void>(resolve=>pending.push(resolve));},
  } as never,()=>{});
  assert.equal(state.homeLoading,false);assert.equal(reads,3);assert.equal(homeContinueItems(state).length,10);
  state.homeAbortController?.abort();for(const resolve of pending)resolve();
  await new Promise<void>(resolve=>setImmediate(resolve));assert.equal(reads,3);
});

// contract-test: supporting surface=cli assertions=chats.rendering.inline-entity-interaction,cli.surface.semantic-parity
test("fullscreen commands keep controls visible and Escape interrupts pending loading",async()=>{
  const {runTui}=await import("../src/tui.js");
  let key!:(chunk:string,key:{name?:string;ctrl?:boolean})=>void;
  let lastFrame="",ready=false,opened=false,resolveEmbed!:(embed:unknown)=>void;
  const terminal={width:100,height:32,colorMode:"none",ascii:true,enter:()=>{},leave:()=>{},onResize:()=>{},
    onKey:(handler:typeof key)=>{key=handler;},render:(frame:string)=>{lastFrame=stripAnsi(frame);if(lastFrame.includes("DAILY INSPIRATION"))ready=true;}};
  const client={hasSession:()=>false,beginInteractiveViewerSession:()=>{},endInteractiveViewerSession:()=>{},clearInteractiveChatViewer:()=>{},
    getEmbed:async(id:string)=>{assert.equal(id,"fixture");opened=true;return await new Promise(resolve=>{resolveEmbed=resolve;});}};
  const result=runTui(client as never,terminal as never,{privacyOffer:async()=>false,privacyInstall:async()=>{},updateCheck:async()=>null,updateInstall:async()=>{},updateSkip:()=>{}});
  const wait=async(predicate:()=>boolean)=>{for(let i=0;i<100 && !predicate();i++)await new Promise(resolve=>setTimeout(resolve,5));assert.ok(predicate());};
  try {
    await wait(()=>ready);
    for(const character of "/embed fixture")key(character,{name:character});key("\r",{name:"return"});
    await wait(()=>opened && lastFrame.includes("Loading saved embed"));assert.match(lastFrame,/Esc back/);assert.match(lastFrame,/PgUp\/PgDn/);
    key("\x1b",{name:"escape"});await wait(()=>lastFrame.includes("DAILY INSPIRATION"));
    resolveEmbed({id:"fixture",embedId:"fixture",type:"code",content:{code:"const answer = 42;"},textPreview:null,createdAt:null,appId:"code",skillId:"code"});
    await new Promise(resolve=>setTimeout(resolve,25));assert.match(lastFrame,/DAILY INSPIRATION/);assert.doesNotMatch(lastFrame,/const answer/);
  } finally {key("\x03",{name:"c",ctrl:true});await result;}
});

// contract-test: supporting surface=cli assertions=chats.rendering.inline-entity-interaction,cli.surface.semantic-parity
test("long fullscreen embeds retain their header and visible keyboard controls above background status",()=>{
  for(const width of [60,100]){
    const state=createInitialTuiState();state.screen="embed";state.focus="content";state.status="Showing cached chats. Sync failed; /refresh to retry.";
    state.detailTitle="Code fixture";state.detailEmbed={id:"fixture",embedId:"fixture",type:"code",appId:"code",skillId:"code",textPreview:null,createdAt:null,content:{code:"source"}};
    state.detailLines=Array.from({length:120},(_,i)=>`Source line ${i}`);
    for(const offset of [0,60,110]){
      state.scrollOffset=offset;const frame=stripAnsi(renderTuiFrame(state,width,24));
      assert.match(frame,/Code fixture/);assert.match(frame,/Esc back/);assert.match(frame,/PgUp\/PgDn/);assert.doesNotMatch(frame,/Enter send/);
    }
  }
});
