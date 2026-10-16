// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import type { OpenMatesClient, DecryptedMessage } from '../src/client.js';
import { sendTuiMessage } from '../src/tui.js';
import { createInitialTuiState, renderTuiFrame } from '../src/tuiRenderer.js';
import { createTuiTeamChatRefresh, mergeTuiTeamChatWindow, tuiChatMessages } from '../src/tuiTeamChat.js';
import type { TuiModelSelectorShell } from '../src/tuiModelSelectorShell.js';

const hash = (id: string) => createHash('sha256').update(id).digest('hex');
const chat = (id: string) => ({id,shortId:id,title:'Team notes',summary:null,category:null,mateName:null,updatedAt:null});
const message = (id: string, senderName: string, senderId: string): DecryptedMessage => ({
  id,chatId:'chat-1',role:'user',content:id,senderName,hashedSenderUserId:hash(senderId),
  category:null,modelName:null,createdAt:1,embedIds:[],
});
const delay = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));
const until = async (ready: () => boolean) => {
  for (let attempt = 0; attempt < 30 && !ready(); attempt++) await delay(1);
  assert.ok(ready(), 'deferred send did not reach its in-flight checkpoint');
};

function deferredSendClient() {
  const session = { apiUrl:'https://example.invalid',hashedEmail:'owner',activeTeamId:'team-a',createdAt:1,masterKeyExportedB64:'key' };
  const calls: Array<{ message: string; chatId: string }> = [];
  const releases = new Map<string, (result: Awaited<ReturnType<OpenMatesClient['sendMessage']>>) => void>();
  const failures = new Map<string, (error: Error) => void>();
  const client = {
    apiUrl: session.apiUrl, hasSession: () => true, getSession: () => session,
    getActiveTeamId: () => session.activeTeamId, clearInteractiveChatViewer: () => {},
    sendMessage: (input: Parameters<OpenMatesClient['sendMessage']>[0]) => {
      const chatId = input.chatId ?? input.newChatId ?? '';
      calls.push({ message: input.message, chatId });
      return new Promise<Awaited<ReturnType<OpenMatesClient['sendMessage']>>>((resolve, reject) => {
        releases.set(input.message, resolve); failures.set(input.message, reject);
      });
    },
  } as unknown as OpenMatesClient;
  const modelShell = {
    consumeMention: async (value: string) => ({ message: value, blocked: false }),
    selectionForSend: () => 'auto', adoptNewChat: () => {}, persistCreatedChat: async () => {},
  } as unknown as TuiModelSelectorShell;
  const finish = (message: string, userMessageId?: string) => {
    const release = releases.get(message);
    assert.ok(release, `missing deferred send: ${message}`);
    const result = { chatId: calls.find((call) => call.message === message)!.chatId, assistant: '', followUpSuggestions: [], userMessageId };
    release(result as unknown as Awaited<ReturnType<OpenMatesClient['sendMessage']>>);
  };
  const fail = (message: string) => {
    const reject = failures.get(message);
    assert.ok(reject, `missing deferred send: ${message}`);
    reject(new Error('Old Team send failed'));
  };
  return { client, session, calls, modelShell, finish, fail };
}

// contract-test: supporting surface=cli assertions=teams.collaboration.realtime-team-sync,teams.chat.encrypted-until-invoked
test('completed human sends retain their canonical identity when a latest window arrives', async () => {
  const { client, calls, modelShell, finish } = deferredSendClient();
  const state = createInitialTuiState(); state.signedIn = true; state.activeTeamId = 'team-a';
  const pending = sendTuiMessage({ message:'Human reply', state, client, render:() => {}, modelShell });
  await until(() => calls.length === 1);
  finish('Human reply', 'canonical-human'); await pending;
  assert.equal(state.messages.length, 1, 'ordinary Team turns must have no Assistant placeholder');
  assert.equal(state.messages[0].id, 'canonical-human');
  const fetched = tuiChatMessages([{...message('durable-row', 'Alex', 'member-1'),
    clientMessageId:'canonical-human', content:'Human reply'}], 'team-a', 'Alex', hash('member-1'));
  const merged = mergeTuiTeamChatWindow(state.messages, fetched, true);
  assert.equal(merged.hasGap, false);
  assert.equal(merged.messages.length, 1);
  assert.equal(merged.messages[0].id, 'canonical-human');
});

// contract-test: supporting surface=cli assertions=teams.collaboration.realtime-team-sync
test('bounded Team windows preserve older history and distinct messages with identical text', () => {
  const state = createInitialTuiState();
  state.messages = Array.from({length:140}, (_,i) => ({id:`message-${i}`,role:'user' as const,content:'Same text'}));
  const latest = Array.from({length:100}, (_,i) => ({id:`message-${i+41}`,role:'user' as const,content:'Same text'}));
  const merged = mergeTuiTeamChatWindow(state.messages, latest, true);
  assert.equal(merged.hasGap, false);
  assert.equal(merged.messages.length, 141);
  assert.deepEqual(merged.messages.map(row => row.id), Array.from({length:141}, (_,i) => `message-${i}`));
  assert.equal(mergeTuiTeamChatWindow(merged.messages, latest, true).messages.length, 141);
});

// contract-test: supporting surface=cli assertions=teams.collaboration.realtime-team-sync
test('a latest window replaces covered rows while retaining a send not yet acknowledged by the server', () => {
  const rows = ['old','overlap','deleted','last','optimistic'].map(id => ({id:id === 'optimistic' ? undefined : id,role:'user' as const,content:id}));
  const latest = [rows[1], {...rows[3],content:'Updated'}, {id:'remote',role:'user' as const,content:'Reply'}];
  const merged = mergeTuiTeamChatWindow(rows, latest, true);
  assert.deepEqual(merged.messages.map(row => row.content), ['old','overlap','Updated','Reply','optimistic']);
  assert.equal(merged.messages[2].content, 'Updated');
  const complete = mergeTuiTeamChatWindow(rows, latest, false);
  assert.deepEqual(complete.messages, latest);
  const gap = mergeTuiTeamChatWindow(rows, [{id:'newer',role:'user',content:'New'}], true);
  assert.equal(gap.hasGap, true);
  assert.deepEqual(gap.messages.map(row => row.content), ['old','overlap','deleted','last','optimistic','New']);
  const confirmed = ['old','overlap','last','deleted-tail'].map(id => ({id,role:'user' as const,content:id}));
  assert.deepEqual(mergeTuiTeamChatWindow(confirmed,confirmed.slice(1,3),true).messages.map(row=>row.id),
    ['old','overlap','last'],'a deleted confirmed tail must not become a permanent optimistic row');
});

// contract-test: supporting surface=cli assertions=teams.context.full-switch-local
test('late Team A send cannot clear an in-flight Team B send or admit a third send', async () => {
  const { client, session, calls, modelShell, finish, fail } = deferredSendClient();
  const state = createInitialTuiState(); state.signedIn = true; state.activeTeamId = 'team-a';
  let renders = 0;
  const render = () => { renders++; };
  const pendingA = sendTuiMessage({ message:'Team A message', state, client, render, modelShell });
  await until(() => calls.length === 1);

  session.activeTeamId = 'team-b';
  Object.assign(state, createInitialTuiState(), { signedIn:true, activeTeamId:'team-b', routeVersion:state.routeVersion+1 });
  const pendingB = sendTuiMessage({ message:'@openmates Team B message', state, client, render, modelShell });
  await until(() => calls.length === 2);
  assert.equal(state.isBusy, true); assert.equal(state.isAwaitingAi, true);
  const focus = { chatId:state.activeChatId!, projectId:'project-b', focusId:'focus-b', requestId:'request-b', expiresAt:1, reject:async () => {} };
  state.projectFocusPending = focus; state.aiTaskId = 'task-b'; state.status = 'Team B still sending';
  state.input = 'Team B draft'; state.drafts[state.activeChatId!] = 'Team B draft';
  const bMessages = state.messages, bChatId = state.activeChatId, beforeLateRender = renders;

  fail('Team A message'); await pendingA;
  assert.equal(state.isBusy, true); assert.equal(state.isAwaitingAi, true);
  assert.equal(state.projectFocusPending, focus); assert.equal(state.aiTaskId, 'task-b');
  assert.equal(state.status, 'Team B still sending'); assert.equal(state.messages, bMessages);
  assert.equal(state.activeChatId, bChatId); assert.equal(renders, beforeLateRender);
  assert.equal(state.input, 'Team B draft'); assert.equal(state.drafts[bChatId!], 'Team B draft');
  await sendTuiMessage({ message:'Third message', state, client, render, modelShell });
  assert.equal(calls.length, 2);

  finish('@openmates Team B message'); await pendingB;
  assert.equal(state.isBusy, false); assert.equal(state.isAwaitingAi, false);
});

// contract-test: supporting surface=cli assertions=teams.context.full-switch-local
test('switching back to the same Team and chat does not restore an old send owner', async () => {
  const { client, session, calls, modelShell, finish } = deferredSendClient();
  const state = createInitialTuiState(); state.signedIn = true; state.activeTeamId = 'team-a';
  const render = () => {};
  const pendingOld = sendTuiMessage({ message:'Old Team A message', state, client, render, modelShell });
  await until(() => calls.length === 1);
  const oldRoute = state.routeVersion, oldChatId = state.activeChatId;
  session.activeTeamId = 'team-b';
  Object.assign(state, createInitialTuiState(), { signedIn:true, activeTeamId:'team-b', routeVersion:oldRoute+1 });
  session.activeTeamId = 'team-a';
  Object.assign(state, createInitialTuiState(), { signedIn:true, activeTeamId:'team-a', routeVersion:oldRoute, activeChatId:oldChatId });
  const pendingNew = sendTuiMessage({ message:'New Team A message', state, client, render, modelShell });
  await until(() => calls.length === 2);
  state.status = 'New Team A send';
  const newMessages = state.messages;
  finish('Old Team A message'); await pendingOld;
  assert.equal(state.messages, newMessages); assert.equal(state.isBusy, true);
  assert.equal(state.status, 'New Team A send');
  finish('New Team A message'); await pendingNew;
  assert.equal(state.isBusy, false);
});

test('anonymous send still completes with no authenticated workspace owner', async () => {
  const state = createInitialTuiState();
  let sent = 0;
  const client = {
    hasSession: () => false, clearInteractiveChatViewer: () => {},
    sendAnonymousMessage: async () => { sent++; return { chatId:'anonymous-chat', assistant:'Reply', followUpSuggestions:[], category:null, mateName:null }; },
  } as unknown as OpenMatesClient;
  await sendTuiMessage({ message:'Hello', state, client, render:() => {} });
  assert.equal(sent, 1);
  assert.equal(state.isBusy, false);
  assert.equal(state.messages.at(-1)?.content, 'Reply');
});

// contract-test: supporting surface=cli assertions=teams.chat.sender-identity-layout
test('Team message labels use authenticated sender identity, including equal display names', () => {
  const state=createInitialTuiState();state.signedIn=true;state.activeTeamId='team-1';state.screen='chat';state.activeChatId='chat-1';state.activeChat=chat('chat-1');
  state.messages=tuiChatMessages([message('own','Alex','member-1'),message('remote','Alex','member-2')],
    'team-1','Alex',hash('member-1'));
  assert.equal(state.messages[0].remoteUser,false);
  assert.equal(state.messages[1].remoteUser,true);
  assert.equal(tuiChatMessages([message('pending','Alex','member-2')], 'team-1', 'Alex', null)[0].remoteUser, true);
  const frame=renderTuiFrame(state,100,35);
  assert.match(frame,/You/);
  assert.match(frame,/\[A\] Alex/);
  assert.match(frame,/@openmates or a configured Mate/);
});

// contract-test: supporting surface=cli assertions=teams.collaboration.realtime-team-sync,teams.chat.sender-identity-layout
test('Team refresh applies attachment and category metadata on an otherwise unchanged message', async () => {
  const state=createInitialTuiState();state.signedIn=true;state.workspace='chats';state.screen='chat';state.activeChatId='chat-1';
  state.activeTeamId='team-1';state.currentUserHash=hash('member-1');
  state.messages=tuiChatMessages([message('same','Alex','member-1')],'team-1','Alex',state.currentUserHash);
  const session={apiUrl:'https://example.invalid',hashedEmail:'owner',activeTeamId:'team-1',createdAt:1,masterKeyExportedB64:'key'};
  let calls=0,renders=0;
  const client={apiUrl:session.apiUrl,hasSession:()=>true,getSession:()=>session,getActiveTeamId:()=>session.activeTeamId,
    getChatMessages:async()=>{calls++;return {chat:chat('chat-1'),messages:[{
      ...message('same','Alex','member-1'),embedIds:['embed-1'],category:calls===1?null:'travel',
    }]};}} as unknown as OpenMatesClient;
  const refresh=createTuiTeamChatRefresh(state,client,()=>{renders++;});
  refresh.request();await delay(350);
  assert.deepEqual(state.messages[0].embedIds,['embed-1']);assert.equal(renders,1);
  refresh.request();await delay(350);
  assert.equal(state.messages[0].category,'travel');assert.equal(renders,2);
  refresh.dispose();
});

// contract-test: supporting surface=cli assertions=teams.collaboration.realtime-team-sync
test('active Team refresh preserves draft and view while applying one inbound message', async () => {
  const state=createInitialTuiState();state.signedIn=true;state.workspace='chats';state.screen='chat';state.activeChatId='chat-1';
  state.activeTeamId='team-1';state.username='Alex';state.currentUserHash=hash('member-1');
  state.messages=tuiChatMessages([message('own','Alex','member-1')],'team-1','Alex',state.currentUserHash);
  state.input='unsent draft';state.scrollOffset=4;state.selectedIndex=2;state.textSelection=true;
  let calls=0,renders=0;
  const session={apiUrl:'https://example.invalid',hashedEmail:'owner',activeTeamId:'team-1',createdAt:1,masterKeyExportedB64:'key'};
  const client={
    apiUrl:session.apiUrl,hasSession:()=>true,getSession:()=>session,getActiveTeamId:()=>session.activeTeamId,
    getChatMessages:async()=>{calls++;return {chat:chat('chat-1'),messages:[message('own','Alex','member-1'),message('remote','Sam','member-2')]};},
  } as unknown as OpenMatesClient;
  const refresh=createTuiTeamChatRefresh(state,client,()=>{renders++;});
  refresh.request();refresh.request();await delay(350);
  assert.equal(calls,1);assert.equal(renders,1);
  assert.equal(state.messages.length,2);assert.equal(state.messages[1].title,'Sam');
  assert.equal(state.input,'unsent draft');assert.equal(state.scrollOffset,4);
  assert.equal(state.selectedIndex,2);assert.equal(state.textSelection,true);
  refresh.dispose();
});

// contract-test: supporting surface=cli assertions=teams.collaboration.realtime-team-sync,teams.context.full-switch-local
test('an in-flight Team refresh cannot publish after a chat or Team switch', async () => {
  const state=createInitialTuiState();state.signedIn=true;state.workspace='chats';state.screen='chat';state.activeChatId='chat-1';
  const session={apiUrl:'https://example.invalid',hashedEmail:'owner',activeTeamId:'team-1',createdAt:1,masterKeyExportedB64:'key'};
  let release!: (value: {chat:ReturnType<typeof chat>;messages:DecryptedMessage[]})=>void;
  const waiting=new Promise<{chat:ReturnType<typeof chat>;messages:DecryptedMessage[]}>(resolve=>{release=resolve;});
  const client={apiUrl:session.apiUrl,hasSession:()=>true,getSession:()=>session,getActiveTeamId:()=>session.activeTeamId,
    getChatMessages:async()=>waiting} as unknown as OpenMatesClient;
  const refresh=createTuiTeamChatRefresh(state,client,()=>{});
  refresh.request();await delay(300);
  state.routeVersion++;state.activeChatId='chat-2';session.activeTeamId='team-2';
  state.messages=[{role:'user',content:'chat-2 only'}];
  release({chat:chat('chat-1'),messages:[message('stale','Sam','member-2')]});
  await delay(20);
  assert.deepEqual(state.messages,[{role:'user',content:'chat-2 only'}]);
  refresh.dispose();
});

// contract-test: supporting surface=cli assertions=teams.collaboration.realtime-team-sync,teams.context.full-switch-local
test('Team fallback defers while sending and drops an old account response after logout', async () => {
  const state=createInitialTuiState();state.signedIn=true;state.workspace='chats';state.screen='chat';
  state.activeChatId='chat-1';state.activeTeamId='team-1';state.isBusy=true;
  state.messages=[{id:'existing',role:'user',content:'Keep this message'}];
  const original=state.messages;
  const session={apiUrl:'https://example.invalid',hashedEmail:'owner',activeTeamId:'team-1',createdAt:1,masterKeyExportedB64:'key'};
  let signedIn=true,calls=0,renders=0;
  let release!: (value: {chat:ReturnType<typeof chat>;messages:DecryptedMessage[]})=>void;
  const waiting=new Promise<{chat:ReturnType<typeof chat>;messages:DecryptedMessage[]}>(resolve=>{release=resolve;});
  const client={apiUrl:session.apiUrl,hasSession:()=>signedIn,getSession:()=>session,getActiveTeamId:()=>session.activeTeamId,
    getChatMessages:async()=>{calls++;return waiting;}} as unknown as OpenMatesClient;
  const refresh=createTuiTeamChatRefresh(state,client,()=>{renders++;},40);
  await delay(125);
  assert.equal(calls,0,'a local send must not be replaced by the fallback poll');
  state.isBusy=false;
  for(let attempt=0;attempt<40&&calls===0;attempt++)await delay(10);
  assert.equal(calls,1);
  session.hashedEmail='other-account';
  release({chat:chat('chat-1'),messages:[message('stale','Maya','member-2')]});
  await delay(20);
  assert.equal(state.messages,original);
  assert.equal(renders,0);
  signedIn=false;
  await delay(125);
  assert.equal(calls,1,'logout must stop the active-chat fallback');
  refresh.dispose();
});
