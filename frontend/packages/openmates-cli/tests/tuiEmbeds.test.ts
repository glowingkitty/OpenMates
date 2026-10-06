// contract-test-file: infrastructure
/* eslint-disable no-control-regex -- Assert trusted terminal styling and cursor bytes. */
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createInitialTuiState, renderTuiFrame} from '../src/tuiRenderer.js';
import {embedAliasPrefix, registerChatEmbedAliases, renderFitnessPreview, hydrateFitnessResults, fitnessResultDetail} from '../src/tuiEmbeds.js';
import {lineText, cells, stripAnsi} from '../src/tuiText.js';
import {tuiComposerCursor} from '../src/tuiLayout.js';
import {handleWorkspaceKey,handleWorkspaceCommand,type WorkspaceContext} from '../src/tuiWorkspaceController.js';
import type {DecryptedEmbed} from '../src/client.js';

const reference=(id:string,app='fitness',skill='search_classes')=>'```json_embed\n'+JSON.stringify({embed_id:id,app_id:app,skill_id:skill})+'\n```';
const embed:DecryptedEmbed={id:'root',embedId:'root',type:'app_skill_use',appId:'fitness',skillId:'search_classes',textPreview:null,createdAt:null,content:{status:'finished',results:[{provider:'Urban Sports Club',result_count:2,filters:{city:'Berlin',radius_km:5,plan:'M'},summary:'Dance classes nearby',results:[{name:'Modern Dance',venue_name:'Studio One',date:'2026-10-12',time_range:'18:00–19:00',distance_km:1.2,plans_required:'M|L'},{name:'Techno Dance',venue_name:'Studio Two',date:'2026-10-13',time_range:'19:00–20:00',spots_display:'3 spots'}]}]}};
function context(state:ReturnType<typeof createInitialTuiState>,client:Record<string,unknown>={}):WorkspaceContext{return {state,client,terminal:{width:160,height:32},render:()=>{},command:async()=>{},send:async()=>{}} as unknown as WorkspaceContext;}

test('chat-local shortcuts remain stable during hydration and older-history arrival, including prefix collisions',()=>{
  const state=createInitialTuiState();state.screen='chat';state.messages=[{role:'assistant',content:reference('root')},{role:'assistant',content:reference('other','fitbit','send_calendar')}];
  registerChatEmbedAliases(state);assert.equal(embedAliasPrefix('fitness','search_classes'),'fit-s_c');
  assert.equal(state.embedAliases['fit-s_c-1'].embedId,'root');assert.equal(state.embedAliases['fit-s_c-2'].embedId,'other');
  state.chatEmbeds.root=embed;state.messages.unshift({role:'assistant',content:reference('older')});registerChatEmbedAliases(state);
  assert.equal(state.embedAliases['fit-s_c-1'].embedId,'root');assert.equal(state.embedAliases['fit-s_c-3'].embedId,'older');assert.equal(state.embedAliases['fit-s_c-1-2'].resultIndex,1);
});
test('fitness preview shares web normalization, statuses and bounded result fields',()=>{
  const rows=renderFitnessPreview(embed,62,'fit-s_c-1').map(lineText).join('\n');
  for(const text of ['Urban Sports Club','Search classes','Berlin','2 classes','Modern Dance','Techno Dance','Plan: M','/embed fit-s_c-1'])assert.ok(rows.includes(text),text);
  assert.ok(renderFitnessPreview(embed,32,'fit-s_c-1').every(line=>cells(lineText(line))<=32));
  for(const [status,text] of [['error','Search failed'],['processing','Searching'],['cancelled','Search cancelled']])assert.match(renderFitnessPreview({...embed,content:{status}},62,'fit-s_c-1').map(lineText).join('\n'),new RegExp(text));
  assert.match(fitnessResultDetail({name:'Dance',distance_km:1.2,plans_required:'M|L',venue_address:'Studio street',detail_url:'https://example.org/class'}).join('\n'),/1.20 km\nPlans: M, L\nStudio street\nhttps:\/\/example.org\/class/);
});
test('shortcuts open root and individual class details using only canonical ids',async()=>{
  const state=createInitialTuiState();state.screen='chat';state.workspace='chats';state.activeChatId='saved';state.messages=[{role:'assistant',content:reference('root')}];
  state.chatEmbeds.root=embed;registerChatEmbedAliases(state);
  const ctx=context(state,{getEmbed:async()=>{throw Error('cached fixture must not fetch');}});
  await handleWorkspaceCommand(ctx,'/embed fit-s_c-1-2');assert.equal(state.detailEmbed?.type,'fitness-class');assert.match(state.detailLines.join('\n'),/Techno Dance/);
  await handleWorkspaceKey(ctx,'',{name:'escape'});assert.equal(state.screen,'chat');
  state.input='Keep this draft';await handleWorkspaceKey(ctx,'',{name:'escape'});assert.equal(state.screen,'start');assert.equal(state.drafts.saved,'Keep this draft');assert.equal(state.activeChatId,null);
});
test('fitness child hydration uses inherited cached embeds without losing count or filters',async()=>{
  const ids:string[]=[];
  const result=await hydrateFitnessResults({...embed,content:{status:'finished',result_count:2,filters:{city:'Berlin'},embed_ids:'one|two'}},{getEmbed:async(id:string,options:Record<string,unknown>)=>{ids.push(id);assert.equal(options.preferCache,true);return {...embed,content:{name:`Class ${id}`}};}} as never);
  assert.deepEqual(ids,['one','two']);assert.match(JSON.stringify(result.content),/Class one/);assert.equal(result.content.result_count,2);
});
test('a temporary child hydration failure can be retried using the same shortcut',async()=>{
  const parent={...embed,content:{status:'finished',result_count:1,embed_ids:['child']}};
  const failed=await hydrateFitnessResults(parent,{getEmbed:async()=>{throw Error('offline');}} as never);
  let reads=0;const retried=await hydrateFitnessResults(failed,{getEmbed:async()=>{reads++;return {...embed,content:{name:'Recovered class'}};}} as never);
  assert.equal(reads,1);assert.match(JSON.stringify(retried.content),/Recovered class/);assert.ok(!JSON.stringify(retried.content).includes('_tuiUnavailable'));
});
test('Escape during a previous reply preserves a new draft when Enter cannot send yet',async()=>{
  const state=createInitialTuiState();state.screen='chat';state.workspace='chats';state.activeChatId='busy-chat';state.isBusy=true;
  const ctx=context(state);let sends=0;ctx.send=async()=>{sends++;};
  await handleWorkspaceKey(ctx,'',{name:'escape'});state.screen='chats';state.focus='composer';state.input='My next question';
  await handleWorkspaceKey(ctx,'',{name:'return'});assert.equal(sends,0);assert.equal(state.input,'My next question');assert.equal(state.drafts.new,'My next question');
  state.isBusy=false;await handleWorkspaceKey(ctx,'',{name:'return'});assert.equal(sends,1);
});
test('header title is bold, nav omits chat title and active workspace has a color',()=>{
  const state=createInitialTuiState();state.screen='chat';state.activeChat={id:'saved',title:'Dance plans',category:'medical_health',mateName:'Melvin'} as never;
  state.messages=[{role:'assistant',title:'Assistant',category:'medical_health',content:'A helpful answer'},{role:'assistant',title:'Assistant',category:'software_development',content:'A technical answer'}];
  const frame=renderTuiFrame(state,160,32,{colorMode:'truecolor'}),nav=frame.split('\n')[0];
  assert.ok(!nav.includes('Dance plans'));assert.ok(nav.includes('\x1b[38;2;255;85;59m'));assert.match(frame,/\x1b\[1m[^\n]*Dance plans/);assert.match(stripAnsi(frame),/Melvin/);assert.match(stripAnsi(frame),/Sophia/);
});
test('composer caret follows Unicode, wrapping and cursor editing on large workspaces',async()=>{
  const state=createInitialTuiState();state.focus='composer';state.input='漢🧪abc';state.inputCursor=3;
  assert.deepEqual(tuiComposerCursor(state,160,24),{row:21,column:38});
  state.workspace='tasks';state.screen='tasks';assert.deepEqual(tuiComposerCursor(state,240,24),{row:21,column:78});
  state.input='one\ntwo\nthree\nfour\nfive';state.inputCursor=1;
  const rows=stripAnsi(renderTuiFrame(state,160,24)).split('\n');assert.ok(rows.some(row=>row.includes('> one')));assert.ok(!rows.some(row=>row.includes('five')));
  const ctx=context(state);await handleWorkspaceKey(ctx,'',{ctrl:true,name:'y'});assert.equal(state.textSelection,true);assert.equal(tuiComposerCursor(state,160,24),null);
  await handleWorkspaceKey(ctx,'X',{name:'x'});assert.ok(!state.input.includes('X'));await handleWorkspaceKey(ctx,'',{name:'escape'});assert.equal(state.textSelection,false);
});
