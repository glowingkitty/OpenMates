// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {cachedChatLayout,chatRenderCacheStats,CHAT_RENDER_CACHE_MAX_CHARS,
  CHAT_RENDER_CACHE_MAX_MESSAGES} from '../src/tuiRenderCache.js';
import {createInitialTuiState,renderChat,renderTuiFrame,resetEndedTuiSession,type TuiState} from '../src/tuiRenderer.js';
import {pointerTargetAt,beginPointerFrame} from '../src/tuiPointer.js';
import {renderWorkspaceFrame,workspaceGeometry} from '../src/tuiLayout.js';
import {fullscreenHeaderLines} from '../src/tuiFullscreenChrome.js';

const frame=(state:TuiState,width=100,height=28)=>renderTuiFrame(state,width,height);
const chat=()=>{const state=createInitialTuiState();state.screen='chat';state.activeChatId='chat-one';
  state.currentUserHash='owner-one';return state;};
const embed=(name:string)=>({id:'one',embedId:'one',type:'app_skill_use',appId:'notes',skillId:'search',
  content:{title:name},textPreview:null,createdAt:null});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
test('warm chat frames equal a fresh uncached frame while draft and scroll change',()=>{
  const messages=[{role:'user' as const,content:'A **bold** [guide](wiki:guide_id) question'},
    {role:'assistant' as const,content:'## Answer\n'+('Text with *emphasis* and [item](embed:one). '.repeat(12))}];
  const state=chat();state.messages=messages;state.embedAliases={'note-s-1':{embedId:'one',appId:'notes',skillId:'search'}};
  const fresh=chat();fresh.messages=messages.map(message=>({...message}));fresh.embedAliases={...state.embedAliases};
  assert.equal(frame(state),frame(fresh));
  assert.equal(chatRenderCacheStats(state).entries,2);
  state.input='new draft';fresh.input='new draft';
  assert.equal(frame(state),frame(fresh));
  state.scrollOffset=4;fresh.scrollOffset=4;
  assert.equal(frame(state),frame(fresh));
  assert.equal(chatRenderCacheStats(state).entries,2);
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content,terminal-pointer.viewport-coherent
test('alias, hydration, streamed content and resize invalidate layout while pointer targets follow each frame',()=>{
  const state=chat();state.messages=[{role:'assistant',content:'Old line\n'.repeat(24)+'[Item](embed:one)\n'+
    '```json_embed\n{"embed_id":"one","app_id":"notes","skill_id":"search"}\n```'}];
  const checkPointer=(width:number,height:number,alias:string)=>{
    const rendered=frame(state,width,height),rows=rendered.split('\n');
    const row=rows.findIndex(value=>value.includes(`/embed ${alias}`));
    assert.ok(row>=0,`visible alias ${alias}`);
    const column=rows[row].indexOf(`/embed ${alias}`);
    assert.deepEqual(pointerTargetAt(state,column,row,width,height),{kind:'command',command:`/embed ${alias}`});
    return rendered;
  };
  state.embedAliases={'note-s-1':{embedId:'one',appId:'notes',skillId:'search'}};
  assert.match(checkPointer(100,28,'note-s-1'),/Item/);
  assert.equal(chatRenderCacheStats(state).entries,1);
  state.embedAliases['note-s-1'].legacy=true;
  state.embedAliases['note-s-2']={embedId:'one',appId:'notes',skillId:'search'};
  checkPointer(100,28,'note-s-2');
  state.chatEmbeds.one=embed('Hydrated item');
  assert.match(checkPointer(100,28,'note-s-2'),/Hydrated item/);
  state.messages[0].content+='\nStreamed ending';
  assert.match(checkPointer(100,28,'note-s-2'),/Streamed ending/);
  state.scrollOffset=2;
  checkPointer(100,28,'note-s-2');
  checkPointer(72,28,'note-s-2');
  assert.equal(chatRenderCacheStats(state).entries,1);
});

test('private plans are owner-local and stay within entry and memory bounds',()=>{
  const state={},other={};let builds=0;
  const context=(owner:string,embeds:Map<string,unknown>=new Map())=>
    ({owner,width:80,aliases:'{}',embeds,frame:{},variant:'questions',cacheable:true});
  const message={};
  const get=(target:object,owner:string,content:string,embeds?:Map<string,unknown>)=>
    cachedChatLayout(target,message,content,context(owner,embeds),()=>++builds);
  assert.equal(get(state,'user-A','private'),1);
  assert.equal(get(state,'user-A','private'),1);
  assert.equal(get(other,'user-A','private'),2);
  assert.equal(get(state,'user-A','private updated'),3);
  assert.equal(cachedChatLayout(state,message,'private updated',
    {...context('user-A'),variant:'literal-questions'},()=>++builds),4);
  assert.equal(get(state,'user-B','private updated'),5);
  assert.equal(chatRenderCacheStats(state).entries,1);
  const hydrated=new Map<string,unknown>([['one',{title:'loaded'}]]);
  assert.equal(get(state,'user-B','private updated',hydrated),6);
  for(let index=0;index<CHAT_RENDER_CACHE_MAX_MESSAGES+80;index++){
    const item={index};
    cachedChatLayout(state,item,'x'.repeat(3000),context('user-B',hydrated),()=>index);
  }
  const stats=chatRenderCacheStats(state);
  assert.ok(stats.entries<=CHAT_RENDER_CACHE_MAX_MESSAGES);
  assert.ok(stats.chars<=CHAT_RENDER_CACHE_MAX_CHARS);
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
test('question parser mode changes and session reset discard private layout',()=>{
  const state=chat();state.signedIn=true;
  const content='```interactive_question\n{"type":"choice","id":"q","question":"Pick","options":[{"id":"a","text":"A"}]}\n```';
  state.messages=[{role:'assistant',content}];
  const assistant=frame(state);
  assert.match(assistant,/Question 1/);
  state.messages[0].role='user';
  const user=frame(state);
  assert.match(user,/interactive_question/);
  assert.doesNotMatch(user,/Question 1/);
  assert.equal(chatRenderCacheStats(state).entries,1);
  state.screen='chats';frame(state);
  assert.deepEqual(chatRenderCacheStats(state),{entries:0,chars:0});
  state.screen='chat';frame(state);
  assert.equal(resetEndedTuiSession(state,false),true);
  assert.deepEqual(chatRenderCacheStats(state),{entries:0,chars:0});
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
test('results view mode remains live after the descriptor layout is cached',()=>{
  const state=chat();
  state.messages=[{role:'assistant',content:'```embeds_results_view\ntitle: Places\nembeds: one\n```'}];
  state.chatEmbeds.one={...embed('One place'),type:'place',content:{title:'One place',lat:52.5,lon:13.4}};
  assert.match(frame(state),/Places · Map/);
  state.resultsViewModes[1]='list';
  const warm=frame(state);
  assert.match(warm,/Places · List/);
  const fresh=chat();fresh.messages=state.messages.map(message=>({...message}));
  fresh.chatEmbeds={...state.chatEmbeds};fresh.resultsViewModes={...state.resultsViewModes};
  assert.equal(warm,frame(fresh));
  assert.equal(chatRenderCacheStats(state).entries,1);
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content,terminal-pointer.viewport-coherent
test('tail-first chat matches complete history at every scroll boundary and resize',()=>{
  const messages=Array.from({length:120},(_,index)=>({role:index%2?'assistant' as const:'user' as const,
    content:`Message ${index}: **漢👩‍💻 café** [guide](wiki:Guide). `+'Wrapped content. '.repeat(index%7+1)}));
  for(const [width,height] of [[48,16],[100,28],[240,70]])for(const offset of [0,1,17,75,300,10000]){
    const state=chat(),reference=chat();state.messages=messages;reference.messages=messages;
    state.scrollOffset=reference.scrollOffset=offset;
    const geometry=workspaceGeometry(reference,width),header=fullscreenHeaderLines(reference,geometry.contentWidth);
    beginPointerFrame(reference,width,height);
    const full=renderWorkspaceFrame(reference,width,height,[...header,...renderChat(reference,geometry.contentWidth,height,true)],{stickyRows:header.length});
    assert.equal(frame(state,width,height),full,`${width}x${height} offset ${offset}`);
    assert.equal(state.scrollOffset,reference.scrollOffset);
    for(let y=0;y<height;y++)for(let x=0;x<width;x++)
      assert.deepEqual(pointerTargetAt(state,x,y,width,height),pointerTargetAt(reference,x,y,width,height));
  }
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
test('cold long chat prepares only the visible tail and expands on earlier scrolling',()=>{
  const state=chat();state.messages=Array.from({length:500},(_,index)=>({role:'assistant',content:`Message ${index}\n`+'Text **bold**. '.repeat(100)}));
  assert.match(frame(state),/Message 499|Text bold/);
  const cold=chatRenderCacheStats(state).entries;assert.ok(cold<10,`${cold} prepared messages`);
  state.scrollOffset=100;frame(state);assert.ok(chatRenderCacheStats(state).entries>cold);
  state.scrollOffset=10000;frame(state);assert.ok(chatRenderCacheStats(state).entries<=CHAT_RENDER_CACHE_MAX_MESSAGES);
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content,terminal-pointer.viewport-coherent
test('offscreen protocol blocks retain global keys and selection jumps find an earlier embed',()=>{
  const state=chat();const fence='```';
  const question=(id:string)=>fence+'interactive_question\n'+JSON.stringify({type:'choice',id,question:`Pick ${id}`,options:[{id:'a',text:'A'}]})+'\n'+fence;
  const results=fence+'embeds_results_view\ntitle: Places\nembeds: one\n'+fence;
  state.messages=[{role:'assistant',content:question('old')+'\n'+results+'\n'+fence+'json_embed\n{"embed_id":"one"}\n'+fence},
    ...Array.from({length:80},(_,i)=>({role:'user' as const,content:`Old ${i}`})),{role:'assistant',content:question('new')+'\n'+results}];
  state.chatEmbeds.one={...embed('Earlier embed'),type:'place',content:{title:'Earlier embed',lat:52.5,lon:13.4}};state.embedAliases={'not-s-1':{embedId:'one',appId:'notes',skillId:'search'}};
  const tail=frame(state,100,45);assert.match(tail,/Question 2/);assert.match(tail,/\/view 2/);assert.doesNotMatch(tail,/Question 1/);
  state.focus='content';state.followSelection=true;state.chatSelectedEmbedId='one';
  assert.match(frame(state,100,45),/Earlier embed/);
  assert.ok(state.scrollOffset>0);
});
