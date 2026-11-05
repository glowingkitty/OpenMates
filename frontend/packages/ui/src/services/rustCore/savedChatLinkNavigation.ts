/** Synchronous DOM/navigation policy only. Never admit an account or fetch data. */
export interface SavedLinkActivation { readonly newTab:boolean; }
export interface SavedLinkTarget extends SavedLinkActivation {
  readonly kind:'same_origin'|'external_http'|'external_protocol'; readonly href:string;
}
/** True when any UTF-16 code unit is a C0 control (U+0000-U+001F) or DEL. */
function hasControlCodeUnit(value:string):boolean {
  for(let i=0;i<value.length;i++){const unit=value.charCodeAt(i);if(unit<=0x1f||unit===0x7f)return true;}
  return false;
}
export function savedLinkTarget(href:string,baseUrl:string,intent:SavedLinkActivation):SavedLinkTarget {
  if(!href||href!==href.trim()||hasControlCodeUnit(href))throw Error('unavailable');
  let base:URL,url:URL;
  try{base=new URL(baseUrl);url=new URL(href,base);}catch{throw Error('unavailable');}
  if(!['https:','http:'].includes(base.protocol)||base.username||base.password||url.username||url.password)throw Error('unavailable');
  if(url.protocol==='https:'||url.protocol==='http:')return Object.freeze({kind:url.origin===base.origin?'same_origin':'external_http',href:url.href,newTab:intent.newTab===true});
  if(url.protocol==='mailto:'||url.protocol==='tel:')return Object.freeze({kind:'external_protocol',href:url.href,newTab:false});
  throw Error('unavailable');
}
export interface SavedBrowserNavigationPort {
  open(url:string,target:'_blank',features:'noopener,noreferrer'):unknown;
  assignExternalProtocol(url:string):void;
}
/** No async popup preparation. In-app routing is REQUIRED and explicit; this
 * adapter never falls back to an existing legacy route/window.location. */
export function savedBrowserNavigation(port:SavedBrowserNavigationPort,
  navigateInApp:(target:SavedLinkTarget,current:()=>void)=>void):(target:SavedLinkTarget,current:()=>void)=>void {
  return(target,current)=>{
    current();
    if(target.kind==='same_origin'){navigateInApp(target,current);return;}
    current();
    if(target.kind==='external_http'){port.open(target.href,'_blank','noopener,noreferrer');return;}
    port.assignExternalProtocol(target.href);
  };
}
