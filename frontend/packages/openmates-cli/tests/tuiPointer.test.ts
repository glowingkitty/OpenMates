import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createInitialTuiState} from '../src/tuiRenderer.js';
import {renderWorkspaceFrame,sidebarPointerIds,workspaceGeometry} from '../src/tuiLayout.js';
import {pointerLine,pointerTargetAt} from '../src/tuiPointer.js';
import {handleTuiPointer} from '../src/tuiPointerActions.js';
import {handleWorkspaceKey,type WorkspaceContext} from '../src/tuiWorkspaceController.js';
import {buildTaskForm} from '../src/tuiTasksWorkspace.js';
import {cells,stripAnsi,type TuiLine} from '../src/tuiText.js';

const context=()=>{
  const state=createInitialTuiState(),commands:string[]=[],sent:string[]=[];
  state.signedIn=true;
  const ctx={state,client:{},terminal:{width:120,height:24},render:()=>{},
    command:async (value:string)=>{commands.push(value);},send:async(value:string)=>{sent.push(value);}} as WorkspaceContext;
  const keyboard=async(chunk:string,key:Parameters<typeof handleWorkspaceKey>[2])=>{await handleWorkspaceKey(ctx,chunk,key);};
  return {state,ctx,keyboard,commands,sent};
};
const at=(state:ReturnType<typeof createInitialTuiState>,frame:string,text:string,width:number,height:number,offset=0)=>{
  const rows=stripAnsi(frame).split('\n'),row=rows.findIndex(line=>line.includes(text));
  assert.ok(row>=0,text);
  const column=cells(rows[row].slice(0,rows[row].indexOf(text)))+offset;
  return pointerTargetAt(state,column,row,width,height);
};

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity,terminal-pointer.viewport-coherent
test('visible header and composer actions respect centering and do not send drafts',async()=>{
  const {state,ctx,keyboard,commands,sent}=context();state.input='Unsent draft';
  const frame=renderWorkspaceFrame(state,220,24,[]);
  const action=at(state,frame,'Projects',220,24)!;
  assert.deepEqual(action,{kind:'command',command:'/projects'});
  await handleTuiPointer(ctx,action,keyboard);
  assert.deepEqual(commands,['/projects']);
  await handleTuiPointer(ctx,at(state,frame,'Unsent draft',220,24)!,keyboard);
  assert.equal(state.focus,'composer');assert.equal(state.input,'Unsent draft');assert.deepEqual(sent,[]);
  assert.equal(pointerTargetAt(state,0,0,220,24),null);
});

// contract-test: supporting surface=cli assertions=terminal-pointer.viewport-coherent
test('targets follow actual scroll rows, sticky headers, span clipping and wide cells',()=>{
  const {state}=context();state.screen='projects';
  const body:TuiLine[]=[pointerLine('Sticky',{kind:'command',command:'/projects'}),
    ...Array.from({length:35},(_,index)=>pointerLine(`Row ${index}`,{kind:'command',command:`/project ${index}`}))];
  state.scrollOffset=18;
  const frame=renderWorkspaceFrame(state,100,20,body,{stickyRows:1});
  assert.deepEqual(at(state,frame,'Sticky',100,20),{kind:'command',command:'/projects'});
  assert.deepEqual(at(state,frame,'Row 18',100,20),{kind:'command',command:'/project 18'});
  assert.equal(pointerTargetAt(state,4,2,99,20),null,'resize invalidates the old geometry');
  const geometry=workspaceGeometry(state,32);
  const clipped=renderWorkspaceFrame(state,32,14,[{text:'',inset:2,spans:[
    {text:'確認 🧪 ',action:{kind:'command',command:'/embed one'}},
    {text:'abcdefghijklmnopqrstuvwxy',action:{kind:'command',command:'/embed two'}}]}]);
  const first=geometry.gutter+geometry.inset+2;
  assert.deepEqual(pointerTargetAt(state,first+3,2,32,14),{kind:'command',command:'/embed one'});
  assert.deepEqual(pointerTargetAt(state,first+cells('確認 🧪 '),2,32,14),{kind:'command',command:'/embed two'});
  assert.equal(pointerTargetAt(state,31,2,32,14),null);
  assert.ok(clipped.split('\n').every(row=>cells(row)===32));
});

// contract-test: supporting surface=cli assertions=terminal-pointer.viewport-coherent,terminal-pointer.lifecycle-selection-safe
test('modal overlays, narrow sidebar, stale routes and text selection block hidden targets',()=>{
  const {state}=context();
  const body=[pointerLine('Hidden card',{kind:'command',command:'/chat hidden'})];
  const frame=renderWorkspaceFrame(state,100,20,body);
  assert.ok(at(state,frame,'Hidden card',100,20));
  state.routeVersion++;assert.equal(pointerTargetAt(state,4,2,100,20),null);
  state.form={kind:'test',title:'Form',fields:[],fieldIndex:0,busy:false};
  const modal=renderWorkspaceFrame(state,100,20,body);
  assert.equal(at(state,modal,'Projects',100,20),null);
  state.form=null;state.sidebarOpen=true;
  const side=renderWorkspaceFrame(state,50,20,body);assert.doesNotMatch(side,/Hidden card/);
  assert.deepEqual(at(state,side,'+ New chat',50,20)?.kind,'select');
  state.textSelection=true;assert.equal(at(state,side,'+ New chat',50,20),null);
});

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity,terminal-pointer.viewport-coherent
test('sidebar targets carry stable identities and remain correct after background sorting',async()=>{
  const {state,ctx,keyboard,commands}=context();state.workspace='projects';state.screen='projects';state.sidebarOpen=true;
  state.projects=[{id:'one',name:'First'},{id:'two',name:'Second'}] as typeof state.projects;
  const ids=sidebarPointerIds(state),frame=renderWorkspaceFrame(state,120,20,[]);
  const action=at(state,frame,'Second',120,20)!;
  state.projects.reverse();await handleTuiPointer(ctx,action,keyboard);
  assert.equal(state.sidebarIndex,0);assert.deepEqual(commands,['/project two']);
  state.projects=[];await handleTuiPointer(ctx,action,keyboard);assert.equal(commands.length,1);
  assert.deepEqual(ids,['one','two']);
});

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity
test('form field clicks focus or change a draft and respect busy guards',async()=>{
  const {state,ctx,keyboard}=context();
  state.form={kind:'test',title:'Form',fieldIndex:0,busy:false,fields:[
    {name:'name',label:'Name',value:'Kept'}, {name:'mode',label:'Mode',value:'one',options:['one','two']}]};
  let frame=renderWorkspaceFrame(state,100,24,[]);
  await handleTuiPointer(ctx,at(state,frame,'Mode',100,24)!,keyboard);
  assert.equal(state.form.fieldIndex,1);assert.equal(state.form.fields[1].value,'one');
  frame=renderWorkspaceFrame(state,100,24,[]);
  await handleTuiPointer(ctx,at(state,frame,'Next ›',100,24)!,keyboard);
  assert.equal(state.form.fields[1].value,'two');
  state.form.busy=true;
  await handleTuiPointer(ctx,{kind:'select',target:'form-field',index:0,id:'name'},keyboard);
  assert.equal(state.form.fieldIndex,1);
});

// contract-test: supporting surface=cli assertions=terminal-pointer.viewport-coherent
test('project file targets resolve stable IDs rather than an obsolete list position',async()=>{
  const {state,ctx}=context();state.screen='project';state.projectTab='files';
  state.projectFiles=[{id:'second',name:'Second',kind:'file'},{id:'first',name:'First',kind:'file'}] as typeof state.projectFiles;
  let activations=0;
  const keyboard=async()=>{activations++;};
  await handleTuiPointer(ctx,{kind:'select',target:'content',index:0,id:'first',activate:true},keyboard);
  assert.equal(state.selectedIndex,1);assert.equal(activations,1);
  state.projectFiles=[];await handleTuiPointer(ctx,{kind:'select',target:'content',index:0,id:'first',activate:true},keyboard);
  assert.equal(activations,1);
  state.screen='tasks';state.tasks=[];
  await handleTuiPointer(ctx,{kind:'select',target:'task',column:3,index:0},keyboard);
  assert.equal(state.taskStatusFilter,'blocked');assert.equal(activations,1);
});

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity
test('clicking Save cannot bypass a destructive confirmation or a busy form',async()=>{
  const {state,ctx,keyboard}=context();let deleted=0;
  const task={taskId:'owned-task',shortId:'TASK-42',title:'Kept task',version:1} as NonNullable<typeof state.activeTask>;
  state.activeTask=task;state.form=buildTaskForm('task-delete',task);
  ctx.client={getMasterKeyBytes:()=>new Uint8Array(32),deleteUserTask:async()=>{deleted++;}} as typeof ctx.client;
  const frame=renderWorkspaceFrame(state,100,24,[]);
  const save=at(state,frame,'Save · Ctrl+S',100,24)!;
  await handleTuiPointer(ctx,save,keyboard);
  assert.equal(deleted,0);assert.match(state.form!.error??'',/DELETE/);
  state.form!.fields[0].value='DELETE';state.form!.busy=true;
  await handleTuiPointer(ctx,save,keyboard);assert.equal(deleted,0);
});

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity
test('modal clicks reach their own controls after navigation receives keyboard focus',async()=>{
  const {state,ctx,keyboard,commands}=context();
  state.focus='navigation';state.form={kind:'test',title:'Draft form',fieldIndex:0,fields:[
    {name:'title',label:'Title',value:'Unsent'}]};
  let frame=renderWorkspaceFrame(state,100,24,[]);
  const cancel=at(state,frame,'Cancel · Esc',100,24)!;
  await handleTuiPointer(ctx,cancel,keyboard);
  assert.equal(state.form,null);assert.deepEqual(commands,[]);
  state.focus='navigation';state.form={kind:'test',title:'Saving form',fieldIndex:0,busy:true,fields:[
    {name:'title',label:'Title',value:'Kept'}]};
  await handleTuiPointer(ctx,cancel,keyboard);assert.equal(state.form.fields[0].value,'Kept');
  state.form=null;state.focus='navigation';state.paletteOpen=true;state.paletteQuery='Projects';
  frame=renderWorkspaceFrame(state,100,24,[]);
  await handleTuiPointer(ctx,at(state,frame,'Projects  /projects',100,24)!,keyboard);
  assert.equal(state.paletteOpen,false);assert.deepEqual(commands,['/projects']);
});
