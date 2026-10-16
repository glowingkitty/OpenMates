// contract-test-file: infrastructure
/* eslint-disable no-control-regex -- Verify trusted ANSI styling without accepting terminal controls from chat text. */
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createInitialTuiState, renderMessageContentStyled, renderTuiFrame} from '../src/tuiRenderer.js';
import {handleWorkspaceCommand,handleWorkspaceKey,type WorkspaceContext} from '../src/tuiWorkspaceController.js';
import {aliasForEmbed,hydrateChatEmbedPreviews,registerChatEmbedAliases} from '../src/tuiEmbeds.js';
import {chatResultsViews} from '../src/tuiChatResults.js';
import {parseMessageSegments} from '../src/messageSegments.js';
import {lineText,stripAnsi} from '../src/tuiText.js';
import type {DecryptedEmbed} from '../src/client.js';

const reference='```json_embed\n'+JSON.stringify({embed_id:'search',app_id:'fitness',skill_id:'search_classes'})+'\n```';
const results='```embeds_results_view\ntitle: Mapped results\nsources: search\n```';
const embed=(id:string,content:Record<string,unknown>,type='fitness-class'):DecryptedEmbed=>({id,embedId:id,type,appId:'fitness',skillId:'search_classes',content,textPreview:null,createdAt:null});
const parent=embed('search',{status:'finished',embed_ids:['one','two'],result_count:2,filters:{city:'Berlin'}},'app_skill_use');
const one=embed('one',{name:'Morning Dance',date:'2026-10-14',time_range:'09:00–10:00',venue_lat:52.51,venue_lon:13.4,venue_name:'Studio One'});
const two=embed('two',{name:'Evening Dance',date:'2026-10-14',time_range:'18:00–19:00',venue_lat:52.52,venue_lon:13.41,venue_name:'Studio Two'});
function context(content=reference+'\n'+results,client:Record<string,unknown>={}):WorkspaceContext {
  const state=createInitialTuiState();state.screen='chat';state.workspace='chats';state.activeChatId='chat';
  state.messages=[{role:'user',content:'Find dance classes',embedIds:['search']},{role:'assistant',content}];
  const ctx={state,client,terminal:{width:160,height:50},render:()=>{},send:async()=>{}} as unknown as WorkspaceContext;
  ctx.command=async command=>{await handleWorkspaceCommand(ctx,command);};return ctx;
}

test('chat renders bold headings and usable inline commands while text-only user metadata stays absent',()=>{
  const ctx=context('### Dance options\n**Verified** [Watch](wiki:Apple_Watch) and [Dance](embed:search)');
  ctx.state.chatEmbeds.search=parent;registerChatEmbedAliases(ctx.state);
  const styled=renderMessageContentStyled(ctx.state.messages[1].content,160,new Map([['search',parent]]),ctx.state);
  assert.ok(styled.some(line=>typeof line!=='string'&&line.bold&&line.text==='Dance options'));
  assert.ok(styled.some(line=>typeof line!=='string'&&line.spans?.some(span=>span.text==='Verified'&&span.bold)));
  const text=styled.map(lineText).join('\n');assert.match(text,/\/wiki Apple_Watch/);assert.match(text,/\/embed fit-s_c-1/);
  assert.doesNotMatch(text,/\*\*|###|\(wiki:|\(embed:|╭/);
  const frame=renderTuiFrame(ctx.state,160,50,{colorMode:'truecolor'});
  assert.match(frame,/\x1b\[1m/);assert.doesNotMatch(stripAnsi(frame),/Search classes|2 classes/);
});

test('source-only results hydrate cached children and allocate actionable aliases without duplicate preview cards',async()=>{
  const reads:string[]=[];const fixtures:Record<string,DecryptedEmbed>={search:parent,one,two};
  const ctx=context(results,{getEmbed:async(id:string,options:Record<string,unknown>)=>{reads.push(id);assert.equal(options.preferCache,true);assert.equal(options.chatId,'chat');return fixtures[id];}});
  await hydrateChatEmbedPreviews(ctx.state,ctx.client,ctx.render);
  assert.ok(reads.includes('search')&&reads.includes('one')&&reads.includes('two'));
  assert.equal(aliasForEmbed(ctx.state,'search'),'fit-s_c-1');assert.equal(aliasForEmbed(ctx.state,'one'),'fit-s_c-1-1');
  assert.equal(chatResultsViews(ctx.state).length,1);
  const frame=stripAnsi(renderTuiFrame(ctx.state,160,50));
  assert.match(frame,/Mapped results · Map · 2 results/);assert.match(frame,/Morning Dance/);assert.match(frame,/\/embed fit-s_c-1-2/);
  assert.doesNotMatch(frame,/embeds_results_view|sources:|Search classes/);
});

test('calendar and map switch by command and keyboard; nested embed Escape returns through results to chat',async()=>{
  const fixtures:Record<string,DecryptedEmbed>={search:parent,one,two};
  const ctx=context(reference+'\n'+results,{getEmbed:async(id:string)=>fixtures[id]});
  await hydrateChatEmbedPreviews(ctx.state,ctx.client,ctx.render);
  await ctx.command('/view 1 calendar');assert.equal(ctx.state.screen,'results-view');
  assert.match(stripAnsi(renderTuiFrame(ctx.state,160,50)),/Mapped results · Calendar · 2 results/);
  await ctx.command('/embed fit-s_c-1-1');assert.equal(ctx.state.detailTitle,'Morning Dance');
  await handleWorkspaceKey(ctx,'',{name:'escape'});assert.equal(ctx.state.screen,'results-view');
  await handleWorkspaceKey(ctx,'m',{name:'m'});assert.equal(ctx.state.resultsViewModes[1],'map');
  await handleWorkspaceKey(ctx,'',{name:'escape'});assert.equal(ctx.state.screen,'chat');
  assert.match(stripAnsi(renderTuiFrame(ctx.state,160,50)),/Mapped results · Map/);
  await handleWorkspaceKey(ctx,'',{name:'escape'});assert.equal(ctx.state.screen,'start');assert.deepEqual(ctx.state.resultsViewModes,{});
});

test('wiki links open the existing summary API, preserve language, and ignore completion after leaving',async()=>{
  let resolve!:(value:Record<string,unknown>)=>void;const response=new Promise<Record<string,unknown>>(done=>{resolve=done;});
  const calls:string[][]=[];const ctx=context('Read [Watch](wiki:de:Apple_Watch)',{wikipediaSummary:async(title:string,language:string)=>{calls.push([title,language]);return response;}});
  const loading=ctx.command('/wiki de:Apple_Watch');assert.equal(ctx.state.screen,'embed');
  await handleWorkspaceKey(ctx,'',{name:'escape'});assert.equal(ctx.state.screen,'chat');
  resolve({title:'Apple Watch',extract:'Late article'});await loading;
  assert.deepEqual(calls,[['Apple_Watch','de']]);assert.equal(ctx.state.screen,'chat');assert.doesNotMatch(ctx.state.detailLines.join('\n'),/Late article/);
  ctx.client.wikipediaSummary=async()=>({title:'Apple Watch',description:'Smartwatch',extract:'Article text',source_url:'https://en.wikipedia.org/wiki/Apple_Watch'});
  await ctx.command('/wiki Apple_Watch');assert.match(ctx.state.detailLines.join('\n'),/Article text/);
  await handleWorkspaceKey(ctx,'',{name:'escape'});assert.equal(ctx.state.screen,'chat');
});

test('late source hydration cannot restore cached results after navigating to a different chat',async()=>{
  let resolve!:(value:DecryptedEmbed)=>void;const response=new Promise<DecryptedEmbed>(done=>{resolve=done;});
  const ctx=context(results,{getEmbed:async()=>response});const loading=hydrateChatEmbedPreviews(ctx.state,ctx.client,ctx.render);
  await handleWorkspaceKey(ctx,'',{name:'escape'});resolve(parent);await loading;
  assert.equal(ctx.state.activeChatId,null);assert.deepEqual(ctx.state.chatEmbeds,{});assert.deepEqual(ctx.state.embedAliases,{});
});

test('embed JSON inside a longer ordinary code fence stays literal and never hydrates',async()=>{
  const code='````markdown\n'+reference+'\n[Dance](embed:search)\n````';
  const ctx=context(code,{getEmbed:async()=>{throw Error('Code examples must never fetch');}});
  assert.equal(parseMessageSegments(code).filter(segment=>segment.type==='embed').length,0);
  registerChatEmbedAliases(ctx.state);assert.deepEqual(ctx.state.embedAliases,{});
  await hydrateChatEmbedPreviews(ctx.state,ctx.client,ctx.render);
  const text=renderMessageContentStyled(code,160).map(lineText).join('\n');
  assert.match(text,/json_embed/);assert.match(text,/\[Dance\]\(embed:search\)/);assert.doesNotMatch(text,/\/embed search|╭/);
});

test('bundled example results use the same map mode and validation as their renderer',async()=>{
  const ctx=context();ctx.state.messages=[];ctx.state.screen='example';
  ctx.state.activeExample={messages:[{role:'assistant',content:'```embeds_results_view\nembeds: one\n```'}],embeds:[{embed_id:'one',type:one.type,content:JSON.stringify(one.content)}]} as typeof ctx.state.activeExample;
  await ctx.command('/view 1');assert.equal(ctx.state.resultsViewModes[1],'map');
  assert.match(stripAnsi(renderTuiFrame(ctx.state,160,50)),/Results view · Map · 1 results/);
});
