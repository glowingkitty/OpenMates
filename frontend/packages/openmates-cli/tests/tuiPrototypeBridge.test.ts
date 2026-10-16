// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createInitialTuiState} from '../src/tuiRenderer.js';
import {currentPrototypeAction,prototypeSnapshot} from '../src/tuiPrototypeBridge.js';

test('prototype actions are fenced by epoch, owner and owned target IDs',()=>{
  const state=createInitialTuiState();state.signedIn=true;state.currentUserHash='owner';state.activeChatId='chat';
  state.recentChats=[{id:'chat',title:'Owned',category:'software_development'} as typeof state.recentChats[number]];
  const snapshot=prototypeSnapshot(state,7,80);
  const action={v:1,type:'action',epoch:7,scope:snapshot.scope,action:'open_chat',id:'chat'};
  assert.ok(currentPrototypeAction(action,snapshot));
  for(const wrong of [{epoch:6},{scope:'another owner'},{id:'outsider'},{action:'delete_chat'},{v:2}])
    assert.equal(currentPrototypeAction({...action,...wrong},snapshot),null);
  assert.equal(currentPrototypeAction({...action,action:'draft_changed',value:'x'.repeat(8193)},snapshot),null);
  state.activeTeamId='another-team';assert.equal(currentPrototypeAction(action,prototypeSnapshot(state,7,80)),null);
});
test('prototype projection uses terminal-safe styled text without credentials',()=>{
  const state=createInitialTuiState();state.messages=[{id:'m',role:'assistant',content:'### Heading\n**Bold** [Berlin](wiki:Berlin)\u001b[31m'}];
  const snapshot=prototypeSnapshot(state,1,80);const serialized=JSON.stringify(snapshot);
  assert.ok(snapshot.state.messages[0].lines[0].spans.some(span=>span.bold));
  assert.match(serialized,/\/wiki Berlin/);assert.ok(!serialized.includes('\\u001b'));
  assert.ok(!('masterKey' in snapshot.state));assert.equal(snapshot.state.sidebarOpen,false);
});

test('prototype retains semantic roles and explicit local, remote and Mate labels',()=>{
  const state=createInitialTuiState();state.messages=[
    {id:'local',role:'user',content:'Local'},
    {id:'remote',role:'user',remoteUser:true,title:'Alex',content:'Remote'},
    {id:'mate',role:'assistant',title:'Sophia',content:'Reply'},
  ];
  const snapshot=prototypeSnapshot(state,1,80);
  assert.deepEqual(snapshot.state.messages.map(({role,senderName})=>[role,senderName]),
    [['user','You'],['user','Alex'],['assistant','Sophia']]);
});

test('prototype task presentation preserves owned camelCase task IDs',()=>{
  const state=createInitialTuiState();state.workspace='tasks';
  state.tasks=[{taskId:'owned-task',title:'Owned task'} as typeof state.tasks[number]];
  const snapshot=prototypeSnapshot(state,3,80);
  assert.deepEqual(snapshot.state.workspaceRows,[{id:'owned-task',label:'Owned task'}]);
  assert.ok(currentPrototypeAction({v:1,type:'action',epoch:3,scope:snapshot.scope,
    action:'open_workspace_item',id:'owned-task'},snapshot));
  assert.equal(currentPrototypeAction({v:1,type:'action',epoch:3,scope:snapshot.scope,
    action:'open_workspace_item',id:'unowned-task'},snapshot),null);
});
