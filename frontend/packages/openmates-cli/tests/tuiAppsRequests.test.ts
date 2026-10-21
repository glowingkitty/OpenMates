// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import {test,after} from 'node:test';
import {mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import type {DecryptedMemoryEntry,OpenMatesClient} from '../src/client.js';
import {createInitialTuiState} from '../src/tuiRenderer.js';
import {handleWorkspaceCommand,handleWorkspaceKey,submitTuiAppsRequest,type WorkspaceContext} from '../src/tuiWorkspaceController.js';
import {interpretTuiAppsRequest,expireTuiAppsRecommendations,parseTuiAppsLibrary,renderTuiAppsResultCards,renderTuiAppsWorkspace,tuiAppsLibraryEntries,type TuiApp} from '../src/tuiAppsWorkspace.js';
import {lineText,cells} from '../src/tuiText.js';

const previousStateDir = process.env.OPENMATES_STATE_DIR;
const privacyStateDir = mkdtempSync(join(tmpdir(), 'openmates-apps-privacy-unit-'));
process.env.OPENMATES_STATE_DIR = privacyStateDir;
after(() => {
  if (previousStateDir === undefined) delete process.env.OPENMATES_STATE_DIR; else process.env.OPENMATES_STATE_DIR = previousStateDir;
  rmSync(privacyStateDir, {recursive:true,force:true});
});

const app:TuiApp={id:'web',name:'Web',description:'Browse websites',category:'research',skills:[{id:'search',name:'Search',description:'Find websites',providers:['Brave']}],focusModes:[],settingsMemories:[]};
function fixture(overrides:Record<string,unknown>={}) {
  const state=createInitialTuiState();state.workspace='apps';state.screen='app';state.activeApp=app;state.apps=[app];state.signedIn=true;
  const sent:string[]=[];
  const client={hasSession:()=>true,getActiveTeamId:()=>null,whoAmI:async()=>({id:"11111111-1111-4111-8111-111111111111"}),listMemories:async()=>[],...overrides} as unknown as OpenMatesClient;
  const context:WorkspaceContext={state,client,terminal:{width:120,height:36} as never,render:()=>{},command:async(command)=>{await handleWorkspaceCommand(context,command);},send:async(text)=>{sent.push(text);}};
  return {state,client,context,sent};
}

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract,cli.surface.semantic-parity
test('Apps natural language request waits for routing before fullscreen and hands chat readable context',async()=>{
  let release:(value:unknown)=>void=()=>{},started!:()=>void;
  const admitted=new Promise<void>(resolve=>{started=resolve;});
  const {state,context,sent}=fixture({interpretAppsWorkspaceRequest:(request:Record<string,unknown>)=>new Promise(resolve=>{release=value=>resolve({...value as object,request_id:request.request_id});started();})});
  state.screen='app-result';state.activeAppResult={embedId:'prior',appId:'web',skillId:'search',status:'finished',content:{input:{query:'gardens'}},children:[{embedId:'child',type:'web-website',content:{title:'Community garden',url:'https://garden.example'}}]};
  const pending=submitTuiAppsRequest(context,'Explain the first result');
  assert.equal(state.screen,'app-result');assert.equal(sent.length,0);assert.equal(state.appRequestBusy,true);
  await admitted;release({action:'chat'});await pending;
  assert.equal(state.workspace,'chats');assert.equal(sent.length,1);assert.match(sent[0],/Explain the first result[\s\S]*gardens[\s\S]*Community garden[\s\S]*garden.example/);
  assert.equal(state.appRequestBusy,false);
});

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract,workflows.surface.semantic-parity,pii.surface.semantic-parity
test('Apps workflow handoff submits authoring once with existing result context',async()=>{
  const authored:Record<string,unknown>[]=[];
  const {state,context}=fixture({interpretAppsWorkspaceRequest:async(request:Record<string,unknown>)=>{assert.ok(!String(request.text).includes('private@example.invalid'));return {action:'workflow',request_id:request.request_id};},
    startWorkflowInput:async(request:Record<string,unknown>)=>{authored.push(request);return {session_id:'session',status:'processing'};}});
  await submitTuiAppsRequest(context,'Make this a weekly workflow for private@example.invalid');
  assert.equal(authored.length,1);assert.equal(authored[0].text,'Make this a weekly workflow for private@example.invalid');assert.equal(state.workspace,'workflows');assert.equal(state.workflowInputSessionId,'session');assert.equal(state.form,null);
});

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract
test('Apps rejects foreign request plans and validates selected skill schema before execution',async()=>{
  const {client}=fixture({interpretAppsWorkspaceRequest:async()=>({action:'execute',request_id:'foreign',skill_id:'search',input:{query:'x'}})});
  await assert.rejects(interpretTuiAppsRequest(client,app,'find gardens'),/invalid request plan/);
  client.interpretAppsWorkspaceRequest=async(request)=>({action:'execute',request_id:request.request_id,skill_id:'search',input:{}});
  client.getAppsWorkspaceSkillDetails=async()=>({app_id:'web',skill_id:'search',input_schema:{type:'object',required:['query'],properties:{query:{type:'string'}}},execution_available:true});
  await assert.rejects(interpretTuiAppsRequest(client,app,'find gardens'),/valid request/);
});

// contract-test: supporting surface=cli assertions=apps.library.embeds-account-paginated,cli.surface.semantic-parity
test('Apps library keeps saved searches first and excludes expired recommendations',()=>{
  const {state}=fixture(),now=Date.now();
  state.appLibrary=parseTuiAppsLibrary({app_id:'web',daily_searches_enabled:true,saved_searches:[{id:'saved',skill_id:'search',title:'Gardens',query:'gardens',parameters:{query:'gardens'}}],recommendations:[{id:'fresh',skill_id:'search',created_at:now-100,expires_at:now+10000,result:{results:[{title:'Garden result',url:'https://garden.example'}]}},{id:'stale',created_at:now-90000000,expires_at:now-1}]},'web',now);
  state.appResults={items:[{embedId:'recent',appId:'web',skillId:'search',createdAt:now,status:'finished'}],offset:0,hasMore:false};
  assert.deepEqual(state.appLibrary.recommendations.map(item=>item.id),['fresh']);
  const entries=tuiAppsLibraryEntries(state);assert.equal(entries[0].section,'Saved');assert.equal(entries[1].section,'Recent');assert.ok(entries.some(item=>item.section==='Example chats'));
  const text=renderTuiAppsWorkspace(state,100).map(lineText).join('\n');assert.match(text,/Recommended[\s\S]*Garden result[\s\S]*Saved[\s\S]*Gardens[\s\S]*Recent/);assert.doesNotMatch(text,/input form|Which app skill/);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,terminal-pointer.visible-action-parity
test('Apps result grid renders meaningful child preview cards with working local child actions',async()=>{
  const {state,context}=fixture();
  state.screen='app-result';state.activeAppResult={embedId:'root',appId:'web',skillId:'search',status:'finished',content:{results:[{title:'duplicated parent'}]},children:[{embedId:'child',type:'web-website',content:{title:'Garden result',url:'https://garden.example',description:'Open every day'}}]};
  const lines=renderTuiAppsResultCards(state.activeAppResult,100);const text=lines.map(lineText).join('\n');
  assert.match(text,/Garden result[\s\S]*Open every day[\s\S]*garden.example/);assert.doesNotMatch(text,/duplicated parent|Response|app_id/);assert.ok(lines.every(line=>cells(lineText(line))<=100));
  state.focus='composer';state.input='Only Sunday gardens';state.filter='Garden';state.scrollOffset=4;state.selectedIndex=2;
  await handleWorkspaceCommand(context,'/embed child');assert.equal(state.detailEmbed?.embedId,'child');assert.equal(state.detailEmbed?.content?.title,'Garden result');
  assert.equal(state.screen,'embed');assert.match(state.detailLines.join('\n'),/Garden result[\s\S]*garden.example[\s\S]*Open every day/);
  await handleWorkspaceKey(context,'',{name:'escape'});
  assert.equal(state.workspace,'apps');assert.equal(state.screen,'app-result');assert.equal(state.activeAppResult?.embedId,'root');assert.equal(state.detailEmbed,null);
  assert.equal(state.focus,'composer');assert.equal(state.input,'Only Sunday gardens');assert.equal(state.filter,'Garden');assert.equal(state.scrollOffset,4);assert.equal(state.selectedIndex,2);
  assert.match(renderTuiAppsResultCards(state.activeAppResult!,100,state.filter).map(lineText).join('\n'),/Garden result[\s\S]*Open every day[\s\S]*garden.example/);
});

// contract-test: supporting surface=cli assertions=apps.library.embeds-account-paginated,terminal-pointer.visible-action-parity
test('first saved search offers OK and Turn off and later saves preserve disabled Daily searches',async()=>{
  const savedRequests:Record<string,unknown>[]=[];
  let enabled=true,first=true;
  const library=()=>({app_id:'web',daily_searches_enabled:enabled,saved_searches:[{id:'saved',skill_id:'search',title:'Gardens',query:'gardens',parameters:{query:'gardens'}}],recommendations:[],first_save:first});
  const {state,context}=fixture({whoAmI:async()=>({id:'owner'}),saveAppsWorkspaceSearch:async(_app:string,request:Record<string,unknown>)=>{savedRequests.push(request);return library();},
    updateAppsWorkspaceSettings:async(_app:string,request:Record<string,unknown>)=>{enabled=request.daily_searches_enabled===true;return library();}});
  state.screen='app-result';state.activeAppResult={embedId:'root',appId:'web',skillId:'search',status:'finished',content:{input:{query:'gardens'},request_text:'Find gardens'},children:[]};
  await handleWorkspaceCommand(context,'/app-save');assert.equal(savedRequests[0].query,'Find gardens');assert.equal(savedRequests[0].title,'Find gardens');assert.equal(state.appDailyNotice,true);
  const notice=renderTuiAppsResultCards(state.activeAppResult,100,'',state.appDailyNotice);
  const commands=notice.flatMap(line=>typeof line==='string'?[]:(line.spans??[]).flatMap(span=>span.action?.kind==='command'?[span.action.command]:[]));
  assert.ok(commands.includes('/app-daily-ok'));assert.ok(commands.includes('/app-daily off'));
  await handleWorkspaceCommand(context,'/app-daily off');assert.equal(state.appDailyNotice,false);assert.equal(state.appLibrary.dailySearchesEnabled,false);
  first=false;await handleWorkspaceCommand(context,'/app-save');assert.equal(state.appDailyNotice,false);assert.equal(state.appLibrary.dailySearchesEnabled,false);
});

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract
 test('Apps navigation during interpretation discards the plan before skill dispatch',async()=>{
  let resolve:(value:unknown)=>void=()=>{},dispatches=0,started!:()=>void;
  const admitted=new Promise<void>(done=>{started=done;});
  const {state,context}=fixture({interpretAppsWorkspaceRequest:(request:Record<string,unknown>)=>new Promise(done=>{resolve=value=>done({...value as object,request_id:request.request_id});started();}),
    getAppsWorkspaceSkillDetails:async()=>({app_id:'web',skill_id:'search',input_schema:{type:'object'},execution_available:true}),runSkill:async()=>{dispatches++;}});
  const pending=submitTuiAppsRequest(context,'Find gardens');await admitted;state.routeVersion++;state.screen='apps';resolve({action:'execute',skill_id:'search',input:{query:'gardens'}});await pending;
  assert.equal(dispatches,0);assert.equal(state.screen,'apps');assert.equal(state.appRequestBusy,false);
});

// contract-test: supporting surface=cli assertions=apps.recommendations.private-daily
test('Apps private recommendations remain separate and expire into fresh public fallback even while open',async()=>{
  const now=Date.now();let publicCalls=0;
  const batch=(id:string,expires:number)=>({id,skill_id:'search',created_at:now-100,expires_at:expires,input:{query:id},request_text:id,result:{results:[{title:id,url:'https://example.test/result'}]}});
  const {state,context}=fixture({getAppsWorkspaceLibrary:async()=>({app_id:'web',daily_searches_enabled:true,saved_searches:[],recommendations:[batch('private',now+1000)]}),
    getAppsWorkspacePublicRecommendations:async()=>{publicCalls++;return {recommendations:[batch('public',now+10000),batch('stale',now-1)]};},
    listAppsWorkspaceResults:async()=>({items:[],offset:0,has_more:false})});
  await handleWorkspaceCommand(context,'/app web');assert.equal(publicCalls,1);assert.deepEqual(state.appLibrary.recommendations.map(item=>item.id),['private']);assert.deepEqual(state.appPublicRecommendations.map(item=>item.id),['public']);
  await handleWorkspaceCommand(context,'/app-recommendation private');assert.equal(state.activeAppResult?.content.input&&JSON.stringify(state.activeAppResult.content.input),'{"query":"private"}');
  assert.equal(expireTuiAppsRecommendations(state,now+1001),true);assert.deepEqual(state.appLibrary.recommendations.map(item=>item.id),['public']);assert.equal(state.activeAppResult?.status,'expired');assert.deepEqual(state.activeAppResult?.content,{});
  const rendered=renderTuiAppsResultCards(state.activeAppResult!,100).map(lineText).join('\n');assert.match(rendered,/recommendation expired/);assert.doesNotMatch(rendered,/private/);
});

// contract-test: supporting surface=cli assertions=apps.recommendations.private-daily
test('guest Apps home fetches public inspiration without reading account libraries',async()=>{
  let privateCalls=0;const now=Date.now();
  const {state,context}=fixture({hasSession:()=>false,getSession:()=>null,getAppsWorkspaceLibrary:async()=>{privateCalls++;throw Error('private read');},
    getAppsWorkspacePublicRecommendations:async()=>({recommendations:[{id:'public',skill_id:'search',created_at:now-100,expires_at:now+10000,result:{results:[{title:'Public garden',url:'https://example.test/garden'}]}}]})});
  state.signedIn=false;await handleWorkspaceCommand(context,'/app web');assert.equal(privateCalls,0);assert.deepEqual(state.appLibrary.recommendations.map(item=>item.id),['public']);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,apps.recommendations.private-daily
test('Apps falls back to bounded decrypted Focus chats before published examples',async()=>{
  let limit=0;
  const {state,context}=fixture({getAppsWorkspaceLibrary:async()=>({app_id:'web',saved_searches:[],recommendations:[],daily_searches_enabled:true}),listAppsWorkspaceResults:async()=>({items:[],has_more:false}),
    listCachedChats:async(count:number)=>{limit=count;return {chats:[{id:'related',title:'Planning a garden',summary:'Web research',activeFocusId:'web-research'},{id:'other',title:'Other private chat',activeFocusId:'health-appointments'}]};}});
  await handleWorkspaceCommand(context,'/app web');assert.equal(limit,60);const entries=tuiAppsLibraryEntries(state);assert.equal(entries[0].command,'/chat related');assert.equal(entries[0].section,'Recent');assert.ok(entries.slice(1).some(item=>item.section==='Example chats'));assert.ok(!entries.some(item=>item.command==='/chat other'));
});

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract,pii.surface.semantic-parity
test('Apps interpretation protects text and nested prior context then restores accepted native input locally',async()=>{
  const email='owner@example.invalid',secret='OrbitPrivateProject';
  const opaque='https://example.test/file?X-Amz-Signature=opaque-owner@example.invalid';
  let submitted:Record<string,any>|undefined;
  const {client}=fixture({listMemories:async()=>[
    {id:'custom',app_id:'privacy',item_type:'personal_data_entry',data:{enabled:true,textToHide:secret,replaceWith:'[PROJECT]'}},
    {id:'readonly',app_id:'email',item_type:'account',data:{private_note:'Readonly memories must not enter the interpreter'}},
  ] as DecryptedMemoryEntry[],interpretAppsWorkspaceRequest:async(request:Record<string,any>)=>{
    submitted=request;
    assert.ok(!request.text.includes(email)&&!request.text.includes(secret));
    assert.equal(request.context.input.requests[0].signed_url,opaque);
    assert.equal(request.context.input.requests[0].url,opaque);
    assert.equal(request.expected_user_id,"11111111-1111-4111-8111-111111111111");
    assert.ok(!request.context.input.requests[0].query.includes(email));
    assert.ok(!request.context.input.requests[0].query.includes(secret));
    assert.ok(!JSON.stringify(request.context.result).includes(email));
    assert.ok(!JSON.stringify(request.context.result).includes(secret));
    assert.equal(request.context.input.pii_mappings,undefined);
    assert.ok(!JSON.stringify(request).includes('Readonly memories'));
    return {action:'execute',request_id:request.request_id,skill_id:'search',input:{requests:[{query:request.context.input.requests[0].query,count:3}]}};
  },getAppsWorkspaceSkillDetails:async()=>({app_id:'web',skill_id:'search',input_schema:{type:'object',required:['requests'],properties:{requests:{type:'array',items:{type:'object',required:['query','count'],properties:{query:{type:'string'},count:{type:'integer',minimum:1}}}}}},execution_available:true})});
  const originalInput={requests:[{query:`Contact ${email} about ${secret}`,count:3,signed_url:opaque,url:opaque}],pii_mappings:[{original:email,placeholder:'[EMAIL]'}]};
  const prior={embedId:'11111111-1111-4111-8111-111111111111',appId:'web',skillId:'search',status:'finished',content:{input:originalInput},children:[{embedId:'child',type:'web-website',content:{title:`${secret}: ${email}`,url:'https://example.test',description:'Private result'}}]};
  const plan=await interpretTuiAppsRequest(client,app,`Find ${secret} and email ${email}`,prior);
  assert.equal(plan.action,'execute');assert.deepEqual(plan.run?.input,{requests:[{query:originalInput.requests[0].query,count:3}]});
  assert.equal(plan.run?.requestText,`Find ${secret} and email ${email}`);
  assert.equal(prior.content.input,originalInput);assert.equal(prior.children[0].content.title,`${secret}: ${email}`);
  assert.equal(submitted?.context.embed_id,prior.embedId);assert.equal(submitted?.context.skill_id,'search');
});

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract,pii.surface.semantic-parity
test('Apps chat handoff keeps original private request and result context while parser receives protected text',async()=>{
  const email='private@example.invalid';let parsed:Record<string,any>|undefined;
  const {state,context,sent}=fixture({interpretAppsWorkspaceRequest:async(request:Record<string,any>)=>{parsed=request;return {action:'chat',request_id:request.request_id};}});
  state.screen='app-result';state.activeAppResult={embedId:'prior',appId:'web',skillId:'search',status:'finished',content:{input:{query:email}},children:[{embedId:'child',type:'web-website',content:{title:email}}]};
  await submitTuiAppsRequest(context,`Explain the result for ${email}`);
  assert.equal(sent.length,1);assert.ok(sent[0].includes(email));assert.ok(sent[0].includes('Previous web/search request and results'));
  assert.ok(!JSON.stringify(parsed).includes(email));assert.ok(!JSON.stringify(parsed).includes('original'));
});

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract,pii.surface.semantic-parity
test('Apps privacy failures stop before parser egress and unknown response mappings never reach native execution',async()=>{
  let calls=0;
  const {client}=fixture({listMemories:async()=>{throw Error('Privacy preferences unavailable');},interpretAppsWorkspaceRequest:async()=>{calls++;}});
  await assert.rejects(interpretTuiAppsRequest(client,app,'Contact owner@example.invalid'),/Privacy preferences unavailable/);assert.equal(calls,0);
  client.listMemories=async()=>[];
  client.interpretAppsWorkspaceRequest=async(request)=>{calls++;return {action:'execute',request_id:request.request_id,skill_id:'search',input:{query:'[OM_PII_00000000000000000000000000000001]'}};};
  client.getAppsWorkspaceSkillDetails=async()=>({app_id:'web',skill_id:'search',input_schema:{type:'object',required:['query'],properties:{query:{type:'string'}}},execution_available:true});
  await assert.rejects(interpretTuiAppsRequest(client,app,'Find gardens'),/pii_mapping_unavailable/);assert.equal(calls,1);
  writeFileSync(join(privacyStateDir,'privacy-preferences.json'),'{invalid preferences');
  try {await assert.rejects(interpretTuiAppsRequest(client,app,'Find gardens'));assert.equal(calls,1);}
  finally {rmSync(join(privacyStateDir,'privacy-preferences.json'));}
});

// contract-test: supporting surface=cli assertions=apps.execution.direct-shared-contract,pii.surface.semantic-parity
test('Apps discards privacy preparation when its Personal account becomes a Team before egress',async()=>{
  let team:string|null=null,calls=0;
  const {client}=fixture({getActiveTeamId:()=>team,listMemories:async()=>{team='other-team';return [];},interpretAppsWorkspaceRequest:async()=>{calls++;}});
  await assert.rejects(interpretTuiAppsRequest(client,app,'Find owner@example.invalid'),/account context changed/);
  assert.equal(calls,0);
});
