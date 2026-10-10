// contract-test-file: infrastructure
/** Synthetic send timing contracts for the terminal chat UI. */
import assert from 'node:assert/strict';
import {test} from 'node:test';
import type {OpenMatesClient} from '../src/client.js';
import type {StreamEvent} from '../src/ws.js';
import {sendTuiMessage} from '../src/tui.js';
import {route} from '../src/tuiWorkspaceController.js';
import {closeTuiFullscreen} from '../src/tuiFullscreenChrome.js';
import {createInitialTuiState} from '../src/tuiRenderer.js';
import type {TuiModelSelectorShell} from '../src/tuiModelSelectorShell.js';

function deferred<T>() {
  let resolve!: (value:T)=>void, reject!: (error:Error)=>void;
  const promise = new Promise<T>((yes,no)=>{resolve=yes;reject=no;});
  return {promise,resolve,reject};
}

const session={apiUrl:'https://example.invalid',hashedEmail:'owner',activeTeamId:null,
  createdAt:1,masterKeyExportedB64:'key'};
type SendInput=Parameters<OpenMatesClient['sendMessage']>[0];
type SendResult=Awaited<ReturnType<OpenMatesClient['sendMessage']>>;
const result=(chatId:string,assistant:string):SendResult=>({chatId,assistant,userMessageId:'canonical-user',
  followUpSuggestions:[],mateName:'Ada',category:'software_development',modelName:'known-model',status:'completed',
  messageId:'canonical-assistant',taskProposals:[],taskUpdateProposals:[]} as SendResult);
function fixture(options?:{teamId?:string|null;mention?:Promise<{message:string;blocked:boolean}>;selection?:string|null}) {
  const state=createInitialTuiState();state.signedIn=true;state.screen='chat';state.activeChatId='chat-1';
  state.input='Ask something';state.drafts['chat-1']='Ask something';
  const pending=deferred<SendResult>();
  const calls:SendInput[]=[];
  const frames:Array<{messages:Array<{id?:string;role:string;content:string}>;screen:string;input:string;awaiting:boolean;streaming:boolean}>=[];
  const client={apiUrl:session.apiUrl,hasSession:()=>true,getSession:()=>session,
    getActiveTeamId:()=>options?.teamId??null,clearInteractiveChatViewer:()=>{},
    setInteractiveChatViewer:async()=>{},sendMessage:(input:SendInput)=>{calls.push(input);return pending.promise;},
  } as unknown as OpenMatesClient;
  const modelShell={consumeMention:async(value:string)=>options?.mention??{message:value,blocked:false},
    selectionForSend:()=>options?.selection===undefined?'auto':options.selection,
    adoptNewChat:()=>{},persistCreatedChat:async()=>{},
  } as unknown as TuiModelSelectorShell;
  const render=()=>frames.push({messages:state.messages.map(({id,role,content})=>({id,role,content})),
    screen:state.screen,input:state.input,awaiting:state.isAwaitingAi,streaming:!!state.streamingMessage});
  return {state,client,modelShell,render,frames,calls,pending};
}
const tick=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve();};
const stream=(kind:StreamEvent['kind'],content:string):StreamEvent=>({kind,content,category:'software_development',
  modelName:'known-model',taskId:'task-1'});

// contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation,terminal-ui.chat.rich-content
test('send shows one optimistic user row and clears composer before mention resolution',async()=>{
  const mention=deferred<{message:string;blocked:boolean}>();
  const f=fixture({mention:mention.promise});
  const send=sendTuiMessage({message:'Ask something',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  assert.equal(f.frames[0]?.screen,'chat');
  assert.deepEqual(f.frames[0]?.messages.map(m=>[m.role,m.content]),[['user','Ask something']]);
  assert.ok(f.frames[0]?.messages[0]?.id);
  assert.equal(f.frames[0]?.input,'');
  assert.equal(f.frames[0]?.awaiting,false,'AI waiting begins only after preparation');
  assert.equal(f.calls.length,0);
  mention.resolve({message:'Resolved question',blocked:false});await tick();
  assert.equal(f.calls.length,1);
  assert.equal(f.state.messages.length,1,'empty Assistant row remains transient');
  assert.equal(f.state.messages[0].content,'Resolved question');
  assert.equal(f.state.isAwaitingAi,true);
  assert.ok(f.state.streamingMessage);
  f.pending.resolve(result('chat-1','Finished'));await send;
  assert.deepEqual(f.state.messages.map(m=>m.role),['user','assistant']);
  assert.equal(f.state.streamingMessage,null);
});

// contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation,chats.streaming.ordered-final
test('typing stays transient and ordered chunks update one stable assistant object',async()=>{
  const f=fixture();
  const send=sendTuiMessage({message:'Ask something',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  await tick();assert.equal(f.calls.length,1);
  const assistant=f.state.streamingMessage;
  assert.ok(assistant?.id);
  f.calls[0].onStream?.(stream('typing',''));
  assert.equal(f.state.messages.length,1);
  assert.equal(f.state.streamingMessage,assistant);
  assert.equal(assistant?.modelName,'known-model');
  f.calls[0].onStream?.({...stream('typing',''),thinkingContent:'Actual visible reasoning',thinkingActive:true});
  assert.equal(assistant?.thinkingContent,'Actual visible reasoning');assert.equal(assistant?.thinkingActive,true);
  f.calls[0].onStream?.({...stream('chunk','First'),thinkingActive:false});
  assert.equal(assistant?.thinkingActive,false);
  assert.equal(f.state.messages[1],assistant);
  f.calls[0].onStream?.(stream('chunk','First and second'));
  f.calls[0].onStream?.(stream('done','First and second.'));
  assert.equal(f.state.messages.length,2);
  assert.equal(f.state.messages[1],assistant);
  assert.equal(assistant.content,'First and second.');
  f.pending.resolve(result('chat-1','First and second.'));await send;
  assert.equal(f.state.messages.length,2);
  assert.equal(f.state.messages[1],assistant);
  assert.equal(f.state.isAwaitingAi,false);
});

// contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation
test('blocked model mention restores the unsent draft, while a newer draft is preserved',async()=>{
  const mention=deferred<{message:string;blocked:boolean}>();const f=fixture({mention:mention.promise});
  const send=sendTuiMessage({message:'Ask something',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  f.state.input='New draft';f.state.drafts['chat-1']='New draft';
  mention.resolve({message:'',blocked:true});await send;
  assert.equal(f.calls.length,0);assert.equal(f.state.messages.length,0);
  assert.equal(f.state.input,'New draft');assert.equal(f.state.drafts['chat-1'],'New draft');
  assert.equal(f.state.isBusy,false);assert.equal(f.state.isAwaitingAi,false);
});

// contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation
test('attachment preparation failure rolls back the optimistic row and restores retry text',async()=>{
  const f=fixture();
  const memories=deferred<never[]>();
  (f.client as unknown as {listMemories:()=>Promise<never[]>}).listMemories=()=>memories.promise;
  const send=sendTuiMessage({message:'Read @./missing.txt',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  assert.equal(f.state.messages[0]?.content,'Read @./missing.txt');
  assert.equal(f.state.input,'');
  await tick();memories.reject(new Error('privacy unavailable'));await send;
  assert.equal(f.calls.length,0);assert.equal(f.state.messages.length,0);
  assert.equal(f.state.input,'Read @./missing.txt');
  assert.match(f.state.status??'',/privacy unavailable/);
});

// contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation
test('loading model selection blocks send and returns the draft to the composer',async()=>{
  const f=fixture({selection:null});
  await sendTuiMessage({message:'Ask something',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  assert.equal(f.calls.length,0);assert.equal(f.state.messages.length,0);
  assert.equal(f.state.input,'Ask something');assert.equal(f.state.isBusy,false);
  assert.match(f.state.status??'',/Model selection is loading/);
});

// contract-test: supporting surface=cli assertions=chats.streaming.ordered-final
test('failed question answer removes both optimistic turns before retry',async()=>{
  const f=fixture();
  const send=sendTuiMessage({message:'Choice A',questionAnswer:true,state:f.state,
    client:f.client,render:f.render,modelShell:f.modelShell});
  await tick();assert.equal(f.calls.length,1);
  f.pending.reject(new Error('Question send rejected'));
  await assert.rejects(send,/Question send rejected/);
  assert.equal(f.state.messages.length,0);
  assert.equal(f.state.streamingMessage,null);
  assert.equal(f.state.isBusy,false);
});

// contract-test: supporting surface=cli assertions=chats.streaming.progressive-presentation
test('human-only Team sends never create an assistant stream',async()=>{
  const f=fixture({teamId:'team-1'});
  const send=sendTuiMessage({message:'Human reply',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  assert.equal(f.state.messages.length,1);assert.equal(f.state.isAwaitingAi,false);
  await tick();assert.equal(f.calls.length,1);
  assert.equal(f.state.streamingMessage,null);assert.equal(f.state.messages.length,1);
  f.pending.resolve(result('chat-1',''));await send;
  assert.deepEqual(f.state.messages.map(m=>m.role),['user']);
});

// contract-test: supporting surface=cli assertions=chats.streaming.ordered-final
test('late stream events cannot write into a different chat owner',async()=>{
  const f=fixture();
  const send=sendTuiMessage({message:'Ask something',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  await tick();assert.equal(f.calls.length,1);
  const next=createInitialTuiState();
  Object.assign(f.state,next,{signedIn:true,routeVersion:f.state.routeVersion+1,
    activeChatId:'chat-2',messages:[{role:'user',content:'Keep this chat'}]});
  f.calls[0].onStream?.(stream('chunk','Stale reply'));
  f.pending.resolve(result('chat-1','Stale final'));await send;
  assert.deepEqual(f.state.messages.map(m=>m.content),['Keep this chat']);
  assert.equal(f.state.activeChatId,'chat-2');
});

// contract-test: supporting surface=cli assertions=chats.streaming.ordered-final
test('anonymous history excludes the immediate optimistic user row',async()=>{
  const state=createInitialTuiState();state.messages=[{role:'user',content:'Earlier'}];
  state.input='Next';state.drafts.new='Next';
  const pending=deferred<Awaited<ReturnType<OpenMatesClient['sendAnonymousMessage']>>>();
  let request:Parameters<OpenMatesClient['sendAnonymousMessage']>[0]|undefined;
  const client={hasSession:()=>false,clearInteractiveChatViewer:()=>{},
    sendAnonymousMessage:(input:NonNullable<typeof request>)=>{request=input;return pending.promise;}} as unknown as OpenMatesClient;
  const send=sendTuiMessage({message:'Next',state,client,render:()=>{}});
  assert.deepEqual(state.messages.map(m=>m.content),['Earlier','Next']);
  await tick();assert.deepEqual(request?.messageHistory?.map(m=>m.content),['Earlier']);
  assert.equal(state.messages.length,2);
  pending.resolve({chatId:'anonymous-chat',assistant:'Answer',category:null,mateName:null,followUpSuggestions:[]});await send;
  assert.deepEqual(state.messages.map(m=>m.content),['Earlier','Next','Answer']);
});

// contract-test: supporting surface=cli assertions=chats.streaming.ordered-final
test('continuing an example shows the new turn immediately and sends only the example as history',async()=>{
  const f=fixture();
  f.state.screen='example';f.state.activeChatId=null;
  f.state.activeExample={chat:{id:'public',shortId:'public',slug:'demo',title:'Public example',summary:null,
    updatedAt:null,category:null,mateName:null,source:'example'},
    messages:[{id:'example-user',chatId:'public',role:'user',content:'Earlier question',senderName:'User',
      category:null,modelName:null,createdAt:1,embedIds:[]},
    {id:'example-assistant',chatId:'public',role:'assistant',content:'Earlier answer',senderName:null,
      category:null,modelName:null,createdAt:2,embedIds:[]}],embeds:[],files:[],followUpSuggestions:[]};
  const send=sendTuiMessage({message:'Follow up',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  assert.deepEqual(f.state.messages.map(m=>m.content),['Earlier question','Earlier answer','Follow up']);
  assert.equal(f.frames[0]?.input,'');
  await tick();assert.equal(f.calls.length,1);
  assert.deepEqual(f.calls[0].messageHistory?.map(m=>m.content),['Earlier question','Earlier answer']);
  assert.ok(f.calls[0].newChatId);
  f.pending.resolve(result(f.calls[0].newChatId!,'New answer'));await send;
  assert.deepEqual(f.state.messages.map(m=>m.content),['Earlier question','Earlier answer','Follow up','New answer']);
});

// contract-test: supporting surface=cli assertions=chats.streaming.ordered-final
test('viewer follow-up throwing after acceptance cannot roll back the acknowledged turn',async()=>{
  const f=fixture({teamId:'team-1'});
  (f.client as unknown as {setInteractiveChatViewer:()=>Promise<void>}).setInteractiveChatViewer=()=>{
    throw new Error('viewer unavailable');
  };
  const send=sendTuiMessage({message:'Human reply',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  await tick();f.pending.resolve(result('chat-1',''));await send;await tick();
  assert.deepEqual(f.state.messages.map(m=>[m.role,m.content]),[['user','Human reply']]);
  assert.equal(f.state.messages[0].id,'canonical-user');
  assert.equal(f.state.input,'');assert.equal(f.state.isBusy,false);
  assert.equal(f.state.headerState,'ready');
});

// contract-test: supporting surface=cli assertions=chats.streaming.ordered-final
test('model preference persistence throwing after acceptance preserves the new chat and reply',async()=>{
  const f=fixture();f.state.activeChatId=null;
  (f.modelShell as unknown as {persistCreatedChat:()=>Promise<void>}).persistCreatedChat=()=>{
    throw new Error('model preference unavailable');
  };
  const send=sendTuiMessage({message:'Start chat',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  await tick();assert.ok(f.calls[0]?.newChatId);
  f.pending.resolve(result(f.calls[0].newChatId!,'Accepted answer'));await send;await tick();
  assert.equal(f.state.activeChatId,f.calls[0].newChatId);
  assert.deepEqual(f.state.messages.map(m=>m.content),['Start chat','Accepted answer']);
  assert.equal(f.state.input,'');assert.equal(f.state.isBusy,false);
  assert.equal(f.state.headerState,'ready');
});

// contract-test: supporting surface=cli assertions=chats.streaming.ordered-final,terminal-pointer.viewport-coherent
test('navigation releases a pending preparation and its late completion cannot unlock a newer send',async()=>{
  const mention=deferred<{message:string;blocked:boolean}>();const f=fixture({mention:mention.promise});
  const first=sendTuiMessage({message:'Old draft',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  assert.equal(f.state.isBusy,true);
  route(f.state,'chats','chat');f.state.activeChatId='chat-2';f.state.messages=[];
  assert.equal(f.state.isBusy,false);assert.equal(f.state.streamingMessage,null);
  const currentShell={...f.modelShell,consumeMention:async()=>({message:'New request',blocked:false})};
  const second=sendTuiMessage({message:'New request',state:f.state,client:f.client,render:f.render,modelShell:currentShell});
  await tick();assert.equal(f.calls.length,1);assert.equal(f.state.isAwaitingAi,true);
  mention.resolve({message:'Old draft',blocked:false});await first;
  assert.equal(f.state.isBusy,true);assert.equal(f.state.isAwaitingAi,true);
  assert.deepEqual(f.state.messages.map(m=>m.content),['New request']);
  f.pending.resolve(result('chat-2','New answer'));await second;
  assert.equal(f.state.isBusy,false);assert.deepEqual(f.state.messages.map(m=>m.content),['New request','New answer']);
});

// contract-test: supporting surface=cli assertions=chats.streaming.ordered-final,terminal-chrome.navigation.origin-preserved
test('Escape discards transient response state and stale events cannot reach the next chat',async()=>{
  const f=fixture();const send=sendTuiMessage({message:'Ask something',state:f.state,client:f.client,render:f.render,modelShell:f.modelShell});
  await tick();assert.equal(f.state.isAwaitingAi,true);assert.ok(closeTuiFullscreen(f.state));
  assert.equal(f.state.isBusy,false);assert.equal(f.state.isAwaitingAi,false);assert.equal(f.state.streamingMessage,null);
  route(f.state,'chats','chat');f.state.activeChatId='chat-2';f.state.messages=[{role:'user',content:'New chat'}];
  f.calls[0].onStream?.(stream('chunk','Old response'));f.pending.resolve(result('chat-1','Old response'));await send;
  assert.deepEqual(f.state.messages.map(m=>m.content),['New chat']);assert.equal(f.state.isAwaitingAi,false);
});
