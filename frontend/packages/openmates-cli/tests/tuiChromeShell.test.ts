import assert from 'node:assert/strict';
import {test} from 'node:test';
import {emitKeypressEvents} from 'node:readline';
import {PassThrough} from 'node:stream';
import {once} from 'node:events';
import {runTui} from '../src/tui.js';
import type {OpenMatesClient} from '../src/client.js';
import type {TuiTerminal,TerminalKey} from '../src/tuiTerminal.js';
import {listExampleChats} from '../src/exampleChats.js';
import {createInitialTuiState,renderChatHeader,renderTuiFrame,resetEndedTuiSession} from '../src/tuiRenderer.js';
import {cells,lineText,stripAnsi} from '../src/tuiText.js';
import {workspaceGeometry,tuiComposerCursor} from '../src/tuiLayout.js';
import {captureTuiView,closeTuiFullscreen} from '../src/tuiFullscreenChrome.js';
import {createTuiSettingsState} from '../src/tuiSettings.js';
import {closeTuiSettings} from '../src/tuiSettingsShell.js';
import {pointerTargetAt} from '../src/tuiPointer.js';
import {handleWorkspaceKey,handleWorkspaceCommand,openSavedChat,type WorkspaceContext} from '../src/tuiWorkspaceController.js';

function setup(){
  const state=createInitialTuiState();state.signedIn=true;
  const client={hasSession:()=>true,getChatMessages:async(id:string)=>({chat:{id,title:'Project discussion',createdAt:1,updatedAt:1},messages:[{id:'m',role:'user',content:'Read me'}]})};
  const ctx={state,client,terminal:{width:160,height:30},render:()=>{},send:async()=>{},
    command:async(command:string)=>{await handleWorkspaceCommand(ctx,command);}} as unknown as WorkspaceContext;
  return {state,ctx};
}
function actionAt(state:ReturnType<typeof createInitialTuiState>,frame:string,text:string,width:number,height:number){
  const rows=stripAnsi(frame).split('\n'),row=rows.findIndex(line=>line.includes(text));assert.ok(row>=0,text);
  return pointerTargetAt(state,cells(rows[row].slice(0,rows[row].indexOf(text))),row,width,height);
}

// contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned,terminal-chrome.navigation.origin-preserved
test('chat hero centers wide-character title, summary and metadata while adapting its height',()=>{
  const {state}=setup();state.screen='chat';state.activeChat={id:'chat',title:'漢🧪 Notes',summary:'A centered summary',category:'science',createdAt:1} as typeof state.activeChat;
  const wide=renderChatHeader(state,100,32),narrow=renderChatHeader(state,28,14);
  assert.ok(wide.length>=7);assert.ok(narrow.length<wide.length);
  for(const [rows,width] of [[wide,100],[narrow,28]] as const){
    const title=rows.find(row=>lineText(row).includes('漢🧪 Notes'))!;
    assert.ok(title);assert.ok(typeof title!=='string'&&title.background,'category color covers the centered hero');
    const text=lineText(title),left=cells(text.slice(0,text.indexOf('漢🧪 Notes'))),right=width-left-cells('漢🧪 Notes');
    assert.ok(Math.abs(left-right)<=1,`title is centered at ${width} columns`);
    assert.ok(rows.every(row=>cells(lineText(row))<=width));
  }
  assert.ok(wide.some(row=>lineText(row).includes('A centered summary')));
  assert.ok(wide.some(row=>lineText(row).includes('Science')));
  state.activeChat={id:'chat',title:'No summary'} as typeof state.activeChat;
  assert.equal(renderChatHeader(state,100,32).length,7,'loaded headers keep their spacious size without optional metadata');
});

// contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned,terminal-chrome.actions.contextual-and-functional,terminal-pointer.visible-action-parity
test('embed hero and fullscreen actions stay centered and clickable through resize',()=>{
  const {state}=setup();state.screen='embed';state.detailTitle='漢🧪 Map';state.detailLines=['Map details'];
  for(const [width,height] of [[100,32],[28,16],[10,10]] as const){
    const frame=renderTuiFrame(state,width,height,{colorMode:'truecolor'}),raw=frame.split('\n'),plain=stripAnsi(frame).split('\n');
    assert.equal(plain.length,height);assert.ok(plain.every(row=>cells(row)===width));
    const visibleTitle=width<12?'漢🧪 M':'漢🧪 Map';
    const heroIndex=raw.findIndex(row=>row.includes(visibleTitle)&&row.includes('\x1b[48;2;'));
    assert.ok(heroIndex>=0,`colored embed hero is visible at ${width} columns`);
    const row=plain[heroIndex],left=cells(row.slice(0,row.indexOf(visibleTitle))),right=width-left-cells(visibleTitle);
    assert.ok(Math.abs(left-right)<=1,`embed title is centered at ${width} columns`);
    assert.deepEqual(actionAt(state,frame,width<14?'‹':'‹ Back',width,height),{kind:'command',command:'/back'});
    assert.deepEqual(actionAt(state,frame,'×',width,height),{kind:'command',command:'/close'});
  }
  state.screen='chat';state.activeChatId='chat';state.activeChat={id:'chat',title:'Chat'} as typeof state.activeChat;
  state.messages=[{role:'user',content:'Hello'}];
  const narrow=renderTuiFrame(state,28,18);
  assert.deepEqual(actionAt(state,narrow,'More',28,18),{kind:'command',command:'/header more'});
});

// contract-test: supporting surface=cli assertions=terminal-chrome.navigation.origin-preserved,terminal-ui.workspaces.web-aligned
test('embed scrolling keeps the whole adaptive hero together or releases it on short screens',()=>{
  const {state}=setup();state.screen='embed';state.detailTitle='Scroll-safe embed';
  state.detailLines=Array.from({length:60},(_,index)=>`Detail ${index}`);
  const wideTop=renderTuiFrame(state,100,32,{colorMode:'truecolor'});
  const heroRow=(frame:string)=>frame.split('\n').findIndex(row=>row.includes('Scroll-safe embed')&&row.includes('\x1b[48;2;'));
  assert.ok(heroRow(wideTop)>=0);
  state.scrollOffset=20;
  const wideScrolled=renderTuiFrame(state,100,32,{colorMode:'truecolor'});
  assert.equal(heroRow(wideScrolled),heroRow(wideTop),'the title and its banner stay as one sticky group');
  assert.match(stripAnsi(wideScrolled),/Saved embeds/);
  assert.match(stripAnsi(wideScrolled),/Detail 20/);
  state.scrollOffset=20;
  const shortScrolled=renderTuiFrame(state,28,16,{colorMode:'truecolor'});
  assert.equal(heroRow(shortScrolled),-1,'short screens scroll the whole banner instead of freezing half of it');
  assert.match(stripAnsi(shortScrolled),/Detail 20/);
  assert.deepEqual(actionAt(state,shortScrolled,'‹ Back',28,16),{kind:'command',command:'/back'});
});

// contract-test: supporting surface=cli assertions=terminal-chrome.navigation.origin-preserved
test('chat Close restores its actual project origin and preserves the follow-up draft',async()=>{
  const {state,ctx}=setup();state.workspace='projects';state.screen='project';state.focus='content';
  state.activeProject={id:'project',name:'Trip'} as typeof state.activeProject;
  state.projectTab='tasks';state.selectedIndex=7;state.scrollOffset=4;state.input='Original project draft';
  await openSavedChat(ctx,'chat');state.input='Unsent follow-up';
  await handleWorkspaceCommand(ctx,'/close');
  assert.equal(state.screen,'project');assert.equal(state.workspace,'projects');assert.equal(state.projectTab,'tasks');
  assert.equal(state.selectedIndex,7);assert.equal(state.scrollOffset,4);assert.equal(state.input,'Original project draft');
  assert.equal(state.drafts.chat,'Unsent follow-up');
});

// contract-test: supporting surface=cli assertions=terminal-chrome.navigation.origin-preserved
test('embed Back preserves the chat draft, history position and selection',()=>{
  const {state}=setup();state.screen='chat';state.activeChatId='chat';state.input='Draft';state.inputCursor=2;
  state.scrollOffset=14;state.selectedIndex=3;state.embedOrigin=captureTuiView(state);
  state.screen='embed';state.input='';state.scrollOffset=0;state.selectedIndex=0;
  assert.equal(closeTuiFullscreen(state),true);assert.equal(state.screen,'chat');
  assert.equal(state.input,'Draft');assert.equal(state.inputCursor,2);assert.equal(state.scrollOffset,14);assert.equal(state.selectedIndex,3);
});

// contract-test: supporting surface=cli assertions=terminal-settings.shell.responsive-and-restorable,terminal-pointer.viewport-coherent
test('Settings splits on the right at wide widths, goes fullscreen when narrow and preserves fields and composer',()=>{
  const {state}=setup();state.screen='chat';state.input='Kept message';state.focus='settings';
  state.settings=createTuiSettingsState('owner');state.settings.route='interface/language';state.settings.drafts['interface/language']={language:'draft'};
  state.settingsRestore={focus:'composer',sidebarOpen:true};
  const wide=renderTuiFrame(state,160,30,{colorMode:'truecolor'});
  assert.match(stripAnsi(wide),/Settings {2}\/ {2}Language/);assert.match(stripAnsi(wide),/Kept message/);
  assert.equal(workspaceGeometry(state,160).sidebarWidth,0);assert.equal(workspaceGeometry(state,160).settingsWidth,44);assert.equal(workspaceGeometry(state,160).composerWidth,100);
  assert.equal(tuiComposerCursor(state,160,30),null);
  assert.equal(actionAt(state,wide,'Language code:',160,30)?.kind,'command');
  const wideRows=stripAnsi(wide).split('\n');
  const languageRow=wideRows.find(row=>row.includes('Language code:'))!;
  assert.equal(languageRow[160-2-44],'│');
  assert.ok(languageRow.indexOf('Language code:')>160-2-44,'Settings control is in the right pane');
  assert.ok(wideRows.find(row=>row.includes('Kept message'))!.indexOf('Kept message')<160-2-44,'draft stays in the left pane');
  assert.equal(actionAt(state,wide,'Kept message',160,30),null,'Settings does not click through to the composer');
  const narrow=renderTuiFrame(state,80,30);assert.doesNotMatch(narrow,/Kept message/);
  assert.equal(workspaceGeometry(state,80).settingsFullscreen,true);
  assert.equal(pointerTargetAt(state,70,26,80,30),null);
  for(const [width,height] of [[160,30],[80,20],[30,14],[5,5],[1,1]]){
    const rows=stripAnsi(renderTuiFrame(state,width,height)).split('\n');assert.equal(rows.length,height);assert.ok(rows.every(line=>cells(line)===width));
  }
  assert.equal(state.settings.drafts['interface/language'].language,'draft');closeTuiSettings(state);
  assert.equal(state.input,'Kept message');assert.equal(state.focus,'composer');assert.equal(state.sidebarOpen,true);
});

// contract-test: supporting surface=cli assertions=terminal-settings.shell.responsive-and-restorable,terminal-pointer.viewport-coherent
test('closing split Settings produces a clean full-width frame without its old divider',()=>{
  const {state}=setup();state.screen='chat';state.activeChatId='chat';
  state.activeChat={id:'chat',title:'Full width after close'} as typeof state.activeChat;
  state.messages=[{role:'user',content:'A chat message'}];state.sidebarOpen=false;
  state.settings=createTuiSettingsState('owner');state.settingsRestore={focus:'composer',sidebarOpen:false};state.focus='settings';
  const split=stripAnsi(renderTuiFrame(state,160,30)).split('\n');
  const dividerColumn=160-2-44;
  assert.equal(split[12]?.[dividerColumn],'│');
  assert.ok(dividerColumn>=0,'split frame has a settings divider');
  closeTuiSettings(state);
  const full=stripAnsi(renderTuiFrame(state,160,30)).split('\n');
  assert.equal(full.length,30);
  assert.ok(full.every(row=>cells(row)===160));
  assert.ok(full.slice(5,24).every(row=>Array.from(row)[dividerColumn]!=='│'),'old settings divider is gone in the completed frame');
  assert.match(full.join('\n'),/Full width after close/);
});


// contract-test: supporting surface=cli assertions=terminal-settings.shell.responsive-and-restorable,terminal-pointer.viewport-coherent
test('right Settings panel keeps pointer positions at 120, 160 and 200 columns',()=>{
  const {state}=setup();state.screen='chat';state.activeChatId='chat';
  state.activeChat={id:'chat',title:'Visible chat'} as typeof state.activeChat;
  state.messages=[{role:'user',content:'Left-hand conversation'}];state.input='Preserved draft';
  state.settings=createTuiSettingsState('owner');state.settings.route='interface/language';state.focus='settings';
  for(const width of [120,160,200]){
    const frame=renderTuiFrame(state,width,30),rows=stripAnsi(frame).split('\n');
    const geometry=workspaceGeometry(state,width),divider=width-geometry.gutter-geometry.settingsWidth;
    assert.equal(geometry.settingsWidth,44);assert.equal(geometry.sidebarWidth,0);
    assert.ok(rows.every(row=>cells(row)===width));
    const settingRow=rows.find(row=>row.includes('Language code:'))!;
    assert.equal(settingRow[divider],'│');
    assert.ok(settingRow.indexOf('Language code:')>divider);
    assert.ok(rows.find(row=>row.includes('Left-hand conversation'))!.indexOf('Left-hand conversation')<divider);
    assert.equal(actionAt(state,frame,'Language code:',width,30)?.kind,'command');
    assert.deepEqual(actionAt(state,frame,'Settings',width,30),{kind:'command',command:'/settings-close'});
    const inputTop=rows.find(row=>/^\s+╭─+╮\s+$/.test(row))!;
    assert.equal(inputTop.indexOf('╭'),geometry.gutter+geometry.composerInset,'composer is centered in the remaining left pane');
    const composer=rows.find(row=>row.includes('Preserved draft'))!;
    assert.ok(composer.indexOf('Preserved draft')<divider);
  }
});

// contract-test: supporting surface=cli assertions=terminal-pointer.viewport-coherent
test('ordinary chat sidebar pointer stays on the left of the workspace',()=>{
  const {state}=setup();state.workspace='chats';state.screen='chats';state.sidebarOpen=true;
  state.recentChats=[{id:'sidebar-chat',title:'Sidebar pointer chat'} as typeof state.recentChats[number]];
  const frame=renderTuiFrame(state,160,30),rows=stripAnsi(frame).split('\n');
  const row=rows.find(line=>line.includes('Sidebar pointer chat'))!;
  assert.ok(row.indexOf('Sidebar pointer chat')<27);
  const action=actionAt(state,frame,'Sidebar pointer chat',160,30);
  assert.equal(action?.kind,'select');
  assert.equal(action?.target,'sidebar');
  assert.equal(workspaceGeometry(state,160).sidebarWidth,27);
  assert.equal(workspaceGeometry(state,160).settingsWidth,0);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped
test('a render after an owner change removes every old settings value and secret',()=>{
  const {state}=setup();state.settings=createTuiSettingsState('old');state.settings.profile.username='Old private owner';
  state.settings.drafts.secret={value:'Old private draft'};state.settings.data.account={name:'Old account'};
  state.settings.oneTimeSecret='Old private key';state.settings.secretRevealed=true;state.settingsOwnerCurrent=()=>false;
  const frame=renderTuiFrame(state,160,30);assert.doesNotMatch(frame,/Old private|Old account/);
  assert.equal(state.settings.ownerStale,true);assert.equal(state.settings.oneTimeSecret,null);assert.deepEqual(state.settings.drafts,{});
  assert.match(frame,/Account or team changed/);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped,terminal-ui.offline.cache-first
test('confirmed logout clears the private view and drafts before the next terminal frame',async()=>{
  const {state,ctx}=setup();let authenticated=true, stopped=0;
  Object.assign(ctx.client,{hasSession:()=>authenticated,apiUrl:'https://api.example.com',
    getSession:()=>{if(!authenticated)throw new Error('Signed out');return {apiUrl:'https://api.example.com',hashedEmail:'owner',createdAt:1,masterKeyExportedB64:'key'};},
    logout:async()=>{authenticated=false;}});
  let lastFrame='';ctx.render=()=>{resetEndedTuiSession(state,authenticated);lastFrame=renderTuiFrame(state,160,30);};
  state.screen='chat';state.activeChatId='private';state.activeChat={id:'private',title:'Private retained title'} as typeof state.activeChat;
  state.messages=[{role:'user',content:'Private retained message'}];state.input='Private retained input';state.drafts.private='Private retained draft';
  state.homeAbortController=new AbortController();const controller=state.homeAbortController;
  state.chatContextAuthoringControls.private={stop:()=>{stopped++;}};
  await handleWorkspaceCommand(ctx,'/settings');await handleWorkspaceCommand(ctx,'/settings-action action:logout');
  assert.match(lastFrame,/Private retained/);assert.equal(authenticated,true);
  await handleWorkspaceCommand(ctx,'/settings-action confirm');
  assert.equal(authenticated,false);assert.equal(state.signedIn,false);assert.equal(state.activeChatId,null);assert.equal(state.activeChat,null);
  assert.deepEqual(state.messages,[]);assert.deepEqual(state.drafts,{});assert.equal(state.input,'');assert.equal(state.settings,null);
  assert.equal(controller.signal.aborted,true);assert.equal(stopped,1);assert.doesNotMatch(lastFrame,/Private retained/);
  assert.equal(resetEndedTuiSession(state,false),false);assert.equal(stopped,1);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional,terminal-chrome.navigation.origin-preserved
test('keyboard header focus is visible, and Escape dismisses More before closing the chat',async()=>{
  const {state,ctx}=setup();state.screen='chat';state.activeChatId='chat';state.activeChat={id:'chat',title:'A chat'} as typeof state.activeChat;
  state.messages=[{role:'user',content:'Hello'}];
  const input=new PassThrough();emitKeypressEvents(input);
  const event=once(input,'keypress');input.write('\x1bh');
  const [chunk,key]=await event;
  await handleWorkspaceKey(ctx,chunk,key);assert.equal(state.focus,'header');input.destroy();
  const focused=renderTuiFrame(state,160,30,{colorMode:'truecolor'});assert.ok(focused.includes('\x1b[38;2;50;173;230m'));
  assert.match(stripAnsi(focused),/Alt\+H header/);
  await handleWorkspaceCommand(ctx,'/header more');assert.equal(state.chrome?.kind,'more');
  await handleWorkspaceKey(ctx,'',{name:'escape'});assert.equal(state.chrome,null);assert.equal(state.screen,'chat');
  await handleWorkspaceKey(ctx,'',{name:'escape'});assert.equal(state.screen,'start');
});

// contract-test: supporting surface=cli assertions=terminal-settings.shell.responsive-and-restorable,terminal-chrome.actions.contextual-and-functional
test('Settings stays clickable at the top right and Ctrl+G dismisses chrome before navigation',async()=>{
  const {state,ctx}=setup();state.screen='chat';state.activeChatId='chat';state.messages=[{role:'user',content:'Hello'}];
  const frame=renderTuiFrame(state,220,30);assert.deepEqual(actionAt(state,frame,'Settings',220,30),{kind:'command',command:'/settings'});
  await handleWorkspaceCommand(ctx,'/header more');await handleWorkspaceKey(ctx,'',{ctrl:true,name:'g'});
  assert.equal(state.chrome,null);assert.equal(state.focus,'navigation');
  for(let i=0;i<5;i++)await handleWorkspaceKey(ctx,'',{name:'right'});
  assert.equal(state.navigationIndex,5);assert.match(renderTuiFrame(state,160,30),/› Settings/);
});

// contract-test: supporting surface=cli assertions=terminal-settings.operations.validated-and-owner-scoped,terminal-ui.offline.cache-first
test('the running terminal restores public example cards after confirmed Settings logout',async()=>{
  let authenticated=true,frame='',pressed!:(chunk:string,key:TerminalKey)=>void;
  const client={apiUrl:'https://fake-client.example',hasSession:()=>authenticated,
    // Deliberately mismatched API disables disk cache access for this synthetic client.
    getSession:()=>{if(!authenticated)throw new Error('Signed out');return {apiUrl:'https://fake-session.example',hashedEmail:'fake',createdAt:1,masterKeyExportedB64:'fake'};},
    getActiveTeamId:()=>null,resolveTeamContext:()=>null,
    beginInteractiveViewerSession:()=>{},clearInteractiveChatViewer:()=>{},endInteractiveViewerSession:()=>{},
    getDailyInspirations:async()=>[],listChats:async()=>({chats:[{id:'private',title:'Private account preview'}]}),
    logout:async()=>{authenticated=false;},
  } as unknown as OpenMatesClient;
  const terminal={width:160,height:40,colorMode:'none',ascii:false,
    enter:()=>{},leave:()=>{},onResize:()=>{},onKey:(callback:typeof pressed)=>{pressed=callback;},
    render:(value:string)=>{frame=stripAnsi(value);},
  } as unknown as TuiTerminal;
  const result=runTui(client,terminal,{privacyOffer:async()=>false,privacyInstall:async()=>{},
    updateCheck:async()=>null,updateInstall:async()=>{},updateSkip:()=>{}});
  const visible=async(text:string)=>{
    const deadline=Date.now()+2000;
    while(!frame.includes(text) && Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,10));
    assert.ok(frame.includes(text),`Expected ${text} in terminal frame:\n${frame}`);
  };
  const click=(text:string)=>{
    const rows=frame.split('\n'),row=rows.findIndex(line=>line.includes(text));assert.ok(row>=0,text);
    pressed('',{name:'mouseclick',mouse:{column:cells(rows[row].slice(0,rows[row].indexOf(text))),row}});
  };
  try{
    await visible('Private account preview');
    pressed('Private unsent draft',{name:'paste'});await visible('Private unsent draft');
    click('Settings');await visible('Log out');click('Log out');await visible('Confirm');click('Confirm');
    await visible('Session ended. Sign in to reopen your work.');
    await visible('Explore example chats');
    assert.match(frame,/Chat 1 of/);assert.doesNotMatch(frame,/Private account preview|Private unsent draft|Start a chat below/);
    assert.ok(frame.includes(listExampleChats(20,1).chats[0].title.slice(0,20)),'public example title is visible in the first preview');
  }finally{pressed('',{name:'c',ctrl:true});await result;}
});
