/**
 * Transient assistant presentation for the terminal.
 * Skill phase uses canonical skill IDs, never query text.
 * Timer ticks recolor one painted viewport row without parsing history.
 * Cached frames are fenced by owner, route and visible draft/content.
 * No identities, regions or timing estimates are synthesized.
 */
import type {TuiState, TuiMessage} from './tuiRenderer.js';
import {cells,foreground,truncateCells,type TuiColorMode,type TuiLine} from './tuiText.js';

const COLORS=['#ff2d55','#ff6b2b','#ffd60a','#30d158','#32ade6','#bf5af2'];
const glowLines=new WeakSet<object>();
export type TuiResponsePhase='Thinking'|'Researching'|'Working';
const ACTION_SKILL=/^(?:add|cancel|clean|create|delete|edit|generate|keep-temporary|modify|remove|run|schedule|send|set|share|speak|transcribe|translate|update|vectorize|write)(?:$|[-_])/;
/** Match the web's terminal adjacent skill group; authored text means Working. */
export function tuiResponsePhase(segments:readonly {type:'text'|'embed';value:string;meta?:Record<string,unknown>}[]):TuiResponsePhase {
  const skills:string[]=[];
  for(let i=segments.length-1;i>=0;i--){
    const segment=segments[i];
    if(segment.type==='text'){if(segment.value.trim())break;continue;}
    skills.push(typeof segment.meta?.skill_id==='string'?segment.meta.skill_id:'');
  }
  return skills.length?(skills.some(id=>ACTION_SKILL.test(id.toLowerCase()))?'Working':'Researching'):'Working';
}
export function clearTuiSendState(state:TuiState):void {
  state.isBusy=false;state.isAwaitingAi=false;state.streamingMessage=null;
  state.aiTaskId=null;state.projectFocusPending=null;
}
const owner=(state:TuiState)=>JSON.stringify([state.signedIn,state.currentUserHash,state.activeTeamId,state.activeChatId,state.routeVersion]);
type Snapshot={owner:string;width:number;height:number;mode:TuiColorMode;ascii:boolean;rows:string[];row:number;variants:string[];
  messages:TuiState['messages'];message:TuiMessage|null;content:string|undefined;thinking:string|undefined;thinkingActive:boolean|undefined;expanded:boolean|undefined;model:string|null|undefined;
  scroll:number;input:string;focus:TuiState['focus'];sidebar:boolean;settings:TuiState['settings']};
const frames=new WeakMap<TuiState,Snapshot>();

/** Keep identity left and status centered, falling back to separate rows on small terminals. */
export function renderTuiThinking(mate:string,width:number,model?:string|null,phase:TuiResponsePhase='Thinking'):TuiLine[] {
  const status=truncateCells(`✦ ${phase}…`,width),statusStart=Math.max(0,Math.floor((width-cells(status))/2));
  const name=truncateCells(mate,Math.max(0,statusStart-1));
  const spans=[{text:name,bold:true,color:'#5a85eb'},
    {text:' '.repeat(Math.max(0,statusStart-cells(name)))},{text:status,bold:true,color:'#80caff'}];
  const rows:TuiLine[]=name?[{text:spans.map(span=>span.text).join(''),spans}]:[
    {text:truncateCells(mate,width),bold:true,color:'#5a85eb'},{text:status,bold:true,color:'#80caff'}];
  if(model)rows.push({text:truncateCells(model,width),color:'#808080'});
  return rows;
}

export function renderTuiStreamingGlow(width:number,phase:number):TuiLine {
  const size=Math.max(1,Math.min(72,width)),inset=Math.max(0,Math.floor((width-size)/2));
  const spans=[{text:' '.repeat(inset),color:'#e6e6e6'},...Array.from({length:size},(_,index)=>({text:'▁',
    color:COLORS[((Math.floor(index*COLORS.length/size-phase/2)%COLORS.length)+COLORS.length)%COLORS.length]})),
    {text:' '.repeat(Math.max(0,width-size-inset)),color:'#e6e6e6'}];
  const line={text:spans.map(span=>span.text).join(''),spans};glowLines.add(line);return line;
}
export function isTuiStreamingGlow(line:TuiLine):boolean {return typeof line!=='string'&&glowLines.has(line);}
export function clearTuiStreamingFrame(state:TuiState):void {frames.delete(state);}

/** Called only after a normal frame has established the current visible glow row. */
export function rememberTuiStreamingFrame(state:TuiState,frame:string,width:number,height:number,bodyWidth:number,
  painted:{row:number;rendered:string;line:string}|undefined,options:{colorMode?:TuiColorMode;ascii?:boolean;reducedMotion?:boolean}):void {
  const mode=options.colorMode??'none';
  if(!painted||!state.isAwaitingAi||state.screen!=='chat'||mode==='none'||options.reducedMotion||state.modelSelector?.open)return;
  const at=painted.line.indexOf(painted.rendered);if(at<0)return;
  const prefix=painted.line.slice(0,at),suffix=painted.line.slice(at+painted.rendered.length);
  const variants=Array.from({length:12},(_,phase)=>{
    const glow=renderTuiStreamingGlow(bodyWidth,phase);
    return prefix+(typeof glow==='string'?glow:glow.spans!.map(span=>foreground(span.text,span.color??'#e6e6e6',mode)).join(''))+suffix;
  });
  frames.set(state,{owner:owner(state),width,height,mode,ascii:options.ascii??false,rows:frame.split('\n'),row:painted.row,variants,
    messages:state.messages,message:state.streamingMessage,content:state.streamingMessage?.content,thinking:state.streamingMessage?.thinkingContent,thinkingActive:state.streamingMessage?.thinkingActive,expanded:state.streamingMessage?.thinkingExpanded,model:state.streamingMessage?.modelName,
    scroll:state.scrollOffset,input:state.input,focus:state.focus,sidebar:state.sidebarOpen,settings:state.settings});
}

/** No Markdown, protocol discovery, pointer rebuild, or history traversal on a tick. */
export function renderTuiStreamingAnimationFrame(state:TuiState,width:number,height:number,
  options:{colorMode?:TuiColorMode;ascii?:boolean;reducedMotion?:boolean}={}):string|null {
  const saved=frames.get(state);
  if(options.reducedMotion||!saved||!state.isAwaitingAi||state.screen!=='chat'||state.textSelection||state.form||state.chrome||state.questionEditor||state.paletteOpen||
    state.modelSelector?.open||saved.owner!==owner(state)||saved.width!==width||saved.height!==height||saved.mode!==(options.colorMode??'none')||
    saved.ascii!==(options.ascii??false)||saved.messages!==state.messages||saved.message!==state.streamingMessage||
    saved.content!==state.streamingMessage?.content||saved.thinking!==state.streamingMessage?.thinkingContent||saved.thinkingActive!==state.streamingMessage?.thinkingActive||saved.expanded!==state.streamingMessage?.thinkingExpanded||saved.model!==state.streamingMessage?.modelName||saved.scroll!==state.scrollOffset||
    saved.input!==state.input||saved.focus!==state.focus||saved.sidebar!==state.sidebarOpen||saved.settings!==state.settings)return null;
  saved.rows[saved.row]=saved.variants[((state.streamingPhase%12)+12)%12];
  return saved.rows.join('\n');
}
