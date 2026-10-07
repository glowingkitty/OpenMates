/** Terminal question cards and drafts use the same response protocol as web. */
import { formatInteractiveQuestionAnswer, isCustomChoiceOption, validateInteractiveQuestionAnswer,
  type InteractiveQuestionPayload, type InteractiveQuestionAnswer } from './interactiveQuestions.js';
import { parseTuiMarkdown } from './tuiMarkdown.js';
import type { TuiState } from './tuiRenderer.js';
import type { WorkspaceContext } from './tuiWorkspaceController.js';
import type { TerminalKey } from './tuiTerminal.js';
import type { TuiPointerAction } from './tuiPointer.js';
import { eraseGrapheme, terminalText, wrapCells, type TuiLine } from './tuiText.js';

export type TuiQuestion = { key:number; messageIndex:number; payload:InteractiveQuestionPayload; response?:InteractiveQuestionAnswer };
export type TuiQuestionEditor = { question:TuiQuestion; answer:InteractiveQuestionAnswer; fieldIndex:number; touched:boolean; error?:string; busy?:boolean };

export function messageQuestions(content:string): InteractiveQuestionPayload[] {
  return parseTuiMarkdown(content,160).flatMap(block=>block.type==='question'?[block.payload]:[]);
}
export function chatQuestions(state:TuiState):TuiQuestion[] {
  const messages=state.screen==='example'&&state.activeExample?state.activeExample.messages:state.messages;
  const questions:TuiQuestion[]=[];
  messages.forEach((message,messageIndex)=>{
    if(message.role!=='assistant')return;
    messageQuestions(message.content).forEach(payload=>questions.push({key:questions.length+1,messageIndex,payload}));
  });
  for(const question of questions){
    const latest=questions.filter(item=>item.payload.id===question.payload.id).at(-1)!;
    for(let index=messages.length-1;index>latest.messageIndex;index--){
      if(messages[index].role!=='user')continue;
      const response=parseTuiMarkdown(messages[index].content,160).find(block=>block.type==='response'&&block.payload.id===question.payload.id);
      if(response?.type==='response'&&!validateInteractiveQuestionAnswer(question.payload,response.payload)){
        question.response=formatInteractiveQuestionAnswer(question.payload,response.payload).responsePayload;break;
      }
    }
  }
  return questions;
}

function initialAnswer(question:InteractiveQuestionPayload):InteractiveQuestionAnswer {
  switch(question.type){
    case 'choice':return {selection:[]};
    case 'input':return {inputs:Object.fromEntries((question.fields??[]).map(field=>[field.id,'']))};
    case 'slider':return {value:question.default??Math.round(((question.min??0)+(question.max??100))/2)};
    case 'swipe':return {swipes:Object.create(null)};
    case 'rating':return {rating:0,comment:''};
  }
}
function controls(editor:TuiQuestionEditor):Array<{id:string;label:string;value?:string;selected?:boolean;text?:boolean}> {
  const {payload:q}=editor.question,a=editor.answer;
  switch(q.type){
    case 'choice':return [...(q.options??[]).map(option=>({id:option.id,label:option.text,selected:(a.selection as string[]).includes(option.id)})),
      ...((a.selection as string[]).some(id=>isCustomChoiceOption(q,id))?[{id:'custom',label:q.custom_placeholder??'Your own answer',value:String(a.custom_answer??''),text:true}]:[])];
    case 'input':return (q.fields??[]).map(field=>({id:field.id,label:field.label+(field.required?' · required':''),value:String((a.inputs as Record<string,string>)[field.id]??''),text:true}));
    case 'slider':return [{id:'value',label:`${q.min} ← Value → ${q.max}`,value:`${a.value}${q.labels?.[Number(a.value)]?` (${q.labels[Number(a.value)]})`:''}`}];
    case 'rating':return [{id:'rating',label:`Rating · ${q.max_stars??q.max??q.scale??5} stars`,value:`${'★'.repeat(Math.min(20,Number(a.rating)))}${'☆'.repeat(Math.max(0,Math.min(20,q.max_stars??q.max??q.scale??5)-Number(a.rating)))} ${a.rating}/${q.max_stars??q.max??q.scale??5}`},
      {id:'comment',label:q.comment_placeholder??`Comment${q.require_comment?' · required':' · optional'}`,value:String(a.comment??''),text:true}];
    case 'swipe':return (q.cards??[]).map(card=>({id:card.id,label:card.text,value:String((a.swipes as Record<string,string>)[card.id]??'← dislike · like →')}));
  }
}

export function renderQuestionCard(question:TuiQuestion,width:number):TuiLine[] {
  const q=question.payload,answer=question.response;
  const rows:TuiLine[]=wrapCells(`Question ${question.key} · ${q.question??(q.type==='input'?'Tell us more':'Review these options')}`,width).map(text=>({text,bold:true,color:'#80caff'}));
  const editor={question,answer:answer??initialAnswer(q),fieldIndex:0,touched:false};
  for(const control of controls(editor)){
    const marker=q.type==='choice'?(control.selected?'[✓]':q.multiple?'[ ]':'( )'):'';
    rows.push(...wrapCells(`${marker} ${control.label}${control.value!==undefined?` · ${control.value||'(empty)'}`:''}`.trim(),width));
  }
  rows.push(...wrapCells(answer?'Answered':`/question ${question.key} · Answer${q.multiple?' · Choose several':''} · Ctrl+Q latest question`,width)
    .map(text=>({text,color:answer?'#808080':'#85c9e8',
      ...(answer?{}:{action:{kind:'question' as const,index:question.key,activate:true}})})),'');
  return rows;
}

export function renderQuestionEditor(editor:TuiQuestionEditor,width:number):TuiLine[] {
  const q=editor.question.payload,items=controls(editor),rows:TuiLine[]=[];
  const add=(text:string,color='#e6e6e6',bold=false,action?:TuiPointerAction)=>
    rows.push(...wrapCells(text,width).map(text=>({text,color,bold,action})));
  add(`Answer question ${editor.question.key}`,'#80caff',true);
  add(q.question??(q.type==='input'?'Tell us more':'Review these options'),'#ffffff',true);rows.push('');
  items.forEach((item,index)=>{
    const focused=index===editor.fieldIndex,marker=q.type==='choice'?(item.selected?'[✓]':q.multiple?'[ ]':'( )'):'';
    const action:TuiPointerAction={kind:'question',index,activate:q.type==='choice'};
    add(`${focused?'›':' '} ${marker} ${item.label}`,focused?'#32ade6':'#e6e6e6',focused,action);
    if(item.value!==undefined)add(`    ${item.value||'(empty)'}${focused&&item.text&&!editor.busy?'_':''}`,'#e6e6e6',false,action);
    if(q.type==='rating'&&index===0){
      const max=q.max_stars??q.max??q.scale??5;
      add('    '+Array.from({length:Math.min(max,20)},(_,star)=>`[${star+1}]`).join(' '),'#85c9e8');
      const line=rows.at(-1);
      if(typeof line!=='string'&&line){
        const spans=[];let text='    ';
        spans.push({text});
        for(let star=1;star<=Math.min(max,20);star++){
          text=`[${star}]${star<Math.min(max,20)?' ':''}`;
          spans.push({text,action:{kind:'question' as const,index,value:star}});
        }
        if(spans.map(span=>span.text).join('')===line.text)line.spans=spans;
      }
    }
    if(q.type==='slider'){
      const min=q.min!,max=q.max!,step=q.step??1,current=Number(editor.answer.value);
      const values=[min,Math.max(min,Math.min(max,min+Math.round((current-min)/step-1)*step)),
        current,Math.max(min,Math.min(max,min+Math.round((current-min)/step+1)*step)),max]
        .filter((value,position,all)=>position===all.indexOf(value));
      const text='    '+values.map(value=>`[${value}]`).join(' ');
      if(wrapCells(text,width).length===1){
        const spans=[{text:'    '},...values.map((value,position)=>({
          text:`[${value}]${position<values.length-1?' ':''}`,
          action:{kind:'question' as const,index,value},
        }))];
        rows.push({text,spans});
      }
    }
    if(q.type==='swipe'){
      const text='    [← dislike]  [like →]';
      if(wrapCells(text,width).length===1)rows.push({text,spans:[
        {text:'    '},{text:'[← dislike]',action:{kind:'question',index,value:'dislike'}},
        {text:'  '},{text:'[like →]',action:{kind:'question',index,value:'like'}},
      ]});
    }
  });
  rows.push('');
  add(`${editor.fieldIndex===items.length?'›':' '} [Send answer]`,'#32ade6',true,
    {kind:'question',index:items.length,activate:true});
  add(`${editor.fieldIndex===items.length+1?'›':' '} [Clear]`,'#a0a0a0',false,
    {kind:'question',index:items.length+1,activate:true});
  add(' [Cancel]','#a0a0a0',false,{kind:'question',index:items.length+2,activate:true});
  if(editor.error)add(editor.error,'#ff6b6b',true);
  add(editor.busy?'Sending…':'Tab / ↑↓ move · Space choose · ←/→ adjust · Ctrl+S send · Ctrl+U clear · Esc cancel','#a0a0a0');
  return rows;
}

export function openQuestion(state:TuiState,key?:number):void {
  if(!['chat','example'].includes(state.screen))throw Error('Open a chat to answer a question.');
  const questions=chatQuestions(state),question=key===undefined?questions.filter(item=>!item.response).at(-1):questions.find(item=>item.key===key);
  if(!question)throw Error('No unanswered question here. Use /question <number> for a question shown in this chat.');
  if(question.response)throw Error('This question has already been answered.');
  state.questionEditor={question,answer:initialAnswer(question.payload),fieldIndex:0,touched:false};
  state.focus='content';state.textSelection=false;
}

export async function handleQuestionKey(context:WorkspaceContext,chunk:string,key:TerminalKey):Promise<boolean> {
  const {state,render}=context,editor=state.questionEditor;
  if(!editor){
    if(key.ctrl&&key.name==='q'&&['chat','example'].includes(state.screen)){try{openQuestion(state);}catch(error){state.status=String((error as Error).message);}render();return true;}
    return false;
  }
  if(editor.busy)return true;
  const q=editor.question.payload,items=controls(editor),field=items[editor.fieldIndex];
  const clear=()=>{editor.answer=initialAnswer(q);editor.fieldIndex=0;editor.touched=false;editor.error=undefined;};
  const submit=async()=>{
    if(state.isBusy){editor.error='Wait for the current response before sending.';return;}
    const current=chatQuestions(state).find(item=>item.key===editor.question.key);
    if(!current||current.messageIndex!==editor.question.messageIndex||JSON.stringify(current.payload)!==JSON.stringify(q)){
      editor.error='This question changed. Cancel and reopen it.';return;
    }
    if(current.response){editor.error='This question has already been answered.';return;}
    editor.error=q.type==='slider'&&!editor.touched?'Adjust the slider before sending.':validateInteractiveQuestionAnswer(q,editor.answer);
    if(editor.error)return;
    editor.busy=true;render();
    const message=formatInteractiveQuestionAnswer(q,editor.answer).messageContent;
    const route=state.routeVersion,messages=state.messages,chatId=state.activeChatId;
    // Close before sending so ordinary encrypted chat streaming stays visible.
    state.questionEditor=null;
    try{await context.send(message,{questionAnswer:true});}
    catch(error){
      // Failed adapters retain the draft only if the same chat and route still own it.
      if(route===state.routeVersion&&messages===state.messages&&chatId===state.activeChatId&&['chat','example'].includes(state.screen)&&chatQuestions(state).some(item=>item.messageIndex===editor.question.messageIndex&&item.payload.id===q.id&&!item.response)){
        editor.busy=false;editor.error=error instanceof Error?error.message:String(error);state.questionEditor=editor;
      }
    }
  };
  if(key.name==='escape'){state.questionEditor=null;render();return true;}
  if(key.ctrl&&key.name==='s'){await submit();render();return true;}
  if(key.ctrl&&key.name==='u'){clear();render();return true;}
  if(key.name==='tab'||key.name==='up'||key.name==='down'){
    const delta=key.name==='up'||key.name==='tab'&&key.shift?-1:1;
    editor.fieldIndex=(editor.fieldIndex+delta+items.length+2)%(items.length+2);
  }else if(key.name==='return'&&editor.fieldIndex===items.length)await submit();
  else if(key.name==='return'&&editor.fieldIndex===items.length+1)clear();
  else if(field?.text){
    let value=field.value??'';
    if(key.name==='backspace')value=eraseGrapheme(value);
    else if(key.name==='return'){editor.fieldIndex++;render();return true;}
    else if(!key.ctrl&&!key.meta&&chunk)value+=terminalText(chunk);
    if(q.type==='input')(editor.answer.inputs as Record<string,string>)[field.id]=value;
    else editor.answer[field.id==='custom'?'custom_answer':field.id]=value;
    editor.error=undefined;
  }else if(field&&q.type==='choice'&&['space','return'].includes(key.name??'')){
    const selected=editor.answer.selection as string[];
    editor.answer.selection=q.multiple?(selected.includes(field.id)?selected.filter(id=>id!==field.id):[...selected,field.id]):[field.id];
    editor.error=undefined;
  }else if(field&&['left','right'].includes(key.name??'')){
    const delta=key.name==='left'?-1:1;
    if(q.type==='slider'){
      const min=q.min!,max=q.max!,step=q.step??1;
      editor.answer.value=Number(Math.max(min,Math.min(max,min+Math.round((Number(editor.answer.value)-min)/step+delta)*step)).toFixed(10));editor.touched=true;
    }else if(q.type==='rating')editor.answer.rating=Math.max(1,Math.min(q.max_stars??q.max??q.scale??5,Number(editor.answer.rating)+delta));
    else if(q.type==='swipe'){
      (editor.answer.swipes as Record<string,string>)[field.id]=delta<0?'dislike':'like';editor.fieldIndex=Math.min(items.length,editor.fieldIndex+1);
    }
    editor.error=undefined;
  }
  render();return true;
}

/** Pointer actions use the same draft and submit path as keyboard interaction. */
export async function handleQuestionPointer(
  context:WorkspaceContext,action:Extract<TuiPointerAction,{kind:'question'}>,
):Promise<void> {
  const {state,render}=context,editor=state.questionEditor;
  if(!editor){
    if(!action.activate||!['chat','example'].includes(state.screen))return;
    const key=typeof action.index==='number'?action.index:Number(action.index);
    if(!Number.isInteger(key)||key<1)return;
    try{openQuestion(state,key);}catch(error){state.status=String((error as Error).message);}
    render();return;
  }
  if(editor.busy)return;
  const q=editor.question.payload,items=controls(editor),
    index=typeof action.index==='number'?action.index:Number(action.index);
  if(!Number.isInteger(index)||index<0||index>items.length+2)return;
  if(index>=items.length&&!action.activate)return;
  if(index===items.length+2){await handleQuestionKey(context,'',{name:'escape'});return;}
  if(index===items.length+1){await handleQuestionKey(context,'',{name:'u',ctrl:true});return;}
  if(index===items.length){await handleQuestionKey(context,'',{name:'s',ctrl:true});return;}
  editor.fieldIndex=index;
  if(q.type==='choice'&&action.activate){
    await handleQuestionKey(context,'',{name:'space'});return;
  }
  if(q.type==='slider'&&typeof action.value==='number'){
    const min=q.min!,max=q.max!,step=q.step??1,value=action.value;
    if(Number.isFinite(value)&&value>=min&&value<=max&&Math.abs((value-min)/step-Math.round((value-min)/step))<1e-7){
      editor.answer.value=value;editor.touched=true;editor.error=undefined;
    }
  }else if(q.type==='rating'&&typeof action.value==='number'){
    const max=q.max_stars??q.max??q.scale??5;
    if(Number.isInteger(action.value)&&action.value>=1&&action.value<=max){
      editor.answer.rating=action.value;editor.error=undefined;
    }
  }else if(q.type==='swipe'&&(action.value==='like'||action.value==='dislike')){
    (editor.answer.swipes as Record<string,string>)[items[index].id]=action.value;
    editor.error=undefined;
  }
  render();
}
