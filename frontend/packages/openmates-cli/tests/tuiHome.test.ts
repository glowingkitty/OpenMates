// contract-test-file: infrastructure
import assert from "node:assert/strict";
import { test } from "node:test";
import { createInitialTuiState, renderTuiFrame } from "../src/tuiRenderer.js";
import { loadHomeData, workspaceInspirations } from "../src/tuiHome.js";
import { handleWorkspaceCommand, handleWorkspaceKey, type WorkspaceContext } from "../src/tuiWorkspaceController.js";
import { cells, stripAnsi } from "../src/tuiText.js";
import type { TuiApp } from "../src/tuiAppsWorkspace.js";

function context(state=createInitialTuiState(),client:Record<string,unknown>={}) {
  const commands:string[]=[];
  const ctx={state,client,terminal:{width:120},render:()=>{},send:async()=>{},command:async(command:string)=>{commands.push(command);await handleWorkspaceCommand(ctx as WorkspaceContext,command);}} as unknown as WorkspaceContext;
  return {ctx,commands};
}
const inspiration={id:"daily",phrase:"Make room for the next idea",title:"A daily planning tip",category:"productivity",content_type:"feature",video:null,generated_at:1,assistant_response:"Plan one small action.",follow_up_suggestions:[]};
const chat=(i:number)=>({id:`chat-${i}`,shortId:`C${i}`,title:`Conversation ${i}`,summary:`Summary ${i}`,category:"technology",mateName:null,updatedAt:null});
const app=(id:string,name:string):TuiApp=>({id,name,description:`${name} description`,category:"general_knowledge",skills:[],focusModes:[],settingsMemories:[]});

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
