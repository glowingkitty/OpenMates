import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { headerCapabilities, openHeaderAction, handleHeaderCommand, handleHeaderKey, renderHeaderDialog, type TuiChromeState } from '../src/tuiHeaderActions.js';
import { requestTerminalClipboard } from '../src/tuiClipboard.js';
import type { WorkspaceContext } from '../src/tuiWorkspaceController.js';
import type { TuiState } from '../src/tuiRenderer.js';

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
