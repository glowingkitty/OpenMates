// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createInitialTuiState,renderTuiFrame,renderTuiStreamingAnimationFrame} from '../src/tuiRenderer.js';
import {chatRenderCacheStats} from '../src/tuiRenderCache.js';
import {pointerTargetAt} from '../src/tuiPointer.js';
import {tuiResponsePhase,renderTuiStreamingGlow} from '../src/tuiStreamingRender.js';
import {handleWorkspaceCommand,type WorkspaceContext} from '../src/tuiWorkspaceController.js';
import {parseMessageSegments} from '../src/messageSegments.js';
import {stripAnsi,cells} from '../src/tuiText.js';

function active(content=''){
  const state=createInitialTuiState();state.screen='chat';state.activeChatId='chat';state.currentUserHash='owner';
  state.isAwaitingAi=true;state.streamingMessage={role:'assistant',content,title:'Sophia',modelName:'Known model'};
  state.messages=[{role:'user',content:'Request'},...(content?[state.streamingMessage]:[])];return state;
}

// contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation,terminal-ui.chat.rich-content
test('transient Thinking keeps known identity left and status centered, with no empty history row',()=>{
  for(const width of [24,48,100,240]){
    const state=active();const frame=renderTuiFrame(state,width,24),rows=frame.split('\n');
    assert.equal(state.messages.length,1);assert.match(frame,/Thinking…/);assert.match(frame,/Known model/);
    assert.ok(rows.every(row=>cells(row)===width));
    const thinking=rows.find(row=>row.includes('Thinking…'))!;
    if(width>=48){assert.ok(thinking.includes('Sophia'));assert.ok(Math.abs(cells(thinking.slice(0,thinking.indexOf('✦ Thinking…')))+5.5-width/2)<=1);}
  }
});

// contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation,terminal-pointer.viewport-coherent
test('rainbow ticks recolor exactly one response row without traversing history or changing pointer targets',()=>{
  const state=active('Answer [guide](wiki:Guide)');
  const options={colorMode:'truecolor' as const};let frame=renderTuiFrame(state,100,28,options);
  assert.match(frame,/Known model/);
  const stats=chatRenderCacheStats(state),rows=frame.split('\n');
  const row=rows.findIndex(value=>value.includes('/wiki Guide')),column=stripAnsi(rows[row]).indexOf('/wiki Guide');
  const action=pointerTargetAt(state,column,row,100,28);
  // Any iterator traversal of the message array on a timer is a regression.
  Object.defineProperty(state.messages,Symbol.iterator,{value:()=>{throw Error('history traversed by animation');}});
  for(let phase=1;phase<=12;phase++){
    state.streamingPhase=phase;const next=renderTuiStreamingAnimationFrame(state,100,28,options)!;
    assert.ok(next);assert.equal(stripAnsi(next),stripAnsi(frame));
    assert.equal(next.split('\n').filter((line,index)=>line!==frame.split('\n')[index]).length,1);
    assert.deepEqual(pointerTargetAt(state,column,row,100,28),action);assert.deepEqual(chatRenderCacheStats(state),stats);frame=next;
  }
});

// contract-test: supporting surface=cli assertions=terminal-pointer.viewport-coherent,terminal-ui.offline.cache-first
test('animation cache refuses stale drafts, content, viewports, owners and hidden responses',()=>{
  const options={colorMode:'truecolor' as const};
  const mutations=[(s:ReturnType<typeof active>)=>{s.input='new draft';},s=>{s.streamingMessage!.content+='more';},
    s=>{s.scrollOffset++;},s=>{s.activeTeamId='another-team';},s=>{s.currentUserHash='another-owner';},
    s=>{s.routeVersion++;},s=>{s.screen='chats';},s=>{s.textSelection=true;},s=>{s.isAwaitingAi=false;}];
  for(const change of mutations){const state=active('Answer');renderTuiFrame(state,100,28,options);change(state);
    assert.equal(renderTuiStreamingAnimationFrame(state,100,28,options),null);}
  const state=active('Answer');renderTuiFrame(state,100,28,options);
  assert.equal(renderTuiStreamingAnimationFrame(state,72,28,options),null);
  state.scrollOffset=10000;renderTuiFrame(state,100,28,options);
  state.isAwaitingAi=false;state.streamingMessage=null;
  assert.doesNotMatch(renderTuiFrame(state,100,28),/Thinking…|▁/);
  const monochrome=active();renderTuiFrame(monochrome,100,28);
  assert.equal(renderTuiStreamingAnimationFrame(monochrome,100,28),null);
});

// contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation
test('active status follows the trailing adjacent skills and authored text, with action precedence',()=>{
  const fence=(skill:string,id=skill)=>'```json_embed\n'+JSON.stringify({type:'app_skill_use',embed_id:id,app_id:'workflows',skill_id:skill})+'\n```';
  for(const skill of ['search_classes','lookup','get','unknown_id']){
    const content=fence(skill);assert.equal(tuiResponsePhase(parseMessageSegments(content)),'Researching');
    const state=active(content);assert.match(renderTuiFrame(state,100,28),/✦ Researching…/);
  }
  for(const skill of ['create','write_file','schedule-once','schedule-recurring','keep-temporary'])
    assert.equal(tuiResponsePhase(parseMessageSegments(fence('search')+'\n\n'+fence(skill))),'Working');
  assert.equal(tuiResponsePhase(parseMessageSegments(fence('create')+'\n\nAuthored answer\n\n'+fence('search'))),'Researching');
  assert.equal(tuiResponsePhase(parseMessageSegments(fence('search')+'\n\nAuthored answer')),'Working');
  const completed=active('Done');completed.isAwaitingAi=false;completed.streamingMessage=null;
  assert.doesNotMatch(renderTuiFrame(completed,100,28),/✦ (Thinking|Researching|Working)/);
});

// contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation
test('rainbow moves left to right and reduced motion retains a static visible response indicator',()=>{
  const before=renderTuiStreamingGlow(72,0),after=renderTuiStreamingGlow(72,2);
  assert.equal(typeof before,'object');assert.equal(typeof after,'object');
  if(typeof before==='string'||typeof after==='string')throw Error('Expected colored spans');
  assert.equal(after.spans![13].color,before.spans![1].color);
  const state=active('Answer'),options={colorMode:'truecolor' as const,reducedMotion:true};
  const frame=renderTuiFrame(state,100,28,options);assert.match(frame,/▁/);
  state.streamingPhase=2;assert.equal(renderTuiStreamingAnimationFrame(state,100,28,options),null);
});

// contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation,terminal-ui.chat.rich-content
test('actual response-wide reasoning is disclosed once and a targeted control expands the correct response',async()=>{
  const state=active('Authored answer');state.streamingMessage!.id='current';
  state.streamingMessage!.thinkingContent='Visible reasoning one.\nVisible reasoning two.';state.streamingMessage!.thinkingActive=true;
  let frame=renderTuiFrame(state,100,28,{colorMode:'truecolor'});
  assert.equal(frame.split('Thinking for this response').length,2);assert.match(frame,/✦ Thinking…/);assert.doesNotMatch(frame,/Visible reasoning one/);
  const context={state,client:{},render:()=>{},terminal:{},send:async()=>{},command:async()=>{}} as unknown as WorkspaceContext;
  state.input='Keep my newer draft';state.inputCursor=5;
  await handleWorkspaceCommand(context,'/thinking current');
  assert.equal(state.input,'Keep my newer draft');assert.equal(state.inputCursor,5);
  frame=renderTuiFrame(state,100,28,{colorMode:'truecolor'});assert.match(frame,/Visible reasoning one/);assert.match(frame,/Visible reasoning two/);
  state.isAwaitingAi=false;state.streamingMessage=null;
  frame=renderTuiFrame(state,100,28);assert.equal(frame.split('Thinking for this response').length,2);assert.doesNotMatch(frame,/✦ Thinking…/);
  await handleWorkspaceCommand(context,'/thinking current');assert.doesNotMatch(renderTuiFrame(state,100,28),/Visible reasoning one/);
  assert.equal(renderTuiFrame(active('No reasoning'),100,28).includes('Thinking for this response'),false);
});
