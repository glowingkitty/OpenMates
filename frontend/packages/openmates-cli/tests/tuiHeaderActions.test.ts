import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { headerCapabilities, openHeaderAction, handleHeaderCommand, handleHeaderKey, renderHeaderDialog, type TuiChromeState } from '../src/tuiHeaderActions.js';
import { requestTerminalClipboard } from '../src/tuiClipboard.js';
import type { WorkspaceContext } from '../src/tuiWorkspaceController.js';
import type { TuiState } from '../src/tuiRenderer.js';
import { createTuiShareQr, validTuiShareUrl } from '../src/tuiQrCode.js';

function setup(client:Record<string,unknown>={}) {
  const state={chrome:null,signedIn:true,screen:'chat',activeChatId:'chat-id',status:null,input:'draft',scrollOffset:7} as unknown as TuiState&{chrome:TuiChromeState|null};
  state.activeChat={id:'chat-id',shortId:'chat',title:'Saved Chat',summary:null,updatedAt:null,category:null,mateName:null};
  state.messages=[{role:'user',content:'hello'}];state.input='draft';state.scrollOffset=7;
  let renders=0;
  const context={state,client:{apiUrl:'https://api.openmates.org',...client},render:()=>{renders++;}} as unknown as WorkspaceContext;
  return {state,context,get renders(){return renders;}};
}
function ownedClient(extra:Record<string,unknown>={}){
  const session={apiUrl:'https://api.openmates.org',hashedEmail:'owner-a',activeTeamId:null,createdAt:1,masterKeyExportedB64:'key-a'};
  return {session,client:{hasSession:()=>true,getSession:()=>session,...extra}};
}
const lines=(dialog:TuiChromeState|null)=>renderHeaderDialog(dialog,80).map(line=>typeof line==='string'?line:line.text).join('\n');

// contract-test: supporting surface=cli assertions=terminal-chrome.share.explicit-and-private,terminal-chrome.navigation.origin-preserved
test('opening private Share preserves view and draft; only Generate Link invokes encrypted client',async()=>{
  let calls=0,options:unknown;
  const {state,context}=setup({createChatShareLink:async (...args:unknown[])=>{calls++;options=args;return 'https://openmates.org/share/chat/id#key=secret';}});
  openHeaderAction(context,'share');
  assert.equal(calls,0);assert.equal(state.chrome?.kind,'share');
  assert.match(lines(state.chrome),/Expiration: Never/);
  await handleHeaderCommand(context,'duration');
  await handleHeaderCommand(context,'sensitive');
  await handleHeaderCommand(context,'generate');
  assert.equal(calls,1);assert.deepEqual(options,['chat-id',60,undefined,{includeSensitiveData:true}]);
  assert.doesNotMatch(lines(state.chrome),/secret/);
  assert.match(lines(state.chrome),/Copy Link/);
  assert.match(lines(state.chrome),/Show URL/);
  assert.equal(state.input,'draft');assert.equal(state.scrollOffset,7);
  await handleHeaderKey(context,'',{name:'escape'});
  assert.equal(state.chrome,null);assert.equal(state.screen,'chat');
});

// contract-test: supporting surface=cli assertions=terminal-chrome.share.explicit-and-private,terminal-chrome.actions.contextual-and-functional
test('busy share suppresses duplicate generation and private failures never display client secrets',async()=>{
  let calls=0,finish!:(value:string)=>void;
  const {state,context}=setup({createChatShareLink:async()=>{calls++;return new Promise<string>(resolve=>{finish=resolve;});}});
  openHeaderAction(context,'share');
  const pending=handleHeaderCommand(context,'generate');
  await handleHeaderCommand(context,'generate');assert.equal(calls,1);
  finish('https://openmates.org/share/chat/id#key=secret');await pending;
  assert.equal((state.chrome as Extract<TuiChromeState,{kind:'share'}>).url?.includes('secret'),true);
  const failed=setup({createChatShareLink:async()=>{throw new Error('password=hunter2 #key=private');}});
  openHeaderAction(failed.context,'share');await handleHeaderCommand(failed.context,'generate');
  assert.match(lines(failed.state.chrome),/Could not generate link/);
  assert.doesNotMatch(lines(failed.state.chrome),/hunter2|private/);
  assert.equal(failed.state.status,null);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.share.explicit-and-private
test('share response from a previous owner never reveals its private URL',async()=>{
  let finish!:(value:string)=>void;
  const owner=ownedClient({createChatShareLink:async()=>new Promise<string>(resolve=>{finish=resolve;})});
  const {state,context}=setup(owner.client);
  openHeaderAction(context,'share');const pending=handleHeaderCommand(context,'generate');
  owner.session.hashedEmail='owner-b';
  finish('https://openmates.org/share/chat/id#key=old-private-key');await pending;
  assert.equal(state.chrome,null);assert.equal(state.status,null);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.share.explicit-and-private
test('password stays masked and changed settings invalidate a generated URL',async()=>{
  const {state,context}=setup({createChatShareLink:async()=> 'https://openmates.org/share/chat/id#key=secret'});
  openHeaderAction(context,'share');
  await handleHeaderCommand(context,'focus 1');
  await handleHeaderKey(context,'hunter2',{name:'paste'});
  assert.match(lines(state.chrome),/Password: \*\*\*\*\*\*\*/);
  assert.doesNotMatch(lines(state.chrome),/hunter2/);
  await handleHeaderCommand(context,'generate');assert.match(lines(state.chrome),/Copy Link/);
  await handleHeaderCommand(context,'duration');assert.doesNotMatch(lines(state.chrome),/Copy Link|Show URL/);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional,terminal-chrome.share.explicit-and-private
test('public example reuses its URL and unsupported embed actions are hidden',async()=>{
  const {state,context}=setup({createChatShareLink:async()=>{throw new Error('must not be called');}});
  state.screen='example';state.activeExample={chat:{id:'public-id',shortId:'public',slug:'demo',title:'Demo',summary:null,updatedAt:null,category:null,mateName:null,source:'example'},messages:[],embeds:[],files:[],followUpSuggestions:[]};
  openHeaderAction(context,'share');assert.match(lines(state.chrome),/Public link/);
  await handleHeaderCommand(context,'show-url');assert.match(lines(state.chrome),/\/example\/demo/);
  state.screen='embed';state.detailEmbed={id:'audio',embedId:'audio',type:'audio-recording',content:{},textPreview:null,appId:null,skillId:null,createdAt:null};
  assert.deepEqual(headerCapabilities(state),[]);
  state.detailEmbed={...state.detailEmbed,id:'code',embedId:'code',type:'code',content:{code:'print(1)',language:'python'}};
  assert.deepEqual(headerCapabilities(state).map(item=>item.label),['Share','Copy','Download','More']);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional
test('download confirms overwrite, writes only after confirmation, and reports CLI path',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'openmates-header-'));
  try{
    const {state,context}=setup();openHeaderAction(context,'download');
    assert.equal(state.chrome?.kind,'download');
    const destination=join(directory,'chat.md');await writeFile(destination,'original');
    (state.chrome as Extract<TuiChromeState,{kind:'download'}>).path=destination;
    await handleHeaderCommand(context,'save');assert.match(lines(state.chrome),/Overwrite existing file/);
    assert.equal(await readFile(destination,'utf8'),'original');
    await handleHeaderCommand(context,'overwrite');
    assert.match(await readFile(destination,'utf8'),/hello/);
    assert.equal(state.chrome,null);assert.match(state.status!,/Saved on this CLI machine/);
  }finally{await rm(directory,{recursive:true,force:true});}
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional
test('signed original file downloads only after Save; unsupported Share stays absent',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'openmates-header-file-'));
  const previousFetch=globalThis.fetch;let fetches=0;
  globalThis.fetch=async()=>{fetches++;return new Response(new Uint8Array([0,1,2,255]),{status:200});};
  try{
    const {state,context}=setup();state.screen='embed';
    state.detailEmbed={id:'audio',embedId:'audio',type:'audio-generated',content:{files:{original:{download_url:'https://files.example/original',filename:'recording.mp3'}}},textPreview:null,appId:null,skillId:null,createdAt:null};
    assert.deepEqual(headerCapabilities(state).map(item=>item.label),['Download','More']);
    openHeaderAction(context,'download');assert.equal(fetches,0);
    const destination=join(directory,'recording.mp3');
    (state.chrome as Extract<TuiChromeState,{kind:'download'}>).path=destination;
    await handleHeaderCommand(context,'save');
    assert.equal(fetches,1);assert.deepEqual(await readFile(destination),Buffer.from([0,1,2,255]));
  }finally{globalThis.fetch=previousFetch;await rm(directory,{recursive:true,force:true});}
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional
test('canonical relative original file uses existing authenticated client getRaw',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'openmates-header-relative-'));
  const paths:string[]=[];
  try{
    const {state,context}=setup({getRaw:async(path:string)=>{paths.push(path);return {contentType:'image/png',data:new Uint8Array([1,2,3])};}});
    state.screen='embed';state.detailEmbed={id:'image',embedId:'image',type:'image',content:{files:{original:{asset_id:'asset-123',filename:'image.png'}}},textPreview:null,appId:null,skillId:null,createdAt:null};
    openHeaderAction(context,'download');
    (state.chrome as Extract<TuiChromeState,{kind:'download'}>).path=join(directory,'image.png');
    await handleHeaderCommand(context,'save');
    assert.deepEqual(paths,['/v1/embeds/asset-123/file?format=original']);
    assert.deepEqual(await readFile(join(directory,'image.png')),Buffer.from([1,2,3]));
  }finally{await rm(directory,{recursive:true,force:true});}
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional
test('incomplete cached chat history cannot be exported as a complete chat',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'openmates-header-incomplete-'));
  const options:unknown[]=[];
  try{
    const {state,context}=setup({getChatMessages:async(_id:string,opts:unknown)=>{options.push(opts);return {chat:state.activeChat,messages:[],historyIncomplete:true};}});
    openHeaderAction(context,'download');
    (state.chrome as Extract<TuiChromeState,{kind:'download'}>).path=join(directory,'chat.md');
    await handleHeaderCommand(context,'save');
    assert.deepEqual(options,[undefined]);
    assert.match(lines(state.chrome),/Chat history is incomplete/);
    await assert.rejects(readFile(join(directory,'chat.md')));
  }finally{await rm(directory,{recursive:true,force:true});}
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional
test('owner change during chat export does not write old-owner content',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'openmates-header-owner-'));
  let finish!:(value:unknown)=>void;
  const owner=ownedClient({getChatMessages:async()=>new Promise(resolve=>{finish=resolve;})});
  try{
    const {state,context}=setup(owner.client);openHeaderAction(context,'download');
    const destination=join(directory,'chat.md');
    (state.chrome as Extract<TuiChromeState,{kind:'download'}>).path=destination;
    const pending=handleHeaderCommand(context,'save');
    owner.session.activeTeamId='other-team';
    finish({chat:state.activeChat,messages:[],historyIncomplete:false});await pending;
    assert.equal(state.chrome,null);await assert.rejects(readFile(destination));
  }finally{await rm(directory,{recursive:true,force:true});}
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional
test('overwrite rejects a file changed after the confirmation prompt',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'openmates-header-race-'));
  try{
    const {state,context}=setup();openHeaderAction(context,'download');
    const destination=join(directory,'chat.md');await writeFile(destination,'original');
    (state.chrome as Extract<TuiChromeState,{kind:'download'}>).path=destination;
    await handleHeaderCommand(context,'save');await writeFile(destination,'changed longer content');
    await handleHeaderCommand(context,'overwrite');
    assert.equal(await readFile(destination,'utf8'),'changed longer content');
    assert.match(lines(state.chrome),/Destination changed/);
  }finally{await rm(directory,{recursive:true,force:true});}
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional
test('OSC 52 requests are encoded and never claim confirmed clipboard delivery',()=>{
  const writes:string[]=[];
  const term=process.env.TERM;process.env.TERM='xterm-256color';
  try{
    assert.equal(requestTerminalClipboard('text\x1b]52;c;bad',{isTTY:true,write:(chunk:string)=>{writes.push(chunk);return true;}} as never),false);
    assert.equal(writes.length,1);
    // eslint-disable-next-line no-control-regex -- Inspect the trusted OSC 52 envelope, not user escape bytes.
    assert.match(writes[0],/^\x1b\]52;c;[A-Za-z0-9+/=]+\x07$/);
    assert.equal(writes[0].includes('bad'),false);
  }finally{if(term===undefined)delete process.env.TERM;else process.env.TERM=term;}
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional
test('long selectable copy fallback supports keyboard and wheel paging',async()=>{
  const {state,context}=setup();state.messages[0].content='a'.repeat(2500);
  openHeaderAction(context,'copy');
  assert.ok(renderHeaderDialog(state.chrome,40).length>40);
  await handleHeaderKey(context,'',{name:'pagedown'});
  assert.ok((state.chrome as Extract<TuiChromeState,{kind:'copy'}>).scrollOffset>0);
  await handleHeaderKey(context,'',{name:'end'});
  const end=(state.chrome as Extract<TuiChromeState,{kind:'copy'}>).scrollOffset;
  await handleHeaderKey(context,'',{name:'scrollup'});
  assert.equal((state.chrome as Extract<TuiChromeState,{kind:'copy'}>).scrollOffset,end-1);
  await handleHeaderKey(context,'',{name:'home'});
  assert.equal((state.chrome as Extract<TuiChromeState,{kind:'copy'}>).scrollOffset,0);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional,terminal-chrome.share.explicit-and-private
test('chat settings opens native tabs without changing the draft and routes Share to the encrypted form',async()=>{
  const {state,context}=setup();
  assert.ok(headerCapabilities(state).some(item=>item.label==='Chat settings'));
  openHeaderAction(context,'settings');
  assert.equal(state.chrome?.kind,'chat-settings');
  assert.match(renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n'),/Plan[\s\S]*Tasks[\s\S]*Files[\s\S]*Usage[\s\S]*Share/);
  const strip=renderHeaderDialog(state.chrome,80,24,state).find(line=>typeof line!=='string'&&line.spans?.some(span=>span.action?.kind==='command'&&span.action.command==='/header-action settings-tab tasks'));
  assert.ok(strip && typeof strip!=='string' && strip.spans?.some(span=>span.text==='Tasks'));
  const narrowTabs=renderHeaderDialog(state.chrome,19,24,state).filter(line=>typeof line!=='string'&&line.spans?.some(span=>span.action?.kind==='command'&&span.action.command.startsWith('/header-action settings-tab')));
  assert.ok(narrowTabs.length>1);assert.ok(narrowTabs.every(line=>typeof line!=='string'&&line.text.length<=19));
  await handleHeaderCommand(context,'settings-tab usage');
  assert.match(renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n'),/Total credits|Loading usage|Could not load usage/);
  await handleHeaderCommand(context,'settings-tab share');
  assert.match(renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n'),/Share chat/);
  await handleHeaderCommand(context,'settings-share');
  assert.equal(state.chrome?.kind,'share');
  assert.equal(state.input,'draft');assert.equal(state.scrollOffset,7);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional,terminal-chrome.navigation.origin-preserved
test('chat settings ignores a late task load after owner change',async()=>{
  let finish!:(records:[])=>void;
  const owner=ownedClient({getMasterKeyBytes:()=>new Uint8Array(32),listUserTasks:()=>new Promise<[]>(resolve=>{finish=resolve;})});
  const {state,context}=setup(owner.client);
  openHeaderAction(context,'settings');
  await handleHeaderCommand(context,'settings-tab tasks');
  assert.match(renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n'),/Loading tasks/);
  owner.session.hashedEmail='new-owner';finish([]);
  await new Promise(resolve=>setImmediate(resolve));
  assert.doesNotMatch(renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n'),/No tasks linked/);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.share.explicit-and-private,terminal-pointer.viewport-coherent
test('QR is generated only after choosing a valid encrypted URL and never displays a clipped matrix',async()=>{
  const url='https://openmates.org/share/chat/id#key=secret%2Bfragment';
  const {state,context}=setup({createChatShareLink:async()=>url});
  openHeaderAction(context,'share');
  assert.doesNotMatch(lines(state.chrome),/Show QR code/);
  await handleHeaderCommand(context,'show-qr');assert.equal(state.chrome?.kind,'share');
  await handleHeaderCommand(context,'generate');
  assert.match(lines(state.chrome),/Show QR code/);
  await handleHeaderCommand(context,'show-qr');
  assert.equal(state.chrome?.kind,'qr');
  const qr=(state.chrome as Extract<TuiChromeState,{kind:'qr'}>).qr;
  assert.equal(qr.url,url);
  assert.ok(qr.lines.every(line=>line.length===qr.width));
  const wide=renderHeaderDialog(state.chrome,qr.width+4,qr.height+4,state).map(line=>line.text);
  assert.equal(wide.filter(line=>/[▄▀█]/u.test(line)).length,qr.height);
  const narrow=renderHeaderDialog(state.chrome,20,12,state).map(line=>line.text).join('\n');
  assert.match(narrow.replace(/\n/g,' '),/QR needs \d+ columns and \d+ rows/);
  assert.doesNotMatch(narrow,/[▄▀█]/u);
  assert.doesNotMatch(narrow,/secret/);
  await handleHeaderKey(context,'',{name:'escape'});
  assert.equal(state.chrome?.kind,'share');assert.equal(state.input,'draft');
});

// contract-test: supporting surface=cli assertions=terminal-chrome.share.explicit-and-private,terminal-pointer.viewport-coherent
test('QR matrix has standard finder patterns and changes when encrypted fragment changes',()=>{
  const prefix='https://openmates.org/share/chat/id#key=';
  const qr=createTuiShareQr(prefix+'secret','https://openmates.org','chat');
  const other=createTuiShareQr(prefix+'different','https://openmates.org','chat');
  assert.ok(qr&&other);assert.notDeepEqual(qr.lines,other.lines);
  // Decode Unicode half-block cells into black/white modules independently of the renderer.
  const module=(r:number,c:number)=>{const char=qr.lines[Math.floor(r/2)]?.[c];return r%2===0?char===' '||char==='▄':char===' '||char==='▀';};
  const n=qr.width-8;
  for(let r=0;r<qr.width;r++)for(let c=0;c<qr.width;c++)if(r<4||c<4||r>=n+4||c>=n+4)assert.equal(module(r,c),false,'four-module light quiet zone');
  for(const [top,left] of [[4,4],[4,n-3],[n-3,4]])for(let r=0;r<7;r++)for(let c=0;c<7;c++){
    const expected=r===0||r===6||c===0||c===6||(r>=2&&r<=4&&c>=2&&c<=4);
    assert.equal(module(top+r,left+c),expected,`finder ${top},${left} at ${r},${c}`);
  }
  assert.equal(validTuiShareUrl(prefix+'secret','https://openmates.org','chat'),true);
  assert.equal(validTuiShareUrl('https://evil.test/share/chat/id#key=secret','https://openmates.org','chat'),false);
  assert.equal(validTuiShareUrl('https://openmates.org/share/chat/id','https://openmates.org','chat'),false);
  assert.equal(createTuiShareQr(prefix+'x'.repeat(4000),'https://openmates.org','chat'),null);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.share.explicit-and-private,terminal-pointer.viewport-coherent
test('QR disappears after owner changes and malformed SDK links cannot offer QR',async()=>{
  const owner=ownedClient({createChatShareLink:async()=> 'https://openmates.org/share/chat/id#key=old-secret'});
  const {state,context}=setup(owner.client);
  openHeaderAction(context,'share');await handleHeaderCommand(context,'generate');await handleHeaderCommand(context,'show-qr');
  owner.session.hashedEmail='new-owner';
  assert.match(renderHeaderDialog(state.chrome,80,100,state).map(line=>line.text).join('\n'),/no longer available/);
  await handleHeaderCommand(context,'copy-link');assert.equal(state.chrome,null);
  const bad=setup({createChatShareLink:async()=> 'https://evil.test/share/chat/id#key=stolen'});
  openHeaderAction(bad.context,'share');await handleHeaderCommand(bad.context,'generate');
  assert.doesNotMatch(lines(bad.state.chrome),/Show QR code|stolen/);
  assert.match(lines(bad.state.chrome),/Could not generate link/);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional,terminal-chrome.navigation.origin-preserved
test('chat task Create and Done use encrypted chat-bound SDK inputs and remain in settings',async()=>{
  const key=new Uint8Array(32).fill(7);let record:Record<string,unknown>|null=null,creates=0,updates=0;
  const owner=ownedClient({getMasterKeyBytes:()=>key,listUserPlans:async()=>[],listUserTasks:async()=>[],
    createUserTask:async(input:Record<string,unknown>)=>{creates++;record={...input,short_id:'T-1'};return record;},
    updateUserTask:async(_id:string,patch:Record<string,unknown>)=>{updates++;record={...record,...patch,version:2};return record;}});
  const {state,context}=setup(owner.client);state.tasks=[];
  openHeaderAction(context,'settings');assert.equal((state.chrome as Extract<TuiChromeState,{kind:'chat-settings'}>).tab,'plan');
  await handleHeaderCommand(context,'settings-tab tasks');await new Promise(resolve=>setImmediate(resolve));
  await handleHeaderCommand(context,'settings-task-create');
  await handleHeaderKey(context,'New linked task',{name:'paste'});
  await handleHeaderCommand(context,'settings-task-save');
  assert.equal(creates,1);assert.equal(record?.primary_chat_id,'chat-id');
  assert.equal(state.chrome?.kind,'chat-settings');
  const dialog=state.chrome as Extract<TuiChromeState,{kind:'chat-settings'}>;
  assert.equal(dialog.tasks[0]?.title,'New linked task');
  assert.match(renderHeaderDialog(dialog,80,24,state).map(line=>line.text).join('\n'),/0\/1 tasks done/);
  await handleHeaderCommand(context,`settings-task-toggle ${dialog.tasks[0].taskId}`);
  assert.equal(updates,1);assert.equal(dialog.tasks[0]?.status,'done');
  assert.match(renderHeaderDialog(dialog,80,24,state).map(line=>line.text).join('\n'),/1\/1 tasks done/);
  let opened='';context.command=async(command:string)=>{opened=command;};
  await handleHeaderCommand(context,`settings-task-open ${dialog.tasks[0].taskId}`);
  assert.equal(opened,`/task-open ${dialog.tasks[0].taskId}`);assert.equal(state.chrome,null);
  assert.equal(state.input,'draft');
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional,terminal-chrome.share.explicit-and-private
test('chat task validation keeps typed title on failure and never posts after owner changes',async()=>{
  let posts=0;let reject=true;
  const owner=ownedClient({getMasterKeyBytes:()=>new Uint8Array(32).fill(9),listUserPlans:async()=>[],listUserTasks:async()=>[],createUserTask:async()=>{posts++;throw Error(reject?'secret backend detail':'should not post');}});
  const {state,context}=setup(owner.client);state.tasks=[];
  openHeaderAction(context,'settings');await handleHeaderCommand(context,'settings-tab tasks');await new Promise(resolve=>setImmediate(resolve));
  await handleHeaderCommand(context,'settings-task-create');await handleHeaderCommand(context,'settings-task-save');
  assert.match(renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n'),/Task title must be 1–200 characters/);
  await handleHeaderKey(context,'Keep this title',{name:'paste'});await handleHeaderCommand(context,'settings-task-save');
  const dialog=state.chrome as Extract<TuiChromeState,{kind:'chat-settings'}>;
  assert.equal(dialog.taskTitle,'Keep this title');assert.equal(dialog.editingTask,true);
  assert.doesNotMatch(renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n'),/secret backend detail/);
  reject=false;const before=posts;
  context.render=()=>{if(dialog.busy)owner.session.hashedEmail='new-owner';};
  await handleHeaderCommand(context,'settings-task-save');assert.equal(posts,before);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional,terminal-chrome.share.explicit-and-private
test('chat task save reports its operation and HTTP status without private response text',async()=>{
  const owner=ownedClient({getMasterKeyBytes:()=>new Uint8Array(32).fill(9),listUserPlans:async()=>[],listUserTasks:async()=>[],
    createUserTask:async()=>{throw Object.assign(Error('password=private-secret encrypted_task_key=hidden'),{status:503});}});
  const {state,context}=setup(owner.client);state.tasks=[];
  openHeaderAction(context,'settings');await handleHeaderCommand(context,'settings-tab tasks');await new Promise(resolve=>setImmediate(resolve));
  await handleHeaderCommand(context,'settings-task-create');await handleHeaderKey(context,'Preserve this task',{name:'paste'});
  await handleHeaderCommand(context,'settings-task-save');
  const dialog=state.chrome as Extract<TuiChromeState,{kind:'chat-settings'}>;
  assert.match(dialog.error??'',/save: HTTP 503/);
  assert.doesNotMatch(dialog.error??'',/private-secret|encrypted_task_key|hidden/);
  assert.equal(dialog.taskTitle,'Preserve this task');assert.equal(dialog.editingTask,true);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional,terminal-chrome.share.explicit-and-private
test('chat usage reads existing settings endpoints and offers reviewed CSV/YAML destination',async()=>{
  const reads:string[]=[];
  const {state,context}=setup({settingsGet:async(path:string)=>{reads.push(path);return path.includes('chat-entries')?{entries:[{id:'entry-1',type:'ai',model_used:'model',credits:3,created_at:1}]}:{total_credits:3};}});
  openHeaderAction(context,'settings');await handleHeaderCommand(context,'settings-tab usage');await new Promise(resolve=>setImmediate(resolve));
  const text=renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n');
  assert.match(text,/Total credits: 3/);assert.match(text,/Download usage CSV/);
  assert.equal(reads.length,2);assert.ok(reads.every(path=>path.includes('chat_id=chat-id')));
  await handleHeaderCommand(context,'settings-usage-download csv');
  assert.equal(state.chrome?.kind,'download');
  assert.match((state.chrome as Extract<TuiChromeState,{kind:'download'}>).content!.toString(),/"entry-1"/);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional,terminal-chrome.navigation.origin-preserved
test('public example settings expose Share and only static Files, never private Plan or Tasks',()=>{
  const {state,context}=setup();state.screen='example';state.activeExample={chat:{id:'public-id',shortId:'public',slug:'demo',title:'Demo',summary:null,updatedAt:null,category:null,mateName:null,source:'example'},messages:[],embeds:[],files:[],followUpSuggestions:[]};
  openHeaderAction(context,'settings');
  const publicTabs=renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n');
  assert.match(publicTabs,/›\[Share\]/);assert.doesNotMatch(publicTabs,/\b(?:Plan|Tasks|Usage)\b/);
  state.activeExample.files=[{embedId:'file-1',contentRef:'file-1',title:'File',subtitle:'',type:'document',nodeType:'file',iconName:'file',createdAt:0,updatedAt:0,metadata:'',appId:null,skillId:null,url:null,mimeType:null}];
  assert.match(renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n'),/Files/);
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional,terminal-chrome.share.explicit-and-private
test('web-only chat controls offer the actual chat settings deep link for copying',async()=>{
  const {state,context}=setup();openHeaderAction(context,'settings');await handleHeaderCommand(context,'settings-tab share');
  assert.match(renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n'),/Copy web settings link/);
  await handleHeaderCommand(context,'settings-web');
  assert.equal(state.chrome?.kind,'copy');
  assert.equal((state.chrome as Extract<TuiChromeState,{kind:'copy'}>).text,'https://openmates.org/#settings/chats/chat-id/share');
});

// contract-test: supporting surface=cli assertions=terminal-chrome.actions.contextual-and-functional,terminal-chrome.navigation.origin-preserved
test('static example file offers a native reviewed download only for loaded content',async()=>{
  const {state,context}=setup();state.screen='example';state.embedAliases={};state.chatEmbeds={};
  state.activeExample={chat:{id:'public-id',shortId:'public',slug:'demo',title:'Demo',summary:null,updatedAt:null,category:null,mateName:null,source:'example'},messages:[],
    embeds:[{embed_id:'code-1',type:'code',content:JSON.stringify({code:'print(1)',language:'python'}),parent_embed_id:null,embed_ids:null}],
    files:[{embedId:'code-1',contentRef:'code-1',title:'Code',subtitle:'',type:'code',nodeType:'file',iconName:'code',createdAt:0,updatedAt:0,metadata:'',appId:null,skillId:null,url:null,mimeType:null}],followUpSuggestions:[]};
  openHeaderAction(context,'settings');await handleHeaderCommand(context,'settings-tab files');
  const rendered=renderHeaderDialog(state.chrome,80,24,state).map(line=>line.text).join('\n');
  assert.match(rendered,/Download code-1/);
  await handleHeaderCommand(context,'settings-file-download code-1');
  assert.equal(state.chrome?.kind,'download');
  assert.equal((state.chrome as Extract<TuiChromeState,{kind:'download'}>).content,'print(1)');
});
