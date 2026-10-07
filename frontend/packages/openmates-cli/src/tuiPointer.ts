/** Click targets belong to the rendered frame, never to user-provided text. */
import type {TuiState} from './tuiRenderer.js';
import type {TuiLine} from './tuiText.js';

export type TuiPointerAction =
  | {kind:'command';command:string}
  | {kind:'key';name:string;chunk?:string;ctrl?:boolean;focus?:TuiState['focus']}
  | {kind:'focus';focus:TuiState['focus']}
  | {kind:'select';target:'sidebar'|'content'|'task'|'workflow-node'|'workflow-run'|'form-field'|'palette';index:number;column?:number;id?:string;activate?:boolean;name?:string;chunk?:string}
  | {kind:'question';index:number|string;value?:number|string;activate?:boolean};
export type TuiPointerTarget = {column:number;row:number;width:number;action:TuiPointerAction};
type PointerFrame = {width:number;height:number;route:number;screen:TuiState['screen'];workspace:TuiState['workspace'];signedIn:boolean;overlay:unknown;targets:TuiPointerTarget[]};
const frames=new WeakMap<TuiState,PointerFrame>();
const overlay=(state:TuiState)=>state.questionEditor??state.form??(state.paletteOpen?'palette':null)??(state.sidebarOpen?'sidebar':null);
export function beginPointerFrame(state:TuiState,width:number,height:number):void {
  frames.set(state,{width,height,route:state.routeVersion,screen:state.screen,workspace:state.workspace,signedIn:state.signedIn,overlay:overlay(state),targets:[]});
}
export function pointerLine(line:TuiLine,action:TuiPointerAction):TuiLine {
  return typeof line==='string'?{text:line,action}:{...line,action};
}
export function addPointerTarget(state:TuiState,column:number,row:number,width:number,action:TuiPointerAction):void {
  const frame=frames.get(state);if(!frame||row<0||row>=frame.height)return;
  const left=Math.max(0,column),right=Math.min(frame.width,column+width);
  if(right>left)frame.targets.push({column:left,row,width:right-left,action});
}
export function pointerTargetAt(state:TuiState,column:number,row:number,width:number,height:number):TuiPointerAction|null {
  const frame=frames.get(state);
  if(!frame||state.textSelection||state.startup||state.privacyOffer||frame.width!==width||frame.height!==height||
    frame.route!==state.routeVersion||frame.screen!==state.screen||frame.workspace!==state.workspace||frame.signedIn!==state.signedIn||frame.overlay!==overlay(state))return null;
  return frame.targets.findLast(target=>target.row===row&&column>=target.column&&column<target.column+target.width)?.action??null;
}
