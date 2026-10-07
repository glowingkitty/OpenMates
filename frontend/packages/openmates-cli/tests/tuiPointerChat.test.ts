import assert from 'node:assert/strict';
import {test} from 'node:test';
import {renderTuiMarkdownLines} from '../src/tuiMarkdown.js';
import {renderMessageContentStyled,createInitialTuiState} from '../src/tuiRenderer.js';
import {renderTuiEmbedPreview} from '../src/tuiEmbedPreviews.js';
import {handleQuestionPointer,renderQuestionCard,renderQuestionEditor} from '../src/tuiInteractiveQuestions.js';
import type {InteractiveQuestionPayload} from '../src/interactiveQuestions.js';
import type {WorkspaceContext} from '../src/tuiWorkspaceController.js';
import type {TuiLine} from '../src/tuiText.js';

const actions=(lines:TuiLine[])=>lines.flatMap(line=>typeof line==='string'?[]:
  [line.action,...(line.spans??[]).map(span=>span.action)].filter(Boolean));
const fence=(question:InteractiveQuestionPayload)=>`\`\`\`interactive_question\n${JSON.stringify(question)}\n\`\`\``;
const choice:InteractiveQuestionPayload={type:'choice',id:'pick',question:'Pick one',options:[
  {id:'a',text:'First'},{id:'b',text:'Second'}]};
function setup(question:InteractiveQuestionPayload=choice){
  const state=createInitialTuiState();state.screen='chat';state.activeChatId='chat';
  state.messages=[{role:'assistant',content:fence(question)}];
  const sent:string[]=[];
  const context={state,render:()=>{},send:async(message:string)=>{sent.push(message);state.messages.push({role:'user',content:message});}} as unknown as WorkspaceContext;
  return {state,context,sent};
}

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity
test('wrapped wiki and embed links carry typed actions while quoted and coded text stay inert',()=>{
  const lines=renderTuiMarkdownLines('Before [A long link](embed:canonical-id) and [guide](wiki:guide_id).',16,
    {resolveEmbedAlias:()=> 'emb-s-1'});
  assert.ok(lines.length>2);
  assert.ok(actions(lines).some(action=>action?.kind==='command'&&action.command==='/embed emb-s-1'));
  assert.ok(actions(lines).some(action=>action?.kind==='command'&&action.command==='/wiki guide_id'));
  assert.equal(actions(renderTuiMarkdownLines('`[guide](wiki:guide_id)`\n```text\n[ref](embed:canonical-id)\n```',16)).length,0);
  assert.equal(actions(renderMessageContentStyled('User said /embed emb-s-1',30)).length,0);
});

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity
test('embed preview cards use their trusted alias and reject unsafe alias commands',()=>{
  const embed={id:'id',embedId:'id',type:'app_skill_use',appId:'notes',skillId:'search',content:{title:'Result'},
    textPreview:null,createdAt:null};
  assert.ok(actions(renderTuiEmbedPreview(embed,40,'notes-s-1')).some(action=>
    action?.kind==='command'&&action.command==='/embed notes-s-1'));
  assert.equal(actions(renderTuiEmbedPreview(embed,40,'bad alias; run')).length,0);
});

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity,terminal-pointer.viewport-coherent
test('typed embed carousel and results view expose their own canonical result actions',()=>{
  const state=createInitialTuiState();state.screen='chat';
  const first={id:'one',embedId:'one',type:'fitness-class',appId:'fitness',skillId:'search_classes',
    content:{name:'First class',venue_lat:52.5,venue_lon:13.4,date:'2026-10-14'},textPreview:null,createdAt:null};
  const second={...first,id:'two',embedId:'two',content:{name:'Second class',venue_lat:52.6,venue_lon:13.5,date:'2026-10-15'}};
  state.chatEmbeds={one:first,two:second};
  state.embedAliases={'fit-1':{embedId:'one',appId:'fitness',skillId:'search_classes'},
    'fit-2':{embedId:'two',appId:'fitness',skillId:'search_classes'}};
  const refs=['one','two'].map(id=>`\`\`\`json_embed\n${JSON.stringify({embed_id:id,app_id:'fitness',skill_id:'search_classes'})}\n\`\`\``).join('\n');
  const cardActions=actions(renderMessageContentStyled(refs,100,new Map(Object.entries(state.chatEmbeds)),state));
  assert.ok(cardActions.some(action=>action?.kind==='command'&&action.command==='/embed fit-1'));
  assert.ok(cardActions.some(action=>action?.kind==='command'&&action.command==='/embed fit-2'));
  const view='```embeds_results_view\ntitle: Classes\nembeds: one, two\n```';
  const viewActions=actions(renderMessageContentStyled(view,26,new Map(Object.entries(state.chatEmbeds)),state));
  assert.ok(viewActions.some(action=>action?.kind==='command'&&action.command==='/view 1'));
  assert.ok(viewActions.some(action=>action?.kind==='command'&&action.command==='/embed fit-1'));
  assert.ok(viewActions.some(action=>action?.kind==='command'&&action.command==='/embed fit-2'));
});

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity,terminal-pointer.lifecycle-selection-safe
test('question card opens an editor; choices remain draft until explicit Send and validate',async()=>{
  const {state,context,sent}=setup();
  const card=renderQuestionCard({key:1,messageIndex:0,payload:choice},50);
  assert.ok(actions(card).some(action=>action?.kind==='question'&&action.index===1&&action.activate));
  await handleQuestionPointer(context,{kind:'question',index:1,activate:true});
  assert.ok(state.questionEditor);
  let editorLines=renderQuestionEditor(state.questionEditor!,60);
  assert.ok(actions(editorLines).some(action=>action?.kind==='question'&&action.index===0));
  await handleQuestionPointer(context,{kind:'question',index:2,activate:true});
  assert.equal(sent.length,0);assert.match(state.questionEditor!.error!,/Select/);
  await handleQuestionPointer(context,{kind:'question',index:1,activate:true});
  assert.deepEqual(state.questionEditor!.answer.selection,['b']);assert.equal(sent.length,0);
  await handleQuestionPointer(context,{kind:'question',index:2,activate:true});
  assert.equal(sent.length,1);assert.equal(state.questionEditor,null);
  await handleQuestionPointer(context,{kind:'question',index:1,activate:true});
  assert.equal(state.questionEditor,null);
  editorLines=renderQuestionCard({key:1,messageIndex:0,payload:choice,response:{selection:['b']}},60);
  assert.equal(actions(editorLines).length,0);
});

// contract-test: supporting surface=cli assertions=terminal-pointer.lifecycle-selection-safe
test('Clear, Cancel and busy pointer guards preserve the question draft lifecycle',async()=>{
  const {state,context,sent}=setup();
  await handleQuestionPointer(context,{kind:'question',index:1,activate:true});
  await handleQuestionPointer(context,{kind:'question',index:0,activate:true});
  assert.deepEqual(state.questionEditor!.answer.selection,['a']);
  await handleQuestionPointer(context,{kind:'question',index:3,activate:true});
  assert.deepEqual(state.questionEditor!.answer.selection,[]);
  state.questionEditor!.busy=true;
  await handleQuestionPointer(context,{kind:'question',index:0,activate:true});
  assert.deepEqual(state.questionEditor!.answer.selection,[]);
  state.questionEditor!.busy=false;
  await handleQuestionPointer(context,{kind:'question',index:4,activate:true});
  assert.equal(state.questionEditor,null);assert.equal(sent.length,0);
});

// contract-test: supporting surface=cli assertions=terminal-pointer.visible-action-parity,terminal-pointer.lifecycle-selection-safe
test('slider, rating and swipe pointer values obey payload ranges and remain drafts',async()=>{
  const slider=setup({type:'slider',id:'level',question:'Level',min:0,max:1,step:0.25});
  await handleQuestionPointer(slider.context,{kind:'question',index:1,activate:true});
  await handleQuestionPointer(slider.context,{kind:'question',index:0,value:0.3});
  assert.equal(slider.state.questionEditor!.touched,false);
  await handleQuestionPointer(slider.context,{kind:'question',index:0,value:0.75});
  assert.equal(slider.state.questionEditor!.answer.value,0.75);
  assert.equal(slider.sent.length,0);
  const rating=setup({type:'rating',id:'rate',question:'Rate',max_stars:5});
  await handleQuestionPointer(rating.context,{kind:'question',index:1,activate:true});
  await handleQuestionPointer(rating.context,{kind:'question',index:0,value:6});
  assert.equal(rating.state.questionEditor!.answer.rating,0);
  await handleQuestionPointer(rating.context,{kind:'question',index:0,value:4});
  assert.equal(rating.state.questionEditor!.answer.rating,4);
  const swipe=setup({type:'swipe',id:'cards',cards:[{id:'one',text:'One'},{id:'two',text:'Two'}]});
  await handleQuestionPointer(swipe.context,{kind:'question',index:1,activate:true});
  await handleQuestionPointer(swipe.context,{kind:'question',index:0,value:'like'});
  await handleQuestionPointer(swipe.context,{kind:'question',index:1,value:'dislike'});
  assert.deepEqual({...swipe.state.questionEditor!.answer.swipes as object},{one:'like',two:'dislike'});
  assert.equal(swipe.sent.length,0);
});
