import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createInitialTuiState,renderTuiFrame,renderMessageContentStyled} from '../src/tuiRenderer.js';
import {chatQuestions, messageQuestions} from '../src/tuiInteractiveQuestions.js';
import {handleWorkspaceCommand,handleWorkspaceKey,route,type WorkspaceContext} from '../src/tuiWorkspaceController.js';
import {lineText,stripAnsi,cells} from '../src/tuiText.js';
import {formatInteractiveQuestionAnswer,type InteractiveQuestionPayload} from '../src/interactiveQuestions.js';
import {runTui} from '../src/tui.js';
const fence=(payload:unknown,language='interactive_question')=>'```'+language+'\n'+JSON.stringify(payload)+'\n```';
const choice:InteractiveQuestionPayload={type:'choice',id:'goal',question:'Which approach fits your habits?',options:[{id:'lock',text:'Unbreakable lockout'},{id:'pause',text:'Mindful pause'},{id:'custom',text:'Other'}],custom_option_id:'custom'};
function setup(payload:InteractiveQuestionPayload|InteractiveQuestionPayload[]=choice){
  const state=createInitialTuiState();state.screen='chat';state.activeChatId='chat';
  state.messages=[{role:'assistant',content:(Array.isArray(payload)?payload:[payload]).map(item=>fence(item)).join('\n')}];
  const sent:string[]=[];
  const context={state,client:{},terminal:{width:120,height:40},render:()=>{},send:async(message:string)=>{sent.push(message);state.messages.push({role:'user',content:message});}} as unknown as WorkspaceContext;
  context.command=async command=>{await handleWorkspaceCommand(context,command);};
  const key=(name:string,chunk='',ctrl=false,shift=false)=>handleWorkspaceKey(context,chunk,{name,ctrl,shift});
  const answer=()=>JSON.parse(sent.at(-1)!.match(/```interactive_response\n([\s\S]*?)\n```/)![1]);
  return {state,context,sent,key,answer};
}

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable
test('question cards replace JSON, use safe colored bold prompts and fit narrow terminals',()=>{
  const {state}=setup();
  for(const width of [36,80,180]){
    const frame=renderTuiFrame(state,width,40,{colorMode:'truecolor'}),text=stripAnsi(frame);
    assert.ok(text.replace(/\s/g,'').includes('Whichapproachfitsyourhabits?'));assert.match(text,/\/question 1/);assert.doesNotMatch(text,/interactive_question|"options"/);
    assert.ok(text.split('\n').every(line=>cells(line)<=width));assert.ok(frame.includes('\x1b[1m'));
  }
  const dangerous={...choice,question:'Choose\x1b[2J safely'};
  const output=renderMessageContentStyled(fence(dangerous),80).map(lineText).join('\n');assert.ok(!output.includes('\x1b'));
});

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable
test('single choice requires explicit send and hides protocol after answering or cached reopen',async()=>{
  const {state,context,key,sent,answer}=setup();await context.command('/question 1');
  await key('s','',true);assert.equal(sent.length,0);assert.match(state.questionEditor!.error!,/select|choose/i);
  await key('down');await key('space',' ');assert.equal(sent.length,0);
  await key('s','',true);assert.deepEqual(answer(),{id:'goal',selection:['pause']});
  assert.equal(state.questionEditor,null);assert.ok(chatQuestions(state)[0].response);
  const frame=stripAnsi(renderTuiFrame(state,120,40));assert.match(frame,/Answered/);assert.doesNotMatch(frame,/interactive_response/);
  await assert.rejects(context.command('/question 1'),/already.*answered/);
  const reopened=setup().state;reopened.messages=structuredClone(state.messages);assert.ok(chatQuestions(reopened)[0].response);
});

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable
test('multi choice/custom text validation, Clear and Escape never send draft values',async()=>{
  const {state,context,key,sent,answer}=setup({...choice,multiple:true});await context.command('/question 1');
  await key('space',' ');await key('down');await key('down');await key('space',' ');
  await key('s','',true);assert.equal(sent.length,0);assert.match(state.questionEditor!.error!,/custom|own|answer/i);
  await key('tab');await key('x','My own approach');await key('s','',true);
  assert.deepEqual(answer(),{id:'goal',selection:['lock','custom'],custom_answer:'My own approach'});
  const draft=setup();await draft.context.command('/question 1');await draft.key('space',' ');await draft.key('u','',true);
  assert.deepEqual(draft.state.questionEditor!.answer.selection,[]);await draft.key('escape');assert.equal(draft.state.screen,'chat');assert.equal(draft.sent.length,0);
});

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable
test('input fields enforce required answers while optional fields may stay empty',async()=>{
  const {state,context,key,sent,answer}=setup({type:'input',id:'details',fields:[{id:'name',label:'Name',required:true},{id:'note',label:'Note'}]});
  await context.command('/question 1');await key('s','',true);assert.equal(sent.length,0);assert.match(state.questionEditor!.error!,/required/);
  await key('text','Ada');await key('s','',true);assert.deepEqual(answer(),{id:'details',inputs:{name:'Ada',note:''}});
});

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable
test('slider requires adjustment and respects fractional steps; rating requires its comment',async()=>{
  const slider=setup({type:'slider',id:'level',question:'How much?',min:0,max:1,step:0.1,default:0.5,labels:{0.6:'More'}});
  await slider.context.command('/question 1');await slider.key('s','',true);assert.equal(slider.sent.length,0);
  await slider.key('right');await slider.key('s','',true);assert.equal(slider.answer().value,0.6);assert.match(slider.sent[0],/^0.6 \(More\)/);
  const rating=setup({type:'rating',id:'score',question:'How was it?',require_comment:true});
  await rating.context.command('/question 1');await rating.key('right');await rating.key('s','',true);assert.equal(rating.sent.length,0);
  await rating.key('tab');await rating.key('text','Useful');await rating.key('s','',true);assert.deepEqual(rating.answer(),{id:'score',rating:1,comment:'Useful'});
});

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable
test('swipe reviews all cards and submits web swipes including referenced embeds',async()=>{
  const {context,key,sent,answer}=setup({type:'swipe',id:'review',cards:[{id:'a',text:'First',embed_ids:['first']},{id:'b',text:'Second',embed_ids:['second']}]});
  await context.command('/question 1');await key('right');await key('s','',true);assert.equal(sent.length,0);
  await key('left');await key('s','',true);assert.deepEqual(answer(),{id:'review',swipes:{a:'like',b:'dislike'},embed_ids:['first','second']});
});

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable
test('latest same-ID question ignores earlier responses; malformed and longer fenced examples remain literal',async()=>{
  const {state,context,key}=setup();state.messages.push({role:'user',content:formatInteractiveQuestionAnswer(choice,{selection:['lock']}).messageContent});
  state.messages.push({role:'assistant',content:fence(choice)});assert.ok(chatQuestions(state).every(question=>!question.response));
  await key('q','',true);assert.equal(state.questionEditor!.question.key,2);
  route(state,'tasks','tasks');assert.equal(state.questionEditor,null);
  const literal='````markdown\n'+fence(choice)+'\n````';assert.deepEqual(messageQuestions(literal),[]);
  for(const content of [literal,fence({type:'choice',id:'bad',question:'Bad',options:[null]}),fence(choice).slice(0,-3)]){
    const text=renderMessageContentStyled(content,120).map(lineText).join('\n');assert.match(text,/interactive_question/);assert.doesNotMatch(text,/\/question 1/);
  }
  await assert.rejects(context.command('/question 1'),/Open a chat/);
});

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable
test('quoted user questions stay literal, navigation closes the editor and sends mark answers as inert text',async()=>{
  const {state,context,key}=setup();state.messages.unshift({role:'user',content:fence(choice)});
  assert.equal(chatQuestions(state).length,1);
  const frame=stripAnsi(renderTuiFrame(state,120,40));assert.match(frame,/interactive_question/);
  assert.equal((frame.match(/\/question 1/g)??[]).length,1);
  await context.command('/question 1');await key('space',' ');await key('g','',true);
  assert.equal(state.questionEditor,null);assert.equal(state.focus,'navigation');
  await key('escape');await context.command('/question 1');await key('space',' ');
  let options:unknown;context.send=async(_message,flags)=>{options=flags;};await key('s','',true);
  assert.deepEqual(options,{questionAnswer:true});
});

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable
test('failed send retains its answer draft, while route changes and replaced questions reject stale submission',async()=>{
  const {state,context,key}=setup();await context.command('/question 1');await key('space',' ');
  context.send=async()=>{throw Error('Unavailable');};await key('s','',true);
  assert.deepEqual(state.questionEditor!.answer.selection,['lock']);assert.equal(state.questionEditor!.error,'Unavailable');
  state.messages[0].content=fence({...choice,question:'Changed'});await key('s','',true);assert.match(state.questionEditor!.error!,/changed/);
  await key('escape');await context.command('/question 1');await key('space',' ');
  context.send=async()=>{route(state,'tasks','tasks');throw Error('Late failure');};await key('s','',true);assert.equal(state.questionEditor,null);
});

// contract-test: direct surface=cli assertions=cli.surface.semantic-parity,cli.output.actionable-readable
test('cached legacy input and swipe answers render as locked canonical questions',()=>{
  const input=setup({type:'input',id:'details',fields:[{id:'name',label:'Name',required:true}]});
  input.state.messages.push({role:'user',content:'Ada\n'+fence({id:'details',values:{name:'Ada'}},'interactive_response')});
  const swipe=setup({type:'swipe',id:'review',cards:[{id:'a',text:'First'},{id:'b',text:'Second'}]});
  swipe.state.messages.push({role:'user',content:'First\n'+fence({id:'review',liked:['a'],disliked:['b']},'interactive_response')});
  for(const fixture of [input,swipe]){
    const frame=stripAnsi(renderTuiFrame(fixture.state,120,40));assert.match(frame,/Answered/);assert.doesNotMatch(frame,/interactive_response/);
  }
  assert.deepEqual(chatQuestions(input.state)[0].response,{id:'details',inputs:{name:'Ada'}});
  assert.deepEqual(chatQuestions(swipe.state)[0].response,{id:'review',swipes:{a:'like',b:'dislike'}});
  assert.deepEqual(messageQuestions(fence({type:'input',id:'bad',question:42,fields:[{id:'name',label:'Name'}]})),[]);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,chats.rendering.inline-entity-interaction
test('completed answers release controls during delayed sync; failed answers keep a retryable draft',async()=>{
  let key!:(chunk:string,key:{name?:string;ctrl?:boolean})=>void,lastFrame='';
  const terminal={width:120,height:45,colorMode:'none',ascii:true,enter:()=>{},leave:()=>{},onResize:()=>{},
    onKey:(handler:typeof key)=>{key=handler;},render:(frame:string)=>{lastFrame=stripAnsi(frame);}};
  const metadata=new Promise<never>(()=>{}),viewer=new Promise<void>(()=>{});
  const sent:string[]=[],q2={...choice,id:'second',multiple:true};let rejectAnswer=false;
  const client={hasSession:()=>true,beginInteractiveViewerSession:()=>{},endInteractiveViewerSession:()=>{},clearInteractiveChatViewer:()=>{},
    getChatMessages:async()=>({chat:{id:'saved',shortId:'saved',title:'Saved questions',createdAt:1,category:'general_knowledge'},
      messages:[{role:'assistant',content:fence(choice)+'\n'+fence(q2),embedIds:[]}]}),getDraft:async()=>null,
    setInteractiveChatViewer:()=>viewer,getChatMetadata:()=>metadata,
    sendMessage:async(options:{message:string;chatId:string;interactiveHuman:boolean})=>{
      assert.equal(options.interactiveHuman,true);assert.equal(options.chatId,'saved');sent.push(options.message);
      if (rejectAnswer) throw Error('Offline answer send');
      return {chatId:'saved',assistant:'Reply received',followUpSuggestions:[]};
    }};
  const run=runTui(client as never,terminal as never,{privacyOffer:async()=>false,privacyInstall:async()=>{},updateCheck:async()=>null,updateInstall:async()=>{},updateSkip:()=>{}});
  const wait=async(predicate:()=>boolean)=>{for(let i=0;i<100&&!predicate();i++)await new Promise(resolve=>setTimeout(resolve,5));assert.ok(predicate(),lastFrame);};
  const command=(value:string)=>{for(const character of value)key(character,{name:character});key('\r',{name:'return'});};
  try {
    await wait(()=>lastFrame.includes('DAILY INSPIRATION'));command('/chat saved');await wait(()=>lastFrame.includes('/question 2'));
    command('/question 1');await wait(()=>lastFrame.includes('Answer question 1'));key(' ',{name:'space'});key('\x13',{name:'s',ctrl:true});
    await wait(()=>lastFrame.includes('Reply received')&&!lastFrame.includes('is typing...'));
    key('\t',{name:'tab'});command('/question 2');await wait(()=>lastFrame.includes('Answer question 2'));
    key(' ',{name:'space'});key('\x1b[B',{name:'down'});key('\x1b[B',{name:'down'});key(' ',{name:'space'});key('\x1b[B',{name:'down'});
    key('Bandages',{name:'text'});rejectAnswer=true;key('\x13',{name:'s',ctrl:true});
    await wait(()=>lastFrame.includes('Offline answer send')&&lastFrame.includes('Answer question 2'));
    assert.match(lastFrame,/Bandages/);assert.doesNotMatch(lastFrame,/already been answered/);
    rejectAnswer=false;key('\x13',{name:'s',ctrl:true});
    await wait(()=>sent.length===3&&lastFrame.includes('Reply received')&&!lastFrame.includes('Answer question 2'));
    assert.match(sent[2],/Bandages/);assert.doesNotMatch(lastFrame,/Wait for the current response/);
  } finally {key('\x03',{name:'c',ctrl:true});await run;}
});
