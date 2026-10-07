import assert from "node:assert/strict";
import { test } from "node:test";
import type { WorkflowDetail } from "../src/client.js";
import type { DecryptedUserTask } from "../src/tasksCli.js";
import { renderCardCarousel, renderLineCarousel } from "../src/tuiCarousel.js";
import { renderTuiAppTabs, renderTuiAppsResults } from "../src/tuiAppsWorkspace.js";
import { renderProjectPointerTabs, renderProjectDetail, type TuiProject } from "../src/tuiProjectsWorkspace.js";
import { renderTaskBoard, renderTaskDetails } from "../src/tuiTasksWorkspace.js";
import { cells, lineText, type TuiLine } from "../src/tuiText.js";
import { renderWorkflowWorkspace } from "../src/tuiWorkflowWorkspace.js";

const actions = (line:TuiLine) => typeof line === "string" ? [] : [
  ...(line.action ? [line.action] : []), ...(line.spans ?? []).flatMap((span) => span.action ? [span.action] : []),
];
const targets = (lines:TuiLine[]) => lines.flatMap(actions);

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity,terminal-pointer.viewport-coherent
test("carousel actions survive horizontal clipping and wide card names", () => {
  const cards = ["left", "確認 🧪 very wide title", "right"].map((title, index) => ({
    title, description:"Details", footer:"Open", background:"#334455",
    action:{kind:"command" as const,command:`/project opaque-${index}`},
  }));
  const lines=renderCardCarousel(cards,48,1,true);
  assert.ok(lines.every((line)=>cells(lineText(line))===48));
  assert.ok(targets(lines).some((action)=>action.kind==="command"&&action.command==="/project opaque-0"));
  assert.ok(targets(lines).some((action)=>action.kind==="command"&&action.command==="/project opaque-1"));
  assert.ok(targets(lines).some((action)=>action.kind==="command"&&action.command==="/project opaque-2"));
  const edgeSpans=lines.flatMap((line)=>typeof line==="string"?[]:line.spans??[])
    .filter((span)=>span.action?.kind==="command"&&span.action.command==="/project opaque-0");
  assert.ok(edgeSpans.length>0&&edgeSpans.every((span)=>cells(span.text)===4));
  const rich=renderLineCarousel([
    [{text:"abcdefghij",action:{kind:"command",command:"/chat left"}}],
    [{text:"確認 🧪 name",action:{kind:"command",command:"/chat center"}}],
    [{text:"klmnopqrst",action:{kind:"command",command:"/chat right"}}],
  ],20,1,false,10);
  assert.ok(rich.every((line)=>cells(lineText(line))===20));
  assert.deepEqual(new Set(targets(rich).filter((action)=>action.kind==="command").map((action)=>action.command)),
    new Set(["/chat left","/chat center","/chat right"]));
  assert.ok(rich.flatMap((line)=>typeof line==="string"?[]:line.spans??[])
    .some((span)=>span.action?.kind==="command"&&span.action.command==="/chat left"&&cells(span.text)===3));
});

function task(id:string,status:DecryptedUserTask["status"],position:number):DecryptedUserTask {
  return {taskId:id,shortId:id,slug:id,title:`Task ${id}`,description:"",labels:[],tags:[],latestInstruction:"",status,
    assigneeType:"unassigned",assigneeIdentity:null,assigneeHash:null,primaryChatId:null,externalChat:null,
    linkedProjectIds:[],planId:null,dueAt:null,priority:0,priorityLevel:"none",position,queueState:"none",
    blockedReasonCode:null,blockedReason:"",aiExecutionState:null,version:1,encrypted:{} as DecryptedUserTask["encrypted"]};
}

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity,terminal-pointer.viewport-coherent
test("each visible task column carries stable IDs across title and border cells", () => {
  const statuses:DecryptedUserTask["status"][]=["backlog","todo","in_progress","blocked","done"];
  const lines=renderTaskBoard(statuses.map((status,index)=>task(`opaque-${index}`,status,index)),{width:125,selectedTaskId:"opaque-2"});
  for(const [column,id] of statuses.map((_,index)=>[index,`opaque-${index}`] as const)){
    const matching=targets(lines).filter((action)=>action.kind==="select"&&action.target==="task"&&action.id===id);
    assert.ok(matching.length>=3,id);
    assert.ok(matching.every((action)=>action.kind==="select"&&action.column===column&&action.activate));
    assert.ok(targets(lines).some((action)=>action.kind==="select"&&action.target==="task"&&action.column===column&&action.id===undefined&&action.activate===undefined));
  }
  const selectedBorder=lines.find((line)=>lineText(line).includes("╔═"));
  assert.ok(selectedBorder&&actions(selectedBorder).some((action)=>action.kind==="select"&&action.id==="opaque-2"));
  assert.ok(lines.every((line)=>cells(lineText(line))<=125));
});

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity,terminal-pointer.viewport-coherent
test("task detail shortcut labels keep their keyboard action through narrow wraps", () => {
  const record=task("opaque-detail","todo",0);
  const plain=renderTaskDetails(record,{width:18});
  const rich=renderTaskDetails(record,{width:18,pointer:true});
  assert.deepEqual(rich.map(lineText),plain);
  assert.deepEqual(new Set(targets(rich).filter((action)=>action.kind==="key").map((action)=>action.chunk)),
    new Set(["c","e","m","p","r","s","d","b","u","k","x"]));
  assert.ok(rich.every((line)=>cells(lineText(line))<=18));
});

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity
test("project and app tabs keep per-label actions; rows use canonical IDs", () => {
  const tabs=renderProjectPointerTabs("files",56);
  assert.deepEqual(new Set(targets(tabs).filter((action)=>action.kind==="key").map((action)=>action.chunk)),new Set(["1","2","3"]));
  const appTabs=renderTuiAppTabs("skills",84,{pointer:true});
  assert.deepEqual(new Set(targets(appTabs).filter((action)=>action.kind==="key").map((action)=>action.chunk)),new Set(["1","2","3","4","5"]));
  const narrowTabs=renderTuiAppTabs("skills",18,{pointer:true});
  assert.ok(narrowTabs.every((line)=>cells(lineText(line))<=18));
  assert.ok(targets(narrowTabs).some((action)=>action.kind==="key"&&action.chunk==="1"));
  const project={id:"opaque-project",name:"Wide 研究 Project",description:"",icon:"folder",readme:"",items:[],files:[],folders:[],sources:[],
    itemCount:0,color:"#005ba5",pinned:false,archived:false,projectKey:new Uint8Array(),teamId:null,sourceRecords:[],slug:"project"} as TuiProject;
  const detail=renderProjectDetail(project,{width:64,tab:"files",files:[{id:"opaque-file",name:"長い name 🧪",path:"name",kind:"stored"}]});
  assert.ok(targets(detail).some((action)=>action.kind==="select"&&action.id==="opaque-file"&&action.activate));
  const results=renderTuiAppsResults({items:[{embedId:"opaque-result",skillId:"search",status:"done"}],offset:0,hasMore:false} as Parameters<typeof renderTuiAppsResults>[0],{width:32,pointer:true});
  assert.ok(targets(results).some((action)=>action.kind==="command"&&action.command==="/app-result opaque-result"));
});

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity
test("workflow graph and run list bind nodes and runs by immutable IDs", () => {
  const workflow={id:"opaque-workflow",title:"Workflow",description:"",enabled:true,created_at:1,next_run_at:null,category:"general_knowledge",
    graph:{trigger_node_id:"node-a",nodes:[{id:"node-a",type:"manual_trigger",title:"Start",config:{}},{id:"node-b",type:"send_notification",title:"Notify",config:{body:"Hello"}}],edges:[{from:"node-a",to:"node-b"}]},
  } as unknown as WorkflowDetail;
  const graph=renderWorkflowWorkspace(workflow,{width:80,tab:"graph",selectedNodeIndex:0,expandedNodeId:"node-a"});
  assert.ok(targets(graph).some((action)=>action.kind==="select"&&action.target==="workflow-node"&&action.id==="node-a"));
  assert.ok(targets(graph).some((action)=>action.kind==="select"&&action.target==="workflow-node"&&action.id==="node-b"));
  assert.ok(targets(graph).some((action)=>action.kind==="key"&&action.chunk==="e"));
  assert.ok(targets(graph).some((action)=>action.kind==="key"&&action.chunk==="E"));
  const runs=renderWorkflowWorkspace(workflow,{width:80,tab:"runs",runs:[{id:"opaque-run",status:"completed",workflow_id:"opaque-workflow",version_id:"version-1"}] as never});
  assert.ok(targets(runs).some((action)=>action.kind==="select"&&action.target==="workflow-run"&&action.id==="opaque-run"));
});
